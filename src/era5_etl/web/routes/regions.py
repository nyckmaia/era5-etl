"""Brazilian region (UF) bounding boxes for the download wizard.

Read-only; sourced from the bundled IBGE ``uf.csv``. Polygon-clip availability
comes from the bundled ``grid_membership.parquet`` (per dataset).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from era5_etl.datasets import DatasetRegistry
from era5_etl.utils.ibge_regions import RegionType, load_region_data
from era5_etl.web.models import UfBboxOut

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("/uf", response_model=list[UfBboxOut])
def list_uf() -> list[UfBboxOut]:
    df = load_region_data(RegionType.UF)
    rows = df.sort("uf").to_dicts()
    return [
        UfBboxOut(
            uf=str(r["uf"]),
            north=float(r["north"]),
            west=float(r["west"]),
            south=float(r["south"]),
            east=float(r["east"]),
        )
        for r in rows
    ]


@router.get("/clip-available")
def clip_available(dataset: str) -> dict[str, list[str]]:
    """Regions with pre-computed polygon membership for ``dataset``.

    Returns ``{"regions": ["AC", ..., "BR"]}``. Only gridded datasets have
    a membership table; passing a station source (e.g. INMET) returns an
    empty list so the UI can hide the option.
    """
    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")
    if not DatasetRegistry.get(dataset).is_gridded:
        return {"regions": []}
    from era5_etl.regions.membership import available_regions

    return {"regions": available_regions(dataset)}


@router.get("/uf-cell-counts")
def uf_cell_counts(dataset: str) -> dict[str, int]:
    """Grid-cell count per region for ``dataset``.

    Returns ``{"SP": 460, "RJ": 91, ...}``. Regions with zero cells are
    still present in the response (value ``0``) so the UI can flag them.
    Stations sources (e.g. INMET) return an empty dict — clipping by UF
    polygon does not apply to them.
    """
    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")
    if not DatasetRegistry.get(dataset).is_gridded:
        return {}
    from era5_etl.regions.membership import region_counts

    counts = region_counts(dataset)
    df_uf = load_region_data(RegionType.UF)
    all_ufs = [str(r["uf"]) for r in df_uf.to_dicts()]
    return {uf: counts.get(uf, 0) for uf in all_ufs}
