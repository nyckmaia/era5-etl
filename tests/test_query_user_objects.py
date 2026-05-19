"""User objects are replayed into the query path and isolated on error."""

import pytest
from fastapi.testclient import TestClient

import era5_etl.web.user_views_store as store
from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def test_user_view_is_queryable(client):
    store.add_object(
        name="ones",
        kind="view",
        sql="CREATE OR REPLACE VIEW ones AS SELECT 42 AS n",
    )
    r = client.post(
        "/api/query", json={"sql": "SELECT n FROM ones", "limit": 10}
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[42]]


def test_user_macro_is_callable(client):
    store.add_object(
        name="addone",
        kind="macro",
        sql="CREATE OR REPLACE MACRO addone(x) AS x + 1",
    )
    r = client.post(
        "/api/query", json={"sql": "SELECT addone(41) AS v", "limit": 1}
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[42]]


def test_broken_user_view_does_not_break_query(client):
    store.add_object(
        name="ok_v",
        kind="view",
        sql="CREATE OR REPLACE VIEW ok_v AS SELECT 1 AS a",
    )
    store.add_object(
        name="bad_v",
        kind="view",
        sql="CREATE OR REPLACE VIEW bad_v AS SELECT * FROM does_not_exist",
    )
    r = client.post(
        "/api/query", json={"sql": "SELECT a FROM ok_v", "limit": 1}
    )
    assert r.status_code == 200 and r.json()["rows"] == [[1]]


def test_schema_endpoint_serves_user_view(client):
    store.add_object(
        name="sv",
        kind="view",
        sql="CREATE OR REPLACE VIEW sv AS SELECT 1 AS a, 'x' AS b",
    )
    r = client.get("/api/query/schema", params={"dataset": "sv"})
    assert r.status_code == 200, r.text
    names = [c["name"] for c in r.json()["columns"]]
    assert names == ["a", "b"]
