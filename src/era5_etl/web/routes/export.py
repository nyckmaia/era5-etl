"""Export query results to CSV / Parquet."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from era5_etl.web.models import QueryIn
from era5_etl.web.query_engine import query_conn
from era5_etl.web.routes.query import _validate_sql

router = APIRouter(prefix="/api/export", tags=["export"])


def _run(sql: str, data_dir: Path):
    _validate_sql(sql)
    with query_conn(data_dir) as (conn, registered):
        if not registered:
            raise HTTPException(
                status_code=404, detail="No Parquet data for any dataset yet."
            )
        return conn.execute(sql).fetch_arrow_table()


@router.post("/csv")
def export_csv(body: QueryIn, request: Request):
    table = _run(body.sql, request.app.state.data_dir)
    df = table.to_pandas()
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    name = body.dataset or "query"
    headers = {"Content-Disposition": f'attachment; filename="{name}-export.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


@router.post("/parquet")
def export_parquet(body: QueryIn, request: Request):
    import pyarrow.parquet as pq

    table = _run(body.sql, request.app.state.data_dir)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    buf.seek(0)
    name = body.dataset or "query"
    headers = {"Content-Disposition": f'attachment; filename="{name}-export.parquet"'}
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="application/octet-stream", headers=headers
    )
