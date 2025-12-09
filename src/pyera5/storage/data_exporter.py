"""Data exporter for ERA5 data (simplified version)."""

import logging
from pathlib import Path

import polars as pl

from pyera5.exceptions import StorageError


class DataExporter:
    """Export ERA5 data to various formats."""

    def __init__(self) -> None:
        """Initialize the exporter."""
        self.logger = logging.getLogger(__name__)

    def export_to_csv(
        self,
        df: pl.DataFrame,
        output_file: Path,
        delimiter: str = ",",
    ) -> Path:
        """Export DataFrame to CSV."""
        self.logger.info(f"Exporting to CSV: {output_file}")

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            df.write_csv(output_file, separator=delimiter)
            self.logger.info(f"Exported {len(df):,} rows to {output_file}")
            return output_file
        except Exception as e:
            raise StorageError(f"CSV export failed: {e}") from e

    def export_parquet_to_csv(
        self,
        parquet_path: Path,
        output_file: Path,
        delimiter: str = ",",
    ) -> Path:
        """Export Parquet to CSV."""
        self.logger.info(f"Exporting Parquet to CSV: {parquet_path} -> {output_file}")

        try:
            if parquet_path.is_file():
                df = pl.read_parquet(parquet_path)
            else:
                files = list(parquet_path.glob("**/*.parquet"))
                if not files:
                    raise StorageError(f"No Parquet files in {parquet_path}")
                df = pl.concat([pl.read_parquet(f) for f in files])

            return self.export_to_csv(df, output_file, delimiter)
        except Exception as e:
            raise StorageError(f"Parquet to CSV export failed: {e}") from e
