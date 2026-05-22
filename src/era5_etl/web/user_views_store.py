"""Persisted user-defined DuckDB VIEW / MACRO definitions.

Stored as SQL text in JSON next to ``query_store.json`` (reusing
:func:`era5_etl.web.user_config._config_dir`). Replayed onto the
per-request in-memory connection -- parquet stays immutable, there is no
writable DuckDB file and therefore no single-writer lock between the web
server and the CLI. This is exactly the on-demand model the old
``era5_inmet`` view used, now user-driven.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Literal

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.paths import view_name_for
from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DDL_RE = re.compile(
    r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(TEMP\s+|TEMPORARY\s+)?(VIEW|MACRO)\b",
    re.IGNORECASE | re.DOTALL,
)
_OR_REPLACE_RE = re.compile(r"^\s*CREATE\s+OR\s+REPLACE\b", re.IGNORECASE)
# Block anything that could mutate state or read/write outside the
# read-only parquet sandbox. Parity with query._validate_sql plus DDL.
_DENIED_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|ATTACH|DETACH|COPY|"
    r"EXPORT|IMPORT|PRAGMA|INSTALL|LOAD|CALL)\b|;\s*\S",
    re.IGNORECASE,
)


class UserObjectError(ValueError):
    """Invalid user object (bad name, duplicate, or unsafe SQL)."""


def _store_path():
    return _config_dir() / "user_views.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"objects": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s -- starting empty", path, exc)
        return {"objects": []}
    if not isinstance(data, dict) or not isinstance(data.get("objects"), list):
        return {"objects": []}
    return data


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic on same volume


def _reserved_names() -> set[str]:
    # The Parquet-backed base views plus the system-provided builtin
    # objects (e.g. the bilinear_weights macro) are reserved. `era5_inmet`
    # is NOT reserved — it is a user-created view (the era5-inmet-compare
    # template exists precisely so the user can save it under that name).
    from era5_etl.web.builtin_objects import BUILTIN_NAMES

    return (
        {view_name_for(n) for n in DatasetRegistry.names()}
        | {"era5", "era5_land", "inmet"}
        | set(BUILTIN_NAMES)
    )


def validate_ddl(name: str, kind: str, sql: str) -> None:
    """Reject bad names and non-``CREATE VIEW/MACRO`` or unsafe SQL.

    A trailing ``;`` is allowed; a second statement after it is not (the
    ``;\\s*\\S`` arm of :data:`_DENIED_RE`).
    """
    if kind not in ("view", "macro"):
        raise UserObjectError(f"Unknown kind: {kind!r}")
    if not _IDENT_RE.match(name):
        raise UserObjectError(
            "Name must be a valid SQL identifier (letters, digits, _)."
        )
    if name.lower() in _reserved_names():
        raise UserObjectError(f"'{name}' is a reserved base-view name.")
    if not _DDL_RE.match(sql):
        raise UserObjectError(
            "SQL must be a CREATE [OR REPLACE] VIEW/MACRO statement."
        )
    # Strip the leading CREATE ... clause before scanning so the
    # statement's own VIEW/MACRO keyword isn't a false positive, and a
    # single trailing ';' doesn't trip the multi-statement guard.
    body = _DDL_RE.sub("", sql, count=1).strip().rstrip(";")
    if _DENIED_RE.search(body):
        raise UserObjectError("SQL contains a disallowed statement.")


def is_or_replace(sql: str) -> bool:
    """True when the DDL starts with ``CREATE OR REPLACE``.

    SQL semantics: ``CREATE OR REPLACE VIEW`` means "create it, or
    overwrite the existing one of the same name". Callers use this to
    decide whether a name collision is an error (plain ``CREATE``) or an
    intentional overwrite (``CREATE OR REPLACE``).
    """
    return bool(_OR_REPLACE_RE.match(sql))


def add_object(
    *,
    name: str,
    kind: Literal["view", "macro"],
    sql: str,
    builder_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_ddl(name, kind, sql)
    now = int(time.time() * 1000)
    obj = {
        "id": uuid.uuid4().hex,
        "name": name,
        "kind": kind,
        "sql": sql,
        # Snapshot of the visual-builder selections that produced this SQL
        # (``None`` when the object was saved via the SQL editor). The
        # builder modal re-hydrates from it on edit.
        "builder_spec": builder_spec,
        "created_ts": now,
        "updated_ts": now,
    }
    with _LOCK:
        data = _load()
        if any(o["name"].lower() == name.lower() for o in data["objects"]):
            raise UserObjectError(f"An object named '{name}' already exists.")
        data["objects"].append(obj)
        _save(data)
    return obj


def update_object(
    obj_id: str,
    *,
    name: str,
    kind: str,
    sql: str,
    builder_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_ddl(name, kind, sql)
    with _LOCK:
        data = _load()
        target = next(
            (o for o in data["objects"] if o["id"] == obj_id), None
        )
        if target is None:
            raise UserObjectError(f"Unknown object id: {obj_id}")
        if any(
            o["id"] != obj_id and o["name"].lower() == name.lower()
            for o in data["objects"]
        ):
            raise UserObjectError(f"An object named '{name}' already exists.")
        target.update(
            name=name,
            kind=kind,
            sql=sql,
            builder_spec=builder_spec,
            updated_ts=int(time.time() * 1000),
        )
        _save(data)
    assert isinstance(target, dict)
    return target


def delete_object(obj_id: str) -> None:
    with _LOCK:
        data = _load()
        data["objects"] = [
            o for o in data["objects"] if o["id"] != obj_id
        ]
        _save(data)


def list_objects() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_load()["objects"])


def find_by_name(name: str) -> dict[str, Any] | None:
    """Case-insensitive lookup. Returns ``None`` if no match."""
    target = name.lower()
    for o in list_objects():
        if o["name"].lower() == target:
            return o
    return None


def register_user_objects(conn) -> list[dict[str, Any]]:
    """Replay every stored object onto ``conn`` (base views must already
    be registered).

    Returns per-object status dicts (the stored fields plus ``ok`` and
    ``error``). A broken object is skipped with its error captured --
    never aborting the request.
    """
    results: list[dict[str, Any]] = []
    for o in sorted(list_objects(), key=lambda x: x["created_ts"]):
        try:
            conn.execute(o["sql"])
            results.append({**o, "ok": True, "error": None})
        except Exception as exc:
            results.append({**o, "ok": False, "error": str(exc)})
    return results


__all__ = [
    "UserObjectError",
    "add_object",
    "delete_object",
    "find_by_name",
    "is_or_replace",
    "list_objects",
    "register_user_objects",
    "update_object",
    "validate_ddl",
]
