"""ERA5 single-level reanalysis dataset configuration."""

from __future__ import annotations

from pathlib import Path

from era5_etl.datasets import DatasetRegistry
from era5_etl.datasets.base import DatasetConfig


@DatasetRegistry.register
class Era5Config(DatasetConfig):
    """ERA5 reanalysis on single levels (``reanalysis-era5-single-levels``).

    Native horizontal resolution: 0.25 degrees.
    """

    NAME = "era5"
    CDS_DATASET_ID = "reanalysis-era5-single-levels"
    GRID_RESOLUTION_DEG = 0.25
    VARIABLES_YAML = "variables.yaml"

    def _variables_yaml_path(self) -> Path:
        return Path(__file__).parent / self.VARIABLES_YAML
