"""M04 + M01 + M02b backend tests: column_types, /query/schema, precision API.

Uses TestClient + tmp_path; no network.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from era5_etl.storage.parquet_manager import merge_into_partitioned_parquet
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the user config to a temp dir so tests never touch (or
    pollute) the real ~/AppData/Roaming/era5-etl/config.toml.
    """
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


def _seed_parquet(tmp_path: Path) -> None:
    parquet_dir = resolve_dataset_dir(tmp_path, "era5-land")
    df = pl.DataFrame(
        {
            "latitude": [-22.5, -22.4],
            "longitude": [-44.0, -43.9],
            "hour_utc": [0, 12],
            "date": ["2024-01-01", "2024-01-01"],
            "t2m": [290.123, 291.456],
        }
    )
    merge_into_partitioned_parquet(df, parquet_dir)


# --- M04: /api/query returns column_types ------------------------------------


def test_query_returns_column_types(client: TestClient, tmp_path: Path) -> None:
    _seed_parquet(tmp_path)
    r = client.post(
        "/api/query",
        json={
            "dataset": "era5-land",
            "sql": "SELECT latitude, hour_utc, t2m, date FROM era5_land",
            "limit": 10,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["latitude", "hour_utc", "t2m", "date"]
    assert "column_types" in body
    assert len(body["column_types"]) == len(body["columns"])
    tmap = dict(zip(body["columns"], body["column_types"]))
    assert tmap["latitude"] == "float"
    assert tmap["hour_utc"] == "int"
    assert tmap["t2m"] == "float"
    assert tmap["date"] in {"date", "str"}  # hive partition col


# --- M01: /api/query/schema --------------------------------------------------


def test_query_schema_returns_columns_and_types(
    client: TestClient, tmp_path: Path
) -> None:
    _seed_parquet(tmp_path)
    r = client.get("/api/query/schema", params={"dataset": "era5-land"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["view"] == "era5_land"
    names = {c["name"]: c["type"] for c in body["columns"]}
    assert "latitude" in names and names["latitude"] == "float"
    assert "t2m" in names and names["t2m"] == "float"
    assert "hour_utc" in names and names["hour_utc"] == "int"


def test_query_schema_empty_when_no_parquet(client: TestClient) -> None:
    r = client.get("/api/query/schema", params={"dataset": "era5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["view"] == "era5"
    assert body["columns"] == []


def test_query_schema_unknown_dataset_400(client: TestClient) -> None:
    r = client.get("/api/query/schema", params={"dataset": "nope"})
    assert r.status_code == 400


# --- M02b: display-precision settings API ------------------------------------


def test_precision_defaults(client: TestClient) -> None:
    r = client.get("/api/settings/precision", params={"dataset": "era5-land"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset"] == "era5-land"
    assert body["default_decimals"] == 4
    assert body["default_method"] == "round"
    assert body["columns"] == {}


def test_precision_roundtrip(client: TestClient) -> None:
    payload = {
        "dataset": "era5-land",
        "default_decimals": 3,
        "default_method": "truncate",
        "columns": {"t2m": {"decimals": 2, "method": "round"}},
    }
    r = client.post("/api/settings/precision", json=payload)
    assert r.status_code == 200, r.text

    r2 = client.get("/api/settings/precision", params={"dataset": "era5-land"})
    body = r2.json()
    assert body["default_decimals"] == 3
    assert body["default_method"] == "truncate"
    assert body["columns"]["t2m"]["decimals"] == 2
    assert body["columns"]["t2m"]["method"] == "round"

    # Other dataset stays default (per-dataset isolation).
    r3 = client.get("/api/settings/precision", params={"dataset": "era5"})
    assert r3.json()["default_decimals"] == 4


def test_precision_rejects_bad_method(client: TestClient) -> None:
    r = client.post(
        "/api/settings/precision",
        json={"dataset": "era5", "default_decimals": 2, "default_method": "floor"},
    )
    assert r.status_code == 422


# --- M02a: /api/query registers all views; dataset optional ------------------


def test_query_without_dataset_uses_view_name(
    client: TestClient, tmp_path: Path
) -> None:
    _seed_parquet(tmp_path)
    # No `dataset` in the body; SQL references the view directly.
    r = client.post(
        "/api/query",
        json={"sql": "SELECT COUNT(*) AS n FROM era5_land", "limit": 10},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] == 2


def test_query_no_parquet_anywhere_404(client: TestClient) -> None:
    r = client.post("/api/query", json={"sql": "SELECT 1"})
    assert r.status_code == 404


# --- M06: /api/inventory/date-range ------------------------------------------


def test_date_range_empty(client: TestClient) -> None:
    r = client.get("/api/inventory/date-range", params={"dataset": "era5-land"})
    assert r.status_code == 200, r.text
    assert r.json() == {"min": None, "max": None}


def test_date_range_after_rebuild(client: TestClient, tmp_path: Path) -> None:
    from era5_etl.storage.coverage import rebuild_from_parquet

    pd = resolve_dataset_dir(tmp_path, "era5-land")
    df = pl.DataFrame(
        {
            "latitude": [-22.5, -22.5],
            "longitude": [-44.0, -44.0],
            "hour_utc": [0, 0],
            "date": ["2024-01-01", "2024-01-05"],
            "t2m": [290.0, 291.0],
        }
    )
    merge_into_partitioned_parquet(df, pd)
    rebuild_from_parquet("era5-land", tmp_path)

    r = client.get("/api/inventory/date-range", params={"dataset": "era5-land"})
    assert r.status_code == 200, r.text
    assert r.json() == {"min": "2024-01-01", "max": "2024-01-05"}


# --- M07: grid-points multi-variable filter ----------------------------------


def test_grid_points_multi_variable(client: TestClient, tmp_path: Path) -> None:
    from era5_etl.storage.coverage import rebuild_from_parquet

    pd = resolve_dataset_dir(tmp_path, "era5-land")
    df = pl.DataFrame(
        {
            "latitude": [-22.5, -22.4, -22.3],
            "longitude": [-44.0, -43.9, -43.8],
            "hour_utc": [0, 0, 0],
            "date": ["2024-01-01"] * 3,
            "t2m": [290.0, 291.0, 292.0],
            "tp": [1.0, 2.0, 3.0],
        }
    )
    merge_into_partitioned_parquet(df, pd)
    rebuild_from_parquet("era5-land", tmp_path)

    # Two variables requested -> still the 3 distinct cells.
    r = client.get(
        "/api/inventory/grid-points",
        params=[
            ("dataset", "era5-land"),
            ("variable", "t2m"),
            ("variable", "tp"),
            ("format", "json"),
        ],
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3
    # Single variable still works.
    r2 = client.get(
        "/api/inventory/grid-points",
        params=[("dataset", "era5-land"), ("variable", "t2m"), ("format", "json")],
    )
    assert len(r2.json()) == 3
    # No variable param = all.
    r3 = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "format": "json"},
    )
    assert len(r3.json()) == 3
