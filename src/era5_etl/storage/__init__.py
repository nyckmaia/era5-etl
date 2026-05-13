"""Storage components for ERA5-ETL.

Submodules import each other (and the top-level ``config``) so we keep this
package init free of side-effect imports to avoid circular initialization.
Import the concrete classes from their submodules instead, e.g.::

    from era5_etl.storage.parquet_manager import ParquetManager
    from era5_etl.storage.duckdb_manager import DuckDBManager
    from era5_etl.storage.manifest import Manifest
    from era5_etl.storage.paths import resolve_dataset_dir
"""
