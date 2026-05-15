"""Tests for v0.6.0 phase 2: tile-based sort.

Behaviour under test:

1. ``merge_into_partitioned_parquet`` sorts rows by transient
   ``(_lat_tile, _lon_tile, latitude, longitude, hour_utc)`` keys, then
   drops the tile columns before writing. The on-disk schema must NOT
   contain the tile columns, but row groups must have tight 2D min/max
   stats on both latitude and longitude.

2. Two parallel writers targeting the SAME date partition serialise behind
   a per-partition ``filelock`` instead of racing on the parquet read /
   write / delete cycle (which previously produced "must end with PAR1" or
   Windows mmap "os error 1224" failures).

The coverage index is no longer updated inline by the writer (DuckDB only
allows one writer per file, which broke under parallel conversion). It is
refreshed once at the end of the pipeline by the ``RefreshCoverageStage``;
see ``tests/test_coverage_index.py::test_ensure_coverage_index_rebuilds``
for the equivalent end-to-end test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pyarrow.parquet as pq
import pytest

from era5_etl.storage import parquet_manager as pm_module
from era5_etl.storage.coverage import COVERAGE_DB_FILENAME, CoverageIndex
from era5_etl.storage.parquet_manager import (
    PARQUET_TILE_DEG,
    ParquetManager,
    merge_into_partitioned_parquet,
)
from era5_etl.storage.paths import resolve_dataset_dir

if TYPE_CHECKING:
    from pathlib import Path


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _grid_df(
    *,
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    step: float = 0.1,
    date_str: str = "2024-01-01",
    hour: int = 12,
    var_name: str = "t2m",
    var_value: float = 273.15,
) -> pl.DataFrame:
    """Build a synthetic dense lat/lon grid for write tests."""
    lats: list[float] = []
    lons: list[float] = []
    lat = lat_range[0]
    while lat <= lat_range[1] + 1e-9:
        lon = lon_range[0]
        while lon <= lon_range[1] + 1e-9:
            lats.append(round(lat, 3))
            lons.append(round(lon, 3))
            lon += step
        lat += step
    return pl.DataFrame(
        {
            "latitude": lats,
            "longitude": lons,
            "date": [date_str] * len(lats),
            "hour_utc": [hour] * len(lats),
            var_name: [var_value] * len(lats),
        }
    )


# ----------------------------------------------------------------------
# Test 1 -- transient tile columns must NOT reach the parquet file
# ----------------------------------------------------------------------


def test_tile_sort_drops_transient_cols(tmp_path: Path) -> None:
    """Written parquet must have NO ``_lat_tile`` or ``_lon_tile`` columns."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _grid_df(lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5))
    manager.write_dataframe(df)

    files = manager.list_parquet_files()
    assert len(files) == 1
    readback = pl.read_parquet(files[0])

    # Schema is exactly what callers expect: no tile leakage.
    assert "_lat_tile" not in readback.columns
    assert "_lon_tile" not in readback.columns
    # And the file contains the expected payload columns + hour_utc + var.
    assert set(readback.columns) == {"latitude", "longitude", "hour_utc", "t2m"}


# ----------------------------------------------------------------------
# Test 2 -- 2D row-group min/max stats must be tile-tight on longitude
# ----------------------------------------------------------------------


def test_tile_sort_produces_tight_2d_row_group_stats(tmp_path: Path) -> None:
    """After the tile sort, longitude min/max stats per row group must be
    bounded by the tile size for the vast majority of row groups.

    With a plain ``sort([latitude, longitude])`` (the v0.5.0 behaviour) every
    row group covers a thin lat slice across the WHOLE longitude range --
    DuckDB cannot prune any row group for a longitude filter. With the tile
    sort, rows are ordered into 5deg x 5deg tiles, so when a row group fits
    inside one (lat-tile, lon-tile) cell its lon span collapses to ~5deg.

    Setup: 30deg x 30deg grid at 0.2deg step (151 x 151 = 22 801 rows) into
    6 x 6 = 36 tiles. Each tile-cell holds ~625 rows; a row_group_size of
    200 ensures multiple row groups land inside each cell so most have a
    lon span of one tile (~5deg). Row groups that straddle a lat-tile
    boundary span the full lon range (lon resets from ~max back to ~min
    when lat-tile increments), but those are a small minority.
    """
    manager = ParquetManager(tmp_path, "era5-land")
    df = _grid_df(lat_range=(-45.0, -15.0), lon_range=(-75.0, -45.0), step=0.2)
    manager.write_dataframe(df, row_group_size=200)

    file = next((manager.parquet_dir / "date=2024-01-01").glob("*.parquet"))
    meta = pq.ParquetFile(file).metadata
    assert meta.num_row_groups >= 2, "Need multiple row groups for the test to be meaningful"

    schema_names = [meta.schema.column(i).name for i in range(meta.num_columns)]
    lon_idx = schema_names.index("longitude")

    spans: list[float] = []
    for i in range(meta.num_row_groups):
        stats = meta.row_group(i).column(lon_idx).statistics
        assert stats is not None and stats.has_min_max
        spans.append(stats.max - stats.min)

    full_lon_range = 30.0  # -75..-45
    # With tile sort, row groups fall into three buckets:
    #   - inside one tile cell: span ~= PARQUET_TILE_DEG (~5deg)  -- the majority
    #   - straddling adjacent lon-tiles: span ~= 2 * PARQUET_TILE_DEG (~10deg)
    #   - straddling a lat-tile boundary: span ~= full_lon_range (~30deg)
    # Without the tile sort EVERY row group would land in the third bucket
    # (full lon range). We require >= 80% of row groups to span <= 2 tiles.
    two_tiles_cap = PARQUET_TILE_DEG * 2 + 1.0  # 11 deg -- two tiles + slack
    tight = sum(1 for span in spans if span <= two_tiles_cap)
    fraction_tight = tight / len(spans)
    assert fraction_tight >= 0.8, (
        f"Only {fraction_tight:.0%} of {len(spans)} row groups span <= "
        f"{two_tiles_cap}deg longitude. Spans: {spans}. Without tile sort, "
        f"every row group would span the full range ({full_lon_range}deg) -- "
        f"the tile sort (PARQUET_TILE_DEG={PARQUET_TILE_DEG}) is not in effect."
    )

    # And the average span must be a fraction of the full range -- proves
    # DuckDB pruning will be effective (vs no pruning at all without tile sort).
    avg_span = sum(spans) / len(spans)
    assert avg_span < full_lon_range / 3, (
        f"Average row-group lon span ({avg_span:.1f}deg) is not meaningfully "
        f"smaller than full range ({full_lon_range}deg)."
    )


