"""Tests for the per-dataset manifest."""

import json
from pathlib import Path

from era5_etl.storage.manifest import MANIFEST_VERSION, ChunkRecord, Manifest
from era5_etl.storage.paths import resolve_manifest_path


def _make_chunk(chunk_id: str = "era5_202401_full") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        year=2024,
        month=1,
        variables=["2m_temperature"],
        area=[6.0, -74.0, -34.0, -34.0],
        netcdf_filename=f"{chunk_id}.nc",
        parquet_partitions=["date=2024-01-01"],
        size_bytes=1024,
    )


def test_empty_manifest_starts_empty(tmp_path: Path):
    m = Manifest(tmp_path, "era5-land")
    assert len(m) == 0
    assert m.chunks() == []
    assert m.chunk_ids() == set()


def test_record_and_persist(tmp_path: Path):
    m = Manifest(tmp_path, "era5-land")
    chunk = _make_chunk("era5land_202401")
    m.record(chunk)
    m.save()

    # File written at expected location
    expected = resolve_manifest_path(tmp_path, "era5-land")
    assert expected.exists()

    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert payload["version"] == MANIFEST_VERSION
    assert payload["dataset"] == "era5-land"
    assert "era5land_202401" in payload["chunks"]


def test_round_trip_load(tmp_path: Path):
    a = Manifest(tmp_path, "era5")
    a.record(_make_chunk("c1"))
    a.record(_make_chunk("c2"))
    a.save()

    b = Manifest(tmp_path, "era5")
    assert len(b) == 2
    assert b.has("c1")
    assert b.has("c2")
    rec = b.get("c1")
    assert rec is not None
    assert rec.variables == ["2m_temperature"]


def test_forget(tmp_path: Path):
    m = Manifest(tmp_path, "era5")
    m.record(_make_chunk("c1"))
    m.record(_make_chunk("c2"))
    m.forget("c1")
    assert not m.has("c1")
    assert m.has("c2")


def test_clear(tmp_path: Path):
    m = Manifest(tmp_path, "era5")
    m.record(_make_chunk("c1"))
    m.record(_make_chunk("c2"))
    m.clear()
    assert len(m) == 0


def test_completed_at_filled_automatically(tmp_path: Path):
    m = Manifest(tmp_path, "era5")
    chunk = _make_chunk("auto-ts")
    chunk.completed_at = ""  # explicitly empty
    m.record(chunk)
    assert m.get("auto-ts").completed_at  # non-empty


def test_corrupt_manifest_is_ignored(tmp_path: Path):
    path = resolve_manifest_path(tmp_path, "era5")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    m = Manifest(tmp_path, "era5")
    # Should not have raised; manifest is empty.
    assert len(m) == 0


# ---------------------------------------------------------------------------
# Cell-level coverage (Camada 3)
# ---------------------------------------------------------------------------


def _record_with_coverage(
    chunk_id: str,
    *,
    area: list[float],
    variables: list[str] | None = None,
    days: list[int] | None = None,
    hours: list[str] | None = None,
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        year=2024,
        month=1,
        variables=variables or ["2m_temperature"],
        area=area,
        days=days or list(range(1, 32)),
        hours=hours or [f"{h:02d}:00" for h in range(24)],
    )


def test_covered_rects_filters_by_variable(tmp_path: Path):
    from era5_etl.download.grid import Rect

    m = Manifest(tmp_path, "era5-land")
    m.record(_record_with_coverage("a", area=[6.0, -74.0, -34.0, -34.0], variables=["2m_temperature"]))
    m.record(_record_with_coverage("b", area=[6.0, -74.0, -34.0, -34.0], variables=["total_precipitation"]))

    days = list(range(1, 32))
    hours = [f"{h:02d}:00" for h in range(24)]

    t2m_covered = m.covered_rects_for("2m_temperature", 2024, 1, days, hours)
    assert t2m_covered == [Rect(n=6.0, w=-74.0, s=-34.0, e=-34.0)]
    tp_covered = m.covered_rects_for("total_precipitation", 2024, 1, days, hours)
    assert len(tp_covered) == 1
    other_covered = m.covered_rects_for("surface_pressure", 2024, 1, days, hours)
    assert other_covered == []


