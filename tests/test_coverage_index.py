"""Tests for the per-dataset Coverage Index (v0.6.0 phase 1).

The CoverageIndex tracks which (latitude, longitude, date, variable) cells
exist in local storage with a 24-bit hours bitmap. It is the foundation for
inventory queries, smart-diff downloads, and the future map UI.

Tests use ``tmp_path`` exclusively -- no production data is ever touched.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from era5_etl.storage.coverage import CoverageIndex, ensure_coverage_index
from era5_etl.storage.parquet_manager import merge_into_partitioned_parquet
from era5_etl.storage.paths import resolve_dataset_dir

if TYPE_CHECKING:
    from pathlib import Path


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _grid_df(
    *,
    lats: list[float],
    lons: list[float],
    hours: list[int],
    date_str: str = "2024-01-01",
    variables: dict[str, float] | None = None,
) -> pl.DataFrame:
    """Build a synthetic per-hour grid DataFrame for upsert tests.

    Cartesian product of ``lats x lons x hours``. Each variable column is set
    to a constant value (or its provided value).
    """
    if variables is None:
        variables = {"t2m": 273.15}

    rows_lat: list[float] = []
    rows_lon: list[float] = []
    rows_hour: list[int] = []
    for lat in lats:
        for lon in lons:
            for hour in hours:
                rows_lat.append(lat)
                rows_lon.append(lon)
                rows_hour.append(hour)

    n = len(rows_lat)
    data: dict[str, list] = {
        "latitude": rows_lat,
        "longitude": rows_lon,
        "hour_utc": rows_hour,
        "date": [date_str] * n,
    }
    for var_name, var_value in variables.items():
        data[var_name] = [var_value] * n
    return pl.DataFrame(data)


def _bits(positions: list[int]) -> int:
    """OR together ``1 << p`` for each ``p`` in ``positions``."""
    out = 0
    for p in positions:
        out |= 1 << p
    return out


# ----------------------------------------------------------------------
# 1. Schema / lifecycle
# ----------------------------------------------------------------------


def test_creates_db_and_schema(tmp_path: Path) -> None:
    """Instantiating CoverageIndex + first method call creates the DuckDB file
    with the expected schema and `coverage_meta` row.
    """
    cov = CoverageIndex("era5-land", tmp_path)

    # Path is computed via resolve_dataset_dir
    expected = resolve_dataset_dir(tmp_path, "era5-land") / "_coverage.duckdb"
    assert cov.db_path == expected
    assert not cov.db_path.exists()  # lazy

    # First method call should create the file + schema.
    stats = cov.stats()
    assert cov.db_path.exists()
    assert stats["n_cells"] == 0
    assert stats["total_rows"] == 0

    # Verify the meta row is present. Close the writer first so a separate
    # read-only connection isn't refused by DuckDB.
    cov.close()

    import duckdb

    with duckdb.connect(str(cov.db_path), read_only=True) as conn:
        version = conn.execute(
            "SELECT value FROM coverage_meta WHERE key = 'schema_version'"
        ).fetchone()
        assert version == ("1",)


# ----------------------------------------------------------------------
# 2-6. upsert_from_dataframe behavior
# ----------------------------------------------------------------------


def test_upsert_single_variable(tmp_path: Path) -> None:
    """1 var, 1 date, 4 specific hours -> 1 row with the correct hours_mask."""
    df = _grid_df(
        lats=[-22.5],
        lons=[-43.5],
        hours=[0, 3, 12, 18],
        variables={"t2m": 295.0},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        rows = cov.upsert_from_dataframe(df)
        assert rows == 1

        detail = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        assert detail.height == 1
        row = detail.row(0, named=True)
        assert row["variable"] == "t2m"
        assert row["date"] == date(2024, 1, 1)
        assert row["hours_mask"] == _bits([0, 3, 12, 18])


def test_upsert_multiple_variables(tmp_path: Path) -> None:
    """2 vars -> 2 rows per (lat, lon, date), each with its own mask."""
    df = _grid_df(
        lats=[-22.5],
        lons=[-43.5],
        hours=[0, 6, 12, 18],
        variables={"t2m": 295.0, "tp": 0.001},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        rows = cov.upsert_from_dataframe(df)
        # 1 cell x 2 variables = 2 rows.
        assert rows == 2

        detail = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        assert detail.height == 2
        variables = sorted(detail["variable"].to_list())
        assert variables == ["t2m", "tp"]

        for v in variables:
            row = detail.filter(pl.col("variable") == v).row(0, named=True)
            assert row["hours_mask"] == _bits([0, 6, 12, 18])


def test_upsert_idempotent(tmp_path: Path) -> None:
    """Upserting same DataFrame twice produces the same hours_mask
    (OR with itself is a no-op).
    """
    df = _grid_df(lats=[-22.5], lons=[-43.5], hours=[5, 10, 15])

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df)
        first = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        first_mask = first.row(0, named=True)["hours_mask"]

        cov.upsert_from_dataframe(df)
        second = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        assert second.height == 1  # still one row
        assert second.row(0, named=True)["hours_mask"] == first_mask
        assert first_mask == _bits([5, 10, 15])


def test_upsert_accumulates_hours(tmp_path: Path) -> None:
    """Upsert hours [0, 1] then [12, 13] for same cell+var -> mask has all 4 bits."""
    df_first = _grid_df(lats=[-22.5], lons=[-43.5], hours=[0, 1])
    df_second = _grid_df(lats=[-22.5], lons=[-43.5], hours=[12, 13])

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_first)
        cov.upsert_from_dataframe(df_second)

        detail = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        assert detail.height == 1
        mask = detail.row(0, named=True)["hours_mask"]
        assert mask == _bits([0, 1, 12, 13])


def test_upsert_with_null_values(tmp_path: Path) -> None:
    """When a variable column has NULLs at some hours, those hours are NOT
    included in the mask for that variable.
    """
    # Build by hand to inject nulls at hours 5 and 17.
    df = pl.DataFrame({
        "latitude": [-22.5] * 4,
        "longitude": [-43.5] * 4,
        "hour_utc": [0, 5, 12, 17],
        "date": ["2024-01-01"] * 4,
        "t2m": [273.0, None, 280.0, None],
    })

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df)
        detail = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        mask = detail.row(0, named=True)["hours_mask"]
        # Only hours 0 and 12 have non-null t2m.
        assert mask == _bits([0, 12])


def test_upsert_rolls_back_on_failure(tmp_path: Path) -> None:
    """A failure mid-loop must roll back any prior variables upserted in the
    same call -- nothing partially committed.
    """
    df = _grid_df(
        lats=[-22.5],
        lons=[-43.5],
        hours=[0, 12],
        variables={"t2m": 295.0, "tp": 0.001},
    )

    class _FlakyConn:
        """Proxy that delegates to a real DuckDB connection but raises on the
        second ``INSERT INTO coverage`` to simulate a mid-loop failure.
        """

        def __init__(self, real):  # type: ignore[no-untyped-def]
            self._real = real
            self._insert_calls = 0

        def execute(self, sql: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if sql.lstrip().startswith("INSERT INTO coverage"):
                self._insert_calls += 1
                if self._insert_calls == 2:
                    raise RuntimeError("simulated mid-loop failure")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._real, name)

    with CoverageIndex("era5-land", tmp_path) as cov:
        # Force schema creation so the underlying connection exists, then
        # wrap it with the flaky proxy.
        cov.stats()
        assert cov._conn is not None  # noqa: SLF001
        real_conn = cov._conn  # noqa: SLF001
        cov._conn = _FlakyConn(real_conn)  # type: ignore[assignment]  # noqa: SLF001
        try:
            with pytest.raises(RuntimeError, match="simulated mid-loop failure"):
                cov.upsert_from_dataframe(df)
        finally:
            cov._conn = real_conn  # noqa: SLF001

        # Rollback must have wiped the first variable's insert as well.
        assert cov.stats()["total_rows"] == 0


# ----------------------------------------------------------------------
# 7-9. query_grid_points
# ----------------------------------------------------------------------


def test_query_grid_points_no_filter(tmp_path: Path) -> None:
    """Without filters, returns each (lat, lon) once with correct days/vars counts."""
    df_a = _grid_df(
        lats=[-22.5, -22.0],
        lons=[-43.5],
        hours=[0, 12],
        date_str="2024-01-01",
        variables={"t2m": 1.0, "tp": 0.0},
    )
    df_b = _grid_df(
        lats=[-22.5, -22.0],
        lons=[-43.5],
        hours=[0, 12],
        date_str="2024-01-02",
        variables={"t2m": 1.0},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_a)
        cov.upsert_from_dataframe(df_b)

        grid = cov.query_grid_points()
        assert grid.height == 2  # two distinct (lat, lon) cells
        # Each cell appears on 2 dates with "t2m" (and tp on date 1 only).
        for row in grid.iter_rows(named=True):
            assert row["days"] == 2
            assert row["vars"] == 2


def test_query_grid_points_date_range(tmp_path: Path) -> None:
    """date_from / date_to filters narrow the result correctly."""
    df_jan = _grid_df(lats=[-22.5], lons=[-43.5], hours=[0], date_str="2024-01-01")
    df_feb = _grid_df(lats=[-22.5], lons=[-43.5], hours=[0], date_str="2024-02-01")
    df_mar = _grid_df(lats=[-22.5], lons=[-43.5], hours=[0], date_str="2024-03-01")

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_jan)
        cov.upsert_from_dataframe(df_feb)
        cov.upsert_from_dataframe(df_mar)

        grid = cov.query_grid_points(date_from=date(2024, 2, 1), date_to=date(2024, 2, 28))
        assert grid.height == 1
        assert grid.row(0, named=True)["days"] == 1

        grid_all = cov.query_grid_points()
        assert grid_all.row(0, named=True)["days"] == 3


def test_query_grid_points_variable_filter(tmp_path: Path) -> None:
    """Variable filter narrows the result correctly."""
    df = _grid_df(
        lats=[-22.5, -22.0],
        lons=[-43.5],
        hours=[0],
        variables={"t2m": 1.0, "tp": 0.0},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df)

        # Both cells exist for either variable.
        grid_t2m = cov.query_grid_points(variable="t2m")
        assert grid_t2m.height == 2
        for row in grid_t2m.iter_rows(named=True):
            assert row["vars"] == 1

        # Unknown variable -> empty result.
        grid_none = cov.query_grid_points(variable="nonexistent")
        assert grid_none.height == 0


# ----------------------------------------------------------------------
# 10-11. query_cell_detail
# ----------------------------------------------------------------------


def test_query_cell_detail(tmp_path: Path) -> None:
    """For a specific cell, returns one row per (date, variable) ordered."""
    df_a = _grid_df(
        lats=[-22.5],
        lons=[-43.5],
        hours=[0],
        date_str="2024-01-01",
        variables={"t2m": 1.0, "tp": 0.0},
    )
    df_b = _grid_df(
        lats=[-22.5],
        lons=[-43.5],
        hours=[0],
        date_str="2024-01-02",
        variables={"t2m": 1.0},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_a)
        cov.upsert_from_dataframe(df_b)

        detail = cov.query_cell_detail(latitude=-22.5, longitude=-43.5)
        # 2 dates x (2 vars on day 1, 1 var on day 2) = 3 rows.
        assert detail.height == 3
        # Ordered by (date, variable).
        dates = detail["date"].to_list()
        assert dates == sorted(dates)


def test_query_cell_detail_unknown_cell(tmp_path: Path) -> None:
    """Unknown cell -> empty DataFrame, no exception."""
    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(
            _grid_df(lats=[-22.5], lons=[-43.5], hours=[0]),
        )

        detail = cov.query_cell_detail(latitude=99.0, longitude=99.0)
        assert detail.height == 0
        assert "date" in detail.columns
        assert "variable" in detail.columns
        assert "hours_mask" in detail.columns


# ----------------------------------------------------------------------
# 12-14. diff()
# ----------------------------------------------------------------------


def test_diff_full_coverage(tmp_path: Path) -> None:
    """Request fully covered by what's stored -> diff returns 0 rows."""
    df = _grid_df(lats=[-22.5], lons=[-43.5], hours=[12, 18])

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df)

        request = pl.DataFrame({
            "latitude": [-22.5],
            "longitude": [-43.5],
            "date": [date(2024, 1, 1)],
            "variable": ["t2m"],
            "requested_mask": [_bits([12, 18])],
        })
        diff = cov.diff(request)
        assert diff.height == 0


