"""Read-only SQL endpoint with allowlist validation."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.web.models import QueryIn, QueryOut

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


@router.post("", response_model=QueryOut)
def run_query(body: QueryIn, request: Request) -> QueryOut:
    import duckdb

    if body.dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {body.dataset}")
    _validate_sql(body.sql)

    data_dir: Path = request.app.state.data_dir
    manager = ParquetManager(data_dir, body.dataset)
    if not manager.exists():
        raise HTTPException(status_code=404, detail="No Parquet data for this dataset yet.")

    view_name = body.dataset.replace("-", "_") + "_view"
    conn = duckdb.connect(":memory:")
    try:
        manager.create_duckdb_view(conn, view_name)
        result = conn.execute(body.sql).fetch_arrow_table()
        df = result.to_pandas()
    except duckdb.Error as exc:
        raise HTTPException(status_code=400, detail=f"DuckDB error: {exc}") from exc
    finally:
        conn.close()

    truncated = False
    if len(df) > body.limit:
        df = df.head(body.limit)
        truncated = True

    return QueryOut(
        columns=list(df.columns),
        rows=df.astype(object).where(df.notnull(), None).values.tolist(),
        row_count=int(len(df)),
        truncated=truncated,
    )
