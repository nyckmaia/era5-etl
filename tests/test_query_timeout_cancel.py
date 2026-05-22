"""Settings round-trip for query_timeout_s + /api/query/cancel smoke test."""

import pytest
from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def test_query_timeout_default_and_roundtrip(client):
    # Default is 120 s.
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["query_timeout_s"] == 120

    # Set a new value.
    r = client.post("/api/settings", json={"query_timeout_s": 30})
    assert r.status_code == 200 and r.json()["query_timeout_s"] == 30

    # Persisted.
    assert client.get("/api/settings").json()["query_timeout_s"] == 30

    # 0 means "no timer" — allowed.
    r = client.post("/api/settings", json={"query_timeout_s": 0})
    assert r.status_code == 200 and r.json()["query_timeout_s"] == 0


def test_query_timeout_rejects_out_of_range(client):
    assert client.post(
        "/api/settings", json={"query_timeout_s": -1}
    ).status_code == 400
    assert client.post(
        "/api/settings", json={"query_timeout_s": 10_000}
    ).status_code == 400


def test_cancel_endpoint_is_safe_when_nothing_running(client):
    # No query is in flight; cancel must not error.
    r = client.post("/api/query/cancel")
    assert r.status_code == 200 and r.json() == {"ok": True}
