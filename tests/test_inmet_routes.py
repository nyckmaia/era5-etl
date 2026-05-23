"""Tests for /api/inmet/year-status and /api/inmet/update-years."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")  # required by TestClient

from fastapi.testclient import TestClient

from era5_etl.storage.manifest import ChunkRecord, Manifest
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import rebuild_from_parquet
from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    return TestClient(app)


def _write_station(tmp_path: Path, station_id: str, year: int, last_day: dt.date) -> None:
    pdir = resolve_dataset_dir(tmp_path, "inmet") / f"station={station_id}"
    pdir.mkdir(parents=True, exist_ok=True)
    rows = (last_day - dt.date(year, 1, 1)).days + 1
    df = pl.DataFrame(
        {
            "station_id": [station_id] * rows,
            "latitude": [-15.0] * rows,
            "longitude": [-47.0] * rows,
            "altitude": [1.0] * rows,
            "uf": ["DF"] * rows,
            "regiao": ["CO"] * rows,
            "nome": ["TEST"] * rows,
            "data_fundacao": ["2000-05-07"] * rows,
            "date": [dt.date(year, 1, 1) + dt.timedelta(days=i) for i in range(rows)],
            "hour_utc": [0] * rows,
            "temp_ar": [20.0] * rows,
        }
    )
    df.write_parquet(pdir / f"{station_id}_{year}.parquet")


def _seed_manifest(tmp_path: Path, year: int, completed_at: str = "2026-01-15T10:00:00Z") -> None:
    mf = Manifest(tmp_path, "inmet")
    mf.record(
        ChunkRecord(
            chunk_id=f"inmet:{year}",
            year=year,
            month=0,
            variables=[],
            area=[],
            completed_at=completed_at,
        )
    )
    mf.save()


def test_year_status_empty_when_no_db(client: TestClient):
    r = client.get("/api/inmet/year-status")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["current_year"] >= 2026
    assert body["expected_publish_lag_days"] == 90


def test_year_status_classifies_each_year(client: TestClient, tmp_path: Path):
    # Complete: both stations reached Dec 31 of 2023.
    _write_station(tmp_path, "A001", 2023, dt.date(2023, 12, 31))
    _write_station(tmp_path, "A002", 2023, dt.date(2023, 12, 31))
    # Partial: one reached Dec 31, one stopped in June.
    _write_station(tmp_path, "A001", 2024, dt.date(2024, 12, 31))
    _write_station(tmp_path, "A002", 2024, dt.date(2024, 6, 30))
    # Stale: nobody reached Dec 31.
    _write_station(tmp_path, "A001", 2025, dt.date(2025, 4, 10))

    rebuild_from_parquet("inmet", tmp_path)
    for year in (2023, 2024, 2025):
        _seed_manifest(tmp_path, year)

    r = client.get("/api/inmet/year-status")
    assert r.status_code == 200
    items = {int(i["year"]): i for i in r.json()["items"]}
    assert items[2023]["status"] == "complete"
    assert items[2023]["n_stations"] == 2
    assert items[2023]["n_stations_complete"] == 2
    assert items[2024]["status"] == "partial"
    assert items[2024]["n_stations_complete"] == 1
    assert items[2025]["status"] == "stale"
    assert items[2025]["n_stations_complete"] == 0
    assert items[2023]["downloaded_at"].startswith("2026-01-15")


def test_update_years_purges_parquets_and_forgets_manifest(
    client: TestClient, tmp_path: Path
):
    _write_station(tmp_path, "A001", 2025, dt.date(2025, 4, 10))
    _write_station(tmp_path, "A002", 2025, dt.date(2025, 5, 20))
    _seed_manifest(tmp_path, 2025)

    parquet_a001 = (
        resolve_dataset_dir(tmp_path, "inmet") / "station=A001" / "A001_2025.parquet"
    )
    parquet_a002 = (
        resolve_dataset_dir(tmp_path, "inmet") / "station=A002" / "A002_2025.parquet"
    )
    assert parquet_a001.exists() and parquet_a002.exists()

    # Stub out the actual pipeline run — we don't want to hit CDS/INMET.
    from era5_etl.web.models import PipelineRunOut

    fake_run = PipelineRunOut(run_id="fake-run", dataset="inmet", status="pending")
    with patch(
        "era5_etl.web.routes.inmet.start_run", return_value=fake_run
    ) as mock_start_run:
        r = client.post("/api/inmet/update-years", json={"years": [2025]})
        assert r.status_code == 200, r.text
        assert r.json()["run_id"] == "fake-run"
        assert mock_start_run.called

        # Verify the run was kicked off with override=True and the right year.
        call_body = mock_start_run.call_args.args[0]
        assert call_body.dataset == "inmet"
        assert call_body.years == [2025]
        assert call_body.override is True
        assert call_body.apply_diff is False

    # Parquets gone.
    assert not parquet_a001.exists()
    assert not parquet_a002.exists()
    # Manifest entry forgotten.
    mf = Manifest(tmp_path, "inmet")
    assert not mf.has("inmet:2025")


def test_update_years_rejects_empty_body(client: TestClient):
    r = client.post("/api/inmet/update-years", json={"years": []})
    assert r.status_code == 422  # pydantic min_length validation
