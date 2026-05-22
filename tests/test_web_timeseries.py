"""Web tests for the time-series endpoints (FastAPI TestClient, no net)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from era5_etl.storage.coverage import rebuild_from_parquet as rebuild_coverage
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import rebuild_from_parquet as rebuild_stations
from era5_etl.transform.inmet_to_parquet import NEIGHBOUR_COL_NAMES
from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Isolate the user-views store: without this the test reads the real
    # user's ~/.era5-etl/user_views.json and any object there leaks in.
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def _seed_era5(base: Path, days: int = 3, hours: int = 24):
    """Two grid points × `days` × `hours`, one var `temperature_2m`."""
    for d in range(days):
        day = dt.date(2024, 1, 1) + dt.timedelta(days=d)
        pdir = resolve_dataset_dir(base, "era5") / f"date={day.isoformat()}"
        pdir.mkdir(parents=True, exist_ok=True)
        rows = []
        for h in range(hours):
            rows.append((-15.0, -47.0, h, 20.0 + h + d))
            rows.append((-16.0, -48.0, h, 30.0 + h + d))
        pl.DataFrame(
            rows, schema=["latitude", "longitude", "hour_utc", "temperature_2m"],
            orient="row",
        ).write_parquet(pdir / f"era5_{day.isoformat()}_part-001.parquet")
    rebuild_coverage("era5", base)


def _seed_inmet(base: Path):
    pdir = resolve_dataset_dir(base, "inmet") / "station=A001"
    pdir.mkdir(parents=True, exist_ok=True)
    n = 4
    data = {
        "station_id": ["A001"] * n,
        "latitude": [-15.78] * n,
        "longitude": [-47.92] * n,
        "altitude": [1159.5] * n,
        "uf": ["DF"] * n,
        "regiao": ["CO"] * n,
        "nome": ["BRASILIA"] * n,
        "data_fundacao": ["2000-05-07"] * n,
        "date": [dt.date(2024, 1, 1), dt.date(2024, 1, 1),
                 dt.date(2024, 1, 2), dt.date(2024, 1, 2)],
        "hour_utc": [0, 1, 0, 1],
        "temp_ar": [21.0, 22.0, 23.0, 24.0],
    }
    # Neighbour/dist columns so create_era5_inmet_view can build its joins.
    for c in NEIGHBOUR_COL_NAMES:
        data[c] = [0.0] * n
    pl.DataFrame(data).write_parquet(pdir / "A001_2024.parquet")
    rebuild_stations("inmet", base)


# --- /meta ------------------------------------------------------------


def test_meta_empty_state_200(client: TestClient):
    r = client.get("/api/timeseries/meta")
    assert r.status_code == 200
    assert r.json() == {"views": []}


def test_meta_lists_views(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path)
    _seed_inmet(tmp_path)
    r = client.get("/api/timeseries/meta")
    assert r.status_code == 200
    views = {v["view"]: v for v in r.json()["views"]}
    assert {"era5", "inmet"}.issubset(views)

    era5 = views["era5"]
    assert era5["location_kind"] == "grid"
    assert era5["grid_resolution"] == pytest.approx(0.25)
    ncols = {c["name"] for c in era5["numeric_columns"]}
    assert "temperature_2m" in ncols
    assert "latitude" not in ncols and "hour_utc" not in ncols
    assert era5["date_min"] == "2024-01-01"
    assert era5["date_max"] == "2024-01-03"

    inmet = views["inmet"]
    assert inmet["location_kind"] == "station"
    assert inmet["grid_resolution"] is None
    inmet_cols = {c["name"] for c in inmet["numeric_columns"]}
    assert "temp_ar" in inmet_cols
    # neighbour/dist bookkeeping columns excluded from Y choices
    assert not (set(NEIGHBOUR_COL_NAMES) & inmet_cols)


def test_meta_skips_user_macro_without_500(client: TestClient, tmp_path: Path):
    """A registered user MACRO is not SELECT-able; the meta endpoint must
    skip it gracefully, not crash with HTTP 500."""
    from era5_etl.web import user_views_store as store

    _seed_era5(tmp_path)
    store.add_object(
        name="weights_macro",
        kind="macro",
        sql="CREATE OR REPLACE MACRO weights_macro(x) AS x * 2",
    )
    r = client.get("/api/timeseries/meta")
    assert r.status_code == 200, r.text
    views = {v["view"] for v in r.json()["views"]}
    assert "era5" in views
    assert "weights_macro" not in views  # macro skipped, not listed


# --- POST /api/timeseries --------------------------------------------


def _series(view, ycol, loc, **kw):
    return {"view": view, "y_column": ycol, "location": loc, **kw}


def test_point_series_grid(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path, days=2, hours=3)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-02",
            "bucket": "raw",
            "series": [_series(
                "era5", "temperature_2m",
                {"kind": "point", "lat": -15.0, "lon": -47.0},
            )],
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()["series"][0]
    assert s["error"] is None
    assert s["bucket_used"] == "raw"
    assert s["n_points"] == 6  # 2 days * 3 hours
    assert s["x"][0].startswith("2024-01-01T00:00:00")
    assert s["y"][0] == pytest.approx(20.0)


def test_region_mean_grid(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path, days=1, hours=2)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-01",
            "series": [_series(
                "era5", "temperature_2m",
                {"kind": "region", "south": -20, "north": -10,
                 "west": -50, "east": -40}, agg="avg",
            )],
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()["series"][0]
    assert s["y"][0] == pytest.approx(25.0)  # mean(20, 30) at hour 0


def test_bucket_coarsen_and_cap(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path, days=10, hours=24)  # 240 raw points at the point
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-10",
            "bucket": "raw", "max_points": 100,
            "series": [_series(
                "era5", "temperature_2m",
                {"kind": "point", "lat": -15.0, "lon": -47.0},
            )],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    s = body["series"][0]
    assert s["downsampled"] is True
    # raw(240) -> hour(240) -> day(10) <= 100
    assert s["bucket_used"] == "day"
    assert s["n_points"] == 10
    assert body["truncated"] is True


def test_inmet_station_series(client: TestClient, tmp_path: Path):
    _seed_inmet(tmp_path)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-02",
            "series": [_series(
                "inmet", "temp_ar",
                {"kind": "point", "station_id": "A001"},
            )],
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()["series"][0]
    assert s["error"] is None
    assert s["n_points"] == 4
    assert s["y"] == [21.0, 22.0, 23.0, 24.0]


def test_multi_view_overlay(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path, days=1, hours=2)
    _seed_inmet(tmp_path)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-02",
            "series": [
                _series("era5", "temperature_2m",
                        {"kind": "point", "lat": -15.0, "lon": -47.0}),
                _series("inmet", "temp_ar",
                        {"kind": "point", "station_id": "A001"}, axis="y2"),
            ],
        },
    )
    assert r.status_code == 200, r.text
    series = r.json()["series"]
    assert len(series) == 2
    assert series[1]["axis"] == "y2"
    assert all(s["error"] is None for s in series)


def test_era5_inmet_not_auto_registered(client: TestClient, tmp_path):
    # era5_inmet is no longer Python-generated. With inmet + era5 data
    # present it must NOT appear automatically — it only exists if the
    # user creates a view named era5_inmet (see test_query_user_objects).
    _seed_era5(tmp_path, days=1, hours=2)
    _seed_inmet(tmp_path)
    r = client.get("/api/timeseries/meta")
    views = {v["view"] for v in r.json()["views"]}
    assert "era5_inmet" not in views
    assert {"era5", "inmet"} <= views


def test_unknown_column_is_per_series_error_not_500(client, tmp_path):
    _seed_era5(tmp_path, days=1, hours=1)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-01",
            "series": [_series(
                "era5", "does_not_exist",
                {"kind": "point", "lat": -15.0, "lon": -47.0},
            )],
        },
    )
    assert r.status_code == 200
    assert "não existe" in r.json()["series"][0]["error"]


def test_invalid_agg_rejected_422(client: TestClient, tmp_path: Path):
    _seed_era5(tmp_path, days=1, hours=1)
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-01",
            "series": [_series(
                "era5", "temperature_2m",
                {"kind": "point", "lat": -15.0, "lon": -47.0}, agg="median",
            )],
        },
    )
    assert r.status_code == 422


def test_empty_data_post_200(client: TestClient):
    r = client.post(
        "/api/timeseries",
        json={
            "date_from": "2024-01-01", "date_to": "2024-01-02",
            "series": [_series(
                "era5", "temperature_2m",
                {"kind": "point", "lat": -15.0, "lon": -47.0},
            )],
        },
    )
    assert r.status_code == 200
    s = r.json()["series"][0]
    assert s["error"] and "indisponível" in s["error"]
