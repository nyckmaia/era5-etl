"""List datasets and their available variables.

Each ERA5-family dataset is a registered :class:`DatasetConfig`; here we
expose them as JSON for the web UI's wizard.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.paths import resolve_dataset_dir, resolve_netcdf_temp_dir
from era5_etl.web.models import DatasetDeleteOut, DatasetOut, DatasetVariableOut

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _dir_size_bytes(path: Path) -> int:
    """Sum the size of every file under ``path`` (0 if it doesn't exist)."""
    if not path.exists():
        return 0
    return sum(
        f.stat().st_size for f in path.rglob("*") if f.is_file()
    )


def _to_out(name: str) -> DatasetOut:
    cfg = DatasetRegistry.get(name)
    return DatasetOut(
        name=cfg.NAME,
        cds_dataset_id=cfg.CDS_DATASET_ID,
        grid_resolution_deg=cfg.GRID_RESOLUTION_DEG,
        source_kind=getattr(cfg, "SOURCE_KIND", "cds_grid"),
        is_gridded=cfg.is_gridded,
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


@router.delete("/{name}/data", response_model=DatasetDeleteOut)
def delete_dataset_data(name: str, request: Request) -> DatasetDeleteOut:
    """Permanently wipe ALL on-disk data for one dataset.

    Removes the dataset's storage folder (parquet partitions, manifest,
    the per-dataset DuckDB view file, and the ``_coverage.duckdb`` index)
    *and* its temporary NetCDF directory. This is irreversible — the data
    must be re-downloaded from the CDS afterwards. The dataset itself
    stays registered; only its files are deleted.
    """
    if name not in DatasetRegistry.names():
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {name}")

    data_dir = request.app.state.data_dir
    dataset_dir = resolve_dataset_dir(data_dir, name)
    tmp_dir = resolve_netcdf_temp_dir(data_dir, name)

    freed = _dir_size_bytes(dataset_dir) + _dir_size_bytes(tmp_dir)
    deleted = False
    for target in (dataset_dir, tmp_dir):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            deleted = True

    return DatasetDeleteOut(dataset=name, deleted=deleted, freed_bytes=freed)
