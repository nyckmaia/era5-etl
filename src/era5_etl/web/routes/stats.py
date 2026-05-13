"""Per-dataset storage stats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.manifest import Manifest
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.web.models import StorageStatsOut

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/{dataset}", response_model=StorageStatsOut)
def dataset_stats(dataset: str, request: Request) -> StorageStatsOut:
    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset}")
    data_dir = request.app.state.data_dir
    manager = ParquetManager(data_dir, dataset)
    manifest = Manifest(data_dir, dataset)
    stats = manager.get_storage_stats()
    return StorageStatsOut(
        dataset=dataset,
        parquet_files=stats.total_files,
        total_size_bytes=stats.total_size_bytes,
        partitions=stats.partitions,
        manifest_chunks=len(manifest),
        parquet_dir=str(manager.parquet_dir),
    )
