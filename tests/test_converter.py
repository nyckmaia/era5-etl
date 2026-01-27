"""Tests for NetCDF to Parquet converter."""

from pathlib import Path

import numpy as np
import polars as pl
import pytest
import xarray as xr

from era5_etl.config import StorageConfig, TransformConfig
from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter


@pytest.fixture
def converter(tmp_path: Path) -> NetCDFToParquetConverter:
    """Create a converter instance for testing."""
    output_dir = tmp_path / "parquet" / "era5land"
    return NetCDFToParquetConverter(
        transform_config=TransformConfig(),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=output_dir,
    )


def test_converter_initialization(converter: NetCDFToParquetConverter):
    """Test converter initialization."""
    assert converter.output_dir.exists()


def test_converter_rename_variables(converter: NetCDFToParquetConverter):
    """Test variable renaming from short names to friendly names."""
    ds = xr.Dataset(
        {
            "t2m": (["time", "latitude", "longitude"], np.random.rand(10, 5, 5)),
            "d2m": (["time", "latitude", "longitude"], np.random.rand(10, 5, 5)),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "latitude": np.linspace(-10, 0, 5),
            "longitude": np.linspace(-50, -40, 5),
        },
    )

    renamed = converter._rename_variables(ds)

    assert "temperature_2m" in renamed.data_vars
    assert "dewpoint_2m" in renamed.data_vars
    assert "t2m" not in renamed.data_vars
    assert "d2m" not in renamed.data_vars


def test_converter_convert_temperature(converter: NetCDFToParquetConverter):
    """Test temperature conversion from Kelvin to Celsius."""
    ds = xr.Dataset(
        {
            "temperature_2m": (
                ["time", "latitude", "longitude"],
                np.full((10, 5, 5), 300.0),
            ),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "latitude": np.linspace(-10, 0, 5),
            "longitude": np.linspace(-50, -40, 5),
        },
    )
    ds["temperature_2m"].attrs = {"units": "K"}

    converted = converter._convert_temperature(ds)

    # 300K -> ~26.85°C
    val = float(converted["temperature_2m"].values[0, 0, 0])
    assert 26 < val < 27
    assert converted["temperature_2m"].attrs["units"] == "°C"


def test_converter_no_conversion_without_kelvin_units(converter: NetCDFToParquetConverter):
    """Test that temperatures without Kelvin units are not converted."""
    ds = xr.Dataset(
        {
            "temperature_2m": (
                ["time", "latitude", "longitude"],
                np.full((10, 5, 5), 25.0),
            ),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "latitude": np.linspace(-10, 0, 5),
            "longitude": np.linspace(-50, -40, 5),
        },
    )
    ds["temperature_2m"].attrs = {"units": "°C"}

    converted = converter._convert_temperature(ds)

    val = float(converted["temperature_2m"].values[0, 0, 0])
    assert abs(val - 25.0) < 0.01


def test_converter_calculate_wind_speed(converter: NetCDFToParquetConverter):
    """Test wind speed calculation from U/V components."""
    u_wind = 3.0
    v_wind = 4.0
    expected_speed = 5.0

    ds = xr.Dataset(
        {
            "wind_u_10m": (
                ["time", "latitude", "longitude"],
                np.full((10, 5, 5), u_wind),
            ),
            "wind_v_10m": (
                ["time", "latitude", "longitude"],
                np.full((10, 5, 5), v_wind),
            ),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "latitude": np.linspace(-10, 0, 5),
            "longitude": np.linspace(-50, -40, 5),
        },
    )
    ds["wind_u_10m"].attrs = {"units": "m/s"}
    ds["wind_v_10m"].attrs = {"units": "m/s"}

    result = converter._calculate_wind_speed(ds)

    assert "wind_speed_10m" in result.data_vars
    calculated = float(result["wind_speed_10m"].values[0, 0, 0])
    assert abs(calculated - expected_speed) < 0.01


def test_converter_dataset_to_dataframe(converter: NetCDFToParquetConverter):
    """Test xarray Dataset to Polars DataFrame conversion."""
    ds = xr.Dataset(
        {
            "temperature_2m": (
                ["time", "latitude", "longitude"],
                np.random.rand(10, 3, 3),
            ),
        },
        coords={
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]"),
            "latitude": np.linspace(-10, 0, 3),
            "longitude": np.linspace(-50, -40, 3),
        },
    )

    df = converter._dataset_to_dataframe(ds)

    assert isinstance(df, pl.DataFrame)
    assert len(df) > 0
    assert "temperature_2m" in df.columns
    assert "date" in df.columns
    assert "hour_utc" in df.columns
    assert df.schema["date"] == pl.Date
    assert df.schema["hour_utc"] == pl.Int8
    assert "time" not in df.columns
    assert "valid_time" not in df.columns
    assert "year" not in df.columns
    assert "month" not in df.columns
    assert "day" not in df.columns
    assert "hour" not in df.columns


def test_converter_convert_file(converter: NetCDFToParquetConverter, sample_netcdf_file: Path):
    """Test full file conversion from NetCDF to Parquet."""
    output = converter.convert_file(sample_netcdf_file)

    assert output.exists()
    # Should have created partitioned files or a single file
    parquet_files = list(output.rglob("*.parquet"))
    assert len(parquet_files) > 0


def test_converter_convert_directory_empty(converter: NetCDFToParquetConverter, tmp_path: Path):
    """Test converting empty directory."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    stats = converter.convert_directory(empty_dir)

    assert stats["total"] == 0
    assert stats["converted"] == 0


def test_apply_float_precision(converter: NetCDFToParquetConverter):
    """Test that Float64 columns are cast to Float32 with rounding."""
    df = pl.DataFrame({
        "temperature_2m": [20.123456789, -5.987654321, 30.111222333],
        "surface_pressure": [101325.12345, 99800.54321, 102000.98765],
        "latitude": [1.0, 2.0, 3.0],
    }).cast({"temperature_2m": pl.Float64, "surface_pressure": pl.Float64, "latitude": pl.Float64})

    result = converter._apply_float_precision(df)

    # All Float64 columns should become Float32
    for col in result.columns:
        assert result[col].dtype == pl.Float32, f"{col} should be Float32, got {result[col].dtype}"

    # Check rounding to 4 decimal places
    temp_vals = result["temperature_2m"].to_list()
    assert abs(temp_vals[0] - 20.1235) < 0.001
    assert abs(temp_vals[1] - (-5.9877)) < 0.001


def test_converter_convert_directory_with_files(
    converter: NetCDFToParquetConverter, sample_netcdf_file: Path
):
    """Test converting directory with NetCDF files."""
    stats = converter.convert_directory(sample_netcdf_file.parent)

    assert stats["total"] >= 1
    assert stats["converted"] >= 1
    assert stats["failed"] == 0
