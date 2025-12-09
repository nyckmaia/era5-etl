"""Parquet writer for ERA5 data storage."""

import logging
from pathlib import Path

import polars as pl

from pyera5.config import StorageConfig
from pyera5.exceptions import StorageError


class ParquetWriter:
    """Write ERA5 data to partitioned Parquet files."""

    def __init__(self, config: StorageConfig) -> None:
        """Initialize the writer."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.config.parquet_dir.mkdir(parents=True, exist_ok=True)

    def write_csv_to_parquet(self, csv_file: Path, table_name: str = None) -> Path:
        """Convert CSV to Parquet."""
        if table_name is None:
            table_name = csv_file.stem

        output_dir = self.config.parquet_dir / table_name
        self.logger.info(f"Converting {csv_file.name} to Parquet")

        try:
            df = pl.read_csv(csv_file)
            df = self._ensure_partition_columns(df)
            self._write_partitioned(df, output_dir)
            self.logger.info(f"Wrote Parquet: {output_dir.name} ({len(df):,} rows)")
            return output_dir
        except Exception as e:
            raise StorageError(f"Parquet conversion failed: {e}") from e

    def _ensure_partition_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """Ensure partition columns exist."""
        for col in self.config.partition_cols:
            if col not in df.columns:
                if col == "year" and "time" in df.columns:
                    df = df.with_columns(pl.col("time").dt.year().alias("year"))
                elif col == "month" and "time" in df.columns:
                    df = df.with_columns(pl.col("time").dt.month().alias("month"))
        return df

    def _write_partitioned(self, df: pl.DataFrame, output_dir: Path) -> None:
        """Write partitioned Parquet."""
        valid_cols = [c for c in self.config.partition_cols if c in df.columns]
        if valid_cols:
            df.write_parquet(
                output_dir,
                compression=self.config.compression,
                use_pyarrow=True,
                pyarrow_options={
                    "partition_cols": valid_cols,
                    "max_rows_per_group": self.config.row_group_size,
                },
            )
        else:
            output_file = output_dir / "data.parquet"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(output_file, compression=self.config.compression)
