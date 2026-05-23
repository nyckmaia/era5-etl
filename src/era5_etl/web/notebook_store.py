"""Persisted user notebooks.

Stored as one JSON file per notebook in ``<config_dir>/notebooks/<id>.json``
(reusing :func:`era5_etl.web.user_config._config_dir`). Each file holds the
notebook's cells, persisted outputs, and the history of model runs logged
from the kernel via ``log_model_run`` (template XGBoost).

The file is the source of truth; the kernel is ephemeral state.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

CellType = Literal["code", "sql", "markdown"]
SCHEMA_VERSION = 1


def _notebooks_dir() -> Path:
    return _config_dir() / "notebooks"


def _path_for(notebook_id: str) -> Path:
    safe = "".join(c for c in notebook_id if c.isalnum() or c in "-_")
    if safe != notebook_id or not safe:
        raise ValueError(f"Invalid notebook id: {notebook_id!r}")
    return _notebooks_dir() / f"{safe}.json"


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_notebooks() -> list[dict[str, Any]]:
    """List (id, name, updated_ts, created_ts, n_cells) — small summary only."""
    out: list[dict[str, Any]] = []
    with _LOCK:
        nb_dir = _notebooks_dir()
        if not nb_dir.exists():
            return out
        for path in sorted(nb_dir.glob("*.json")):
            if path.suffix == ".tmp":
                continue
            data = _read(path)
            if data is None or "id" not in data:
                continue
            out.append(
                {
                    "id": str(data["id"]),
                    "name": str(data.get("name", "Untitled")),
                    "updated_ts": int(data.get("updated_ts", 0)),
                    "created_ts": int(data.get("created_ts", 0)),
                    "n_cells": len(data.get("cells", [])),
                }
            )
    out.sort(key=lambda x: x["updated_ts"], reverse=True)
    return out


def get_notebook(notebook_id: str) -> dict[str, Any] | None:
    with _LOCK:
        return _read(_path_for(notebook_id))


def create_notebook(
    name: str,
    cells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nb_id = _new_id()
    now = _now_ms()
    notebook = {
        "schema_version": SCHEMA_VERSION,
        "id": nb_id,
        "name": name or "Untitled notebook",
        "cells": list(cells or []),
        "runs": [],
        "created_ts": now,
        "updated_ts": now,
    }
    with _LOCK:
        _write_atomic(_path_for(nb_id), notebook)
    return notebook


def save_notebook(
    notebook_id: str,
    *,
    name: str | None = None,
    cells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with _LOCK:
        path = _path_for(notebook_id)
        data = _read(path)
        if data is None:
            raise FileNotFoundError(f"Unknown notebook id: {notebook_id}")
        if name is not None:
            data["name"] = name
        if cells is not None:
            data["cells"] = cells
        data["updated_ts"] = _now_ms()
        _write_atomic(path, data)
        return data


def delete_notebook(notebook_id: str) -> bool:
    with _LOCK:
        path = _path_for(notebook_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def append_run(
    notebook_id: str,
    *,
    params: dict[str, Any],
    metrics: dict[str, Any],
    duration_s: float,
    notes: str = "",
    model_name: str = "xgboost",
) -> dict[str, Any]:
    """Append a model-run entry to ``runs[]`` and persist."""
    run = {
        "id": _new_id(),
        "ts": _now_ms(),
        "model_name": model_name,
        "params": params,
        "metrics": metrics,
        "duration_s": float(duration_s),
        "notes": notes,
    }
    with _LOCK:
        path = _path_for(notebook_id)
        data = _read(path)
        if data is None:
            raise FileNotFoundError(f"Unknown notebook id: {notebook_id}")
        data.setdefault("runs", []).append(run)
        data["updated_ts"] = _now_ms()
        _write_atomic(path, data)
    return run


def make_cell(
    cell_type: CellType,
    source: str = "",
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "type": cell_type,
        "source": source,
        "outputs": list(outputs or []),
    }


__all__ = [
    "SCHEMA_VERSION",
    "append_run",
    "create_notebook",
    "delete_notebook",
    "get_notebook",
    "list_notebooks",
    "make_cell",
    "save_notebook",
]
