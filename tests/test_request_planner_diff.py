"""Tests for the cell-level smart-diff request planner (``plan_with_diff``).

These exercise the v0.6.0 phase 3 behaviour: given a CoverageIndex that
already tracks some cells on disk, ``plan_with_diff`` must subtract them
from the planned chunks. When nothing is covered the result is byte-equal
to ``plan_requests``; when everything is covered the result is empty.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest

from era5_etl.config import DownloadConfig
from era5_etl.download.request_planner import (
    RequestChunk,
    _hours_to_mask,
    plan_requests,
    plan_with_diff,
)
from era5_etl.storage.coverage import CoverageIndex

if TYPE_CHECKING:
    from pathlib import Path

MB = 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(
    *,
    dataset: str = "era5-land",
    variables: list[str] | None = None,
    area: list[float] | None = None,
    hours: list[str] | None = None,
    start: str = "2024-01-01",
    end: str = "2024-01-02",
    max_request_bytes: int = 500 * MB,
) -> DownloadConfig:
    """Build a small, valid DownloadConfig for planning tests."""
    cfg = DownloadConfig(
        output_dir="./_unused",
        dataset=dataset,
        variables=variables or ["2m_temperature"],
        start_date=start,
        end_date=end,
        # 2x2 cells at 0.1deg.
        area=area if area is not None else [-10.0, -50.0, -10.2, -49.9],
        hours=hours or ["00:00", "12:00"],
        max_request_bytes=500 * MB,
    )
    cfg.max_request_bytes = max_request_bytes
    return cfg


def _coverage_df(
    *,
    lats: list[float],
    lons: list[float],
    hours: list[int],
    dates: list[str],
    variable: str = "2m_temperature",
) -> pl.DataFrame:
    """Build a per-hour DF compatible with ``CoverageIndex.upsert_from_dataframe``."""
    rows_lat: list[float] = []
    rows_lon: list[float] = []
    rows_hour: list[int] = []
    rows_date: list[str] = []
    for lat in lats:
        for lon in lons:
            for d in dates:
                for hour in hours:
                    rows_lat.append(lat)
                    rows_lon.append(lon)
                    rows_hour.append(hour)
                    rows_date.append(d)
    n = len(rows_lat)
    return pl.DataFrame(
        {
            "latitude": rows_lat,
            "longitude": rows_lon,
            "hour_utc": rows_hour,
            "date": rows_date,
            variable: [273.15] * n,
        }
    )


def _populate_coverage(
    tmp_path: "Path",
    dataset: str,
    df: pl.DataFrame,
) -> None:
    """Open the CoverageIndex and upsert ``df`` (closes the connection)."""
    with CoverageIndex(dataset, tmp_path) as cov:
        cov.upsert_from_dataframe(df)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_coverage_returns_empty(tmp_path: "Path") -> None:
    """Every requested cell is already in the coverage index -> []."""
    cfg = _make_cfg(
        # snap_area_to_grid([-10.0, -50.0, -10.2, -49.9], 0.1) == same input
        # -> 2x2 cells with centres at lat={-10.15,-10.05}, lon={-49.95,-49.85}.
        # Using -49.8 here would float-drift to -49.7 and yield 3 lon cells.
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-01",
    )

    # Cells at 0.1deg resolution inside the snapped bbox.
    # Snapped lats S=-10.2, N=-10.0 -> centres -10.15, -10.05
    # Snapped lons W=-50.0, E=-49.8 -> centres -49.95, -49.85
    df = _coverage_df(
        lats=[-10.15, -10.05],
        lons=[-49.95, -49.85],
        hours=[0, 12],
        dates=["2024-01-01"],
    )
    _populate_coverage(tmp_path, cfg.dataset, df)

    chunks = plan_with_diff(cfg, tmp_path)
    assert chunks == []


def test_zero_coverage_returns_full_plan(tmp_path: "Path") -> None:
    """When the coverage index exists but has nothing relevant, fall back to
    the plain plan_requests output (byte-equal chunk_ids).
    """
    cfg = _make_cfg(
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-02",
    )

    # Populate coverage with completely unrelated cells (different lat).
    df = _coverage_df(
        lats=[5.0],
        lons=[0.0],
        hours=[0],
        dates=["2024-01-01"],
    )
    _populate_coverage(tmp_path, cfg.dataset, df)

    diff_chunks = plan_with_diff(cfg, tmp_path)
    plain_chunks = plan_requests(cfg)

    assert len(diff_chunks) == len(plain_chunks)
    assert [c.chunk_id for c in diff_chunks] == [c.chunk_id for c in plain_chunks]
    assert [c.area for c in diff_chunks] == [c.area for c in plain_chunks]
    assert [c.hours for c in diff_chunks] == [c.hours for c in plain_chunks]
    assert [c.days for c in diff_chunks] == [c.days for c in plain_chunks]


def test_partial_coverage_skips_covered_cells(tmp_path: "Path") -> None:
    """Half the requested cells already covered -> only the uncovered half is
    planned. Verify by inspecting returned areas.
    """
    # 2x2 cell grid; cover the two SW cells fully (all requested hours).
    cfg = _make_cfg(
        # snap_area_to_grid([-10.0, -50.0, -10.2, -49.9], 0.1) == same input
        # -> 2x2 cells with centres at lat={-10.15,-10.05}, lon={-49.95,-49.85}.
        # Using -49.8 here would float-drift to -49.7 and yield 3 lon cells.
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-01",
    )

    # Cover the southern row of cells (lat = -10.15) for both lons.
    df = _coverage_df(
        lats=[-10.15],
        lons=[-49.95, -49.85],
        hours=[0, 12],
        dates=["2024-01-01"],
    )
    _populate_coverage(tmp_path, cfg.dataset, df)

    chunks = plan_with_diff(cfg, tmp_path)

    # Should yield 1 chunk for the northern row.
    assert len(chunks) >= 1
    # All chunks should sit in the northern half (S >= -10.1).
    for c in chunks:
        n, w, s, e = c.area
        assert s >= -10.1 - 1e-9, f"chunk {c.chunk_id} south boundary {s} is too far south"


def test_partial_hour_coverage(tmp_path: "Path") -> None:
    """Same (cell, date, var) but only hour 12 covered. Request asks for
    hours [0, 12] -> resulting chunk's hours = ["00:00"] only.
    """
    cfg = _make_cfg(
        # snap_area_to_grid([-10.0, -50.0, -10.2, -49.9], 0.1) == same input
        # -> 2x2 cells with centres at lat={-10.15,-10.05}, lon={-49.95,-49.85}.
        # Using -49.8 here would float-drift to -49.7 and yield 3 lon cells.
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-01",
    )

    # Cover hour 12 only, on every requested cell.
    df = _coverage_df(
        lats=[-10.15, -10.05],
        lons=[-49.95, -49.85],
        hours=[12],
        dates=["2024-01-01"],
    )
    _populate_coverage(tmp_path, cfg.dataset, df)

    chunks = plan_with_diff(cfg, tmp_path)
    assert len(chunks) == 1
    assert chunks[0].hours == ("00:00",)


def test_non_contiguous_missing_cells(tmp_path: "Path") -> None:
    """A 3x3 grid with only the center missing -> single chunk; a 3x3 grid
    with two opposite corners missing -> two chunks (one per component).
    """
    # 3x3 grid: lats centres -10.25, -10.15, -10.05; lons -49.95, -49.85, -49.75.
    cfg = _make_cfg(
        area=[-10.0, -50.0, -10.3, -49.7],
        hours=["00:00"],
        start="2024-01-01",
        end="2024-01-01",
    )

    # Cover every cell EXCEPT NW corner (-10.05, -49.95) and SE corner
    # (-10.25, -49.75). Those two missing cells are not 4-connected.
    all_lats = [-10.25, -10.15, -10.05]
    all_lons = [-49.95, -49.85, -49.75]
    pairs = [(la, lo) for la in all_lats for lo in all_lons]
    pairs.remove((-10.05, -49.95))
    pairs.remove((-10.25, -49.75))

    rows = []
    for la, lo in pairs:
        rows.append(
            {
                "latitude": la,
                "longitude": lo,
                "hour_utc": 0,
                "date": "2024-01-01",
                "2m_temperature": 273.15,
            }
        )
    df = pl.DataFrame(rows)
    _populate_coverage(tmp_path, cfg.dataset, df)

    chunks = plan_with_diff(cfg, tmp_path)
    assert len(chunks) == 2, (
        f"expected 2 non-contiguous chunks, got {len(chunks)}: "
        f"{[c.area for c in chunks]}"
    )


def test_multi_variable_diff(tmp_path: "Path") -> None:
    """Two variables; coverage has var1 fully + var2 partial -> result only has var2."""
    cfg = _make_cfg(
        variables=["2m_temperature", "surface_pressure"],
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-01",
    )

    # Cover 2m_temperature on every requested cell, hour, date.
    full_var_df = _coverage_df(
        lats=[-10.15, -10.05],
        lons=[-49.95, -49.85],
        hours=[0, 12],
        dates=["2024-01-01"],
        variable="2m_temperature",
    )
    _populate_coverage(tmp_path, cfg.dataset, full_var_df)

    # Cover surface_pressure only at hour 0 (so hour 12 still missing).
    partial_var_df = _coverage_df(
        lats=[-10.15, -10.05],
        lons=[-49.95, -49.85],
        hours=[0],
        dates=["2024-01-01"],
        variable="surface_pressure",
    )
    _populate_coverage(tmp_path, cfg.dataset, partial_var_df)

    chunks = plan_with_diff(cfg, tmp_path)
    assert len(chunks) >= 1
    vars_seen = {v for c in chunks for v in c.variables}
    assert vars_seen == {"surface_pressure"}
    # Only hour 12 should remain for surface_pressure.
    for c in chunks:
        assert c.hours == ("12:00",)


def test_split_to_fit_still_applied(tmp_path: "Path") -> None:
    """A large missing region exceeding the size budget must be split."""
    # Wide area with all 24 hours and a 31-day month -> needs splitting.
    cfg = _make_cfg(
        area=[6.0, -74.0, -34.0, -34.0],  # Brazil-ish bbox
        hours=[f"{h:02d}:00" for h in range(24)],
        start="2024-01-01",
        end="2024-01-31",
        max_request_bytes=200 * MB,
    )

    # Coverage exists for one cell only -> diff returns nearly the full
    # request, which the _split_to_fit cascade must split.
    df = _coverage_df(
        lats=[-10.05],
        lons=[-50.05],
        hours=[0],
        dates=["2024-01-01"],
    )
    _populate_coverage(tmp_path, cfg.dataset, df)

    chunks = plan_with_diff(cfg, tmp_path)
    assert len(chunks) > 1, (
        f"expected >1 chunks from _split_to_fit cascade, got {len(chunks)}"
    )


def test_plan_with_diff_no_coverage_db(tmp_path: "Path") -> None:
    """No ``_coverage.duckdb`` on disk -> identical to plan_requests."""
    cfg = _make_cfg(
        area=[-10.0, -50.0, -10.2, -49.9],
        hours=["00:00", "12:00"],
        start="2024-01-01",
        end="2024-01-02",
    )

    # tmp_path is empty -- no coverage db ever created.
    diff_chunks = plan_with_diff(cfg, tmp_path)
    plain_chunks = plan_requests(cfg)

    assert [c.chunk_id for c in diff_chunks] == [c.chunk_id for c in plain_chunks]
    assert [c.area for c in diff_chunks] == [c.area for c in plain_chunks]
    assert [c.hours for c in diff_chunks] == [c.hours for c in plain_chunks]


# ---------------------------------------------------------------------------
# Sanity check on the helpers
# ---------------------------------------------------------------------------


def test_hours_to_mask_roundtrip() -> None:
    assert _hours_to_mask(["00:00", "12:00"]) == (1 << 0) | (1 << 12)
    assert _hours_to_mask([f"{h:02d}:00" for h in range(24)]) == (1 << 24) - 1
    assert _hours_to_mask([]) == 0


# ---------------------------------------------------------------------------
# Oversized-request guard (memory-safety: must never materialise the dense
# per-cell frame for a state × decades request).
# ---------------------------------------------------------------------------


def test_request_cell_count_is_arithmetic() -> None:
    from era5_etl.download.grid import snap_area_to_grid
    from era5_etl.download.request_planner import request_cell_count

    # area snaps to 1 lat-cell × 2 lon-cells at 0.1deg; 2 dates; 1 var.
    cfg = _make_cfg(
        area=[-10.0, -50.0, -10.1, -49.9],
        start="2024-01-01",
        end="2024-01-02",
        variables=["2m_temperature"],
    )
    snapped = snap_area_to_grid(list(cfg.area), 0.1)
    n, w, s, e = snapped
    from era5_etl.download.request_planner import (
        _date_range,
        _grid_axis,
    )

    expected = (
        _grid_axis(s, n, 0.1).size
        * _grid_axis(w, e, 0.1).size
        * len(_date_range(cfg.start_date, cfg.end_date))
        * len(cfg.variables)
    )
    assert request_cell_count(cfg, 0.1, snapped) == expected
    assert expected == 1 * 2 * 2 * 1


def test_build_request_cells_rejects_oversized_fast() -> None:
    """Above DIFF_MAX_CELLS the guard raises BEFORE any allocation."""
    from era5_etl.download.grid import snap_area_to_grid
    from era5_etl.download.request_planner import (
        DIFF_MAX_CELLS,
        build_request_cells,
        request_cell_count,
    )
    from era5_etl.exceptions import DownloadSizeError

    # ~201x201 cells x ~608 days x 1 var ≈ 24.5M > 20M.
    cfg = _make_cfg(
        area=[0.0, -60.0, -20.0, -40.0],
        start="2022-01-01",
        end="2023-08-31",
        hours=["00:00"],
        variables=["2m_temperature"],
    )
    snapped = snap_area_to_grid(list(cfg.area), 0.1)
    count = request_cell_count(cfg, 0.1, snapped)
    assert count > DIFF_MAX_CELLS
    with pytest.raises(DownloadSizeError, match="cannot be materialised"):
        build_request_cells(cfg, 0.1, snapped)


def test_plan_with_diff_huge_request_falls_back_to_plan_requests(
    tmp_path: "Path",
) -> None:
    """A request too large to diff must NOT crash; it falls back to the
    size-bounded chunk plan (byte-equal to plan_requests).
    """
    cfg = _make_cfg(
        area=[0.0, -60.0, -20.0, -40.0],
        start="2022-01-01",
        end="2023-08-31",
        hours=["00:00"],
        variables=["2m_temperature"],
    )
    diff_chunks = plan_with_diff(cfg, tmp_path)
    assert diff_chunks == plan_requests(cfg)
    assert len(diff_chunks) > 0