# ----------------------------------------------------------------------
# Test 3 -- merge-on-key dedup contract still holds with tile sort
# ----------------------------------------------------------------------


def test_tile_sort_preserves_dedup_within_partition(tmp_path: Path) -> None:
    """Two overlapping writes to the same partition must collapse to one row
    per (lat, lon, hour) cell, latest values winning. This is the v0.5.0
    dedup contract; the tile sort must not break it.
    """
    manager = ParquetManager(tmp_path, "era5-land")

    # Same lat/lon/hour/date in both writes; only the value differs.
    a = _grid_df(lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5), var_value=300.0)
    b = _grid_df(lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5), var_value=310.0)

    manager.write_dataframe(a)
    manager.write_dataframe(b)

    files = manager.list_parquet_files()
    assert len(files) == 1
    final = pl.read_parquet(files[0])

    # Exactly one row per (lat, lon, hour_utc).
    keys = final.select(["latitude", "longitude", "hour_utc"])
    assert len(keys) == len(keys.unique())
    assert len(final) == len(a)
    # New write wins.
    assert (final["t2m"] == 310.0).all()


# ----------------------------------------------------------------------
# Test 4 -- coverage index is updated after a successful merge
# ----------------------------------------------------------------------


def test_merge_does_NOT_create_coverage_db(tmp_path: Path) -> None:
    """Inverse of the v0.6.0-phase-2 hook: writes must NOT touch
    ``_coverage.duckdb`` anymore. Coverage is updated by the pipeline-level
    ``RefreshCoverageStage`` after parallel conversion completes, so the
    DB doesn't exist after a bare ``merge_into_partitioned_parquet`` call.
    """
    parquet_dir = resolve_dataset_dir(tmp_path, "era5-land")
    df = _grid_df(
        lat_range=(-22.0, -21.8),
        lon_range=(-44.0, -43.8),
        step=0.1,
        hour=12,
        var_name="t2m",
        var_value=290.0,
    )
    merge_into_partitioned_parquet(df, parquet_dir)

    cov_db = parquet_dir / COVERAGE_DB_FILENAME
    assert not cov_db.exists(), (
        f"Coverage DB should NOT be created by the writer; found {cov_db}"
    )


def test_concurrent_writes_to_same_partition_serialise(tmp_path: Path) -> None:
    """Two threads writing into the same date partition must serialise via
    the per-partition file lock; both writes should land and produce a
    deduplicated parquet (no PAR1 / mmap collisions).
    """
    import threading

    parquet_dir = resolve_dataset_dir(tmp_path, "era5-land")
    df_a = _grid_df(
        lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), hour=0, var_value=10.0
    )
    df_b = _grid_df(
        lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), hour=12, var_value=20.0
    )
    errors: list[Exception] = []

    def _worker(df: pl.DataFrame) -> None:
        try:
            merge_into_partitioned_parquet(df, parquet_dir)
        except Exception as exc:  # noqa: BLE001 -- collected for the assertion below
            errors.append(exc)

    t_a = threading.Thread(target=_worker, args=(df_a,))
    t_b = threading.Thread(target=_worker, args=(df_b,))
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)

    assert not errors, f"Concurrent writes raised: {errors}"

    files = sorted((parquet_dir / "date=2024-01-01").glob("*.parquet"))
    assert len(files) == 1, f"Expected single merged file; found {files}"
    readback = pl.read_parquet(files[0]).sort(["hour_utc", "latitude", "longitude"])
    # Both writers' rows must be present (4 cells x 2 hours = 8 rows).
    assert len(readback) == 2 * len(df_a), (
        f"Expected {2 * len(df_a)} rows, got {len(readback)}"
    )
    assert set(readback["hour_utc"].to_list()) == {0, 12}
