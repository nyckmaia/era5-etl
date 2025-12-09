"""Tests for core pipeline components."""

import pytest

from pyera5.core.context import PipelineContext
from pyera5.core.pipeline import Pipeline
from pyera5.core.stage import Stage
from pyera5.exceptions import PyERA5Error


class MockStage(Stage):
    """Mock stage for testing."""

    def __init__(self, name: str, should_fail: bool = False) -> None:
        super().__init__(name)
        self.should_fail = should_fail
        self.executed = False

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute mock stage."""
        if self.should_fail:
            raise PyERA5Error(f"Stage {self.name} failed")

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
        """Set up test stages."""
        self.setup_called = True
        self.add_stage(MockStage("stage1"))
        self.add_stage(MockStage("stage2"))
        self.add_stage(MockStage("stage3"))


def test_pipeline_context_basic():
    """Test basic PipelineContext operations."""
    context = PipelineContext()

    # Test set/get
    context.set("key1", "value1")
    assert context.get("key1") == "value1"
    assert context.get("nonexistent", "default") == "default"

    # Test has
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

    with pytest.raises(PyERA5Error):
        stage.execute(context)

    assert stage.executed is False
    assert context.has_errors is True


def test_stage_chaining():
    """Test stage chaining."""
    stage1 = MockStage("stage1")
    stage2 = MockStage("stage2")
    stage3 = MockStage("stage3")

    stage1.set_next(stage2).set_next(stage3)

    context = PipelineContext()
    result = stage1.execute(context)

    # All stages should be executed
    assert stage1.executed is True
    assert stage2.executed is True
    assert stage3.executed is True

    # All results should be in context
    assert result.get("stage1_result") == "success"
    assert result.get("stage2_result") == "success"
    assert result.get("stage3_result") == "success"


def test_pipeline_run_success():
    """Test successful pipeline execution."""
    pipeline = MockPipeline()
    context = pipeline.run()

    assert pipeline.setup_called is True
    assert len(pipeline.stages) == 3
    assert len(context.completed_stages) == 3


def test_pipeline_run_no_stages():
    """Test pipeline run with no stages."""

    class EmptyPipeline(Pipeline):
        def setup_stages(self) -> None:
            pass  # Don't add any stages

    pipeline = EmptyPipeline({})

    with pytest.raises(PyERA5Error, match="No stages defined"):
        pipeline.run()


def test_pipeline_add_stage():
    """Test adding stages to pipeline."""
    pipeline = MockPipeline()
    pipeline.setup_stages()

    assert len(pipeline.stages) == 3

    new_stage = MockStage("new_stage")
    pipeline.add_stage(new_stage)

    assert len(pipeline.stages) == 4