def test_diff_partial_coverage(tmp_path: Path) -> None:
    """Hour 12 covered, hour 18 not -> 1 row with missing_mask = bit 18."""
    df_have = _grid_df(lats=[-22.5], lons=[-43.5], hours=[12])

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_have)

        request = pl.DataFrame({
            "latitude": [-22.5],
            "longitude": [-43.5],
            "date": [date(2024, 1, 1)],
            "variable": ["t2m"],
            "requested_mask": [_bits([12, 18])],
        })
        diff = cov.diff(request)
        assert diff.height == 1
        row = diff.row(0, named=True)
        assert row["missing_mask"] == _bits([18])


def test_diff_unknown_cell(tmp_path: Path) -> None:
    """Cell not present in coverage -> missing_mask equals requested_mask."""
    with CoverageIndex("era5-land", tmp_path) as cov:
        request = pl.DataFrame({
            "latitude": [10.0],
            "longitude": [20.0],
            "date": [date(2024, 1, 1)],
            "variable": ["t2m"],
            "requested_mask": [_bits([0, 6, 12, 18])],
        })
        diff = cov.diff(request)
        assert diff.height == 1
        assert diff.row(0, named=True)["missing_mask"] == _bits([0, 6, 12, 18])


# ----------------------------------------------------------------------
# 15. region summary
# ----------------------------------------------------------------------


