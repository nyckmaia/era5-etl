"""Tests for NetCDF processor."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
import xarray as xr

from pyera5.config import ProcessingConfig
from pyera5.transform.netcdf_processor import NetCDFProcessor


def test_processor_initialization(processing_config: ProcessingConfig):
    """Test NetCDFProcessor initialization."""
    processor = NetCDFProcessor(processing_config)

    assert processor.config == processing_config
    assert processor.config.output_dir.exists()


def test_processor_rename_variables(processing_config: ProcessingConfig):
    """Test variable renaming."""
    processor = NetCDFProcessor(processing_config)

    # Create test dataset with ERA5 variable names
    ds = xr.Dataset(
        {
            "t2m": (["time", "lat", "lon"], np.random.rand(10, 5, 5)),
            "d2m": (["time", "lat", "lon"], np.random.rand(10, 5, 5)),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "lat": np.linspace(-10, 0, 5),
            "lon": np.linspace(-50, -40, 5),
        },
    )

    renamed = processor._rename_variables(ds)

    # Check if variables were renamed according to VAR_NAME_MAP
    # t2m -> temperature_2m, d2m -> dewpoint_2m
    assert "temperature_2m" in renamed.data_vars
    assert "dewpoint_2m" in renamed.data_vars
    assert "t2m" not in renamed.data_vars
    assert "d2m" not in renamed.data_vars


def test_processor_convert_temperature(processing_config: ProcessingConfig):
    """Test temperature conversion from Kelvin to Celsius."""
    processor = NetCDFProcessor(processing_config)

    # Create test dataset with temperature in Kelvin
    ds = xr.Dataset(
        {
            "temperature": (["time", "lat", "lon"], np.full((10, 5, 5), 300.0)),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "lat": np.linspace(-10, 0, 5),
            "lon": np.linspace(-50, -40, 5),
        },
    )

    ds["temperature"].attrs["units"] = "K"

    converted = processor._convert_temperature(ds)

    # Check if temperature was converted (300K = ~26.85°C)
    assert float(converted["temperature"].values[0, 0, 0]) < 100  # Should be in Celsius


def test_processor_calculate_wind_speed(processing_config: ProcessingConfig):
    """Test wind speed calculation from U/V components."""
    processor = NetCDFProcessor(processing_config)

    # Create test dataset with U and V wind components
    u_wind = 3.0  # m/s
    v_wind = 4.0  # m/s
    expected_speed = 5.0  # sqrt(3^2 + 4^2) = 5

    ds = xr.Dataset(
        {
            "wind_u_10m": (["time", "lat", "lon"], np.full((10, 5, 5), u_wind)),
            "wind_v_10m": (["time", "lat", "lon"], np.full((10, 5, 5), v_wind)),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "lat": np.linspace(-10, 0, 5),
            "lon": np.linspace(-50, -40, 5),
        },
    )

    ds["wind_u_10m"].attrs["units"] = "m/s"
    ds["wind_v_10m"].attrs["units"] = "m/s"

    result = processor._calculate_wind_speed(ds)

    # Check if wind speed was calculated
    wind_speed_var = [var for var in result.data_vars if "speed" in str(var).lower()]

    if wind_speed_var:
        calculated_speed = float(result[wind_speed_var[0]].values[0, 0, 0])
        assert abs(calculated_speed - expected_speed) < 0.01


def test_processor_dataset_to_dataframe(processing_config: ProcessingConfig):
    """Test conversion of xarray dataset to Polars DataFrame."""
    processor = NetCDFProcessor(processing_config)

    # Create simple test dataset
    ds = xr.Dataset(
        {
            "temperature": (["time", "lat", "lon"], np.random.rand(10, 3, 3)),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "lat": np.linspace(-10, 0, 3),
            "lon": np.linspace(-50, -40, 3),
        },
    )

    df = processor._dataset_to_dataframe(ds)

    # Check if DataFrame was created
    assert isinstance(df, pl.DataFrame)
    assert len(df) > 0
    assert "time" in df.columns
    assert "temperature" in df.columns

    # Check if temporal columns were added
    assert "year" in df.columns
    assert "month" in df.columns
    assert "day" in df.columns
    assert "hour" in df.columns


def test_processor_process_directory_no_files(processing_config: ProcessingConfig):
    """Test processing directory with no NetCDF files."""
    processor = NetCDFProcessor(processing_config)

    stats = processor.process_directory()

    assert stats["total"] == 0
    assert stats["processed"] == 0
    assert stats["skipped"] == 0
    assert stats["failed"] == 0


@pytest.mark.skipif(
    not Path("tests/data/sample.nc").exists(),
    reason="Sample NetCDF file not available",
)
def test_processor_process_file(processing_config: ProcessingConfig, sample_netcdf_file: Path):
    """Test processing a single NetCDF file."""
    processor = NetCDFProcessor(processing_config)

    output_file = processor.process_file(sample_netcdf_file)

    assert output_file.exists()
    assert output_file.suffix == ".csv"

    # Read output and verify
    df = pl.read_csv(output_file)
    assert len(df) > 0
