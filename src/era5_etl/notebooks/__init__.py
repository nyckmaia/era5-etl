"""In-app Python notebook runtime.

The notebook feature runs a persistent Python subprocess (kernel) per notebook
and streams its outputs back to the SPA over SSE. This package provides:

- :func:`connect` — a fresh DuckDB connection wired with the same base views
  (per-dataset parquet) and user views/macros that the ``/query`` endpoint
  exposes. Reuses logic from :mod:`era5_etl.web.query_engine` and
  :mod:`era5_etl.web.user_views_store` so a notebook sees the exact same
  catalog the user built in the UI.
- :mod:`era5_etl.notebooks.kernel_runner` — the bootstrap script that runs
  inside the subprocess.
- :mod:`era5_etl.notebooks.kernel_manager` — start/stop/run-cell orchestration.
- :mod:`era5_etl.notebooks.templates` — bundled notebook templates.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.storage.paths import view_name_for
from era5_etl.web import user_views_store as uvs
from era5_etl.web.builtin_objects import BUILTIN_NAMES, BUILTIN_OBJECTS


def connect(data_dir: str | Path) -> duckdb.DuckDBPyConnection:
    """Return a fresh in-memory DuckDB connection with all views registered.

    Independent from the cached engine used by ``/api/query`` — the kernel
    owns its own connection so long-running queries inside a notebook do
    not block the rest of the web app. The catalog is built from the same
    sources (base parquet views + builtin macros + user objects).
    """
    data_dir = Path(data_dir).expanduser().resolve()
    conn = duckdb.connect(":memory:")
    for obj in BUILTIN_OBJECTS:
        conn.execute(obj["sql"])
    for name in DatasetRegistry.names():
        mgr = ParquetManager(data_dir, name)
        if mgr.exists():
            mgr.create_duckdb_view(conn, view_name_for(name))
    for obj in sorted(uvs.list_objects(), key=lambda x: x["created_ts"]):
        if obj["name"].lower() in BUILTIN_NAMES:
            continue
        try:
            conn.execute(obj["sql"])
        except duckdb.Error:
            # A broken user view should not crash the kernel boot; the
            # user can still query everything else.
            pass
    return conn


__all__ = ["connect"]
