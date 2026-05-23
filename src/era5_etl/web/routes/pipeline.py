"""Pipeline endpoints: size estimate, start a run, stream progress."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
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

    # Non-grid sources (INMET) have no area×days×vars chunking: acquisition
    # is 1 ZIP per year (all stations). The CDS size estimate doesn't apply
    # and `plan_requests` -> `snap_area_to_grid(res=0.0)` would 500.
    # Short-circuit with an informative, non-fatal payload (years count).
    if not DatasetRegistry.get(body.dataset).is_gridded:
        from era5_etl.download.inmet_portal import years_from_dates

        years = years_from_dates(body.start_date, body.end_date)
        return EstimateOut(
            dataset=body.dataset,
            total_chunks=len(years),
            total_estimated_bytes=0,
            total_estimated_mb=0.0,
            chunks=[],
            estimate_skipped=True,
            skip_reason=(
                f"{body.dataset.upper()} é uma fonte de estações: o download "
                f"é 1 ZIP por ano (todas as estações), {len(years)} ano(s) "
                f"({years[0]}–{years[-1]}). O tamanho só é conhecido ao "
                "baixar; não há estimativa por área/variável."
            ),
        )

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
        max_request_fields=body.max_request_fields,
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
            max_fields=body.max_request_fields,
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
                fields_count=est.fields_count,
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
    try:
        phases = _build_phases(body, data_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = uuid.uuid4().hex
    run = PipelineRun(run_id=run_id, dataset=body.dataset)
    RUNTIME.register(run_id, run)

    def _execute() -> None:
        run.mark_started()
        from era5_etl.pipeline.era5_pipeline import (
            BootstrapGridPipeline,
            ERA5Pipeline,
        )

        total = len(phases)
        for idx, phase in enumerate(phases, start=1):
            run.set_phase(phase.name, idx, total)
            try:
                if phase.is_bootstrap:
                    # Bootstrap phases only need download + grid extraction
                    # (no convert/index/view). The resulting lat/lon-only
                    # parquet lives at `_grids/<dataset>_grid.parquet`;
                    # the per-dataset folder stays empty.
                    boot = BootstrapGridPipeline(
                        phase.config,
                        progress_callback=run.emit_chunk_event,
                    )
                    boot.run()
                else:
                    pipe = ERA5Pipeline(
                        phase.config,
                        progress_callback=run.emit_chunk_event,
                        apply_diff=phase.apply_diff,
                    )
                    pipe.run()
            except Exception as exc:  # pragma: no cover - depends on CDS access
                # Translate the most common pre-flight failure (no CDS
                # credentials) into a UX message that points the user to
                # Settings; any other error propagates verbatim.
                msg = _format_phase_error(phase.name, exc)
                run.mark_failed(msg)
                return
        run.mark_completed()

    threading.Thread(target=_execute, daemon=True).start()
    return PipelineRunOut(run_id=run_id, dataset=body.dataset, status="pending")


@dataclass
class _Phase:
    """One sub-pipeline scheduled by the orchestrator."""

    name: str  # stable token: "bootstrap-era5", "bootstrap-era5-land", "inmet", or "<dataset>"
    config: PipelineConfig
    apply_diff: bool
    is_bootstrap: bool = False  # use BootstrapGridPipeline instead of ERA5Pipeline


def _build_phases(body: PipelineRunIn, data_dir: Path) -> list[_Phase]:
    """Plan the ordered sub-pipelines for one /run request.

    For INMET runs without ERA5/ERA5-LAND data on disk, prepend tiny
    bootstrap sub-pipelines so the comparison view can resolve joins. For
    every other dataset (and for INMET when prerequisites are already on
    disk), this returns a single-phase plan that matches the legacy path.
    """
    main_config = PipelineConfig.create(
        base_dir=data_dir,
        dataset=body.dataset,
        start_date=body.start_date,
        end_date=body.end_date,
        variables=body.variables,
        area=body.area,
        hours=body.hours,
        years=body.years,
        clip_regions=body.clip_regions,
        override=body.override,
    )
    main_phase = _Phase(
        name=body.dataset if body.dataset != "inmet" else "inmet",
        config=main_config,
        apply_diff=body.apply_diff,
    )
    if body.dataset != "inmet":
        return [main_phase]

    # INMET: prepend bootstrap sub-pipelines for any missing grid.
    from era5_etl.web.prereq import (
        BOOTSTRAP_AREA,
        BOOTSTRAP_CLIP_REGIONS,
        BOOTSTRAP_DATE,
        BOOTSTRAP_HOURS,
        BOOTSTRAP_VARIABLES,
        missing_grids,
    )

    phases: list[_Phase] = []
    for grid in missing_grids(data_dir):
        boot_config = PipelineConfig.create(
            base_dir=data_dir,
            dataset=grid,
            start_date=BOOTSTRAP_DATE,
            end_date=BOOTSTRAP_DATE,
            variables=list(BOOTSTRAP_VARIABLES),
            area=list(BOOTSTRAP_AREA),
            hours=list(BOOTSTRAP_HOURS),
            clip_regions=list(BOOTSTRAP_CLIP_REGIONS),
        )
        phases.append(
            _Phase(
                name=f"bootstrap-{grid}",
                config=boot_config,
                apply_diff=False,
                is_bootstrap=True,
            )
        )
    phases.append(main_phase)
    return phases


def _format_phase_error(phase: str, exc: BaseException) -> str:
    """Surface a friendly error for the run, with a hint if it's CDS-auth."""
    msg = str(exc).strip() or exc.__class__.__name__
    lower = msg.lower()
    if phase.startswith("bootstrap-") and (
        "credential" in lower or "401" in lower or "cdsapirc" in lower
    ):
        return (
            f"Falha em {phase}: {msg}. "
            "Configure as credenciais do CDS em Configurações → Credenciais."
        )
    return f"Falha em {phase}: {msg}"


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

    # Smart Diff is a CDS grid concept (per-cell coverage + area snapping).
    # Station sources (INMET, GRID_RESOLUTION_DEG == 0) have no grid to
    # snap to -- calling snap_area_to_grid(res=0.0) would 500. Short-circuit
    # with a clear, non-fatal "diff skipped" payload the wizard already
    # knows how to render; INMET reuse is per-year via the manifest.
    if not DatasetRegistry.get(body.dataset).is_gridded:
        return DiffPreviewOut(
            requested_cells=0,
            missing_cells=0,
            savings_pct=0.0,
            sample_missing=[],
            diff_skipped=True,
            skip_reason=(
                f"{body.dataset.upper()} é uma fonte de estações (não-grade): "
                "o Smart Diff célula-a-célula não se aplica. O download é "
                "feito por ano, reaproveitando o que já está no manifesto."
            ),
        )

    from era5_etl.config import DownloadConfig
    from era5_etl.datasets import DatasetRegistry as Registry
    from era5_etl.download.grid import snap_area_to_grid
    from era5_etl.download.request_planner import (
        DIFF_MAX_CELLS,
        build_request_cells,
        plan_requests,
        request_cell_count,
    )
    from era5_etl.download.size_estimator import (
        PARQUET_DISK_RATIO,
        estimate_request_size,
    )
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

    resolution = Registry.get(cfg.dataset).GRID_RESOLUTION_DEG
    snapped = snap_area_to_grid(list(cfg.area), resolution)

    # Guard: a per-cell diff over a huge request (state × decades) would
    # allocate many GB and abort the backend process. Bound it
    # arithmetically BEFORE materialising anything; when too large, skip
    # the diff and return a memory-safe chunk plan + arithmetic-only size
    # estimate so the UI can let the user proceed with sequential chunks
    # or narrow the selection.
    requested = request_cell_count(cfg, resolution, snapped)
    if requested > DIFF_MAX_CELLS:
        chunks = plan_requests(cfg)
        download_bytes = sum(
            estimate_request_size(
                num_variables=len(c.variables),
                num_hours=len(c.hours),
                num_days=len(c.days),
                area=list(c.area),
                dataset=c.dataset,
            ).estimated_bytes
            for c in chunks
        )
        disk_bytes = int(download_bytes * PARQUET_DISK_RATIO)
        return DiffPreviewOut(
            requested_cells=requested,
            missing_cells=requested,  # diff not applied → assume all to fetch
            savings_pct=0.0,
            sample_missing=[],
            diff_skipped=True,
            skip_reason=(
                f"Requisição expande para {requested:,} células "
                f"(> {DIFF_MAX_CELLS:,}); o diff célula-a-célula não cabe "
                "em memória. O download será feito em chunks sequenciais."
            ),
            estimated_download_bytes=download_bytes,
            estimated_disk_bytes=disk_bytes,
            estimated_chunks=len(chunks),
        )

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

    # Full-request size (arithmetic only, same machinery as the chunked
    # fallback and /estimate). The per-cell *missing* bytes are estimated
    # by scaling this total by the missing fraction — bytes ∝ cells, so
    # this is a good order-of-magnitude figure for "what Smart Diff will
    # actually fetch".
    total_download_bytes = sum(
        estimate_request_size(
            num_variables=len(c.variables),
            num_hours=len(c.hours),
            num_days=len(c.days),
            area=list(c.area),
            dataset=c.dataset,
        ).estimated_bytes
        for c in plan_requests(cfg)
    )
    total_disk_bytes = int(total_download_bytes * PARQUET_DISK_RATIO)

    def _missing_sizes(missing: int) -> tuple[int, int]:
        frac = missing / requested if requested > 0 else 0.0
        return (
            int(total_download_bytes * frac),
            int(total_disk_bytes * frac),
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
        miss_dl, miss_disk = _missing_sizes(requested)
        return DiffPreviewOut(
            requested_cells=requested,
            missing_cells=requested,
            savings_pct=0.0,
            sample_missing=sample,
            estimated_download_bytes=total_download_bytes,
            estimated_disk_bytes=total_disk_bytes,
            missing_download_bytes=miss_dl,
            missing_disk_bytes=miss_disk,
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

    miss_dl, miss_disk = _missing_sizes(missing)
    return DiffPreviewOut(
        requested_cells=requested,
        missing_cells=missing,
        savings_pct=savings,
        sample_missing=sample_rows,
        estimated_download_bytes=total_download_bytes,
        estimated_disk_bytes=total_disk_bytes,
        missing_download_bytes=miss_dl,
        missing_disk_bytes=miss_disk,
    )


@router.get("/runs", response_model=list[PipelineRunOut])
def list_runs() -> list[PipelineRunOut]:
    out: list[PipelineRunOut] = []
    for rid in RUNTIME.ids():
        r = RUNTIME.get(rid)
        if r is not None:
            out.append(PipelineRunOut(run_id=r.run_id, dataset=r.dataset, status=r.status))
    return out
