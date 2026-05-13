"""Parquet storage manager for partitioned ERA5 data.

Manages partitioned Parquet files with Hive-style structure:
- Structure: ``<base_dir>/climate_data_store_db/<dataset>/date=YYYY-MM-DD/*.parquet``
- Manifest tracking: ``_manifest.json`` in the dataset directory
- DuckDB integration: creates VIEWs from Parquet glob patterns

Paths are computed exclusively through :mod:`era5_etl.storage.paths`.

Writes go through :meth:`ParquetManager.write_dataframe`, which deduplicates
by ``(latitude, longitude, hour_utc)`` within each date partition. This is
the defensive layer that catches grid-cell overlap when the user downloads
adjacent regions (e.g., two neighboring UFs whose bboxes overlap).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import polars as pl

from era5_etl.storage.manifest import ChunkRecord, Manifest
from era5_etl.storage.paths import resolve_dataset_dir

# Within a date partition, every (latitude, longitude, hour_utc) tuple is unique.
# Two downloads covering the same grid cell at the same date+hour collapse into
# one row -- new values win for conflicts, old values fill column gaps.
PARTITION_KEY_COLS = ("latitude", "longitude", "hour_utc")


def merge_into_partitioned_parquet(
    df: pl.DataFrame,
    parquet_dir: Path,
    compression: Literal["snappy", "zstd", "gzip"] = "zstd",
    logger: logging.Logger | None = None,
) -> None:
    """Write ``df`` into ``<parquet_dir>/date=YYYY-MM-DD/`` with merge-on-key dedup.

    Split ``df`` by its ``date`` column; for each date partition, merges with
    any existing data on ``PARTITION_KEY_COLS``. New values win for conflicts;
    columns missing on one side are filled from the other (outer-join
    semantics). Each ``(lat, lon, date, hour_utc)`` tuple ends up as exactly
    one row, regardless of how many times the user re-downloads overlapping
    regions.

    This is the canonical write path; both :class:`ParquetManager` and the
    NetCDF converter call into here.
    """
    log = logger or logging.getLogger(__name__)
    if "date" not in df.columns:
        raise ValueError("merge_into_partitioned_parquet requires a 'date' column")

    if df.schema["date"] != pl.Utf8:
        df = df.with_columns(pl.col("date").cast(pl.Utf8).alias("date"))

    parquet_dir.mkdir(parents=True, exist_ok=True)

    for (date_str,), df_part in df.group_by(["date"], maintain_order=True):
        partition_dir = parquet_dir / f"date={date_str}"
        existing_files = (
            sorted(partition_dir.glob("*.parquet")) if partition_dir.exists() else []
        )
        new_payload = df_part.drop("date")

        if existing_files:
            existing = _read_partition_payload(existing_files)
            merged = _merge_by_key(existing, new_payload)
        else:
            merged = new_payload

        _replace_partition_files(partition_dir, merged, existing_files, compression, log)


def _read_partition_payload(files: list[Path]) -> pl.DataFrame:
    """Read all parquet files in a partition into a single DataFrame.

    The date column is excluded -- partition files don't carry it (it lives
    in the directory name). Schemas across files may differ (variable-split
    chunks), so we use ``diagonal_relaxed`` concat to align them with nulls.
    """
    parts = [pl.read_parquet(p) for p in files]
    if len(parts) == 1:
        return parts[0]
    return pl.concat(parts, how="diagonal_relaxed")


def _merge_by_key(old: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """Merge ``new`` into ``old`` on ``PARTITION_KEY_COLS``.

    Order: old rows first, new rows second. Within each key group, the last
    non-null value per non-key column wins -- so new values overwrite old,
    and old fills any column gap that new does not cover.
    """
    key_cols = [c for c in PARTITION_KEY_COLS if c in old.columns or c in new.columns]
    if not key_cols:
        return pl.concat([old, new], how="diagonal_relaxed")

    combined = pl.concat([old, new], how="diagonal_relaxed")
    non_key_cols = [c for c in combined.columns if c not in key_cols]
    if not non_key_cols:
        return combined.unique(subset=key_cols, keep="last")

    return combined.group_by(key_cols, maintain_order=True).agg(
        [pl.col(c).drop_nulls().last().alias(c) for c in non_key_cols]
    )


def _replace_partition_files(
    partition_dir: Path,
    df: pl.DataFrame,
    old_files: list[Path],
    compression: Literal["snappy", "zstd", "gzip"],
    logger: logging.Logger,
) -> None:
    """Write ``df`` as the sole content of ``partition_dir``.

    Sequence: write-new -> delete-old. A crash between the two leaves
    partial duplication, which the next ``merge_into_partitioned_parquet``
    call cleans up (the merge is idempotent on duplicate keys).
    """
    partition_dir.mkdir(parents=True, exist_ok=True)
    new_file = partition_dir / f"part-{uuid.uuid4().hex}.parquet"
    df.write_parquet(new_file, compression=compression)
    for old in old_files:
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not delete old partition file %s: %s", old, exc)


@dataclass
class ParquetStorageStats:
    """Statistics about Parquet storage."""

    total_files: int
    total_size_bytes: int
    partitions: list[str]
    file_count_by_partition: dict[str, int]


class ParquetManager:
    """Manager for partitioned Parquet storage of one ERA5 dataset."""

    def __init__(self, base_dir: Path, dataset: str) -> None:
        """Initialize the Parquet manager.

        Args:
            base_dir: Root data directory (the parent of ``climate_data_store_db``).
            dataset: Dataset name (``"era5"`` or ``"era5-land"``).
        """
        self.dataset = dataset
        self.base_dir = Path(base_dir)
        self.parquet_dir = resolve_dataset_dir(base_dir, dataset)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = Manifest(base_dir, dataset)
        self.logger = logging.getLogger(__name__)

    # ---- manifest (chunk-based) -------------------------------------------

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    def has_chunk(self, chunk_id: str) -> bool:
        return self._manifest.has(chunk_id)

    def record_chunk(self, chunk: ChunkRecord) -> None:
        self._manifest.record(chunk)
        self._manifest.save()
        self.logger.debug("Recorded chunk %s in manifest", chunk.chunk_id)

    # ---- legacy file-based manifest API (kept for backward compatibility) -

    def get_processed_files(self) -> set[str]:
        """Return the set of source NetCDF filenames that have been processed.

        The chunk-based manifest is the source of truth; this helper flattens
        it down to the filenames for callers that only care about uniqueness.
        """
        return {c.netcdf_filename for c in self._manifest.chunks() if c.netcdf_filename}

    def mark_processed(self, source_file: str) -> None:
        """Record a NetCDF source file as processed.

        For backward compatibility this records a minimal ChunkRecord keyed on
        the filename. New code should call ``record_chunk`` with full metadata.
        """
        if not source_file:
            return
        if self._manifest.has(source_file):
            return
        self._manifest.record(
            ChunkRecord(
                chunk_id=source_file,
                year=0,
                month=0,
                variables=[],
                area=[],
                netcdf_filename=source_file,
            )
        )
        self._manifest.save()
        self.logger.debug("Marked as processed: %s", source_file)

    def remove_processed(self, source_file: str) -> None:
        """Remove a NetCDF source file from the manifest."""
        if self._manifest.has(source_file):
            self._manifest.forget(source_file)
            self._manifest.save()
            self.logger.debug("Removed from processed: %s", source_file)

    def clear_manifest(self) -> None:
        """Clear all manifest entries."""
        self._manifest.clear()
        self._manifest.save()
        self.logger.info("Manifest cleared")

    # ---- file system / queries --------------------------------------------

    def get_glob_pattern(self) -> str:
        """Glob pattern for ``read_parquet`` with Hive partitioning."""
        return str(self.parquet_dir / "**" / "*.parquet")

    def get_storage_stats(self) -> ParquetStorageStats:
        """Return statistics about Parquet storage."""
        total_files = 0
        total_size = 0
        file_count_by_partition: dict[str, int] = {}
        partitions: list[str] = []

        if self.parquet_dir.exists():
            for parquet_file in self.parquet_dir.rglob("*.parquet"):
                total_files += 1
                total_size += parquet_file.stat().st_size

                partition_dir = parquet_file.parent.name
                if "=" in partition_dir:
                    key = partition_dir
                    file_count_by_partition[key] = file_count_by_partition.get(key, 0) + 1
                    if key not in partitions:
                        partitions.append(key)

        return ParquetStorageStats(
            total_files=total_files,
            total_size_bytes=total_size,
            partitions=sorted(partitions),
            file_count_by_partition=file_count_by_partition,
        )

    def list_parquet_files(self) -> list[Path]:
        """List all Parquet files in the dataset directory."""
        if not self.parquet_dir.exists():
            return []
        return sorted(self.parquet_dir.rglob("*.parquet"))

    def create_duckdb_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
    ) -> None:
        """Create or replace a DuckDB VIEW pointing at this dataset's Parquet files."""
        glob_pattern = self.get_glob_pattern()
        files = list(self.parquet_dir.rglob("*.parquet"))
        if not files:
            raise ValueError(f"No Parquet files found in {self.parquet_dir}")

        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM read_parquet(
                '{glob_pattern}',
                hive_partitioning=true
            )
        """
        conn.execute(sql)
        self.logger.info("Created VIEW %s from %d Parquet files", view_name, len(files))

    def exists(self) -> bool:
        """Return ``True`` if there is at least one Parquet file on disk."""
        if not self.parquet_dir.exists():
            return False
        return any(self.parquet_dir.rglob("*.parquet"))

    # ---- write path with merge-on-key dedup -------------------------------

    def write_dataframe(
        self,
        df: pl.DataFrame,
        compression: Literal["snappy", "zstd", "gzip"] = "zstd",
    ) -> None:
        """Write ``df`` into the dataset's date-partitioned layout, deduping.

        See :func:`merge_into_partitioned_parquet` for the full contract.
        """
        merge_into_partitioned_parquet(df, self.parquet_dir, compression, self.logger)

    def dedup_existing_partitions(
        self,
        compression: Literal["snappy", "zstd", "gzip"] = "zstd",
    ) -> dict[str, int]:
        """Re-write every partition deduplicated in place.

        One-off migration for datasets created before merge-on-key writes
        landed: reads each ``date=YYYY-MM-DD`` directory, runs the merge
        against itself (idempotent on duplicate keys), writes back.
        Returns a stats dict with ``partitions_processed``, ``rows_before``,
        and ``rows_after``.
        """
        partitions = (
            sorted(
                p for p in self.parquet_dir.iterdir()
                if p.is_dir() and p.name.startswith("date=")
            )
            if self.parquet_dir.exists()
            else []
        )
        stats = {"partitions_processed": 0, "rows_before": 0, "rows_after": 0}
        for partition_dir in partitions:
            files = sorted(partition_dir.glob("*.parquet"))
            if not files:
                continue
            df = _read_partition_payload(files)
            stats["rows_before"] += len(df)
            deduped = _merge_by_key(df.head(0), df)
            stats["rows_after"] += len(deduped)
            _replace_partition_files(partition_dir, deduped, files, compression, self.logger)
            stats["partitions_processed"] += 1
            self.logger.info(
                "Deduped %s: %d -> %d rows",
                partition_dir.name,
                len(df),
                len(deduped),
            )
        return stats

    def __repr__(self) -> str:
        stats = self.get_storage_stats()
        return (
            f"ParquetManager(dataset={self.dataset}, "
            f"files={stats.total_files}, partitions={len(stats.partitions)})"
        )
