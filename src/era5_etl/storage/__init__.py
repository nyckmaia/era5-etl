"""Storage components for ERA5-ETL."""

from era5_etl.storage.duckdb_manager import DuckDBManager
from era5_etl.storage.parquet_manager import ParquetManager

__all__ = [
    "DuckDBManager",
    "ParquetManager",
]
