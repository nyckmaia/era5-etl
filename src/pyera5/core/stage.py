"""Base Stage class for pipeline steps."""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from pyera5.core.context import PipelineContext
from pyera5.exceptions import PyERA5Error


class Stage(ABC):
    """Abstract base class for pipeline stages.

    Each stage represents a step in the data processing pipeline.
    Stages are executed sequentially and can pass data through context.
    """

    def __init__(self, name: str) -> None:
        """Initialize the stage.

        Args:
            name: Name of the stage for logging and identification
        """
        self.name = name
        self.logger = logging.getLogger(f"pyera5.{name}")
        self._next_stage: Optional[Stage] = None

    @abstractmethod
    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute the stage logic.

        This method must be implemented by subclasses.

        Args:
            context: Pipeline context with shared state

        Returns:
            Updated context after stage execution

        Raises:
            PyERA5Error: If stage execution fails
        """
        pass

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute the stage with error handling.

        Args:
            context: Pipeline context

        Returns:
            Updated context

        Raises:
            PyERA5Error: If stage execution fails critically
        """
        self.logger.info(f"Starting stage: {self.name}")

        try:
            context = self._execute(context)
            context.mark_stage_completed(self.name)
            self.logger.info(f"Stage completed successfully: {self.name}")

        except PyERA5Error as e:
            self.logger.error(f"Stage failed: {self.name} - {e}")
            context.add_error(f"{self.name}: {e}")
            raise

        except Exception as e:
            self.logger.exception(f"Unexpected error in stage: {self.name}")
            context.add_error(f"{self.name}: Unexpected error - {e}")
            raise PyERA5Error(f"Stage {self.name} failed: {e}") from e

        # Chain to next stage if exists
        if self._next_stage:
            return self._next_stage.execute(context)

        return context

    def set_next(self, stage: "Stage") -> "Stage":
        """Set the next stage in the chain.

        Implements Chain of Responsibility pattern.

        Args:
            stage: The next stage to execute

        Returns:
            The next stage (for chaining)
        """
        self._next_stage = stage
        return stage

    def __repr__(self) -> str:
        """String representation of the stage."""
        return f"{self.__class__.__name__}(name={self.name!r})"