def test_query_region_summary_basic(tmp_path: Path) -> None:
    """4 points forming a square, polygon contains them all -> n_points=4."""
    # Place 4 points around (-22, -43). Cartesian product of 2 lats x 2 lons.
    df = _grid_df(
        lats=[-22.5, -21.5],
        lons=[-43.5, -42.5],
        hours=[0, 12],
        variables={"t2m": 1.0, "tp": 0.0},
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df)

        # Polygon: square from (-23, -44) to (-21, -42), should enclose all 4 points.
        polygon_lats = [-23.0, -23.0, -21.0, -21.0, -23.0]
        polygon_lons = [-44.0, -42.0, -42.0, -44.0, -44.0]
        summary = cov.query_region_summary(polygon_lats, polygon_lons)

        assert summary["n_points"] == 4
        assert summary["date_range"] is not None
        assert summary["vars_per_cell_avg"] == pytest.approx(2.0)
        assert summary["gaps"] == []  # 100% of cells have both vars on the day

        # A polygon that excludes all 4 -> n_points = 0.
        summary_empty = cov.query_region_summary(
            [10.0, 10.0, 11.0, 11.0, 10.0],
            [10.0, 11.0, 11.0, 10.0, 10.0],
        )
        assert summary_empty["n_points"] == 0
        assert summary_empty["date_range"] is None


