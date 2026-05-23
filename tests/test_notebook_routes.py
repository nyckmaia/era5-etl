"""HTTP endpoints for the notebook feature."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(app)


def test_list_templates(client):
    r = client.get("/api/notebooks/templates")
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()}
    assert {"getting_started", "xgboost_temperature_forecast"}.issubset(ids)


def test_crud_lifecycle(client):
    # Initially empty.
    assert client.get("/api/notebooks").json() == []

    # Create from blank.
    r = client.post("/api/notebooks", json={"name": "test"})
    assert r.status_code == 200
    nb = r.json()
    nb_id = nb["id"]
    assert nb["cells"] == []

    # Get + list.
    assert client.get(f"/api/notebooks/{nb_id}").status_code == 200
    items = client.get("/api/notebooks").json()
    assert [i["id"] for i in items] == [nb_id]

    # Save with new cells.
    payload = {
        "name": "renamed",
        "cells": [{"id": "c1", "type": "code", "source": "print('hi')", "outputs": []}],
    }
    r = client.put(f"/api/notebooks/{nb_id}", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "renamed"
    assert r.json()["cells"][0]["source"] == "print('hi')"

    # Delete.
    assert client.delete(f"/api/notebooks/{nb_id}").json() == {"deleted": True}
    assert client.get(f"/api/notebooks/{nb_id}").status_code == 404


def test_create_from_xgboost_template(client):
    r = client.post(
        "/api/notebooks", json={"template_id": "xgboost_temperature_forecast"}
    )
    assert r.status_code == 200, r.text
    nb = r.json()
    assert len(nb["cells"]) >= 8
    # First cell must be the markdown intro.
    assert nb["cells"][0]["type"] == "markdown"


def test_create_with_unknown_template_returns_404(client):
    r = client.post("/api/notebooks", json={"template_id": "does-not-exist"})
    assert r.status_code == 404


def test_kernel_status_dead_for_unknown_notebook(client):
    r = client.get("/api/notebooks/nonexistent/kernel/status")
    assert r.status_code == 200
    assert r.json()["status"] == "dead"


def test_save_unknown_notebook_returns_404(client):
    r = client.put(
        "/api/notebooks/nonexistent",
        json={"name": "x", "cells": []},
    )
    assert r.status_code == 404


def test_append_run_requires_valid_token(client):
    # Make a notebook so the path exists.
    nb_id = client.post("/api/notebooks", json={"name": "x"}).json()["id"]
    # No kernel started → no valid token → 403.
    r = client.post(
        f"/api/notebooks/{nb_id}/runs",
        json={"params": {}, "metrics": {}, "duration_s": 0.1},
        headers={"X-Notebook-Token": "wrong"},
    )
    assert r.status_code == 403
