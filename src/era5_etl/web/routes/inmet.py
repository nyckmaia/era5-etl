"""INMET-specific endpoints for the dedicated download flow.

The ERA5 wizard's ``/estimate`` and ``/diff-preview`` don't apply to INMET
(no grid, no per-variable/area selection -- one ZIP per year). The SPA
branches to a minimal INMET flow that needs:

- ``/years``      — live list of years offered on the INMET portal
- ``/year-status``— completeness summary of each year already in the local DB
- ``/update-years`` — re-download a year (delete parquets + forget manifest
                     + rerun pipeline with ``override=True``)

The ERA5/ERA5-LAND prerequisite is no longer surfaced to the UI -- the
``/api/pipeline/run`` orchestrator now auto-bootstraps any missing grid as
sub-phases of the INMET run (see ``web/prereq.py``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.download.inmet_portal import manifest_chunk_id, scrape_available_years
from era5_etl.exceptions import DownloadError
from era5_etl.storage.manifest import Manifest
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import StationIndex
from era5_etl.web.models import (
    InmetUpdateYearsIn,
    InmetYearStatusItem,
    InmetYearStatusOut,
    InmetYearsOut,
    PipelineRunIn,
    PipelineRunOut,
)
from era5_etl.web.routes.pipeline import start_run

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inmet", tags=["inmet"])

_INMET_DATASET = "inmet"


@router.get("/years", response_model=InmetYearsOut)
def available_years() -> InmetYearsOut:
    """Years available on the INMET historical-data portal (live scrape)."""
    try:
        years = scrape_available_years()
    except DownloadError as exc:
        # Portal unreachable / changed layout: 502 so the SPA can fall
        # back to a manual year range with a clear message.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return InmetYearsOut(years=years)


def _classify_year(
    year: int,
    n_stations: int,
    n_complete: int,
    current_year: int,
) -> str:
    """Map (year, completeness counts) into the four UI states.

    - ``current``  : it's the calendar year — by construction never complete.
    - ``complete`` : every station reached Dec 31 of ``year``.
    - ``stale``    : no station reached Dec 31 — strong update signal.
    - ``partial``  : some did, some didn't (deactivated station or pending
                     update — UI asks the user).
    """
    if year == current_year:
        return "current"
    if n_stations == 0:
        return "stale"
    if n_complete == n_stations:
        return "complete"
    if n_complete == 0:
        return "stale"
    return "partial"


@router.get("/year-status", response_model=InmetYearStatusOut)
def year_status(request: Request) -> InmetYearStatusOut:
    """Per-year completeness of the local INMET database.

    Empty index (nothing downloaded yet) is a valid state: ``items=[]``.
    """
    base_dir: Path = request.app.state.data_dir
    current_year = datetime.now(UTC).date().year

    parquet_dir = resolve_dataset_dir(base_dir, _INMET_DATASET)
    station_db = parquet_dir / "_stations.duckdb"
    if not station_db.exists():
        return InmetYearStatusOut(items=[], current_year=current_year)

    with StationIndex(_INMET_DATASET, base_dir) as idx:
        df = idx.query_year_status()

    manifest = Manifest(base_dir, _INMET_DATASET)

    items: list[InmetYearStatusItem] = []
    for row in df.iter_rows(named=True):
        year = int(row["year"])
        n_stations = int(row["n_stations"] or 0)
        n_complete = int(row["n_stations_complete"] or 0)
        chunk = manifest.get(manifest_chunk_id(year))
        downloaded_at: datetime | None = None
        if chunk and chunk.completed_at:
            try:
                downloaded_at = datetime.fromisoformat(
                    chunk.completed_at.replace("Z", "+00:00")
                )
            except ValueError:
                downloaded_at = None
        items.append(
            InmetYearStatusItem(
                year=year,
                status=_classify_year(year, n_stations, n_complete, current_year),
                n_stations=n_stations,
                n_stations_complete=n_complete,
                min_date_max=row["min_date_max"],
                max_date_max=row["max_date_max"],
                downloaded_at=downloaded_at,
            )
        )

    return InmetYearStatusOut(items=items, current_year=current_year)


def _purge_year_artifacts(base_dir: Path, year: int) -> int:
    """Delete all INMET parquets for ``year`` and forget its manifest entry.

    Returns the number of parquet files removed (informational; the caller
    logs but does not depend on it being non-zero — a year that was never
    downloaded is a legitimate input).
    """
    parquet_dir = resolve_dataset_dir(base_dir, _INMET_DATASET)
    removed = 0
    for station_dir in parquet_dir.glob("station=*"):
        for parquet in station_dir.glob(f"*_{year}.parquet"):
            try:
                parquet.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Could not delete %s: %s", parquet, exc)
    return removed


@router.post("/update-years", response_model=PipelineRunOut)
def update_years(body: InmetUpdateYearsIn, request: Request) -> PipelineRunOut:
    """Force re-download of one or more INMET years.

    Per year: delete the per-station parquets for that year, then forget the
    ``inmet:<year>`` manifest entry. Persist the manifest, then dispatch a
    regular pipeline run with ``override=True`` so the downloader fetches
    the ZIP again even if a stale copy is on disk.
    """
    base_dir: Path = request.app.state.data_dir
    years = sorted(set(int(y) for y in body.years))

    manifest = Manifest(base_dir, _INMET_DATASET)
    total_removed = 0
    for year in years:
        total_removed += _purge_year_artifacts(base_dir, year)
        manifest.forget(manifest_chunk_id(year))
    manifest.save()
    logger.info(
        "INMET update: purged %d parquet(s) across years %s; manifest forgotten.",
        total_removed,
        years,
    )

    run_body = PipelineRunIn(
        dataset=_INMET_DATASET,
        variables=[],
        start_date=f"{min(years)}-01-01",
        end_date=f"{max(years)}-12-31",
        area=[0, 0, 0, 0],
        hours=[],
        apply_diff=False,
        years=years,
        override=True,
    )
    return start_run(run_body, request)
