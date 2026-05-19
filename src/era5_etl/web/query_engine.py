"""Process-cached DuckDB connection for the read endpoints.

The web UI used to open a fresh ``:memory:`` connection **per request**
and recreate every dataset view from Parquet each time. With INMET that
means a ``union_by_name`` bind over 10k+ files (~10 s) on every
``/api/query``, ``/api/query/schema`` and ``/api/user-views`` call.

This module keeps **one connection per resolved ``data_dir``**, builds
the base parquet views once, and replays user objects only when the
store actually changes. A per-engine re-entrant lock serialises access
(the control panel is effectively single-user; DuckDB has a single
writer anyway). The view *definitions* glob Parquet lazily at query
time, so newly downloaded files are still picked up without rebuilding.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.storage.paths import view_name_for
from era5_etl.web import user_views_store as uvs


class _Engine:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.lock = threading.RLock()
        self.conn = duckdb.connect(":memory:")
        self.base_views: set[str] = set()
        # Datasets without parquet yet — re-checked cheaply each call so a
        # dataset downloaded while the UI is open eventually registers.
        self._missing: set[str] = set(DatasetRegistry.names())
        self._user_sig: tuple | None = None
        self._user_results: list[dict[str, Any]] = []
        self._user_names: set[str] = set()

    def _ensure_base(self) -> None:
        still_missing: set[str] = set()
        for name in self._missing:
            mgr = ParquetManager(self.data_dir, name)
            if not mgr.exists():
                still_missing.add(name)
                continue
            mgr.create_duckdb_view(self.conn, view_name_for(name))
            self.base_views.add(view_name_for(name))
        self._missing = still_missing

    def _ensure_user(self) -> None:
        objs = sorted(uvs.list_objects(), key=lambda x: x["created_ts"])
        sig = tuple((o["id"], o["updated_ts"], o["sql"]) for o in objs)
        if sig == self._user_sig:
            return
        current = {o["name"] for o in objs}
        for stale in self._user_names - current:
            for kind in ("VIEW", "MACRO"):
                try:
                    self.conn.execute(f'DROP {kind} IF EXISTS "{stale}"')
                except duckdb.Error:
                    pass
        results: list[dict[str, Any]] = []
        for o in objs:
            try:
                self.conn.execute(o["sql"])
                results.append({**o, "ok": True, "error": None})
            except Exception as exc:  # noqa: BLE001 -- surfaced, not raised
                results.append({**o, "ok": False, "error": str(exc)})
        self._user_names = current
        self._user_sig = sig
        self._user_results = results

    def registered(self) -> list[str]:
        return list(self.base_views) + [
            r["name"] for r in self._user_results if r["ok"]
        ]


_CACHE: dict[str, _Engine] = {}
_CACHE_LOCK = threading.Lock()


def _engine(data_dir: str | Path) -> _Engine:
    key = str(Path(data_dir).expanduser().resolve())
    with _CACHE_LOCK:
        eng = _CACHE.get(key)
        if eng is None:
            eng = _Engine(Path(key))
            _CACHE[key] = eng
        return eng


@contextmanager
def query_conn(data_dir: str | Path):
    """Yield ``(conn, registered_names)`` for ``data_dir``.

    Base views are created once; user objects are re-synced only when the
    store changed. Held under the per-engine lock for the whole ``with``.
    """
    eng = _engine(data_dir)
    with eng.lock:
        eng._ensure_base()
        eng._ensure_user()
        yield eng.conn, eng.registered()


def user_object_status(data_dir: str | Path) -> list[dict[str, Any]]:
    """Per-object ``ok``/``error`` status (base views ensured first)."""
    eng = _engine(data_dir)
    with eng.lock:
        eng._ensure_base()
        eng._ensure_user()
        return list(eng._user_results)


@contextmanager
def validate_conn(data_dir: str | Path):
    """Yield the cached connection inside a transaction that is always
    rolled back — used to compile/introspect a candidate DDL without
    mutating the catalog or rebuilding the base views.
    """
    eng = _engine(data_dir)
    with eng.lock:
        eng._ensure_base()
        eng._ensure_user()
        eng.conn.execute("BEGIN TRANSACTION")
        try:
            yield eng.conn
        finally:
            try:
                eng.conn.execute("ROLLBACK")
            except duckdb.Error:
                pass
