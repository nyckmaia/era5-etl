"""Version endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from era5_etl.__version__ import __version__
from era5_etl.web.models import VersionOut

router = APIRouter(prefix="/api", tags=["version"])


@router.get("/version", response_model=VersionOut)
def get_version() -> VersionOut:
    return VersionOut(version=__version__)
