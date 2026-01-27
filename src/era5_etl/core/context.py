"""Pipeline context for sharing state between stages."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from era5_etl.exceptions import PipelineCancelled


@dataclass
class StageProgress:
    """Track progress of a single stage."""

    name: str
    weight: float  # Relative weight (0.0 to 1.0)
    progress: float = 0.0  # Current progress (0.0 to 1.0)
    status: str = "pending"  # pending, running, completed, cancelled


class PipelineContext:
    """Context object that carries state through pipeline stages.

    This context is passed between stages and accumulates results,
    metadata, and state information throughout the pipeline execution.

    Supports graceful cancellation via request_cancel() method.
    Supports progress tracking via register_stage() and update_stage_progress().
    """

    def __init__(self) -> None:
        """Initialize empty context."""
        self._data: dict[str, Any] = {}
        self._metadata: dict[str, Any] = {}
        self._errors: list[str] = []
        self._completed_stages: list[str] = []
        self._cancelled = threading.Event()

        # Progress tracking
        self._stages_progress: dict[str, StageProgress] = {}
        self._progress_callback: Callable[[float, str], None] | None = None

    def set(self, key: str, value: Any) -> None:
        """Set a value in the context.

        Args:
            key: The key to store the value under
            value: The value to store
        """
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the context.

        Args:
            key: The key to retrieve
            default: Default value if key doesn't exist

        Returns:
            The value associated with the key, or default if not found
        """
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        """Check if a key exists in the context.

        Args:
            key: The key to check

        Returns:
            True if key exists, False otherwise
        """
        return key in self._data

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata in the context.

        Args:
            key: The metadata key
            value: The metadata value
        """
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata from the context.

        Args:
            key: The metadata key
            default: Default value if key doesn't exist

        Returns:
            The metadata value, or default if not found
        """
        return self._metadata.get(key, default)

    def add_error(self, error: str) -> None:
        """Add an error message to the context.

        Args:
            error: Error message to add
        """
        self._errors.append(error)

    @property
    def errors(self) -> list[str]:
        """Get all errors from the context.

        Returns:
            List of error messages
        """
        return self._errors.copy()

    @property
    def has_errors(self) -> bool:
        """Check if context has any errors.

        Returns:
            True if errors exist, False otherwise
        """
        return len(self._errors) > 0

    def mark_stage_completed(self, stage_name: str) -> None:
        """Mark a stage as completed.

        Args:
            stage_name: Name of the completed stage
        """
        self._completed_stages.append(stage_name)

    @property
    def completed_stages(self) -> list[str]:
        """Get list of completed stages.

        Returns:
            List of completed stage names
        """
        return self._completed_stages.copy()

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary.

        Returns:
            Dictionary representation of the context
        """
        return {
            "data": self._data.copy(),
            "metadata": self._metadata.copy(),
            "errors": self._errors.copy(),
            "completed_stages": self._completed_stages.copy(),
        }

    def request_cancel(self) -> None:
        """Request graceful cancellation of the pipeline."""
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested.

        Returns:
            True if cancellation was requested, False otherwise
        """
        return self._cancelled.is_set()

    def check_cancelled(self) -> None:
        """Check if cancelled and raise exception if so.

        Raises:
            PipelineCancelled: If cancellation was requested
        """
        if self._cancelled.is_set():
            raise PipelineCancelled("Pipeline cancelled by user")

    # Progress tracking methods

    def register_stage(self, name: str, weight: float) -> None:
        """Register a stage for progress tracking.

        Args:
            name: Stage name
            weight: Relative weight (0.0 to 1.0)
        """
        self._stages_progress[name] = StageProgress(name=name, weight=weight)

    def update_stage_progress(
        self, stage_name: str, progress: float, message: str = ""
    ) -> None:
        """Update progress for a stage and notify callback.

        Args:
            stage_name: Name of the stage
            progress: Progress value (0.0 to 1.0)
            message: Optional status message
        """
        if stage_name in self._stages_progress:
            self._stages_progress[stage_name].progress = progress
            self._stages_progress[stage_name].status = "running"

        global_progress = self._calculate_global_progress()
        if self._progress_callback:
            self._progress_callback(global_progress, message)

    def mark_stage_progress_complete(self, stage_name: str) -> None:
        """Mark a stage as completed in progress tracking.

        Args:
            stage_name: Name of the stage
        """
        if stage_name in self._stages_progress:
            self._stages_progress[stage_name].progress = 1.0
            self._stages_progress[stage_name].status = "completed"

        global_progress = self._calculate_global_progress()
        if self._progress_callback:
            self._progress_callback(global_progress, f"[OK] {stage_name}")

    def _calculate_global_progress(self) -> float:
        """Calculate overall pipeline progress based on weighted stages.

        Returns:
            Global progress value (0.0 to 1.0)
        """
        if not self._stages_progress:
            return 0.0

        total = 0.0
        for stage in self._stages_progress.values():
            total += stage.weight * stage.progress
        return min(total, 1.0)

    def set_progress_callback(
        self, callback: Callable[[float, str], None]
    ) -> None:
        """Set callback function to receive progress updates.

        Args:
            callback: Function that receives (progress: float, message: str)
        """
        self._progress_callback = callback

    def get_global_progress(self) -> float:
        """Get current global progress.

        Returns:
            Progress value (0.0 to 1.0)
        """
        return self._calculate_global_progress()
