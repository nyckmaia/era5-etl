"""ERA5-LAND reanalysis dataset configuration."""

from __future__ import annotations

from pathlib import Path

from era5_etl.datasets import DatasetRegistry
from era5_etl.datasets.base import DatasetConfig


@DatasetRegistry.register
class Era5LandConfig(DatasetConfig):
    """ERA5-LAND reanalysis (``reanalysis-era5-land``).

    Native horizontal resolution: 0.1 degrees. Variables describe the land
    surface and shallow subsurface only (no atmospheric profiles).
    """

    NAME = "era5-land"
    CDS_DATASET_ID = "reanalysis-era5-land"
    GRID_RESOLUTION_DEG = 0.1
    VARIABLES_YAML = "variables.yaml"

    def _variables_yaml_path(self) -> Path:
        return Path(__file__).parent / self.VARIABLES_YAML
