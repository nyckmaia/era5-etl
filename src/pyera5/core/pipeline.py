"""Base Pipeline class implementing Template Method pattern."""

import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pyera5.config import PipelineConfig
from pyera5.core.context import PipelineContext
from pyera5.core.stage import Stage
from pyera5.exceptions import PyERA5Error

T = TypeVar("T", bound=PipelineConfig)


class Pipeline(ABC, Generic[T]):
    """Abstract base class for data processing pipelines.

    Implements the Template Method design pattern, where the overall
    algorithm structure is defined but specific steps are implemented
    by subclasses.
    """

    def __init__(self, config: T) -> None:
        """Initialize the pipeline.

        Args:
            config: Pipeline configuration object
        """
        self.config = config
        self.context = PipelineContext()
        self.logger = logging.getLogger(f"pyera5.{self.__class__.__name__}")
        self._stages: list[Stage] = []

    @abstractmethod
    def setup_stages(self) -> None:
        """Set up pipeline stages.

        This method must be implemented by subclasses to define
        the specific stages for the pipeline.
        """
        pass

    def add_stage(self, stage: Stage) -> None:
        """Add a stage to the pipeline.

        Args:
            stage: The stage to add
        """
        self._stages.append(stage)
        self.logger.debug(f"Added stage: {stage.name}")

    def run(self) -> PipelineContext:
        """Execute the complete pipeline.

        This is the Template Method that defines the algorithm structure.

        Returns:
            The final pipeline context with results

        Raises:
            PyERA5Error: If pipeline execution fails
        """
        self.logger.info("=" * 60)
        self.logger.info(f"Starting pipeline: {self.__class__.__name__}")
        self.logger.info("=" * 60)

        try:
            # Setup stages (Template Method hook)
            self.setup_stages()

            if not self._stages:
                raise PyERA5Error("No stages defined in pipeline")

            # Execute stages sequentially
            for i, stage in enumerate(self._stages, 1):
                self.logger.info(f"[{i}/{len(self._stages)}] Executing: {stage.name}")
                self.context = stage.execute(self.context)

            self.logger.info("=" * 60)
            self.logger.info("Pipeline completed successfully!")
            self.logger.info("=" * 60)

            return self.context

        except PyERA5Error:
            self.logger.error("Pipeline failed")
            raise

        except Exception as e:
            self.logger.exception("Unexpected error during pipeline execution")
            raise PyERA5Error(f"Pipeline failed: {e}") from e

    @property
    def stages(self) -> list[Stage]:
        """Get list of configured stages.

        Returns:
            List of pipeline stages
        """
        return self._stages.copy()

    def __repr__(self) -> str:
        """String representation of the pipeline."""
        return f"{self.__class__.__name__}(stages={len(self._stages)})"
