"""DuckDB manager for ERA5 data (simplified version)."""

import logging
from pathlib import Path
from typing import Any, Optional

import duckdb
import polars as pl

from pyera5.config import DatabaseConfig
from pyera5.exceptions import StorageError


class DuckDBManager:
    """Manage DuckDB database for ERA5 data."""

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize the manager."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> None:
        """Connect to DuckDB database."""
        if self._conn is not None:
            return

        db_path_str = str(self.config.db_path) if self.config.db_path else ":memory:"
        self.logger.info(f"Connecting to DuckDB: {db_path_str}")

        try:
            self._conn = duckdb.connect(database=db_path_str, read_only=self.config.read_only)
            if self.config.threads:
                self._conn.execute(f"SET threads TO {self.config.threads}")
        except Exception as e:
            raise StorageError(f"Database connection failed: {e}") from e

    def disconnect(self) -> None:
        """Disconnect from database."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DuckDBManager":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.disconnect()

    def query(self, sql: str) -> pl.DataFrame:
        """Execute query and return Polars DataFrame."""
        if not self._conn:
            raise StorageError("Not connected. Call connect() first.")
        try:
            return self._conn.execute(sql).pl()
        except Exception as e:
            raise StorageError(f"Query failed: {e}") from e

    def register_parquet(self, parquet_path: Path, table_name: str) -> None:
        """Register Parquet as table."""
        if not self._conn:
            raise StorageError("Not connected. Call connect() first.")

        pattern = str(parquet_path / "**/*.parquet") if parquet_path.is_dir() else str(parquet_path)
        query = f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM read_parquet('{pattern}')"
        self._conn.execute(query)
        self.logger.info(f"Registered table: {table_name}")
