"""INMET-specific endpoints for the dedicated download flow.

The ERA5 wizard's ``/estimate`` and ``/diff-preview`` don't apply to INMET
(no grid, no per-variable/area selection -- one ZIP per year). The SPA
branches to a minimal INMET flow that needs two things this router
provides:

* ``GET /api/inmet/years``        -- years offered on the INMET portal, so
  the user can tick exactly which yearly ZIPs to fetch.
* ``GET /api/inmet/prerequisite`` -- whether ERA5 **and** ERA5-LAND already
  have minimal data on disk (INMET ingestion is gated on this; the UI
  shows status + a shortcut to download the missing grids).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.download.inmet_portal import (
    _REQUIRED_GRIDS,
    _grid_has_parquet,
    scrape_available_years,
)
from era5_etl.exceptions import DownloadError
from era5_etl.web.models import InmetPrerequisiteOut, InmetYearsOut

router = APIRouter(prefix="/api/inmet", tags=["inmet"])


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


@router.get("/prerequisite", response_model=InmetPrerequisiteOut)
def prerequisite(request: Request) -> InmetPrerequisiteOut:
    """Is the ERA5/ERA5-LAND minimum present so INMET may be downloaded?"""
    base_dir: Path = request.app.state.data_dir
    present = {d: _grid_has_parquet(base_dir, d) for d in _REQUIRED_GRIDS}
    missing = [d for d, ok in present.items() if not ok]
    return InmetPrerequisiteOut(
        era5=present.get("era5", False),
        era5_land=present.get("era5-land", False),
        ok=not missing,
        missing=missing,
    )
