"""Tests for the hierarchical request planner."""

import pytest

from era5_etl.config import DownloadConfig
from era5_etl.download.request_planner import RequestChunk, plan_requests
from era5_etl.exceptions import DownloadSizeError

MB = 1024 * 1024


def _make(
    dataset: str = "era5-land",
    variables: list[str] | None = None,
    area: list[float] | None = None,
    hours: list[str] | None = None,
    start: str = "2024-01-01",
    end: str = "2024-01-31",
    max_request_bytes: int = 500 * MB,
    max_request_fields: int = 10_000,
) -> DownloadConfig:
    # Construct with a valid floor, then override max_request_bytes for tests
    # that intentionally use absurdly tight budgets to exercise every split tier.
    cfg = DownloadConfig(
        output_dir="./_unused",
        dataset=dataset,
        variables=variables or ["2m_temperature"],
        start_date=start,
        end_date=end,
        area=area or [-10.0, -50.0, -20.0, -40.0],
        hours=hours or ["00:00", "12:00"],
        max_request_bytes=500 * MB,
        max_request_fields=10_000,
    )
    cfg.max_request_bytes = max_request_bytes
    cfg.max_request_fields = max_request_fields
    return cfg


def test_fits_single_chunk_for_small_request():
    cfg = _make()
    chunks = plan_requests(cfg)
    assert len(chunks) == 1
    only = chunks[0]
    assert only.dataset == "era5-land"
    assert only.year == 2024 and only.month == 1
    assert only.variables == ("2m_temperature",)
    assert only.is_full_month


def test_one_month_per_chunk_when_multi_month():
    cfg = _make(start="2024-01-01", end="2024-03-31")
    chunks = plan_requests(cfg)
    months = {(c.year, c.month) for c in chunks}
    assert months == {(2024, 1), (2024, 2), (2024, 3)}


def test_area_split_kicks_in_when_single_day_area_too_big():
    # A single day over the whole Brazil grid: day-splitting can't help
    # (only one day), so the area tier must shrink the rectangle.
    cfg = _make(
        area=[6.0, -74.0, -34.0, -34.0],
        hours=[f"{h:02d}:00" for h in range(24)],
        start="2024-01-15",
        end="2024-01-15",
        max_request_bytes=20 * MB,
    )
    chunks = plan_requests(cfg)
    assert len(chunks) > 1
    # All chunks should still cover the same single day.
    assert {(c.year, c.month) for c in chunks} == {(2024, 1)}
    assert {tuple(sorted(c.days)) for c in chunks} == {(15,)}
    # Areas should differ -> at least one component varies between chunks
    areas = {c.area for c in chunks}
    assert len(areas) >= 2


def test_day_split_kicks_in_for_tight_budget():
    # Single point area so area split is a no-op; budget so tight we must split days.
    cfg = _make(
        area=[0.0, 0.0, 0.0, 0.0],
        variables=["2m_temperature"],
        hours=[f"{h:02d}:00" for h in range(24)],
        max_request_bytes=24 * 8,  # ~1 day fits, but full month doesn't
    )
    chunks = plan_requests(cfg)
    # Same variable, same single-cell area, different day blocks -> >1 chunks.
    assert len(chunks) > 1
    # Days across chunks must cover 1..31 with no overlap and no gap.
    seen: list[int] = []
    for c in chunks:
        seen.extend(c.days)
    assert sorted(seen) == list(range(1, 32))


def test_day_split_greedily_packs_to_budget():
    # A budget that fits ~10 days at a time must yield greedy blocks
    # (e.g. 10+10+10+1), NOT an even halving (16+15).
    one_day = 24 * 8  # 24 hours × 1 var × 1 point × 8 bytes
    cfg = _make(
        area=[0.0, 0.0, 0.0, 0.0],
        variables=["2m_temperature"],
        hours=[f"{h:02d}:00" for h in range(24)],
        max_request_bytes=one_day * 10,  # exactly 10 days per block
    )
    chunks = plan_requests(cfg)
    block_sizes = sorted(len(c.days) for c in chunks)
    # 31 days, 10 per block -> 10, 10, 10, 1 (greedy fills each to the cap,
    # rather than an even 16+15 halving).
    assert block_sizes == [1, 10, 10, 10]
    seen = [d for c in chunks for d in c.days]
    assert sorted(seen) == list(range(1, 32))


