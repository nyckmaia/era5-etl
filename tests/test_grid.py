"""Unit tests for the grid alignment and rectangle algebra helpers."""

from __future__ import annotations

import math

import pytest

from era5_etl.download.grid import (
    Rect,
    iter_grid_cells,
    merge_rects_horizontal,
    rect_intersect,
    rect_subtract,
    rect_union_area,
    snap_area_to_grid,
)


# ---------------------------------------------------------------------------
# snap_area_to_grid
# ---------------------------------------------------------------------------


def test_snap_expands_outward_for_era5_land():
    # ERA5-Land resolution = 0.1; brazil-ish bbox with sub-grid offsets.
    snapped = snap_area_to_grid([5.05, -73.93, -34.07, -33.95], 0.1)
    assert snapped[0] == pytest.approx(5.1)
    assert snapped[1] == pytest.approx(-74.0)
    assert snapped[2] == pytest.approx(-34.1)
    assert snapped[3] == pytest.approx(-33.9)


def test_snap_expands_outward_for_era5():
    # ERA5 resolution = 0.25.
    snapped = snap_area_to_grid([5.1, -74.0, -34.1, -33.9], 0.25)
    assert snapped[0] == pytest.approx(5.25)
    assert snapped[1] == pytest.approx(-74.0)
    assert snapped[2] == pytest.approx(-34.25)
    assert snapped[3] == pytest.approx(-33.75)


def test_snap_idempotent_when_already_aligned():
    aligned = [5.0, -74.0, -34.0, -33.0]
    assert snap_area_to_grid(aligned, 0.1) == aligned
    assert snap_area_to_grid(aligned, 0.25) == aligned


def test_snap_zero_resolution_raises():
    with pytest.raises(ValueError):
        snap_area_to_grid([1, 0, 0, 1], 0.0)


def test_snap_contains_original():
    """Snap must always *contain* the original — never shrink."""
    original = [5.05, -73.93, -34.07, -33.95]
    snapped = snap_area_to_grid(original, 0.1)
    assert snapped[0] >= original[0]  # N >= N
    assert snapped[1] <= original[1]  # W <= W
    assert snapped[2] <= original[2]  # S <= S
    assert snapped[3] >= original[3]  # E >= E


# ---------------------------------------------------------------------------
# Rect invariants
# ---------------------------------------------------------------------------


def test_rect_rejects_inverted_lat():
    with pytest.raises(ValueError):
        Rect(n=0.0, w=0.0, s=1.0, e=1.0)


def test_rect_rejects_inverted_lon():
    with pytest.raises(ValueError):
        Rect(n=1.0, w=1.0, s=0.0, e=0.0)


def test_rect_from_area_roundtrips():
    area = [5.0, -74.0, -34.0, -33.0]
    assert Rect.from_area(area).as_area() == area


# ---------------------------------------------------------------------------
# iter_grid_cells
# ---------------------------------------------------------------------------


def test_iter_grid_cells_counts_match_estimate():
    cells = list(iter_grid_cells([1.0, 0.0, 0.0, 1.0], 0.5))
    # 1deg / 0.5 = 2 cells per axis -> 4 total cells.
    assert len(cells) == 4


def test_iter_grid_cells_centers():
    cells = list(iter_grid_cells([0.0, 0.0, -0.5, 0.5], 0.5))
    # Two cells: south=[-0.5,0], north=[0,0.5] -- but iter is at centers.
    # lat starts at -0.5 + 0.25 = -0.25; only one step (next would be 0.25 > 0).
    # lon starts at 0 + 0.25 = 0.25; only one step.
    assert (-0.25, 0.25) in cells


# ---------------------------------------------------------------------------
# rect_intersect
# ---------------------------------------------------------------------------


def test_intersect_overlapping():
    a = Rect(n=2, w=0, s=0, e=2)
    b = Rect(n=3, w=1, s=1, e=3)
    inter = rect_intersect(a, b)
    assert inter == Rect(n=2, w=1, s=1, e=2)


def test_intersect_disjoint_returns_none():
    a = Rect(n=1, w=0, s=0, e=1)
    b = Rect(n=1, w=2, s=0, e=3)
    assert rect_intersect(a, b) is None


def test_intersect_edge_touching_returns_none():
    """Zero-area intersection (shared edge) is treated as disjoint."""
    a = Rect(n=1, w=0, s=0, e=1)
    b = Rect(n=1, w=1, s=0, e=2)
    assert rect_intersect(a, b) is None


