"""Base Pipeline class implementing Template Method pattern."""

import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from era5_etl.config import PipelineConfig
from era5_etl.core.context import PipelineContext
from era5_etl.core.stage import Stage
from era5_etl.exceptions import ERA5ETLError, PipelineCancelled

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
        self.logger = logging.getLogger(f"era5_etl.{self.__class__.__name__}")
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
            ERA5ETLError: If pipeline execution fails
        """
        try:
            # Setup stages (Template Method hook)
            self.setup_stages()

            if not self._stages:
                raise ERA5ETLError("No stages defined in pipeline")

            total_stages = len(self._stages)

            # Execute stages sequentially
            for i, stage in enumerate(self._stages, 1):
                # Check for cancellation before starting each stage
                self.context.check_cancelled()

                self.context.set_metadata("current_stage", i)
                self.context.set_metadata("total_stages", total_stages)
                self.context = stage.execute(self.context)

            return self.context

        except PipelineCancelled:
            self.logger.info("Pipeline cancelled by user")
            raise

        except ERA5ETLError:
            self.logger.error("Pipeline failed")
            raise

        except Exception as e:
            self.logger.exception("Unexpected error during pipeline execution")
            raise ERA5ETLError(f"Pipeline failed: {e}") from e

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