def test_variable_split_when_required():
    # Several variables, single-point area, single hour. Budget tight enough that
    # even a single day with all 3 variables (24 bytes) does not fit -> must split per variable.
    cfg = _make(
        variables=["2m_temperature", "2m_dewpoint_temperature", "surface_pressure"],
        area=[0.0, 0.0, 0.0, 0.0],
        hours=["00:00"],
        max_request_bytes=20,
    )
    chunks = plan_requests(cfg)
    # Every chunk must contain exactly one variable.
    by_var = {c.variables for c in chunks}
    assert all(len(v) == 1 for v in by_var)
    # All three variables must still appear in the plan.
    distinct_vars = {c.variables[0] for c in chunks}
    assert distinct_vars == {"2m_temperature", "2m_dewpoint_temperature", "surface_pressure"}


def test_raises_when_truly_unfittable():
    # Smallest possible request -- single variable, single day, single grid point,
    # all 24 hours -- still produces 24 * 8 = 192 bytes. A 1-byte budget cannot fit it.
    cfg = _make(
        variables=["2m_temperature"],
        area=[0.0, 0.0, 0.0, 0.0],
        hours=[f"{h:02d}:00" for h in range(24)],
        max_request_bytes=1,
    )
    with pytest.raises(DownloadSizeError):
        plan_requests(cfg)


def test_chunk_ids_are_unique_and_deterministic():
    cfg = _make(
        area=[6.0, -74.0, -34.0, -34.0],
        hours=[f"{h:02d}:00" for h in range(24)],
        max_request_bytes=200 * MB,
        end="2024-02-29",
    )
    chunks = plan_requests(cfg)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_returned_chunks_are_frozen():
    cfg = _make()
    chunk = plan_requests(cfg)[0]
    assert isinstance(chunk, RequestChunk)
    # Frozen dataclasses raise FrozenInstanceError on assignment; pydantic
    # models raise ValidationError. Catch either to stay independent of
    # the underlying immutability mechanism.
    from dataclasses import FrozenInstanceError

    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        chunk.year = 2025  # type: ignore[misc]


def test_planner_snaps_area_to_dataset_grid_era5_land():
    """Chunk areas must land on 0.1-degree boundaries for era5-land."""
    cfg = _make(dataset="era5-land", area=[5.07, -73.93, -34.04, -33.95])
    chunks = plan_requests(cfg)
    res = 0.1
    for c in chunks:
        for coord in c.area:
            assert abs((coord / res) - round(coord / res)) < 1e-6, c.area


def test_planner_snaps_area_to_dataset_grid_era5():
    """ERA5 uses 0.25-degree grid -- chunks must align to 0.25 multiples."""
    cfg = _make(dataset="era5", area=[5.1, -74.0, -34.1, -33.9])
    chunks = plan_requests(cfg)
    res = 0.25
    for c in chunks:
        for coord in c.area:
            assert abs((coord / res) - round(coord / res)) < 1e-6, c.area


def test_snap_contains_user_request():
    """The single chunk produced must contain the user's requested bbox."""
    user_area = [5.07, -73.93, -34.04, -33.95]
    cfg = _make(dataset="era5-land", area=user_area)
    chunks = plan_requests(cfg)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.area[0] >= user_area[0]  # snapped N >= original N
    assert c.area[1] <= user_area[1]
    assert c.area[2] <= user_area[2]
    assert c.area[3] >= user_area[3]


