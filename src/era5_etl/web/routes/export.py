"""Export query results to CSV / Parquet."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.web.models import QueryIn
from era5_etl.web.routes.query import _validate_sql

router = APIRouter(prefix="/api/export", tags=["export"])


def _run(sql: str, dataset: str, data_dir: Path):
    import duckdb

    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")
    _validate_sql(sql)
    manager = ParquetManager(data_dir, dataset)
    if not manager.exists():
        raise HTTPException(status_code=404, detail="No Parquet data for this dataset yet.")
    view_name = dataset.replace("-", "_") + "_view"
    conn = duckdb.connect(":memory:")
    try:
        manager.create_duckdb_view(conn, view_name)
        return conn.execute(sql).fetch_arrow_table()
    finally:
        conn.close()


@router.post("/csv")
def export_csv(body: QueryIn, request: Request):
    table = _run(body.sql, body.dataset, request.app.state.data_dir)
    df = table.to_pandas()
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{body.dataset}-export.csv"'}
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers=headers)


@router.post("/parquet")
def export_parquet(body: QueryIn, request: Request):
    import pyarrow.parquet as pq

    table = _run(body.sql, body.dataset, request.app.state.data_dir)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{body.dataset}-export.parquet"'}
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="application/octet-stream", headers=headers
    )
