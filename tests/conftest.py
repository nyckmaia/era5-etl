"""Pytest configuration and fixtures."""

from collections.abc import Generator
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from era5_etl.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    StorageConfig,
    TransformConfig,
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
    data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def download_config(temp_data_dir: Path) -> DownloadConfig:
    """Create download configuration for testing."""
    return DownloadConfig(
        output_dir=temp_data_dir / "era5land" / "netcdf",
        dataset="era5-land",
        variables=["2m_temperature"],
        start_date="2020-01-01",
        end_date="2020-01-02",
    )


@pytest.fixture
def transform_config() -> TransformConfig:
    """Create transform configuration for testing."""
    return TransformConfig(
        convert_kelvin_to_celsius=True,
        calculate_wind_speed=True,
    )


@pytest.fixture
def storage_config(temp_data_dir: Path) -> StorageConfig:
    """Create storage configuration for testing."""
    return StorageConfig(
        database_dir=temp_data_dir,
        parquet_compression="zstd",
        partition_cols=["date"],
    )


@pytest.fixture
def database_config(temp_data_dir: Path) -> DatabaseConfig:
    """Create database configuration for testing."""
    return DatabaseConfig(
        db_path=temp_data_dir / "test.duckdb",
    )


@pytest.fixture
def pipeline_config(temp_data_dir: Path) -> PipelineConfig:
    """Create complete pipeline configuration using factory method."""
    return PipelineConfig.create(
        base_dir=temp_data_dir,
        dataset="era5-land",
        start_date="2020-01-01",
        end_date="2020-01-02",
        variables=["2m_temperature"],
    )


@pytest.fixture
def sample_netcdf_file(temp_data_dir: Path) -> Generator[Path, None, None]:
    """Create a sample NetCDF file for testing.

    Args:
        temp_data_dir: Temporary data directory

    Yields:
        Path to sample NetCDF file
    """
    netcdf_dir = temp_data_dir / "era5land" / "netcdf"
    netcdf_dir.mkdir(parents=True, exist_ok=True)
    netcdf_file = netcdf_dir / "test_era5land_202001.nc"

    ds = xr.Dataset(
        {
            "t2m": (
                ["time", "latitude", "longitude"],
                np.random.rand(24, 10, 10) + 273.15,
            ),
            "d2m": (
                ["time", "latitude", "longitude"],
                np.random.rand(24, 10, 10) + 270.15,
            ),
            "u10": (
                ["time", "latitude", "longitude"],
                np.full((24, 10, 10), 3.0),
            ),
            "v10": (
                ["time", "latitude", "longitude"],
                np.full((24, 10, 10), 4.0),
            ),
        },
        coords={
            # xarray ≥2024 emits a UserWarning when it has to convert
            # non-nanosecond datetimes to ``ns`` resolution internally —
            # generate the array directly in ``ns`` precision to skip it.
            "time": np.arange(
                "2020-01-01", "2020-01-02", dtype="datetime64[h]"
            ).astype("datetime64[ns]"),
            "latitude": np.linspace(-10, 0, 10),
            "longitude": np.linspace(-50, -40, 10),
        },
    )

    ds["t2m"].attrs = {"units": "K", "long_name": "2m temperature"}
    ds["d2m"].attrs = {"units": "K", "long_name": "2m dewpoint temperature"}
    ds["u10"].attrs = {"units": "m/s", "long_name": "10m u-component of wind"}
    ds["v10"].attrs = {"units": "m/s", "long_name": "10m v-component of wind"}

    ds.to_netcdf(netcdf_file)

    yield netcdf_file

    if netcdf_file.exists():
        netcdf_file.unlink()
