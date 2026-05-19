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


def test_query_schema_unknown_view_empty(client: TestClient) -> None:
    # Any non-base name may be a user-defined view; an unknown one
    # returns empty columns (HTTP 200) so the UI renders gracefully.
    r = client.get("/api/query/schema", params={"dataset": "nope"})
    assert r.status_code == 200
    assert r.json() == {"view": "nope", "columns": []}


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


# --- /api/query truncation: row_count / total_rows / truncated ---------------


def test_query_reports_truncation_and_total(
    client: TestClient, tmp_path: Path
) -> None:
    _seed_parquet(tmp_path)  # 2 rows on disk

    # limit below the total -> truncated, total_rows is the true count.
    r = client.post(
        "/api/query",
        json={"sql": "SELECT * FROM era5_land", "limit": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_count"] == 1
    assert body["total_rows"] == 2
    assert body["truncated"] is True

    # limit above the total -> not truncated, counts agree.
    r2 = client.post(
        "/api/query",
        json={"sql": "SELECT * FROM era5_land", "limit": 100},
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["row_count"] == 2
    assert b2["total_rows"] == 2
    assert b2["truncated"] is False


# --- DELETE /api/datasets/{name}/data ---------------------------------------


def test_delete_dataset_data_wipes_storage(
    client: TestClient, tmp_path: Path
) -> None:
    _seed_parquet(tmp_path)
    dataset_dir = resolve_dataset_dir(tmp_path, "era5-land")
    assert dataset_dir.exists()
    assert any(dataset_dir.rglob("*.parquet"))

    r = client.delete("/api/datasets/era5-land/data")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset"] == "era5-land"
    assert body["deleted"] is True
    assert body["freed_bytes"] > 0
    assert not dataset_dir.exists()

    # Idempotent: a second delete is a no-op (nothing left to remove).
    r2 = client.delete("/api/datasets/era5-land/data")
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["deleted"] is False
    assert b2["freed_bytes"] == 0


def test_delete_unknown_dataset_returns_404(client: TestClient) -> None:
    r = client.delete("/api/datasets/not-a-dataset/data")
    assert r.status_code == 404, r.text


# --- diff-preview: oversized request must not crash the backend -------------


def test_diff_preview_oversized_returns_chunk_plan(client: TestClient) -> None:
    """A state × decades request used to OOM-abort the process. It must now
    return 200 with diff_skipped + an arithmetic size/chunk estimate.
    """
    r = client.post(
        "/api/pipeline/diff-preview",
        json={
            "dataset": "era5-land",
            "area": [-19.7, -53.2, -25.4, -44.1],  # São Paulo, snapped-ish
            "date_from": "2000-01-01",
            "date_to": "2025-12-31",
            "hours": [0, 12],
            "variables": ["2m_temperature", "total_precipitation"],
        },
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["diff_skipped"] is True
    assert b["requested_cells"] > 20_000_000
    assert b["estimated_chunks"] is not None and b["estimated_chunks"] > 0
    assert b["estimated_download_bytes"] is not None
    assert b["estimated_disk_bytes"] is not None
    assert b["skip_reason"]


def test_diff_preview_small_request_not_skipped(client: TestClient) -> None:
    r = client.post(
        "/api/pipeline/diff-preview",
        json={
            "dataset": "era5-land",
            "area": [-10.0, -50.0, -10.1, -49.9],
            "date_from": "2024-01-01",
            "date_to": "2024-01-02",
            "hours": [0, 12],
            "variables": ["2m_temperature"],
        },
    )
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["diff_skipped"] is False
    assert b["requested_cells"] > 0
    # Sizes are reported for the normal path too (Melhoria): full-request
    # totals + the (scaled) "what will be fetched" portion.
    assert b["estimated_download_bytes"] is not None
    assert b["estimated_disk_bytes"] is not None
    assert b["missing_download_bytes"] is not None
    assert b["missing_disk_bytes"] is not None
    assert b["missing_download_bytes"] <= b["estimated_download_bytes"]
    assert b["missing_disk_bytes"] <= b["estimated_disk_bytes"]
