"""Pipeline context for sharing state between stages."""

from typing import Any


class PipelineContext:
    """Context object that carries state through pipeline stages.

    This context is passed between stages and accumulates results,
    metadata, and state information throughout the pipeline execution.
    """

    def __init__(self) -> None:
        """Initialize empty context."""
        self._data: dict[str, Any] = {}
        self._metadata: dict[str, Any] = {}
        self._errors: list[str] = []
        self._completed_stages: list[str] = []

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
