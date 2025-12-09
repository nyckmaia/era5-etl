"""Pytest configuration and fixtures."""

from pathlib import Path
from typing import Generator

import pytest

from pyera5.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    ProcessingConfig,
    StorageConfig,
)


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create temporary data directory structure.

    Args:
        tmp_path: Pytest temporary directory fixture

    Returns:
        Path to temporary data directory
    """
    data_dir = tmp_path / "data"
    (data_dir / "netcdf").mkdir(parents=True)
    (data_dir / "processed").mkdir(parents=True)
    (data_dir / "parquet").mkdir(parents=True)
    return data_dir


@pytest.fixture
def download_config(temp_data_dir: Path) -> DownloadConfig:
    """Create download configuration for testing.

    Args:
        temp_data_dir: Temporary data directory

    Returns:
        DownloadConfig instance
    """
    return DownloadConfig(
        output_dir=temp_data_dir / "netcdf",
        dataset="era5-land",
        variables=["2m_temperature"],
        start_date="2020-01-01",
        end_date="2020-01-02",
    )


@pytest.fixture
def processing_config(temp_data_dir: Path) -> ProcessingConfig:
    """Create processing configuration for testing.

    Args:
        temp_data_dir: Temporary data directory

    Returns:
        ProcessingConfig instance
    """
    return ProcessingConfig(
        input_dir=temp_data_dir / "netcdf",
        output_dir=temp_data_dir / "processed",
    )


@pytest.fixture
def storage_config(temp_data_dir: Path) -> StorageConfig:
    """Create storage configuration for testing.

    Args:
        temp_data_dir: Temporary data directory

    Returns:
        StorageConfig instance
    """
    return StorageConfig(
        parquet_dir=temp_data_dir / "parquet",
    )


@pytest.fixture
def database_config(temp_data_dir: Path) -> DatabaseConfig:
    """Create database configuration for testing.

    Args:
        temp_data_dir: Temporary data directory

    Returns:
        DatabaseConfig instance
    """
    return DatabaseConfig(
        db_path=temp_data_dir / "test.duckdb",
    )


@pytest.fixture
def pipeline_config(
    download_config: DownloadConfig,
    processing_config: ProcessingConfig,
    storage_config: StorageConfig,
    database_config: DatabaseConfig,
) -> PipelineConfig:
    """Create complete pipeline configuration for testing.

    Args:
        download_config: Download configuration
        processing_config: Processing configuration
        storage_config: Storage configuration
        database_config: Database configuration

    Returns:
        PipelineConfig instance
    """
    return PipelineConfig(
        download=download_config,
        processing=processing_config,
        storage=storage_config,
        database=database_config,
    )


@pytest.fixture
def sample_netcdf_file(temp_data_dir: Path) -> Generator[Path, None, None]:
    """Create a sample NetCDF file for testing.

    Args:
        temp_data_dir: Temporary data directory

    Yields:
        Path to sample NetCDF file
    """
    import numpy as np
    import xarray as xr

    netcdf_dir = temp_data_dir / "netcdf"
    netcdf_file = netcdf_dir / "test_era5land_202001.nc"

    # Create simple test dataset
    ds = xr.Dataset(
        {
            "t2m": (["time", "latitude", "longitude"], np.random.rand(24, 10, 10) + 273.15),
            "d2m": (["time", "latitude", "longitude"], np.random.rand(24, 10, 10) + 270.15),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-02", dtype="datetime64[h]"),
            "latitude": np.linspace(-10, 0, 10),
            "longitude": np.linspace(-50, -40, 10),
        },
    )

    # Add attributes
    ds["t2m"].attrs = {"units": "K", "long_name": "2m temperature"}
    ds["d2m"].attrs = {"units": "K", "long_name": "2m dewpoint temperature"}

    # Save to NetCDF
    ds.to_netcdf(netcdf_file)

    yield netcdf_file

    # Cleanup
    if netcdf_file.exists():
        netcdf_file.unlink()
