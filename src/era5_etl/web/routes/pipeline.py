"""Pipeline endpoints: size estimate, start a run, stream progress."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from era5_etl.config import PipelineConfig
from era5_etl.datasets import DatasetRegistry
from era5_etl.download.request_planner import plan_requests
from era5_etl.download.size_estimator import estimate_request_size
from era5_etl.web.models import (
    DiffPreviewIn,
    DiffPreviewOut,
    DiffPreviewSampleRow,
    EstimateChunkOut,
    EstimateIn,
    EstimateOut,
    PipelineRunIn,
    PipelineRunOut,
)
from era5_etl.web.runtime import RUNTIME, PipelineRun

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/estimate", response_model=EstimateOut)
def estimate(body: EstimateIn) -> EstimateOut:
    """Plan requests and report the total estimated size without contacting CDS."""
    if body.dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {body.dataset}")

    # Build a temporary DownloadConfig just for planning.
    from era5_etl.config import DownloadConfig

    cfg = DownloadConfig(
        output_dir=Path("./_unused"),
        dataset=body.dataset,
        variables=body.variables,
        start_date=body.start_date,
        end_date=body.end_date,
        area=body.area,
        hours=body.hours,
        max_request_bytes=body.max_request_bytes,
    )

    chunks = plan_requests(cfg)
    out_chunks: list[EstimateChunkOut] = []
    total_bytes = 0
    for c in chunks:
        est = estimate_request_size(
            num_variables=len(c.variables),
            num_hours=len(c.hours),
            num_days=len(c.days),
            area=list(c.area),
            dataset=c.dataset,
            max_bytes=body.max_request_bytes,
        )
        total_bytes += est.estimated_bytes
        out_chunks.append(
            EstimateChunkOut(
                chunk_id=c.chunk_id,
                year=c.year,
                month=c.month,
                days=list(c.days),
                variables=list(c.variables),
                area=list(c.area),
                estimated_bytes=est.estimated_bytes,
                estimated_mb=est.estimated_mb,
            )
        )

    return EstimateOut(
        dataset=body.dataset,
        total_chunks=len(chunks),
        total_estimated_bytes=total_bytes,
        total_estimated_mb=total_bytes / (1024 * 1024),
        chunks=out_chunks,
    )


@router.post("/run", response_model=PipelineRunOut)
def start_run(body: PipelineRunIn, request: Request) -> PipelineRunOut:
    if body.dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {body.dataset}")

    data_dir: Path = request.app.state.data_dir
    config = PipelineConfig.create(
        base_dir=data_dir,
        dataset=body.dataset,
        start_date=body.start_date,
        end_date=body.end_date,
        variables=body.variables,
        area=body.area,
        hours=body.hours,
    )

    run_id = uuid.uuid4().hex
    run = PipelineRun(run_id=run_id, dataset=body.dataset)
    RUNTIME.register(run_id, run)

    def _execute() -> None:
        run.mark_started()
        try:
            from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

            pipe = ERA5Pipeline(
                config,
                progress_callback=run.emit_chunk_event,
                apply_diff=body.apply_diff,
            )
            pipe.run()
            run.mark_completed()
        except Exception as exc:  # pragma: no cover - depends on CDS access
            run.mark_failed(str(exc))

    threading.Thread(target=_execute, daemon=True).start()
    return PipelineRunOut(run_id=run_id, dataset=body.dataset, status="pending")


@router.get("/runs/{run_id}/progress")
def stream_progress(run_id: str):
    run = RUNTIME.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run id: {run_id}")
    return EventSourceResponse(run.stream())


@router.post("/diff-preview", response_model=DiffPreviewOut)
def diff_preview(body: DiffPreviewIn, request: Request) -> DiffPreviewOut:
    """Compute how many of the requested cells are still missing locally.

    Wraps :func:`CoverageIndex.diff` with the same per-cell expansion
    that ``plan_with_diff`` uses, so the returned counts match what an
    actual download with ``apply_diff=True`` would issue.
    """
    if body.dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {body.dataset}")

    from era5_etl.config import DownloadConfig
    from era5_etl.datasets import DatasetRegistry as _DR
    from era5_etl.download.grid import snap_area_to_grid
    from era5_etl.download.request_planner import build_request_cells
    from era5_etl.storage.coverage import COVERAGE_DB_FILENAME, CoverageIndex
    from era5_etl.storage.paths import resolve_dataset_dir

    # Normalise hours from int -> "HH:00" (matches DownloadConfig contract).
    hours_str = [f"{int(h):02d}:00" for h in body.hours]

    cfg = DownloadConfig(
        output_dir=Path("./_unused"),
        dataset=body.dataset,
        variables=body.variables,
        start_date=body.date_from,
        end_date=body.date_to,
        area=body.area,
        hours=hours_str,
    )

    resolution = _DR.get(cfg.dataset).GRID_RESOLUTION_DEG
    snapped = snap_area_to_grid(list(cfg.area), resolution)
    cells_df = build_request_cells(cfg, resolution, snapped)
    requested = cells_df.height

    base_dir: Path = request.app.state.data_dir
    db_path = resolve_dataset_dir(base_dir, cfg.dataset) / COVERAGE_DB_FILENAME

    if requested == 0:
        return DiffPreviewOut(
            requested_cells=0,
            missing_cells=0,
            savings_pct=0.0,
            sample_missing=[],
        )

    if not db_path.exists():
        # No coverage yet -> nothing covered -> all requested cells are "missing".
        sample = []
        for row in cells_df.head(100).iter_rows(named=True):
            d = row["date"]
            d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
            sample.append(
                DiffPreviewSampleRow(
                    lat=float(row["latitude"]),
                    lon=float(row["longitude"]),
                    date=d_str,
                    variable=str(row["variable"]),
                    missing_mask=int(row["requested_mask"]),
                )
            )
        return DiffPreviewOut(
            requested_cells=requested,
            missing_cells=requested,
            savings_pct=0.0,
            sample_missing=sample,
        )

    with CoverageIndex(cfg.dataset, base_dir) as cov:
        diff_df = cov.diff(cells_df)

    missing = diff_df.height
    savings = round((1 - missing / requested) * 100, 2) if requested > 0 else 0.0
    sample_rows: list[DiffPreviewSampleRow] = []
    for row in diff_df.head(100).iter_rows(named=True):
        d = row["date"]
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        sample_rows.append(
            DiffPreviewSampleRow(
                lat=float(row["latitude"]),
                lon=float(row["longitude"]),
                date=d_str,
                variable=str(row["variable"]),
                missing_mask=int(row["missing_mask"]),
            )
        )

    return DiffPreviewOut(
        requested_cells=requested,
        missing_cells=missing,
        savings_pct=savings,
        sample_missing=sample_rows,
    )


@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs() -> list[PipelineRunOut]:
    out: list[PipelineRunOut] = []
    for rid in RUNTIME.ids():
        r = RUNTIME.get(rid)
        if r is not None:
            out.append(PipelineRunOut(run_id=r.run_id, dataset=r.dataset, status=r.status))
    return out