# ---------------------------------------------------------------------------
# Incremental planning
# ---------------------------------------------------------------------------


def test_incremental_plan_empty_manifest_matches_full_plan(tmp_path):
    """With an empty manifest, incremental plan should match the full plan."""
    from era5_etl.download.request_planner import plan_incremental_requests
    from era5_etl.storage.manifest import Manifest

    cfg = _make(area=[-10.0, -50.0, -20.0, -40.0])
    manifest = Manifest(tmp_path, "era5-land")
    incremental = plan_incremental_requests(cfg, manifest)
    full = plan_requests(cfg)
    # Same variable, same area, same period: number of chunks should match.
    assert len(incremental) == len(full)


def test_incremental_plan_zero_when_fully_covered(tmp_path):
    """If the manifest already covers the requested target, incremental returns []."""
    from era5_etl.download.request_planner import plan_incremental_requests
    from era5_etl.storage.manifest import ChunkRecord, Manifest

    cfg = _make(area=[-10.0, -50.0, -20.0, -40.0])
    manifest = Manifest(tmp_path, "era5-land")
    # Pre-record full-month coverage of the same area.
    manifest.record(ChunkRecord(
        chunk_id="prior",
        year=2024, month=1,
        variables=["2m_temperature"],
        area=[-10.0, -50.0, -20.0, -40.0],
        days=list(range(1, 32)),
        hours=cfg.hours,
    ))
    assert plan_incremental_requests(cfg, manifest) == []


def test_incremental_plan_returns_only_missing_region(tmp_path):
    """Coverage of the western half should leave the eastern half to plan."""
    from era5_etl.download.request_planner import plan_incremental_requests
    from era5_etl.storage.manifest import ChunkRecord, Manifest

    cfg = _make(area=[-10.0, -50.0, -20.0, -40.0])
    manifest = Manifest(tmp_path, "era5-land")
    # Western half already covered.
    manifest.record(ChunkRecord(
        chunk_id="west",
        year=2024, month=1,
        variables=["2m_temperature"],
        area=[-10.0, -50.0, -20.0, -45.0],
        days=list(range(1, 32)),
        hours=cfg.hours,
    ))
    chunks = plan_incremental_requests(cfg, manifest)
    assert len(chunks) >= 1
    # Every planned chunk should be inside the eastern half.
    for c in chunks:
        assert c.area[1] >= -45.0  # west bound east of -45
        assert c.area[3] <= -40.0


def test_incremental_plan_skips_already_covered_variable(tmp_path):
    """Coverage of one variable does not exempt others."""
    from era5_etl.download.request_planner import plan_incremental_requests
    from era5_etl.storage.manifest import ChunkRecord, Manifest

    cfg = _make(
        area=[-10.0, -50.0, -20.0, -40.0],
        variables=["2m_temperature", "total_precipitation"],
    )
    manifest = Manifest(tmp_path, "era5-land")
    manifest.record(ChunkRecord(
        chunk_id="t2m-only",
        year=2024, month=1,
        variables=["2m_temperature"],
        area=[-10.0, -50.0, -20.0, -40.0],
        days=list(range(1, 32)),
        hours=cfg.hours,
    ))
    chunks = plan_incremental_requests(cfg, manifest)
    # 2m_temperature is covered; only total_precipitation should appear.
    vars_in_plan = {v for c in chunks for v in c.variables}
    assert "total_precipitation" in vars_in_plan
    assert "2m_temperature" not in vars_in_plan


def test_partial_month_only_requests_requested_days():
    """Requesting 2 days inside a month must NOT seed the whole 31-day month."""
    cfg = _make(start="2024-01-10", end="2024-01-11")
    chunks = plan_requests(cfg)
    seen: list[int] = []
    for c in chunks:
        seen.extend(c.days)
    assert sorted(set(seen)) == [10, 11], f"expected only days 10,11; got {sorted(set(seen))}"
    assert not chunks[0].is_full_month