def test_covered_rects_skips_partial_day_coverage(tmp_path: Path):
    m = Manifest(tmp_path, "era5-land")
    m.record(_record_with_coverage(
        "partial",
        area=[6.0, -74.0, -34.0, -34.0],
        days=list(range(1, 11)),
    ))
    full_days = list(range(1, 32))
    full_hours = [f"{h:02d}:00" for h in range(24)]
    assert m.covered_rects_for("2m_temperature", 2024, 1, full_days, full_hours) == []


def test_missing_rects_subtracts_coverage(tmp_path: Path):
    m = Manifest(tmp_path, "era5-land")
    m.record(_record_with_coverage("west", area=[6.0, -74.0, -34.0, -54.0]))

    days = list(range(1, 32))
    hours = [f"{h:02d}:00" for h in range(24)]
    missing = m.missing_rects_for(
        target_area=[6.0, -74.0, -34.0, -34.0],
        variable="2m_temperature",
        year=2024, month=1,
        days=days, hours=hours,
        resolution=0.1,
    )
    assert len(missing) == 1
    assert missing[0].w == -54.0
    assert missing[0].e == -34.0


def test_missing_rects_empty_when_fully_covered(tmp_path: Path):
    m = Manifest(tmp_path, "era5-land")
    m.record(_record_with_coverage("full", area=[6.0, -74.0, -34.0, -34.0]))

    days = list(range(1, 32))
    hours = [f"{h:02d}:00" for h in range(24)]
    missing = m.missing_rects_for(
        target_area=[6.0, -74.0, -34.0, -34.0],
        variable="2m_temperature",
        year=2024, month=1,
        days=days, hours=hours,
        resolution=0.1,
    )
    assert missing == []


def test_missing_rects_returns_full_target_when_unrelated_coverage(tmp_path: Path):
    """Coverage for a different month should not affect the result."""
    m = Manifest(tmp_path, "era5-land")
    other = _record_with_coverage("other", area=[6.0, -74.0, -34.0, -34.0])
    other.month = 6
    m.record(other)

    days = list(range(1, 32))
    hours = [f"{h:02d}:00" for h in range(24)]
    missing = m.missing_rects_for(
        target_area=[6.0, -74.0, -34.0, -34.0],
        variable="2m_temperature",
        year=2024, month=1,
        days=days, hours=hours,
        resolution=0.1,
    )
    assert len(missing) == 1
    assert missing[0].as_area() == [6.0, -74.0, -34.0, -34.0]


def test_v1_record_without_days_hours_still_qualifies(tmp_path: Path):
    """A pre-v2 manifest record (no days/hours fields) defaults to full coverage."""
    import json

    path = resolve_manifest_path(tmp_path, "era5-land")
    path.parent.mkdir(parents=True, exist_ok=True)
    v1_payload = {
        "version": 1,
        "dataset": "era5-land",
        "updated_at": "2024-01-01T00:00:00Z",
        "chunks": {
            "legacy": {
                "chunk_id": "legacy",
                "year": 2024, "month": 1,
                "variables": ["2m_temperature"],
                "area": [6.0, -74.0, -34.0, -34.0],
            }
        },
    }
    path.write_text(json.dumps(v1_payload), encoding="utf-8")

    m = Manifest(tmp_path, "era5-land")
    rec = m.get("legacy")
    assert rec is not None
    assert len(rec.days) == 31
    assert len(rec.hours) == 24

    days = list(range(1, 32))
    hours = [f"{h:02d}:00" for h in range(24)]
    missing = m.missing_rects_for(
        target_area=[6.0, -74.0, -34.0, -34.0],
        variable="2m_temperature",
        year=2024, month=1,
        days=days, hours=hours,
        resolution=0.1,
    )
    assert missing == []


def test_record_from_request_chunk(tmp_path: Path):
    from era5_etl.download.request_planner import RequestChunk

    rc = RequestChunk(
        dataset="era5-land",
        variables=("2m_temperature",),
        year=2024, month=1,
        days=tuple(range(1, 32)),
        hours=tuple(f"{h:02d}:00" for h in range(24)),
        area=(6.0, -74.0, -34.0, -34.0),
        chunk_id="era5land_202401",
    )
    rec = ChunkRecord.from_request_chunk(rc)
    assert rec.chunk_id == "era5land_202401"
    assert rec.days == list(range(1, 32))
    assert rec.hours == [f"{h:02d}:00" for h in range(24)]
    assert rec.area == [6.0, -74.0, -34.0, -34.0]
