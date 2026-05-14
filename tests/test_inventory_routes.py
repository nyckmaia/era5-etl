"""Tests for the v0.6.0 inventory + diff-preview FastAPI endpoints.

These exercise the new ``/api/inventory/*`` routes and the
``/api/pipeline/diff-preview`` endpoint, plus the ``apply_diff`` field on
``/api/pipeline/run``. All tests use ``TestClient`` and ``tmp_path``; no
network calls.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import polars as pl
import pyarrow.ipc as pa_ipc
import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")  # required by TestClient

from fastapi.testclient import TestClient

from era5_etl.storage.coverage import CoverageIndex
from era5_etl.web.server import create_app

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    return TestClient(app)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


def _coverage_df(
    *,
    lats: list[float],
    lons: list[float],
    hours: list[int],
    dates: list[str],
    variable: str = "2m_temperature",
) -> pl.DataFrame:
    """Build a per-hour DataFrame compatible with ``upsert_from_dataframe``."""
    rows_lat: list[float] = []
    rows_lon: list[float] = []
    rows_hour: list[int] = []
    rows_date: list[str] = []
    for lat in lats:
        for lon in lons:
            for d in dates:
                for h in hours:
                    rows_lat.append(lat)
                    rows_lon.append(lon)
                    rows_hour.append(h)
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


def _populate(tmp_path: Path, dataset: str, df: pl.DataFrame) -> None:
    with CoverageIndex(dataset, tmp_path) as cov:
        cov.upsert_from_dataframe(df)


# ---------------------------------------------------------------------------
# /api/inventory/grid-points
# ---------------------------------------------------------------------------


def test_grid_points_empty_dataset(client: TestClient):
    """No coverage DB on disk -> 200 with an empty list."""
    r = client.get("/api/inventory/grid-points", params={"dataset": "era5-land"})
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_grid_points_returns_json_for_small(client: TestClient, data_dir: Path):
    df = _coverage_df(
        lats=[-10.0, -10.1, -10.2],
        lons=[-50.0],
        hours=[0, 12],
        dates=["2024-01-01"],
    )
    _populate(data_dir, "era5-land", df)

    r = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "format": "json"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    # Each row has the expected short keys.
    for row in payload:
        assert set(row.keys()) == {"lat", "lon", "days", "vars"}
        assert row["days"] == 1
        assert row["vars"] == 1


def test_grid_points_returns_arrow_when_large(client: TestClient, data_dir: Path):
    """A coverage table with > 5000 distinct cells -> Arrow IPC stream."""
    # Build > 5000 cells: 80 lats * 80 lons = 6400 distinct cells.
    lats = [round(-10.0 - 0.1 * i, 2) for i in range(80)]
    lons = [round(-50.0 - 0.1 * j, 2) for j in range(80)]
    # Single hour & date keep the upsert payload small.
    df = _coverage_df(lats=lats, lons=lons, hours=[0], dates=["2024-01-01"])
    _populate(data_dir, "era5-land", df)

    r = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "format": "auto"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.apache.arrow.stream")

    # Decode the Arrow IPC stream and confirm the row count.
    table = pa_ipc.open_stream(io.BytesIO(r.content)).read_all()
    assert table.num_rows == len(lats) * len(lons)
    assert set(table.column_names) == {"latitude", "longitude", "days", "vars"}


def test_grid_points_filters_by_date_range(client: TestClient, data_dir: Path):
    df = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0],
        dates=[f"2024-01-{d:02d}" for d in range(1, 11)],  # 10 days
    )
    _populate(data_dir, "era5-land", df)

    r = client.get(
        "/api/inventory/grid-points",
        params={
            "dataset": "era5-land",
            "format": "json",
            "date_from": "2024-01-05",
        },
    )
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) == 1
    # 6 dates in [2024-01-05, 2024-01-10] inclusive.
    assert payload[0]["days"] == 6


def test_grid_points_filters_by_variable(client: TestClient, data_dir: Path):
    df = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0],
        dates=["2024-01-01"],
        variable="2m_temperature",
    )
    df2 = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0],
        dates=["2024-01-01"],
        variable="total_precipitation",
    )
    _populate(data_dir, "era5-land", df)
    _populate(data_dir, "era5-land", df2)

    r = client.get(
        "/api/inventory/grid-points",
        params={
            "dataset": "era5-land",
            "format": "json",
            "variable": "2m_temperature",
        },
    )
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) == 1
    assert payload[0]["vars"] == 1  # only the filtered variable counts


# ---------------------------------------------------------------------------
# /api/inventory/cell-detail
# ---------------------------------------------------------------------------


def test_cell_detail_known(client: TestClient, data_dir: Path):
    """Populate one cell, two dates, two vars; check nested response shape."""
    df_t = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0, 6, 12, 18],
        dates=["2024-01-01", "2024-01-02"],
        variable="2m_temperature",
    )
    df_p = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0, 12],
        dates=["2024-01-01", "2024-01-02"],
        variable="total_precipitation",
    )
    _populate(data_dir, "era5-land", df_t)
    _populate(data_dir, "era5-land", df_p)

    r = client.get(
        "/api/inventory/cell-detail",
        params={"dataset": "era5-land", "lat": -10.0, "lon": -50.0},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["latitude"] == pytest.approx(-10.0)
    assert payload["longitude"] == pytest.approx(-50.0)
    assert len(payload["dates"]) == 2
    by_date = {d["date"]: d for d in payload["dates"]}
    assert "2024-01-01" in by_date
    vars_for_d = {v["name"]: v["hours"] for v in by_date["2024-01-01"]["variables"]}
    assert vars_for_d["2m_temperature"] == [0, 6, 12, 18]
    assert vars_for_d["total_precipitation"] == [0, 12]


def test_cell_detail_unknown(client: TestClient, data_dir: Path):
    """Unknown lat/lon (DB exists but cell missing) -> empty dates list."""
    df = _coverage_df(
        lats=[-10.0],
        lons=[-50.0],
        hours=[0],
        dates=["2024-01-01"],
    )
    _populate(data_dir, "era5-land", df)

    r = client.get(
        "/api/inventory/cell-detail",
        params={"dataset": "era5-land", "lat": -99.0, "lon": -99.0},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["dates"] == []


# ---------------------------------------------------------------------------
# /api/inventory/region-summary
# ---------------------------------------------------------------------------


def test_region_summary_valid_polygon(client: TestClient, data_dir: Path):
    df = _coverage_df(
        lats=[-10.0, -10.1, -10.2],
        lons=[-50.0, -50.1],
        hours=[0],
        dates=["2024-01-01"],
    )
    _populate(data_dir, "era5-land", df)

    # Polygon enclosing all six cells (vertices in lat/lon).
    polygon = [
        [-9.9, -50.2],
        [-9.9, -49.9],
        [-10.3, -49.9],
        [-10.3, -50.2],
    ]
    r = client.post(
        "/api/inventory/region-summary",
        json={"dataset": "era5-land", "polygon": polygon},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["n_points"] > 0
    assert payload["date_range"] is not None
    assert isinstance(payload["date_range"], list)
    assert len(payload["date_range"]) == 2


def test_region_summary_invalid_polygon(client: TestClient):
    """Polygon with < 3 vertices -> 422 validation error."""
    r = client.post(
        "/api/inventory/region-summary",
        json={
            "dataset": "era5-land",
            "polygon": [[-10.0, -50.0], [-10.1, -50.0]],
        },
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# /api/pipeline/diff-preview
# ---------------------------------------------------------------------------


def test_diff_preview_full_coverage(client: TestClient, data_dir: Path):
    """Pre-populate everything the request asks for -> savings_pct=100."""
    # Cover the 2x2 cells at 0.1deg in [-10.0, -50.0, -10.2, -49.9].
    # snap_area_to_grid keeps that bbox; cell centers: lat={-10.05,-10.15},
    # lon={-49.95,-49.85}.
    df = _coverage_df(
        lats=[-10.05, -10.15],
        lons=[-49.95, -49.85],
        hours=[0, 12],
        dates=["2024-01-01"],
    )
    _populate(data_dir, "era5-land", df)

    body = {
        "dataset": "era5-land",
        "area": [-10.0, -50.0, -10.2, -49.9],
        "date_from": "2024-01-01",
        "date_to": "2024-01-01",
        "hours": [0, 12],
        "variables": ["2m_temperature"],
    }
    r = client.post("/api/pipeline/diff-preview", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["requested_cells"] == 4  # 2 lat * 2 lon * 1 date * 1 var
    assert payload["missing_cells"] == 0
    assert payload["savings_pct"] == 100.0
    assert payload["sample_missing"] == []


def test_diff_preview_partial_coverage(client: TestClient, data_dir: Path):
    """Cover one of two dates -> savings_pct ~= 50."""
    df = _coverage_df(
        lats=[-10.05, -10.15],
        lons=[-49.95, -49.85],
        hours=[0, 12],
        dates=["2024-01-01"],
    )
    _populate(data_dir, "era5-land", df)

    body = {
        "dataset": "era5-land",
        "area": [-10.0, -50.0, -10.2, -49.9],
        "date_from": "2024-01-01",
        "date_to": "2024-01-02",  # 2 dates total
        "hours": [0, 12],
        "variables": ["2m_temperature"],
    }
    r = client.post("/api/pipeline/diff-preview", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["requested_cells"] == 8  # 2*2*2*1
    assert payload["missing_cells"] == 4  # only 2024-01-02 still missing
    assert payload["savings_pct"] == 50.0
    assert len(payload["sample_missing"]) == 4
    # All sample rows should be from 2024-01-02.
    for row in payload["sample_missing"]:
        assert row["date"] == "2024-01-02"
        assert row["variable"] == "2m_temperature"


def test_diff_preview_no_coverage(client: TestClient):
    """No coverage DB at all -> savings=0, missing=requested."""
    body = {
        "dataset": "era5-land",
        "area": [-10.0, -50.0, -10.2, -49.9],
        "date_from": "2024-01-01",
        "date_to": "2024-01-01",
        "hours": [0, 12],
        "variables": ["2m_temperature"],
    }
    r = client.post("/api/pipeline/diff-preview", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["requested_cells"] == 4
    assert payload["missing_cells"] == 4
    assert payload["savings_pct"] == 0.0
    assert len(payload["sample_missing"]) == 4


# ---------------------------------------------------------------------------
# /api/pipeline/run -- apply_diff field
# ---------------------------------------------------------------------------


def test_run_endpoint_accepts_apply_diff(client: TestClient):
    """POST with apply_diff=False starts a run; pipeline construction is mocked."""

    class _DummyCtx:
        def set_progress_callback(self, cb):  # noqa: ARG002
            return None

    class _DummyPipe:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            self.kwargs = kwargs

        def run(self):
            return _DummyCtx()

    body = {
        "dataset": "era5-land",
        "variables": ["2m_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-01",
        "area": [-10.0, -50.0, -20.0, -40.0],
        "hours": ["00:00"],
        "apply_diff": False,
    }
    with patch("era5_etl.pipeline.era5_pipeline.ERA5Pipeline", _DummyPipe):
        r = client.post("/api/pipeline/run", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["dataset"] == "era5-land"
    assert payload["status"] in {"pending", "running", "completed"}
    assert "run_id" in payload
