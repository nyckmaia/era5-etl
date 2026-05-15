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
    (``era5``, ``era5_land``) or JOIN across them (M02a). Returns the
    list of view names registered (empty if no dataset has data yet).
    """
    registered: list[str] = []
    for name in DatasetRegistry.names():
        mgr = ParquetManager(data_dir, name)
        if not mgr.exists():
            continue
        mgr.create_duckdb_view(conn, view_name_for(name))
        registered.append(view_name_for(name))
    return registered


@router.post("", response_model=QueryOut)
def run_query(body: QueryIn, request: Request) -> QueryOut:
    import duckdb

    _validate_sql(body.sql)

    data_dir: Path = request.app.state.data_dir
    conn = duckdb.connect(":memory:")
    try:
        registered = register_all_views(conn, data_dir)
        if not registered:
            raise HTTPException(
                status_code=404,
                detail="No Parquet data for any dataset yet.",
            )
        result = conn.execute(body.sql).fetch_arrow_table()
        arrow_schema = result.schema
        df = result.to_pandas()
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=f"DuckDB error: {exc}") from exc
    finally:
        conn.close()

    truncated = False
    if len(df) > body.limit:
        df = df.head(body.limit)
        truncated = True

    from era5_etl.web._types import schema_python_types

    return QueryOut(
        columns=list(df.columns),
        column_types=schema_python_types(arrow_schema),
        rows=df.astype(object).where(df.notnull(), None).values.tolist(),
        row_count=int(len(df)),
        truncated=truncated,
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

    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")

    view = view_name_for(dataset)
    data_dir: Path = request.app.state.data_dir
    manager = ParquetManager(data_dir, dataset)
    if not manager.exists():
        return QuerySchemaOut(view=view, columns=[])

    from era5_etl.web._types import arrow_type_to_python

    conn = duckdb.connect(":memory:")
    try:
        manager.create_duckdb_view(conn, view)
        schema = conn.execute(f'SELECT * FROM "{view}" LIMIT 0').fetch_arrow_table().schema  # noqa: S608 -- view is a sanitized identifier
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=f"DuckDB error: {exc}") from exc
    finally:
        conn.close()

    cols = [
        SchemaColumn(name=schema.field(i).name, type=arrow_type_to_python(schema.field(i).type))
        for i in range(len(schema))
    ]
    return QuerySchemaOut(view=view, columns=cols)
