"""Read-only SQL endpoint with allowlist validation."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.storage.paths import view_name_for
from era5_etl.web.models import QueryIn, QueryOut, QuerySchemaOut, SchemaColumn

router = APIRouter(prefix="/api/query", tags=["query"])

# Only SELECT or WITH ... SELECT queries are allowed.
_ALLOWED_PREFIX_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)
_DENIED_PATTERNS = [
    re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|ATTACH|DETACH|COPY|EXPORT|PRAGMA)\b", re.IGNORECASE),
]


def _validate_sql(sql: str) -> None:
    if not _ALLOWED_PREFIX_RE.search(sql):
        raise HTTPException(status_code=400, detail="Only SELECT/WITH queries are allowed.")
    for pat in _DENIED_PATTERNS:
        if pat.search(sql):
            raise HTTPException(status_code=400, detail="SQL contains disallowed statement.")


def register_all_views(conn, data_dir: Path) -> list[str]:
    """Register every dataset's DuckDB view that has parquet on disk.

    Lets a single query reference any dataset by its view name
    (``era5``, ``era5_land``, ``inmet``) or JOIN across them (M02a).
    User-defined views/macros are then replayed on top so they are
    available wherever SQL runs (query, export, schema sidebar). A broken
    user object is skipped (its error surfaces via ``/api/user-views``),
    never aborting the base views.
    Returns the list of view names registered (empty if no dataset has
    data yet).
    """
    registered: list[str] = []
    for name in DatasetRegistry.names():
        mgr = ParquetManager(data_dir, name)
        if not mgr.exists():
            continue
        mgr.create_duckdb_view(conn, view_name_for(name))
        registered.append(view_name_for(name))

    from era5_etl.web.user_views_store import register_user_objects

    for r in register_user_objects(conn):
        if r["ok"]:
            registered.append(r["name"])
    return registered


@router.post("", response_model=QueryOut)
def run_query(body: QueryIn, request: Request) -> QueryOut:
    import threading

    import duckdb

    from era5_etl.web.query_engine import get_engine, query_conn
    from era5_etl.web.user_config import load_user_config

    _validate_sql(body.sql)

    data_dir: Path = request.app.state.data_dir
    timeout_s = max(0, int(load_user_config().query_timeout_s))
    eng = get_engine(data_dir)
    timer_fired = {"v": False}

    try:
        with query_conn(data_dir) as (conn, registered):
            if not registered:
                raise HTTPException(
                    status_code=404,
                    detail="No Parquet data for any dataset yet.",
                )
            # Reset the cancel flag inside the lock so a late-arriving
            # /api/query/cancel can only affect THIS execution.
            eng.cancel_requested = False

            def _on_timeout() -> None:
                timer_fired["v"] = True
                try:
                    eng.conn.interrupt()
                except Exception:  # noqa: BLE001
                    pass

            timer = (
                threading.Timer(timeout_s, _on_timeout)
                if timeout_s > 0
                else None
            )
            if timer is not None:
                timer.daemon = True
                timer.start()
            try:
                result = conn.execute(body.sql).fetch_arrow_table()
                arrow_schema = result.schema
                df = result.to_pandas()
            finally:
                if timer is not None:
                    timer.cancel()
    except duckdb.Error as exc:
        if eng.cancel_requested:
            raise HTTPException(
                status_code=499, detail="Query cancelada pelo usuário."
            ) from exc
        msg = str(exc).lower()
        if timer_fired["v"] or "interrupt" in msg:
            raise HTTPException(
                status_code=408,
                detail=f"Tempo limite excedido ({timeout_s}s).",
            ) from exc
        raise HTTPException(
            status_code=400, detail=f"DuckDB error: {exc}"
        ) from exc

    # The full result is already materialized, so the true row count is
    # known exactly (no extra COUNT(*) probe needed). Expose it so the UI
    # can show "showing X of Y (truncated)".
    total_rows = int(len(df))
    truncated = total_rows > body.limit
    if truncated:
        df = df.head(body.limit)

    from era5_etl.web._types import schema_python_types

    return QueryOut(
        columns=list(df.columns),
        column_types=schema_python_types(arrow_schema),
        rows=df.astype(object).where(df.notnull(), None).values.tolist(),
        row_count=int(len(df)),
        truncated=truncated,
        total_rows=total_rows,
    )


@router.get("/schema", response_model=QuerySchemaOut)
def query_schema(dataset: str, request: Request) -> QuerySchemaOut:
    """Return the dataset view's columns + short Python types.

    Powers the SQL editor's autocomplete (Melhoria 01) and the
    display-precision column list (Melhoria 02b). Returns an empty column
    list (HTTP 200, not 404) when no parquet exists yet so the UI can
    render gracefully before the first download.
    """
    import duckdb

    from era5_etl.web._types import arrow_type_to_python
    from era5_etl.web.query_engine import query_conn

    data_dir: Path = request.app.state.data_dir

    # A base dataset name (era5 / era5-land / inmet) maps to its view
    # name; anything else is treated as a view name directly (user-defined
    # views/macros). Empty columns (HTTP 200, not 404) when the view isn't
    # available yet so the UI can render gracefully before the first
    # download / before the object is created.
    view = (
        view_name_for(dataset)
        if dataset in DatasetRegistry.names()
        else dataset
    )

    try:
        with query_conn(data_dir) as (conn, registered):
            if view not in registered:
                return QuerySchemaOut(view=view, columns=[])
            schema = conn.execute(
                f'SELECT * FROM "{view}" LIMIT 0'  # noqa: S608 -- sanitized
            ).fetch_arrow_table().schema
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=400, detail=f"DuckDB error: {exc}"
        ) from exc

    return QuerySchemaOut(
        view=view,
        columns=[
            SchemaColumn(
                name=schema.field(i).name,
                type=arrow_type_to_python(schema.field(i).type),
            )
            for i in range(len(schema))
        ],
    )


@router.post("/cancel")
def cancel_query(request: Request) -> dict[str, bool]:
    """Interrupt whichever query is currently executing on this data_dir.

    No-op if nothing is running. The matching ``/api/query`` request
    returns HTTP 499 so the UI can show a "cancelled" message. Does NOT
    acquire the engine lock — that is the whole point.
    """
    from era5_etl.web.query_engine import cancel as _cancel

    data_dir: Path = request.app.state.data_dir
    _cancel(data_dir)
    return {"ok": True}
