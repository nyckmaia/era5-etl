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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import polars as pl
from filelock import FileLock

from era5_etl.storage.manifest import ChunkRecord, Manifest
from era5_etl.storage.paths import resolve_dataset_dir

# Within a date partition, every (latitude, longitude, hour_utc) tuple is unique.
# Two downloads covering the same grid cell at the same date+hour collapse into
# one row -- new values win for conflicts, old values fill column gaps.
PARTITION_KEY_COLS = ("latitude", "longitude", "hour_utc")

# Tile size in degrees for the transient sort-key columns. Picked so a typical
# row group (~10k-100k rows) stays roughly inside one tile, giving DuckDB tight
# 2D min/max stats per row group on BOTH latitude and longitude. The tile
# columns themselves are dropped before write -- they never reach the parquet
# file -- so this is purely a row-ordering trick.
PARQUET_TILE_DEG = 5

# Final sort order applied inside each parquet file. ``date`` is the partition
# column (lives in the directory name, not inside the file), so it's not part
# of the sort. Kept as a public constant for back-compat re-export and
# introspection; the actual sort runs through :func:`_compute_sort_keys`,
# which prepends the transient ``_lat_tile`` / ``_lon_tile`` columns.
PARQUET_SORT_COLS = ("latitude", "longitude", "hour_utc")


