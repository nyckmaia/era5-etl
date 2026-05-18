"""INMET historical station dataset configuration.

Unlike ERA5/ERA5-LAND this is NOT a Copernicus CDS gridded source. INMET
publishes one yearly ZIP at ``portal.inmet.gov.br/dadoshistoricos``, each
containing one CSV per weather station. ``SOURCE_KIND = "inmet_zip"`` makes
the pipeline dispatch the INMET downloader/converter/refresh stage instead
of the CDS/NetCDF ones (see ``era5_etl.pipeline.source_handlers``).
"""

from __future__ import annotations

from pathlib import Path

from era5_etl.datasets import DatasetRegistry
from era5_etl.datasets.base import DatasetConfig


@DatasetRegistry.register
class InmetConfig(DatasetConfig):
    """INMET automatic-station historical data.

    Station-based (point) data, not gridded. ``GRID_RESOLUTION_DEG`` is 0
    and ``CDS_DATASET_ID`` is empty -- neither applies. The 17 measurement
    variables are stable across years even though the CSV *formatting*
    (encoding, date/time syntax, missing-value sentinel) evolves; the
    converter normalises the formatting, not the schema.
    """

    NAME = "inmet"
    CDS_DATASET_ID = ""
    GRID_RESOLUTION_DEG = 0.0
    SOURCE_KIND = "inmet_zip"
    VARIABLES_YAML = "variables.yaml"

    def _variables_yaml_path(self) -> Path:
        return Path(__file__).parent / self.VARIABLES_YAML
