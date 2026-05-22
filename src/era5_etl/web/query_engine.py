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
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

import duckdb

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.storage.paths import view_name_for
from era5_etl.web import user_views_store as uvs
from era5_etl.web.builtin_objects import BUILTIN_NAMES, BUILTIN_OBJECTS


class _Engine:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.lock = threading.RLock()
        self.conn = duckdb.connect(":memory:")
        # System-provided objects (e.g. the bilinear_weights macro) — no
        # dependency on parquet, so register them once up front; they are
        # then available to every query, export and validation path.
        for _o in BUILTIN_OBJECTS:
            self.conn.execute(_o["sql"])
        self.base_views: set[str] = set()
        # Datasets without parquet yet — re-checked cheaply each call so a
        # dataset downloaded while the UI is open eventually registers.
        self._missing: set[str] = set(DatasetRegistry.names())
        self._user_sig: tuple | None = None
        self._user_results: list[dict[str, Any]] = []
        self._user_names: set[str] = set()
        #: Set by :func:`cancel` so the request handler can distinguish a
        #: user-initiated abort from a timeout-initiated one.
        self.cancel_requested = False

    def cancel(self) -> None:
        """Interrupt the currently running query.

        Safe to call from a thread that does NOT hold :attr:`lock` (that
        is the whole point — it lets ``POST /api/query/cancel`` abort the
        query that is currently holding the lock). DuckDB's
        ``interrupt()`` is documented as thread-safe.
        """
        self.cancel_requested = True
        with suppress(Exception):
            self.conn.interrupt()

    def _ensure_base(self) -> None:
        still_missing: set[str] = set()
        newly_registered: list[str] = []
        for name in self._missing:
            mgr = ParquetManager(self.data_dir, name)
            if not mgr.exists():
                still_missing.add(name)
                continue
            mgr.create_duckdb_view(self.conn, view_name_for(name))
            self.base_views.add(view_name_for(name))
            newly_registered.append(name)
        self._missing = still_missing
        # If a base view just became available (e.g. the user downloaded
        # ERA5-LAND after seeing a broken user VIEW that depends on it),
        # invalidate the user-view cache so :meth:`_ensure_user` replays
        # the stored DDL against the now-larger catalog. Without this the
        # ``ok``/``error`` status sticks at the moment the view was
        # FIRST registered and stays WARN even after the dependency is
        # downloaded.
        if newly_registered:
            self._user_sig = None

    def _ensure_user(self) -> None:
        # A user object whose name collides with a builtin is ignored —
        # the builtin (registered in __init__) is authoritative.
        objs = [
            o
            for o in sorted(uvs.list_objects(), key=lambda x: x["created_ts"])
            if o["name"].lower() not in BUILTIN_NAMES
        ]
        sig = tuple((o["id"], o["updated_ts"], o["sql"]) for o in objs)
        if sig == self._user_sig:
            return
        current = {o["name"] for o in objs}
        for stale in self._user_names - current:
            for kind in ("VIEW", "MACRO"):
                with suppress(duckdb.Error):
                    self.conn.execute(f'DROP {kind} IF EXISTS "{stale}"')
        results: list[dict[str, Any]] = []
        for o in objs:
            try:
                self.conn.execute(o["sql"])
                results.append({**o, "ok": True, "error": None})
            except Exception as exc:
                results.append({**o, "ok": False, "error": str(exc)})
        self._user_names = current
        self._user_sig = sig
        self._user_results = results

    def registered(self) -> list[str]:
        return (
            list(self.base_views)
            + [o["name"] for o in BUILTIN_OBJECTS]
            + [r["name"] for r in self._user_results if r["ok"]]
        )


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


def get_engine(data_dir: str | Path) -> _Engine:
    """Return the cached engine for ``data_dir`` (creating it on demand).

    Public so :mod:`era5_etl.web.routes.query` can install a timer + read
    the cancel flag for the timeout/cancel logic.
    """
    return _engine(data_dir)


def cancel(data_dir: str | Path) -> None:
    """Interrupt whichever query the cached engine is currently running."""
    _engine(data_dir).cancel()


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
            with suppress(duckdb.Error):
                eng.conn.execute("ROLLBACK")
