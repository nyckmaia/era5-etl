"""Read-only SQL endpoint with allowlist validation."""

from __future__ import annotations

import contextlib
import re
import time
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

# DDL the SQL editor's Run query button is allowed to run: a single
# ``CREATE [OR REPLACE] [TEMP] VIEW|MACRO <name> ...`` statement. The
# match captures the object kind + name so we can persist it under
# Minhas views & macros.
_DDL_NAME_RE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(VIEW|MACRO)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"([A-Za-z_][A-Za-z0-9_]*)"|([A-Za-z_][A-Za-z0-9_]*))',
    re.IGNORECASE | re.DOTALL,
)
_LEADING_COMMENT_RE = re.compile(r"(?:\s+|--[^\n]*\n|/\*.*?\*/)+", re.DOTALL)
_CREATE_PREFIX_RE = re.compile(
    r"^(\s*)CREATE\s+(?:OR\s+REPLACE\s+)?(TEMP(?:ORARY)?\s+)?(VIEW|MACRO)\b",
    re.IGNORECASE | re.DOTALL,
)


def _strip_leading_comments(sql: str) -> str:
    """Drop leading whitespace + ``-- line`` / ``/* block */`` comments."""
    m = _LEADING_COMMENT_RE.match(sql)
    return sql[m.end():] if m and m.start() == 0 else sql


def _normalize_ddl(sql: str) -> str:
    """Rewrite the leading clause to ``CREATE OR REPLACE`` so replays of
    the persisted SQL stay idempotent regardless of what the user typed."""
    return _CREATE_PREFIX_RE.sub(
        lambda m: f"{m.group(1)}CREATE OR REPLACE {m.group(2) or ''}{m.group(3)}",
        sql,
        count=1,
    )


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

    from era5_etl.web import user_views_store as uvs
    from era5_etl.web.query_engine import get_engine, query_conn
    from era5_etl.web.user_config import load_user_config

    data_dir: Path = request.app.state.data_dir
    timeout_s = max(0, int(load_user_config().query_timeout_s))
    eng = get_engine(data_dir)
    timer_fired = {"v": False}

    def _make_timer():
        def _on_timeout() -> None:
            timer_fired["v"] = True
            with contextlib.suppress(Exception):
                eng.conn.interrupt()

        t = (
            threading.Timer(timeout_s, _on_timeout)
            if timeout_s > 0
            else None
        )
        if t is not None:
            t.daemon = True
            t.start()
        return t

    def _map_duckdb_error(exc: duckdb.Error) -> HTTPException:
        if eng.cancel_requested:
            return HTTPException(
                status_code=499, detail="Query cancelada pelo usuário."
            )
        if timer_fired["v"] or "interrupt" in str(exc).lower():
            return HTTPException(
                status_code=408,
                detail=f"Tempo limite excedido ({timeout_s}s).",
            )
        return HTTPException(status_code=400, detail=f"DuckDB error: {exc}")

    # ------------------------------------------------------------------
    # DDL through Run query: a single CREATE [OR REPLACE] VIEW/MACRO is
    # accepted, executed, and persisted under Minhas views & macros so it
    # shows up in the SCHEMA sidebar (and survives restart).
    # ------------------------------------------------------------------
    ddl_m = _DDL_NAME_RE.match(_strip_leading_comments(body.sql))
    if ddl_m:
        # ``_DDL_NAME_RE`` only matches VIEW / MACRO, so the lowered token
        # is one of the two literals expected by ``uvs.add_object`` —
        # narrow the type explicitly for mypy.
        from typing import Literal, cast

        kind = cast("Literal['view', 'macro']", ddl_m.group(1).lower())
        name = ddl_m.group(2) or ddl_m.group(3)
        try:
            uvs.validate_ddl(name, kind, body.sql)
        except uvs.UserObjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            with query_conn(data_dir) as (conn, _registered):
                eng.cancel_requested = False
                timer = _make_timer()
                try:
                    _t0 = time.perf_counter()
                    conn.execute(body.sql)
                    elapsed_ms = (time.perf_counter() - _t0) * 1000.0
                finally:
                    if timer is not None:
                        timer.cancel()
        except duckdb.Error as exc:
            raise _map_duckdb_error(exc) from exc

        # Persist the OR REPLACE form so subsequent engine resyncs stay
        # idempotent even if the user typed plain `CREATE VIEW x`.
        normalized = _normalize_ddl(body.sql)
        existing = uvs.find_by_name(name)
        try:
            if existing is not None:
                uvs.update_object(
                    existing["id"], name=name, kind=kind, sql=normalized
                )
                action = "atualizado"
            else:
                uvs.add_object(name=name, kind=kind, sql=normalized)
                action = "criado"
        except uvs.UserObjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return QueryOut(
            columns=["object", "name", "status"],
            column_types=["str", "str", "str"],
            rows=[[kind.upper(), name, action]],
            row_count=1,
            truncated=False,
            total_rows=1,
            elapsed_ms=elapsed_ms,
        )

    _validate_sql(body.sql)

    try:
        with query_conn(data_dir) as (conn, registered):
            # Builtin objects (e.g. the bilinear_weights macro) are always
            # registered — they must NOT mask the "nothing downloaded yet"
            # state, which is keyed on base views / user objects existing.
            from era5_etl.web.builtin_objects import BUILTIN_NAMES

            if not [r for r in registered if r.lower() not in BUILTIN_NAMES]:
                raise HTTPException(
                    status_code=404,
                    detail="No Parquet data for any dataset yet.",
                )
            # Reset the cancel flag inside the lock so a late-arriving
            # /api/query/cancel can only affect THIS execution.
            eng.cancel_requested = False
            timer = _make_timer()
            try:
                _t0 = time.perf_counter()
                result = conn.execute(body.sql).fetch_arrow_table()
                elapsed_ms = (time.perf_counter() - _t0) * 1000.0
                arrow_schema = result.schema
                df = result.to_pandas()
            finally:
                if timer is not None:
                    timer.cancel()
    except duckdb.Error as exc:
        raise _map_duckdb_error(exc) from exc

    # The full result is already materialized, so the true row count is
    # known exactly (no extra COUNT(*) probe needed). Expose it so the UI
    # can show "showing X of Y (truncated)".
    total_rows = len(df)
    truncated = total_rows > body.limit
    if truncated:
        df = df.head(body.limit)

    from era5_etl.web._types import schema_python_types

    return QueryOut(
        columns=list(df.columns),
        column_types=schema_python_types(arrow_schema),
        rows=df.astype(object).where(df.notnull(), None).values.tolist(),
        row_count=len(df),
        truncated=truncated,
        total_rows=total_rows,
        elapsed_ms=elapsed_ms,
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
                f'SELECT * FROM "{view}" LIMIT 0'
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
