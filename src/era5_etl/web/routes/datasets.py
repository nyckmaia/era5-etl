"""List datasets and their available variables.

Each ERA5-family dataset is a registered :class:`DatasetConfig`; here we
expose them as JSON for the web UI's wizard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from era5_etl.datasets import DatasetRegistry
from era5_etl.web.models import DatasetOut, DatasetVariableOut

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _to_out(name: str) -> DatasetOut:
    cfg = DatasetRegistry.get(name)
    return DatasetOut(
        name=cfg.NAME,
        cds_dataset_id=cfg.CDS_DATASET_ID,
        grid_resolution_deg=cfg.GRID_RESOLUTION_DEG,
        default_variables=list(cfg.default_variables),
        variables=[
            DatasetVariableOut(
                api_name=v.api_name,
                short_name=v.short_name,
                friendly_name=v.friendly_name,
                full_name=v.full_name,
                description=v.description,
                unit=v.unit,
            )
            for v in cfg.variables
        ],
    )


@router.get("", response_model=list[DatasetOut])
def list_datasets() -> list[DatasetOut]:
    return [_to_out(name) for name in DatasetRegistry.names()]


@router.get("/{name}", response_model=DatasetOut)
def get_dataset(name: str) -> DatasetOut:
    if name not in DatasetRegistry.names():
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {name}")
    return _to_out(name)