def test_multi_month_clips_first_and_last_only():
    """Interior months keep all days; only the edge months are clipped."""
    cfg = _make(start="2024-01-30", end="2024-03-02")
    chunks = plan_requests(cfg)
    by_month: dict[tuple[int, int], set[int]] = {}
    for c in chunks:
        by_month.setdefault((c.year, c.month), set()).update(c.days)
    assert by_month[(2024, 1)] == {30, 31}          # clipped start
    assert by_month[(2024, 2)] == set(range(1, 30))  # full Feb (leap year)
    assert by_month[(2024, 3)] == {1, 2}            # clipped end


# ---------------------------------------------------------------------------
# Fields ceiling — independent of bytes ceiling
# ---------------------------------------------------------------------------


_HOURS_24 = [f"{h:02d}:00" for h in range(24)]


def test_fields_limit_triggers_day_split():
    """A request well under the byte budget but over the FIELD budget must
    still be split — the planner respects whichever ceiling is tighter."""
    # 50 vars × 24h × 31d = 37,200 fields → 31 single-day chunks of
    # 50 × 24 × 1 = 1200 fields (under 2000).
    vars_50 = [f"var_{i}" for i in range(50)]
    cfg = _make(
        dataset="era5",
        variables=vars_50,
        hours=_HOURS_24,
        area=[1.0, 0.0, 0.0, 1.0],   # tiny area → bytes negligible
        max_request_bytes=10**12,    # effectively unlimited bytes
        max_request_fields=2_000,
    )
    chunks = plan_requests(cfg)
    # Each chunk must respect the field budget.
    for c in chunks:
        assert len(c.variables) * len(c.hours) * len(c.days) <= 2_000
    assert len(chunks) >= 31, f"expected ≥31 day-splits, got {len(chunks)}"


def test_fields_limit_triggers_variable_split():
    """When days can't shrink any further but fields still exceed, the
    cascade falls through to per-variable chunks. Use a point-area so
    the area-split tier can't multiply the chunk count."""
    vars_100 = [f"v{i}" for i in range(100)]
    cfg = _make(
        dataset="era5",
        variables=vars_100,
        hours=_HOURS_24,
        area=[0.0, 0.0, 0.0, 0.0],   # 1 grid point → area split is a no-op
        start="2024-01-01",
        end="2024-01-01",            # single day already
        max_request_bytes=10**12,
        max_request_fields=24,        # exactly 1 variable per chunk
    )
    chunks = plan_requests(cfg)
    assert all(len(c.variables) == 1 for c in chunks)
    # 100 vars × 1 day × 1 sub-area = 100 chunks.
    assert len(chunks) == 100


def test_fields_only_failure_raises_with_clear_message():
    """A field budget below the smallest possible chunk (1 var × 1 day ×
    24 hours = 24 fields) must raise DownloadSizeError citing both
    ceilings in the message."""
    cfg = _make(
        dataset="era5",
        variables=["t2m"],
        hours=_HOURS_24,
        area=[0.0, 0.0, 0.0, 0.0],
        start="2024-01-01",
        end="2024-01-01",
        max_request_bytes=10**12,
        max_request_fields=10,        # below the floor (24)
    )
    with pytest.raises(DownloadSizeError) as exc:
        plan_requests(cfg)
    msg = str(exc.value)
    assert "fields=" in msg
    assert "bytes=" in msg
    assert "max=10" in msg


def test_fields_under_budget_keeps_single_chunk():
    """Sanity: a request that fits both ceilings produces 1 chunk."""
    cfg = _make(
        dataset="era5",
        variables=["t2m", "d2m"],
        hours=["00:00", "12:00"],
        area=[1.0, 0.0, 0.0, 1.0],
        max_request_fields=10_000,
    )
    chunks = plan_requests(cfg)
    assert len(chunks) == 1
    c = chunks[0]
    assert len(c.variables) * len(c.hours) * len(c.days) <= 10_000
