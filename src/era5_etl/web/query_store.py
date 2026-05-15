"""Persisted SQL-editor query history (M03).

History is server-backed (survives across browsers/sessions), keyed by
*view name* (``era5`` / ``era5_land``) — the era5-etl analogue of the
datasus-etl per-subsystem history. Stored as JSON next to the user
config (reusing :func:`era5_etl.web.user_config._config_dir`) so it is
human-inspectable and trivially portable.

Templates are server-defined and read-only (no user authoring), matching
the datasus precedent. Favorites are a flag on history entries, not a
separate store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

#: Per-view cap. Oldest entries are evicted first; favourited entries are
#: never evicted (they are pinned, like datasus).
HISTORY_CAP = 200

_LOCK = threading.Lock()


def _store_path():
    return _config_dir() / "query_store.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"history": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s -- starting empty", path, exc)
        return {"history": {}}
    if not isinstance(data, dict):
        return {"history": {}}
    data.setdefault("history", {})
    if not isinstance(data["history"], dict):
        data["history"] = {}
    return data


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic on same volume


def list_history(view: str) -> list[dict[str, Any]]:
    """Return entries for ``view``, newest first."""
    with _LOCK:
        data = _load()
        entries = list(data["history"].get(view, []))
    # The bucket is stored in append order (oldest first). Reverse first so
    # that the stable ts-sort breaks same-millisecond ties newest-first.
    entries.reverse()
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return entries


def append_history(
    view: str, sql: str, rows: int, elapsed_ms: int
) -> list[dict[str, Any]]:
    """Append a run, evict to :data:`HISTORY_CAP`, return the new list."""
    entry = {
        "id": uuid.uuid4().hex,
        "sql": sql,
        "ts": int(time.time() * 1000),
        "rows": int(rows),
        "elapsed_ms": int(elapsed_ms),
        "name": None,
        "favorite": False,
    }
    with _LOCK:
        data = _load()
        bucket = list(data["history"].get(view, []))
        bucket.append(entry)
        # Evict oldest non-favorite entries past the cap.
        if len(bucket) > HISTORY_CAP:
            bucket.sort(key=lambda e: e.get("ts", 0))
            keep_favorites = [e for e in bucket if e.get("favorite")]
            others = [e for e in bucket if not e.get("favorite")]
            overflow = len(bucket) - HISTORY_CAP
            others = others[overflow:] if overflow < len(others) else []
            bucket = keep_favorites + others
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def patch_history(
    view: str, entry_id: str, *, name: Any = ..., favorite: Any = ...
) -> list[dict[str, Any]]:
    """Patch ``name`` / ``favorite`` on one entry. Unknown id is a no-op."""
    with _LOCK:
        data = _load()
        bucket = data["history"].get(view, [])
        for e in bucket:
            if e.get("id") == entry_id:
                if name is not ...:
                    e["name"] = name
                if favorite is not ...:
                    e["favorite"] = bool(favorite)
                break
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def delete_history(view: str, entry_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        bucket = [
            e for e in data["history"].get(view, []) if e.get("id") != entry_id
        ]
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def clear_history(view: str) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        data["history"][view] = []
        _save(data)
    return []


# --- Templates (server-defined, read-only) --------------------------------

_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "era5-land-recent",
        "name": "ERA5-LAND — latest 100 rows",
        "category": "era5_land",
        "sql": "SELECT * FROM era5_land\nORDER BY date DESC\nLIMIT 100;",
    },
    {
        "id": "era5-land-daily-mean",
        "name": "ERA5-LAND — daily mean per variable",
        "category": "era5_land",
        "sql": (
            "SELECT date, variable, AVG(value) AS mean_value\n"
            "FROM era5_land\n"
            "GROUP BY date, variable\n"
            "ORDER BY date, variable;"
        ),
    },
    {
        "id": "era5-recent",
        "name": "ERA5 — latest 100 rows",
        "category": "era5",
        "sql": "SELECT * FROM era5\nORDER BY date DESC\nLIMIT 100;",
    },
    {
        "id": "era5-grid-coverage",
        "name": "ERA5 — distinct grid points",
        "category": "era5",
        "sql": (
            "SELECT DISTINCT latitude, longitude\n"
            "FROM era5\n"
            "ORDER BY latitude, longitude;"
        ),
    },
    {
        "id": "join-era5-vs-land",
        "name": "Compare ERA5 vs ERA5-LAND at a point",
        "category": "join",
        "sql": (
            "SELECT a.date, a.variable,\n"
            "       a.value AS era5_value,\n"
            "       b.value AS era5_land_value\n"
            "FROM era5 a\n"
            "JOIN era5_land b\n"
            "  ON a.date = b.date\n"
            " AND a.variable = b.variable\n"
            " AND a.latitude = b.latitude\n"
            " AND a.longitude = b.longitude\n"
            "LIMIT 100;"
        ),
    },
]


def list_templates() -> list[dict[str, Any]]:
    return [dict(t) for t in _TEMPLATES]


__all__ = [
    "HISTORY_CAP",
    "list_history",
    "append_history",
    "patch_history",
    "delete_history",
    "clear_history",
    "list_templates",
]
