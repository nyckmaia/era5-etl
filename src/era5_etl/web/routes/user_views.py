"""CRUD + preview + visual-builder SQL for user-defined views/macros.

Definitions are persisted by :mod:`era5_etl.web.user_views_store` and
replayed onto the per-request in-memory connection by
:func:`era5_etl.web.routes.query.register_all_views`. Validation runs the
DDL against a throwaway connection (base views registered) so a bad
definition is rejected at save time, not silently at query time.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException, Request

from era5_etl.web import user_views_store as store
from era5_etl.web._types import arrow_type_to_python
from era5_etl.web.models import (
    BuildSpec,
    BuildSqlOut,
    SchemaColumn,
    UserObjectIn,
    UserObjectOut,
)
from era5_etl.web.routes.query import register_all_views
from era5_etl.web.sql_builder import build_view_sql

router = APIRouter(prefix="/api/user-views", tags=["user-views"])


def _columns_for(conn, name: str) -> list[SchemaColumn]:
    schema = (
        conn.execute(
            f'SELECT * FROM "{name}" LIMIT 0'  # noqa: S608 -- validated ident
        )
        .fetch_arrow_table()
        .schema
    )
    return [
        SchemaColumn(
            name=schema.field(i).name,
            type=arrow_type_to_python(schema.field(i).type),
        )
        for i in range(len(schema))
    ]


def _validate_against_db(
    data_dir: Path, name: str, kind: str, sql: str
) -> list[SchemaColumn]:
    """Execute ``sql`` on a throwaway connection with base views
    registered. Raises HTTP 400 if it fails. Returns the resulting view
    columns (empty for macros / non-introspectable objects)."""
    conn = duckdb.connect(":memory:")
    try:
        register_all_views(conn, data_dir)
        conn.execute(sql)
        if kind != "view":
            return []
        try:
            return _columns_for(conn, name)
        except duckdb.Error:
            return []
    except duckdb.Error as exc:
        raise HTTPException(
            status_code=400, detail=f"DuckDB error: {exc}"
        ) from exc
    finally:
        conn.close()


@router.get("", response_model=list[UserObjectOut])
def list_user_views(request: Request) -> list[UserObjectOut]:
    data_dir: Path = request.app.state.data_dir
    conn = duckdb.connect(":memory:")
    out: list[UserObjectOut] = []
    try:
        register_all_views(conn, data_dir)
        # register_all_views already replayed the user objects; rerun the
        # store directly so we get per-object ok/error + can introspect
        # columns while the connection is still open.
        for r in store.register_user_objects(conn):
            cols: list[SchemaColumn] = []
            if r["ok"] and r["kind"] == "view":
                try:
                    cols = _columns_for(conn, r["name"])
                except duckdb.Error:
                    cols = []
            out.append(
                UserObjectOut(
                    id=r["id"],
                    name=r["name"],
                    kind=r["kind"],
                    sql=r["sql"],
                    ok=r["ok"],
                    error=r["error"],
                    columns=cols,
                )
            )
    finally:
        conn.close()
    return out


@router.post("", response_model=UserObjectOut)
def create_user_view(body: UserObjectIn, request: Request) -> UserObjectOut:
    try:
        store.validate_ddl(body.name, body.kind, body.sql)
    except store.UserObjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cols = _validate_against_db(
        request.app.state.data_dir, body.name, body.kind, body.sql
    )
    try:
        obj = store.add_object(
            name=body.name, kind=body.kind, sql=body.sql
        )
    except store.UserObjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserObjectOut(**obj, ok=True, columns=cols)


@router.put("/{obj_id}", response_model=UserObjectOut)
def update_user_view(
    obj_id: str, body: UserObjectIn, request: Request
) -> UserObjectOut:
    try:
        store.validate_ddl(body.name, body.kind, body.sql)
    except store.UserObjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cols = _validate_against_db(
        request.app.state.data_dir, body.name, body.kind, body.sql
    )
    try:
        obj = store.update_object(
            obj_id, name=body.name, kind=body.kind, sql=body.sql
        )
    except store.UserObjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserObjectOut(**obj, ok=True, columns=cols)


@router.delete("/{obj_id}")
def delete_user_view(obj_id: str) -> dict[str, bool]:
    store.delete_object(obj_id)
    return {"ok": True}


@router.post("/build-sql", response_model=BuildSqlOut)
def build_sql(spec: BuildSpec) -> BuildSqlOut:
    try:
        return BuildSqlOut(sql=build_view_sql(spec))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview")
def preview(body: UserObjectIn, request: Request) -> dict:
    try:
        store.validate_ddl(body.name, body.kind, body.sql)
    except store.UserObjectError as exc:
        return {"ok": False, "error": str(exc), "columns": []}
    try:
        cols = _validate_against_db(
            request.app.state.data_dir, body.name, body.kind, body.sql
        )
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail), "columns": []}
    return {
        "ok": True,
        "error": None,
        "columns": [c.model_dump() for c in cols],
    }