# ----------------------------------------------------------------------
# 16. stats()
# ----------------------------------------------------------------------


def test_stats(tmp_path: Path) -> None:
    """stats() returns all expected keys with sensible values."""
    with CoverageIndex("era5-land", tmp_path) as cov:
        # Empty.
        empty = cov.stats()
        for key in ("n_cells", "n_dates", "n_variables", "total_rows", "db_size_bytes"):
            assert key in empty
        assert empty["total_rows"] == 0
        assert empty["db_size_bytes"] >= 0  # the DuckDB file may be small but exists

        # Insert some data.
        cov.upsert_from_dataframe(
            _grid_df(
                lats=[-22.5, -22.0],
                lons=[-43.5],
                hours=[0, 12],
                variables={"t2m": 1.0, "tp": 0.0},
            )
        )
        s = cov.stats()
        assert s["n_cells"] == 2
        assert s["n_dates"] == 1
        assert s["n_variables"] == 2
        assert s["total_rows"] == 4  # 2 cells x 2 vars


# ----------------------------------------------------------------------
# 17. ensure_coverage_index helper
# ----------------------------------------------------------------------


def test_ensure_coverage_index_rebuilds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Given parquet files exist but no _coverage.duckdb, the hook rebuilds
    and ends with stats > 0.
    """
    dataset = "era5-land"
    parquet_dir = resolve_dataset_dir(tmp_path, dataset)

    # Lay down a real partitioned parquet file via the canonical write path.
    df = _grid_df(
        lats=[-22.5, -22.0],
        lons=[-43.5],
        hours=[0, 12],
        date_str="2024-01-01",
        variables={"t2m": 273.0},
    )
    merge_into_partitioned_parquet(df, parquet_dir)

    # The writer no longer touches the coverage index (it would race with
    # itself under parallel conversion). The DB is created by the
    # pipeline-level RefreshCoverageStage OR by ``ensure_coverage_index``
    # which is what we exercise here.
    db_path = parquet_dir / "_coverage.duckdb"
    assert not db_path.exists()

    caplog.set_level(logging.INFO)
    rebuilt = ensure_coverage_index(dataset, tmp_path)
    assert rebuilt is True
    assert db_path.exists()

    with CoverageIndex(dataset, tmp_path) as cov:
        s = cov.stats()
        assert s["total_rows"] > 0
        assert s["n_cells"] == 2

    # Second call is a no-op (file already exists, has rows).
    rebuilt_again = ensure_coverage_index(dataset, tmp_path)
    assert rebuilt_again is False
