"""On-demand `mlflow ui` subprocess endpoints (Popen mocked — no real server)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture(autouse=True)
def _reset_mlflow_ui_state():
    from era5_etl.web.routes import mlflow_ui

    yield
    mlflow_ui.shutdown()


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(app)


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.stderr = None

    def poll(self):
        return 1 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def test_server_concurrency_args_are_multithreaded(monkeypatch):
    """The `mlflow ui` server must run multi-threaded so it doesn't 'load
    forever' while a notebook run writes to the file store (single-threaded
    default serves one request at a time)."""
    from era5_etl.web.routes import mlflow_ui

    monkeypatch.setattr(mlflow_ui.sys, "platform", "win32")
    assert mlflow_ui._server_concurrency_args() == ["--waitress-opts", "--threads=8"]
    monkeypatch.setattr(mlflow_ui.sys, "platform", "linux")
    assert mlflow_ui._server_concurrency_args() == ["--workers", "4"]


def test_status_initially_not_running(client):
    r = client.get("/api/mlflow/ui/status")
    assert r.status_code == 200
    assert r.json() == {"running": False, "url": None}


def test_start_is_idempotent_and_status_reports_url(client, monkeypatch):
    from era5_etl.web.routes import mlflow_ui

    proc = _FakeProc()
    monkeypatch.setattr(mlflow_ui, "_spawn", lambda port: proc)
    monkeypatch.setattr(mlflow_ui, "_port_open", lambda port: True)

    r1 = client.post("/api/mlflow/ui/start")
    assert r1.status_code == 200
    url = r1.json()["url"]
    assert url.startswith("http://127.0.0.1:")

    # Second start returns the same URL without spawning again.
    monkeypatch.setattr(
        mlflow_ui, "_spawn", lambda port: pytest.fail("spawned twice")
    )
    assert client.post("/api/mlflow/ui/start").json()["url"] == url
    assert client.get("/api/mlflow/ui/status").json() == {"running": True, "url": url}

    mlflow_ui.shutdown()
    assert proc.terminated
    assert client.get("/api/mlflow/ui/status").json()["running"] is False


def test_start_failure_returns_502(client, monkeypatch):
    import io

    from era5_etl.web.routes import mlflow_ui

    class _DeadProc(_FakeProc):
        def __init__(self):
            super().__init__()
            self.stderr = io.StringIO("boom: port in use")

        def poll(self):
            return 1

    monkeypatch.setattr(mlflow_ui, "_spawn", lambda port: _DeadProc())
    r = client.post("/api/mlflow/ui/start")
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]
