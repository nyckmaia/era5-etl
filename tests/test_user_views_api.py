"""User-views CRUD + preview + build-sql API.

TestClient + isolated ERA5_ETL_CONFIG_DIR; no network.
"""

import pytest
from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def test_crud_and_validation(client):
    r = client.post(
        "/api/user-views",
        json={
            "name": "k",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW k AS SELECT 1 AS a",
        },
    )
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    assert any(o["name"] == "k" for o in client.get("/api/user-views").json())

    bad = client.post(
        "/api/user-views",
        json={
            "name": "evil",
            "kind": "view",
            "sql": "CREATE VIEW evil AS SELECT 1; DROP TABLE x",
        },
    )
    assert bad.status_code == 400

    assert client.delete(f"/api/user-views/{oid}").status_code == 200
    assert client.get("/api/user-views").json() == []


def test_build_sql_endpoint(client):
    r = client.post(
        "/api/user-views/build-sql",
        json={
            "name": "cmp",
            "join_type": "LEFT",
            "sources": [
                {"view": "inmet", "alias": "i", "columns": ["value"]},
                {"view": "era5", "alias": "e", "columns": ["value"]},
            ],
            "joins": [
                {
                    "left": "i.latitude",
                    "right": "e.latitude",
                    "approx": True,
                    "epsilon": 1e-4,
                }
            ],
        },
    )
    assert r.status_code == 200
    assert 'abs(e."latitude" - i."latitude") < 0.0001' in r.json()["sql"]


def test_builder_spec_roundtrip(client):
    """The builder snapshot is persisted on create + returned by list/update."""
    spec = {
        "name": "v",
        "join_type": "LEFT",
        "sources": [{"view": "inmet", "alias": "i", "columns": ["a"]}],
        "joins": [],
    }
    r = client.post(
        "/api/user-views",
        json={
            "name": "v",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW v AS SELECT 1 AS a",
            "builder_spec": spec,
        },
    )
    assert r.status_code == 200, r.text
    obj = r.json()
    assert obj["builder_spec"] is not None
    assert obj["builder_spec"]["name"] == "v"

    listed = client.get("/api/user-views").json()
    assert listed[0]["builder_spec"]["sources"][0]["columns"] == ["a"]

    # Editing without builder_spec wipes the snapshot (the SQL came from
    # the SQL editor, not the builder).
    r2 = client.put(
        f"/api/user-views/{obj['id']}",
        json={
            "name": "v",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW v AS SELECT 2 AS a",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["builder_spec"] is None


def test_preview_reports_error_without_raising(client):
    r = client.post(
        "/api/user-views/preview",
        json={
            "name": "p",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW p AS SELECT * FROM nope",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"]