# ---------------------------------------------------------------------------
# rect_subtract
# ---------------------------------------------------------------------------


def test_subtract_no_holes_returns_target():
    t = Rect(n=10, w=0, s=0, e=10)
    assert rect_subtract(t, []) == [t]


def test_subtract_disjoint_hole_returns_target():
    t = Rect(n=10, w=0, s=0, e=10)
    hole = Rect(n=20, w=20, s=15, e=25)  # outside
    assert rect_subtract(t, [hole]) == [t]


def test_subtract_corner_hole_yields_l_shape():
    """target=[0..10]x[0..10] minus hole [0..5]x[0..5] = L-shaped union of rects."""
    t = Rect(n=10, w=0, s=0, e=10)
    hole = Rect(n=5, w=0, s=0, e=5)
    pieces = rect_subtract(t, [hole])
    assert len(pieces) >= 2
    # Union of pieces should cover everything except the hole.
    covered = rect_union_area(pieces)
    assert covered == pytest.approx(100 - 25)


def test_subtract_full_overlap_yields_empty():
    t = Rect(n=10, w=0, s=0, e=10)
    hole = Rect(n=10, w=0, s=0, e=10)
    assert rect_subtract(t, [hole]) == []


def test_subtract_two_disjoint_holes():
    t = Rect(n=10, w=0, s=0, e=10)
    h1 = Rect(n=3, w=0, s=0, e=3)
    h2 = Rect(n=10, w=7, s=7, e=10)
    pieces = rect_subtract(t, [h1, h2])
    covered = rect_union_area(pieces)
    assert covered == pytest.approx(100 - 9 - 9)


def test_subtract_overlapping_holes_dedup():
    t = Rect(n=10, w=0, s=0, e=10)
    h1 = Rect(n=5, w=0, s=0, e=5)
    h2 = Rect(n=6, w=0, s=0, e=6)  # contains h1
    pieces = rect_subtract(t, [h1, h2])
    covered = rect_union_area(pieces)
    assert covered == pytest.approx(100 - 36)


def test_subtract_grid_aligned_round_trip():
    """SP-like bbox snapped, then a sub-rect of it subtracted, sum-checks out."""
    t = Rect.from_area(snap_area_to_grid([-19.78, -53.11, -25.31, -44.16], 0.1))
    hole = Rect.from_area(snap_area_to_grid([-22.0, -49.0, -24.0, -46.0], 0.1))
    pieces = rect_subtract(t, [hole])
    assert rect_union_area(pieces) + hole.area_deg2() == pytest.approx(t.area_deg2())


# ---------------------------------------------------------------------------
# merge_rects_horizontal
# ---------------------------------------------------------------------------


def test_merge_horizontal_combines_abutting():
    a = Rect(n=2, w=0, s=0, e=1)
    b = Rect(n=2, w=1, s=0, e=2)
    merged = merge_rects_horizontal([a, b])
    assert merged == [Rect(n=2, w=0, s=0, e=2)]


def test_merge_horizontal_keeps_disjoint():
    a = Rect(n=2, w=0, s=0, e=1)
    b = Rect(n=2, w=3, s=0, e=4)
    merged = merge_rects_horizontal([a, b])
    assert sorted(merged, key=lambda r: r.w) == [a, b]


def test_merge_horizontal_respects_y_bands():
    """Rectangles in different y-bands are not merged."""
    a = Rect(n=2, w=0, s=0, e=1)
    b = Rect(n=4, w=1, s=2, e=2)
    merged = merge_rects_horizontal([a, b])
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# rect_union_area
# ---------------------------------------------------------------------------


def test_union_area_disjoint():
    a = Rect(n=1, w=0, s=0, e=1)
    b = Rect(n=2, w=2, s=1, e=3)
    assert rect_union_area([a, b]) == pytest.approx(2.0)


def test_union_area_full_overlap_counts_once():
    a = Rect(n=2, w=0, s=0, e=2)
    b = Rect(n=2, w=0, s=0, e=2)
    assert rect_union_area([a, b]) == pytest.approx(4.0)


def test_union_area_partial_overlap():
    a = Rect(n=2, w=0, s=0, e=2)
    b = Rect(n=3, w=1, s=1, e=3)
    # 4 + 4 - 1 (intersection) = 7
    assert rect_union_area([a, b]) == pytest.approx(7.0)


def test_union_area_empty():
    assert math.isclose(rect_union_area([]), 0.0)
