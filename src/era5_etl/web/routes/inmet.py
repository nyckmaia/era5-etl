"""INMET-specific endpoints for the dedicated download flow.

The ERA5 wizard's ``/estimate`` and ``/diff-preview`` don't apply to INMET
(no grid, no per-variable/area selection -- one ZIP per year). The SPA
branches to a minimal INMET flow that needs one thing this router
provides: the live list of years offered on the INMET portal.

The ERA5/ERA5-LAND prerequisite is no longer surfaced to the UI -- the
``/api/pipeline/run`` orchestrator now auto-bootstraps any missing grid as
sub-phases of the INMET run (see ``web/prereq.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from era5_etl.download.inmet_portal import scrape_available_years
from era5_etl.exceptions import DownloadError
from era5_etl.web.models import InmetYearsOut

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
