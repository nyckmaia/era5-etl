"""Tests for core pipeline components."""

import pytest

from era5_etl.core.context import PipelineContext
from era5_etl.core.pipeline import Pipeline
from era5_etl.core.stage import Stage
from era5_etl.exceptions import ERA5ETLError, PipelineCancelled


class MockStage(Stage):
    """Mock stage for testing."""

    def __init__(self, name: str, should_fail: bool = False) -> None:
        super().__init__(name)
        self.should_fail = should_fail
        self.executed = False

    def _execute(self, context: PipelineContext) -> PipelineContext:
        if self.should_fail:
            raise ERA5ETLError(f"Stage {self.name} failed")
        self.executed = True
        context.set(f"{self.name}_result", "success")
        context.set_metadata(f"{self.name}_count", 1)
        return context


class MockPipeline(Pipeline):
    """Mock pipeline for testing."""

    def __init__(self, config=None) -> None:
        super().__init__(config or {})
        self.setup_called = False

    def setup_stages(self) -> None:
        self.setup_called = True
        self.add_stage(MockStage("stage1"))
        self.add_stage(MockStage("stage2"))
        self.add_stage(MockStage("stage3"))


# -- PipelineContext tests --


def test_pipeline_context_basic():
    """Test basic PipelineContext set/get/has operations."""
    context = PipelineContext()

    context.set("key1", "value1")
    assert context.get("key1") == "value1"
    assert context.get("nonexistent", "default") == "default"

    assert context.has("key1") is True
    assert context.has("nonexistent") is False


def test_pipeline_context_metadata():
    """Test PipelineContext metadata operations."""
    context = PipelineContext()

    context.set_metadata("count", 10)
    context.set_metadata("status", "completed")

    assert context.get_metadata("count") == 10
    assert context.get_metadata("status") == "completed"
    assert context.get_metadata("nonexistent", "default") == "default"


def test_pipeline_context_errors():
    """Test PipelineContext error handling."""
    context = PipelineContext()

    assert context.has_errors is False
    assert context.errors == []

    context.add_error("Error 1")
    context.add_error("Error 2")

    assert context.has_errors is True
    assert len(context.errors) == 2
    assert "Error 1" in context.errors


def test_pipeline_context_stages():
    """Test PipelineContext stage tracking."""
    context = PipelineContext()

    assert context.completed_stages == []

    context.mark_stage_completed("stage1")
    context.mark_stage_completed("stage2")

    assert len(context.completed_stages) == 2
    assert "stage1" in context.completed_stages
    assert "stage2" in context.completed_stages


def test_pipeline_context_to_dict():
    """Test PipelineContext conversion to dict."""
    context = PipelineContext()
    context.set("key1", "value1")
    context.set_metadata("meta1", "meta_value")
    context.add_error("error1")
    context.mark_stage_completed("stage1")

    result = context.to_dict()

    assert "data" in result
    assert "metadata" in result
    assert "errors" in result
    assert "completed_stages" in result
    assert result["data"]["key1"] == "value1"
    assert result["metadata"]["meta1"] == "meta_value"


def test_pipeline_context_cancellation():
    """Test PipelineContext cancellation."""
    context = PipelineContext()

    assert context.is_cancelled() is False

    context.request_cancel()

    assert context.is_cancelled() is True

    with pytest.raises(PipelineCancelled):
        context.check_cancelled()


def test_pipeline_context_progress_tracking():
    """Test PipelineContext progress tracking."""
    context = PipelineContext()

    context.register_stage("download", weight=0.5)
    context.register_stage("convert", weight=0.5)

    assert context.get_global_progress() == 0.0

    context.update_stage_progress("download", 0.5, "Downloading...")
    assert abs(context.get_global_progress() - 0.25) < 0.01

    context.mark_stage_progress_complete("download")
    assert abs(context.get_global_progress() - 0.5) < 0.01

    context.mark_stage_progress_complete("convert")
    assert abs(context.get_global_progress() - 1.0) < 0.01


def test_pipeline_context_progress_callback():
    """Test PipelineContext progress callback."""
    updates: list[tuple[float, str]] = []

    def callback(progress: float, message: str) -> None:
        updates.append((progress, message))

    context = PipelineContext()
    context.set_progress_callback(callback)
    context.register_stage("test", weight=1.0)

    context.update_stage_progress("test", 0.5, "Halfway")
    context.mark_stage_progress_complete("test")

    assert len(updates) == 2
    assert updates[0][1] == "Halfway"
    assert updates[1][0] == 1.0


# -- Stage tests --


def test_stage_execute_success():
    """Test successful stage execution."""
    stage = MockStage("test_stage")
    context = PipelineContext()

    result = stage.execute(context)

    assert stage.executed is True
    assert result.get("test_stage_result") == "success"
    assert "test_stage" in result.completed_stages


def test_stage_execute_failure():
    """Test stage execution failure."""
    stage = MockStage("test_stage", should_fail=True)
    context = PipelineContext()

    with pytest.raises(ERA5ETLError):
        stage.execute(context)

    assert stage.executed is False
    assert context.has_errors is True


def test_stage_chaining():
    """Test stage chaining via Chain of Responsibility."""
    stage1 = MockStage("stage1")
    stage2 = MockStage("stage2")
    stage3 = MockStage("stage3")

    stage1.set_next(stage2).set_next(stage3)

    context = PipelineContext()
    result = stage1.execute(context)

    assert stage1.executed is True
    assert stage2.executed is True
    assert stage3.executed is True
    assert result.get("stage1_result") == "success"
    assert result.get("stage2_result") == "success"
    assert result.get("stage3_result") == "success"


# -- Pipeline tests --


def test_pipeline_run_success():
    """Test successful pipeline execution."""
    pipeline = MockPipeline()
    context = pipeline.run()

    assert pipeline.setup_called is True
    assert len(pipeline.stages) == 3
    assert len(context.completed_stages) == 3


def test_pipeline_run_no_stages():
    """Test pipeline run with no stages raises error."""

    class EmptyPipeline(Pipeline):
        def setup_stages(self) -> None:
            pass

    pipeline = EmptyPipeline({})

    with pytest.raises(ERA5ETLError, match="No stages defined"):
        pipeline.run()


def test_pipeline_add_stage():
    """Test adding stages to pipeline."""
    pipeline = MockPipeline()
    pipeline.setup_stages()

    assert len(pipeline.stages) == 3

    new_stage = MockStage("new_stage")
    pipeline.add_stage(new_stage)

    assert len(pipeline.stages) == 4


def test_pipeline_repr():
    """Test pipeline string representation."""
    pipeline = MockPipeline()
    pipeline.setup_stages()
    assert "MockPipeline" in repr(pipeline)
    assert "3" in repr(pipeline)
