"""Brazilian region (UF) bounding boxes for the download wizard.

Read-only; sourced from the bundled IBGE ``uf.csv``.
"""

from __future__ import annotations

from fastapi import APIRouter

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
