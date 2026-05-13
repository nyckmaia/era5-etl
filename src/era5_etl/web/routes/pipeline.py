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

            pipe = ERA5Pipeline(config, progress_callback=run.emit_chunk_event)
            ctx = pipe.run()
            # Hook into context's progress callback if available.
            ctx.set_progress_callback(
                lambda progress, message: run.emit(
                    stage="overall",
                    stage_progress=progress,
                    message=message,
                    global_progress=progress,
                )
            )
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


@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs() -> list[PipelineRunOut]:
    out: list[PipelineRunOut] = []
    for rid in RUNTIME.ids():
        r = RUNTIME.get(rid)
        if r is not None:
            out.append(PipelineRunOut(run_id=r.run_id, dataset=r.dataset, status=r.status))
    return out
