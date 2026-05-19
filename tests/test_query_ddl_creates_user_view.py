"""DDL through /api/query: CREATE VIEW/MACRO is accepted and persists
under Minhas views & macros so it appears in the SCHEMA sidebar.
"""

import pytest
from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def test_create_view_via_run_query_persists(client):
    r = client.post(
        "/api/query",
        json={
            "sql": "CREATE OR REPLACE VIEW foo AS SELECT 1 AS a",
            "limit": 10,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["object", "name", "status"]
    assert body["rows"] == [["VIEW", "foo", "criado"]]

    listed = client.get("/api/user-views").json()
    assert any(o["name"] == "foo" for o in listed)
    # The persisted SQL is normalised to CREATE OR REPLACE so engine
    # resyncs stay idempotent.
    foo = next(o for o in listed if o["name"] == "foo")
    assert foo["sql"].lstrip().upper().startswith("CREATE OR REPLACE VIEW")
    assert foo["builder_spec"] is None

    # Re-running updates the existing entry, not adds a new one.
    r2 = client.post(
        "/api/query",
        json={
            "sql": "CREATE OR REPLACE VIEW foo AS SELECT 2 AS b",
            "limit": 10,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["rows"] == [["VIEW", "foo", "atualizado"]]
    listed2 = client.get("/api/user-views").json()
    assert sum(1 for o in listed2 if o["name"] == "foo") == 1


def test_create_view_with_plain_create_keyword(client):
    # No OR REPLACE; DuckDB accepts on first create, store normalises.
    r = client.post(
        "/api/query",
        json={"sql": "CREATE VIEW bar AS SELECT 7 AS x", "limit": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][1] == "bar"


def test_macro_via_run_query(client):
    r = client.post(
        "/api/query",
        json={
            "sql": "CREATE OR REPLACE MACRO addone(x) AS x + 1",
            "limit": 1,
        },
    )
    assert r.status_code == 200
    assert r.json()["rows"][0][0] == "MACRO"
    # And it's actually callable from a SELECT now.
    sel = client.post(
        "/api/query",
        json={"sql": "SELECT addone(41) AS v", "limit": 1},
    )
    assert sel.status_code == 200
    assert sel.json()["rows"] == [[42]]


def test_create_view_rejects_reserved_name(client):
    r = client.post(
        "/api/query",
        json={"sql": "CREATE VIEW era5 AS SELECT 1", "limit": 1},
    )
    assert r.status_code == 400
    assert "reserved" in r.json()["detail"].lower()


def test_multi_statement_ddl_rejected(client):
    r = client.post(
        "/api/query",
        json={
            "sql": "CREATE VIEW evil AS SELECT 1; DROP TABLE x",
            "limit": 1,
        },
    )
    assert r.status_code == 400


def test_drop_still_rejected_as_non_ddl_write(client):
    # No CREATE prefix → falls through to the SELECT validator, which
    # blocks anything other than SELECT/WITH.
    r = client.post(
        "/api/query", json={"sql": "DROP TABLE x", "limit": 1}
    )
    assert r.status_code == 400


def test_view_created_via_run_query_appears_in_schema(client):
    client.post(
        "/api/query",
        json={
            "sql": "CREATE OR REPLACE VIEW myview AS SELECT 3 AS c",
            "limit": 1,
        },
    )
    r = client.get("/api/query/schema", params={"dataset": "myview"})
    assert r.status_code == 200
    cols = [c["name"] for c in r.json()["columns"]]
    assert cols == ["c"]
