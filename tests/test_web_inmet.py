"""Web API tests for the INMET dataset (FastAPI TestClient, no network)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import rebuild_from_parquet
from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


def _seed_station(base: Path, station_id="A001", year=2000):
    pdir = resolve_dataset_dir(base, "inmet") / f"station={station_id}"
    pdir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "station_id": [station_id] * 2,
            "latitude": [-15.78, -15.78],
            "longitude": [-47.92, -47.92],
            "altitude": [1159.54, 1159.54],
            "uf": ["DF", "DF"],
            "regiao": ["CO", "CO"],
            "nome": ["BRASILIA", "BRASILIA"],
            "data_fundacao": ["2000-05-07"] * 2,
            "date": [dt.date(year, 1, 1), dt.date(year, 1, 2)],
            "hour_utc": [0, 1],
            "temp_ar": [21.0, 22.0],
        }
    ).write_parquet(pdir / f"{station_id}_{year}.parquet")
    rebuild_from_parquet("inmet", base)


def test_datasets_includes_inmet(client: TestClient):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    by_name = {d["name"]: d for d in r.json()}
    assert "inmet" in by_name
    inmet = by_name["inmet"]
    assert inmet["source_kind"] == "inmet_zip"
    assert inmet["is_gridded"] is False
    assert inmet["cds_dataset_id"] == ""
    api_names = [v["api_name"] for v in inmet["variables"]]
    assert "temp_ar" in api_names


def test_stations_empty_state_ok(client: TestClient):
    r = client.get("/api/inventory/stations", params={"dataset": "inmet"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"dataset": "inmet", "n_stations": 0, "stations": []}


def test_stations_listed_after_seed(client: TestClient, tmp_path: Path):
    _seed_station(tmp_path)
    r = client.get("/api/inventory/stations", params={"dataset": "inmet"})
    assert r.status_code == 200
    body = r.json()
    assert body["n_stations"] == 1
    st = body["stations"][0]
    assert st["station_id"] == "A001"
    assert st["uf"] == "DF"
    assert st["latitude"] == pytest.approx(-15.78, rel=1e-4)
    assert st["year_min"] == 2000 and st["year_max"] == 2000
    assert st["n_vars"] == 1


def test_stations_rejects_gridded_dataset(client: TestClient):
    r = client.get("/api/inventory/stations", params={"dataset": "era5"})
    assert r.status_code == 400


def test_diff_preview_inmet_skips_instead_of_500(client: TestClient):
    """INMET has no grid: diff-preview must NOT 500 (snap_area res=0.0)."""
    r = client.post(
        "/api/pipeline/diff-preview",
        json={
            "dataset": "inmet",
            "area": [5.0, -74.0, -34.0, -34.0],
            "date_from": "2000-01-01",
            "date_to": "2000-12-31",
            "hours": [0, 12],
            "variables": ["temp_ar"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["diff_skipped"] is True
    assert body["requested_cells"] == 0
    assert "estaç" in body["skip_reason"] or "esta" in body["skip_reason"].lower()


def test_diff_preview_grid_dataset_still_works(client: TestClient):
    # Sanity: a gridded dataset is unaffected by the guard (no coverage
    # DB yet -> all requested cells "missing", but a real 200 payload).
    r = client.post(
        "/api/pipeline/diff-preview",
        json={
            "dataset": "era5-land",
            "area": [-22.0, -48.0, -24.0, -46.0],
            "date_from": "2024-01-01",
            "date_to": "2024-01-01",
            "hours": [12],
            "variables": ["2m_temperature"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["diff_skipped"] is False


def test_estimate_inmet_skips_instead_of_500(client: TestClient):
    """INMET has no grid: /estimate must NOT 500 (snap_area res=0.0)."""
    r = client.post(
        "/api/pipeline/estimate",
        json={
            "dataset": "inmet",
            "variables": ["temp_ar"],
            "start_date": "2000-01-01",
            "end_date": "2002-12-31",
            "area": [5.0, -74.0, -34.0, -34.0],
            "hours": ["00:00", "12:00"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate_skipped"] is True
    assert body["total_chunks"] == 3  # 2000, 2001, 2002
    assert body["total_estimated_bytes"] == 0
    assert "2000" in body["skip_reason"]


def test_estimate_grid_dataset_still_works(client: TestClient):
    r = client.post(
        "/api/pipeline/estimate",
        json={
            "dataset": "era5-land",
            "variables": ["2m_temperature"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "area": [-22.0, -48.0, -24.0, -46.0],
            "hours": ["12:00"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["estimate_skipped"] is False


def test_inmet_years_endpoint(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "era5_etl.web.routes.inmet.scrape_available_years",
        lambda: [2000, 2001, 2026],
    )
    r = client.get("/api/inmet/years")
    assert r.status_code == 200
    assert r.json()["years"] == [2000, 2001, 2026]


def test_inmet_years_endpoint_portal_down_502(client: TestClient, monkeypatch):
    from era5_etl.exceptions import DownloadError

    def _boom():
        raise DownloadError("portal unreachable")

    monkeypatch.setattr(
        "era5_etl.web.routes.inmet.scrape_available_years", _boom
    )
    r = client.get("/api/inmet/years")
    assert r.status_code == 502


def test_grid_points_inmet_is_empty(client: TestClient):
    # INMET has no coverage DB; the grid endpoint stays a valid empty state.
    r = client.get("/api/inventory/grid-points", params={"dataset": "inmet"})
    assert r.status_code == 200
    assert r.json() == []
