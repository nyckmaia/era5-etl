"""M03 backend: server-backed query history + templates.

Uses TestClient + an isolated ERA5_ETL_CONFIG_DIR; no network, no DuckDB.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from era5_etl.web import query_store
from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


def test_templates_are_served(client: TestClient) -> None:
    r = client.get("/api/query/templates")
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    assert {"id", "name", "sql"} <= set(items[0])


def test_history_empty_then_append(client: TestClient) -> None:
    assert client.get("/api/query/history/era5_land").json() == []

    r = client.post(
        "/api/query/history/era5_land",
        json={"sql": "SELECT 1;", "rows": 1, "elapsed_ms": 5},
    )
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) == 1
    e = entries[0]
    assert e["sql"] == "SELECT 1;"
    assert e["favorite"] is False
    assert e["name"] is None
    assert e["id"]
    assert e["ts"] > 0


def test_history_is_per_view(client: TestClient) -> None:
    client.post("/api/query/history/era5", json={"sql": "SELECT 1;"})
    assert len(client.get("/api/query/history/era5").json()) == 1
    assert client.get("/api/query/history/era5_land").json() == []


def test_patch_favorite_and_name(client: TestClient) -> None:
    eid = client.post(
        "/api/query/history/era5_land", json={"sql": "SELECT 2;"}
    ).json()[0]["id"]

    r = client.patch(
        f"/api/query/history/era5_land/{eid}",
        json={"favorite": True, "name": "my fave"},
    )
    assert r.status_code == 200
    e = r.json()[0]
    assert e["favorite"] is True
    assert e["name"] == "my fave"


def test_delete_one_and_clear(client: TestClient) -> None:
    eid = client.post(
        "/api/query/history/era5_land", json={"sql": "SELECT 3;"}
    ).json()[0]["id"]
    client.post("/api/query/history/era5_land", json={"sql": "SELECT 4;"})

    after_del = client.delete(f"/api/query/history/era5_land/{eid}").json()
    assert len(after_del) == 1
    assert all(x["sql"] != "SELECT 3;" for x in after_del)

    assert client.delete("/api/query/history/era5_land").json() == []


def test_history_newest_first(client: TestClient) -> None:
    client.post("/api/query/history/era5_land", json={"sql": "first;"})
    client.post("/api/query/history/era5_land", json={"sql": "second;"})
    sqls = [e["sql"] for e in client.get("/api/query/history/era5_land").json()]
    assert sqls == ["second;", "first;"]


def test_history_persists_across_app_instances(tmp_path: Path) -> None:
    """A fresh app (new process analogue) reads back what was written."""
    app1 = TestClient(create_app(tmp_path))
    app1.post("/api/query/history/era5_land", json={"sql": "persisted;"})

    app2 = TestClient(create_app(tmp_path))
    entries = app2.get("/api/query/history/era5_land").json()
    assert [e["sql"] for e in entries] == ["persisted;"]


def test_cap_evicts_oldest_but_keeps_favorites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_store, "HISTORY_CAP", 5)
    favs = query_store.append_history("era5_land", "FAV;", 0, 0)
    query_store.patch_history(
        "era5_land", favs[0]["id"], favorite=True
    )
    for i in range(20):
        query_store.append_history("era5_land", f"q{i};", 0, 0)

    entries = query_store.list_history("era5_land")
    assert len(entries) <= 6  # cap + pinned favorite
    assert any(e["sql"] == "FAV;" and e["favorite"] for e in entries)
    assert any(e["sql"] == "q19;" for e in entries)  # newest kept
    assert all(e["sql"] != "q0;" for e in entries)  # oldest evicted
