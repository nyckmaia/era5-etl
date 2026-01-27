"""ERA5-ETL - Professional ETL pipeline for ERA5/ERA5-Land climate data.

ERA5-ETL downloads, processes, and stores ERA5/ERA5-Land reanalysis data
from the Copernicus Climate Data Store in optimized Parquet format.
"""

from era5_etl.__version__ import __version__
from era5_etl.config import PipelineConfig
from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

__all__ = [
    "ERA5Pipeline",
    "PipelineConfig",
    "__version__",
]
