"""On-demand MLflow UI subprocess (singleton).

``POST /api/mlflow/ui/start`` spawns ``python -m mlflow ui`` against the
local file store (``<config_dir>/mlruns``) on a free localhost port and
returns its URL; subsequent calls are idempotent while the process lives.
``shutdown()`` is registered as a FastAPI shutdown handler in ``server.py``.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException

from era5_etl.web.mlflow_runs import mlflow_tracking_uri

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mlflow/ui", tags=["mlflow"])

_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None
_URL: str | None = None
_START_TIMEOUT_S = 30.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _server_concurrency_args() -> list[str]:
    """Extra ``mlflow ui`` args so the server isn't single-threaded.

    Over a file store every request re-scans ``mlruns``; the default server
    serves one request at a time, so while a notebook run writes runs the UI
    "loads forever". Give it several worker threads. MLflow uses waitress on
    Windows (``--waitress-opts``) and gunicorn on POSIX (``--workers``).
    """
    if sys.platform == "win32":
        return ["--waitress-opts", "--threads=8"]
    return ["--workers", "4"]


def _spawn(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mlflow",
            "ui",
            "--backend-store-uri",
            mlflow_tracking_uri(),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            *_server_concurrency_args(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        # MLflow >= 3.x gates the file-store backend behind this env var.
        env={**os.environ, "MLFLOW_ALLOW_FILE_STORE": "true"},
    )


@router.post("/start")
def start() -> dict[str, str]:
    global _PROC, _URL
    with _LOCK:
        if _PROC is not None and _PROC.poll() is None and _URL:
            return {"url": _URL}
        port = _free_port()
        proc = _spawn(port)
        deadline = time.time() + _START_TIMEOUT_S
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() if proc.stderr else "")[-2000:]
                raise HTTPException(
                    status_code=502, detail=f"mlflow ui exited during boot: {err}"
                )
            if _port_open(port):
                break
            time.sleep(0.25)
        else:
            proc.terminate()
            raise HTTPException(status_code=502, detail="mlflow ui did not start in time")
        _PROC = proc
        _URL = f"http://127.0.0.1:{port}"
        logger.info("mlflow ui started at %s", _URL)
        return {"url": _URL}


@router.get("/status")
def status() -> dict[str, object]:
    with _LOCK:
        running = _PROC is not None and _PROC.poll() is None
        return {"running": running, "url": _URL if running else None}


def shutdown() -> None:
    """Terminate the UI subprocess (no-op when not running)."""
    global _PROC, _URL
    with _LOCK:
        proc = _PROC
        _PROC = None
        _URL = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