def merge_into_partitioned_parquet(
    df: pl.DataFrame,
    parquet_dir: Path,
    compression: Literal["snappy", "zstd", "gzip"] = "zstd",
    logger: logging.Logger | None = None,
    row_group_size: int = 100_000,
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

    for (date_value,), df_part in df.group_by(["date"], maintain_order=True):
        date_str = str(date_value)
        partition_dir = parquet_dir / f"date={date_str}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        # Per-partition lock: under parallel conversion (ProcessPoolExecutor)
        # two workers may target the same date partition. Without
        # serialization, worker B reads worker A's in-progress parquet
        # ("File must end with PAR1") or hits Windows mmap collisions
        # ("os error 1224"). The lock scope brackets read-modify-write;
        # workers across processes still parallelise across DIFFERENT dates.
        lock_path = partition_dir / ".write.lock"
        with FileLock(str(lock_path)):
            existing_files = (
                sorted(partition_dir.glob("*.parquet"))
                if partition_dir.exists()
                else []
            )
            new_payload = df_part.drop("date")

            if existing_files:
                existing = _read_partition_payload(existing_files, log)
                merged = _merge_by_key(existing, new_payload)
            else:
                merged = new_payload

            merged = _sort_for_storage(merged)
            _replace_partition_files(
                parquet_dir,
                date_str,
                merged,
                existing_files,
                compression,
                log,
                row_group_size,
            )

    # NOTE on coverage index updates: previously this function upserted into
    # `_coverage.duckdb` here, but DuckDB only allows one writer per file and
    # the parallel ProcessPoolExecutor in transform/netcdf_to_parquet.py made
    # workers race on the same DB file. Coverage is now refreshed once at the
    # END of the pipeline (see `era5_etl.pipeline.era5_pipeline.ERA5Pipeline`)
    # via `CoverageIndex.rebuild_from_parquet`. The parquet on disk remains
    # the canonical source of truth; coverage is derived state.


def _compute_sort_keys(df: pl.DataFrame) -> pl.DataFrame:
    """Add transient tile columns, sort, then drop them.

    Sort key is ``(_lat_tile, _lon_tile, latitude, longitude, hour_utc)``,
    where the two tile columns are ``floor(coord / PARQUET_TILE_DEG)`` cast
    to ``Int16``. The tile columns are dropped before this returns -- they
    are NOT written to parquet. Their only purpose is to make row groups
    spatially contiguous in BOTH dimensions, so DuckDB row-group min/max
    statistics become tight on latitude AND longitude (not just latitude as
    in the v0.5.0 single-axis sort). This enables row-group pruning for
    queries like ``WHERE lat BETWEEN ... AND lon BETWEEN ...``.
    """
    return (
        df.with_columns(
            [
                (pl.col("latitude") // PARQUET_TILE_DEG).cast(pl.Int16).alias("_lat_tile"),
                (pl.col("longitude") // PARQUET_TILE_DEG).cast(pl.Int16).alias("_lon_tile"),
            ]
        )
        .sort(["_lat_tile", "_lon_tile", "latitude", "longitude", "hour_utc"])
        .drop(["_lat_tile", "_lon_tile"])
    )


def _sort_for_storage(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the canonical intra-file sort, skipping columns that aren't present.

    When latitude+longitude are both present, delegates to
    :func:`_compute_sort_keys` for the tile-aware 2D sort. Otherwise falls
    back to a plain sort on whichever of ``PARQUET_SORT_COLS`` are present
    (legacy / test DataFrames that omit the spatial keys).
    """
    if "latitude" in df.columns and "longitude" in df.columns:
        return _compute_sort_keys(df)
    sort_cols = [c for c in PARQUET_SORT_COLS if c in df.columns]
    if not sort_cols:
        return df
    return df.sort(sort_cols)


def _read_partition_payload(
    files: list[Path], logger: logging.Logger | None = None
) -> pl.DataFrame:
    """Read all parquet files in a partition into a single DataFrame.

    The date column is excluded -- partition files don't carry it (it lives
    in the directory name). Schemas across files may differ (variable-split
    chunks), so we use ``diagonal_relaxed`` concat to align them with nulls.

    **Corrupt-file resilience.** A parquet file left half-written by a
    crashed/killed prior run reads as "Invalid thrift" / "must end with
    PAR1". Because ERA5/ERA5-LAND data is immutable and the merge that
    follows rewrites the whole partition, a corrupt existing file is
    treated as *absent*: we log a warning and skip it. The caller passes
    every existing file (including the corrupt one) to
    ``_replace_partition_files``, which deletes them after the clean
    rewrite -- so the partition self-heals on the next write.
    """
    log = logger or logging.getLogger(__name__)
    parts: list[pl.DataFrame] = []
    for p in files:
        try:
            parts.append(pl.read_parquet(p))
        except Exception as exc:
            log.warning(
                "Skipping unreadable partition file %s (will be replaced on "
                "merge): %s",
                p,
                exc,
            )
    if not parts:
        return pl.DataFrame()
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
    parquet_dir: Path,
    date_str: str,
    df: pl.DataFrame,
    old_files: list[Path],
    compression: Literal["snappy", "zstd", "gzip"],
    logger: logging.Logger,
    row_group_size: int = 100_000,
) -> None:
    """Write ``df`` as the sole content of the partition ``date=<date_str>/``.

    Sequence: write-new -> delete-old. A crash between the two leaves
    partial duplication, which the next ``merge_into_partitioned_parquet``
    call cleans up (the merge is idempotent on duplicate keys).

    The new file is named ``<dataset>_<YYYY-MM-DD>_part-NNN.parquet`` where
    NNN is zero-padded to 3 digits. In normal merge-on-write flow only
    ``_part-001`` exists; higher numbers exist only transiently if a prior
    write left stragglers that haven't been cleaned up yet.
    """
    partition_dir = parquet_dir / f"date={date_str}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    new_file = partition_dir / _compute_part_name(parquet_dir, date_str)
    df.write_parquet(new_file, compression=compression, row_group_size=row_group_size)
    for old in old_files:
        if old == new_file:
            # Edge case: an old file already had the canonical name; we just
            # overwrote it in place via the same Path.
            continue
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not delete old partition file %s: %s", old, exc)


def _compute_part_name(parquet_dir: Path, date_str: str) -> str:
    """Build ``<dataset>_<YYYY-MM-DD>_part-001.parquet``.

    ``dataset`` is derived from ``parquet_dir.name`` -- by the canonical
    layout in :func:`era5_etl.storage.paths.resolve_dataset_dir`, the
    parquet directory of a dataset is named after the dataset itself
    (e.g., ``era5-land``).
    """
    dataset = parquet_dir.name
    return f"{dataset}_{date_str}_part-001.parquet"


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

    def _default_union_by_name(self) -> bool:
        """Non-grid sources (INMET) default to ``union_by_name=true``.

        Each ``station=<id>/<id>_<year>.parquet`` is written independently
        from a CSV format that drifts across years, so combining by column
        name (not position) is the safe default. Unknown/unregistered
        dataset names fall back to ``False`` (grid behaviour).
        """
        try:
            from era5_etl.datasets import DatasetRegistry

            return not DatasetRegistry.get(self.dataset).is_gridded
        except Exception:
            return False

    def create_duckdb_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
        *,
        union_by_name: bool | None = None,
    ) -> None:
        """Create or replace a DuckDB VIEW pointing at this dataset's Parquet files.

        ``union_by_name`` adds ``union_by_name=true`` to ``read_parquet``:
        files are combined by **column name** rather than position, so a
        per-file schema that gains/loses/reorders a column still unions
        cleanly (missing columns become NULL). ``None`` (the default)
        derives it from the dataset: station sources (INMET) -> True,
        gridded ERA5/ERA5-LAND -> False. Pass an explicit bool to override.
        So every view-creation site (pipeline, ``era5 query``, web query)
        gets the right behaviour for INMET without each passing the flag.
        """
        if union_by_name is None:
            union_by_name = self._default_union_by_name()
        glob_pattern = self.get_glob_pattern()
        files = list(self.parquet_dir.rglob("*.parquet"))
        if not files:
            raise ValueError(f"No Parquet files found in {self.parquet_dir}")

        opts = "hive_partitioning=true"
        if union_by_name:
            opts += ", union_by_name=true"
        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM read_parquet(
                '{glob_pattern}',
                {opts}
            )
        """
        conn.execute(sql)
        self.logger.info(
            "Created VIEW %s from %d Parquet files (union_by_name=%s)",
            view_name,
            len(files),
            union_by_name,
        )

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
        row_group_size: int = 100_000,
    ) -> None:
        """Write ``df`` into the dataset's date-partitioned layout, deduping.

        See :func:`merge_into_partitioned_parquet` for the full contract.
        """
        merge_into_partitioned_parquet(
            df, self.parquet_dir, compression, self.logger, row_group_size
        )

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
            deduped = _sort_for_storage(deduped)
            # Recover the date string from "date=YYYY-MM-DD/"
            date_str = partition_dir.name.removeprefix("date=")
            _replace_partition_files(
                self.parquet_dir,
                date_str,
                deduped,
                files,
                compression,
                self.logger,
                100_000,
            )
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
