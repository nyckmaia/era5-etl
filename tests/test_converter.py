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
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]").astype("datetime64[ns]"),
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
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]").astype("datetime64[ns]"),
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
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]").astype("datetime64[ns]"),
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
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]").astype("datetime64[ns]"),
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
            "time": np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]").astype("datetime64[ns]"),
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


def test_convert_directory_cleanup_removes_nc_on_success(
    converter: NetCDFToParquetConverter, sample_netcdf_file: Path
):
    """With cleanup=True, a successfully-converted .nc must be deleted."""
    nc_dir = sample_netcdf_file.parent
    assert sample_netcdf_file.exists()

    stats = converter.convert_directory(nc_dir, cleanup=True)

    assert stats["converted"] >= 1
    assert stats["failed"] == 0
    assert not sample_netcdf_file.exists(), (
        "Successfully converted .nc should have been deleted with cleanup=True"
    )


def test_convert_directory_cleanup_false_keeps_nc(
    converter: NetCDFToParquetConverter, sample_netcdf_file: Path
):
    """Default (cleanup=False) must leave the .nc on disk."""
    converter.convert_directory(sample_netcdf_file.parent, cleanup=False)
    assert sample_netcdf_file.exists()


def test_convert_directory_cleanup_keeps_failed_nc(
    converter: NetCDFToParquetConverter, tmp_path: Path
):
    """A .nc that FAILS to convert must be kept even when cleanup=True so
    the user can inspect/retry it."""
    bad_dir = tmp_path / "bad_nc"
    bad_dir.mkdir()
    bad = bad_dir / "corrupt.nc"
    bad.write_bytes(b"not a real netcdf file")

    stats = converter.convert_directory(bad_dir, cleanup=True)

    assert stats["failed"] == 1
    assert bad.exists(), "Failed .nc must be retained for inspection"


# --- M03: drop number/expver -------------------------------------------------


def test_drop_unused_columns_removes_number_expver(
    converter: NetCDFToParquetConverter,
):
    """`number` and `expver` (CDS scalar coords) must be dropped if present."""
    df = pl.DataFrame(
        {
            "latitude": [1.0, 2.0],
            "longitude": [3.0, 4.0],
            "number": [0, 0],
            "expver": ["0001", "0001"],
            "t2m": [290.0, 291.0],
        }
    )
    out = converter._drop_unused_columns(df)
    assert "number" not in out.columns
    assert "expver" not in out.columns
    assert set(out.columns) == {"latitude", "longitude", "t2m"}


def test_drop_unused_columns_noop_when_absent(
    converter: NetCDFToParquetConverter,
):
    """No `number`/`expver` -> dataframe unchanged."""
    df = pl.DataFrame({"latitude": [1.0], "longitude": [2.0], "t2m": [290.0]})
    out = converter._drop_unused_columns(df)
    assert out.columns == df.columns


# --- M02a: dataset-aware lat/lon rounding ------------------------------------


def _latlon_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "latitude": [-23.456789, -10.114999],
            "longitude": [-46.654321, -49.949001],
            "t2m": [290.0, 291.0],
        }
    ).cast(
        {"latitude": pl.Float64, "longitude": pl.Float64, "t2m": pl.Float64}
    )


def test_round_latlon_era5_two_decimals(tmp_path: Path):
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset="era5",
    )
    out = conv._round_latlon(_latlon_df())
    assert out["latitude"].dtype == pl.Float32
    assert out["longitude"].dtype == pl.Float32
    # 2 decimals for ERA5 (0.25 deg grid)
    assert out["latitude"].to_list()[0] == pytest.approx(-23.46, abs=1e-4)
    assert out["longitude"].to_list()[1] == pytest.approx(-49.95, abs=1e-4)


def test_round_latlon_era5land_one_decimal(tmp_path: Path):
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset="era5-land",
    )
    out = conv._round_latlon(_latlon_df())
    assert out["latitude"].dtype == pl.Float32
    # 1 decimal for ERA5-LAND (0.1 deg grid)
    assert out["latitude"].to_list()[0] == pytest.approx(-23.5, abs=1e-4)
    assert out["latitude"].to_list()[1] == pytest.approx(-10.1, abs=1e-4)


def test_round_latlon_noop_without_dataset(
    converter: NetCDFToParquetConverter,
):
    """Legacy dataset-agnostic path (dataset=None) must not touch lat/lon."""
    df = _latlon_df()
    out = converter._round_latlon(df)
    # converter fixture is built without dataset -> unchanged dtype/values
    assert out["latitude"].dtype == pl.Float64
    assert out["latitude"].to_list() == df["latitude"].to_list()


def test_latlon_decimals_property():
    from era5_etl.datasets import DatasetRegistry

    assert DatasetRegistry.get("era5").latlon_decimals == 2
    assert DatasetRegistry.get("era5-land").latlon_decimals == 1


# ----- Region clipping ----------------------------------------------------


def _frame_for_clip(latlons: list[tuple[float, float]]) -> pl.DataFrame:
    """Build a tiny converter-shaped frame with the given lat/lon pairs."""
    return pl.DataFrame(
        {
            "latitude": pl.Series([lat for lat, _ in latlons], dtype=pl.Float32),
            "longitude": pl.Series([lon for _, lon in latlons], dtype=pl.Float32),
            "t2m": pl.Series([1.0] * len(latlons), dtype=pl.Float64),
        }
    )


def test_clip_to_regions_noop_when_disabled(tmp_path: Path):
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(),  # clip_regions=None
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset="era5",
    )
    df = _frame_for_clip([(-23.5, -46.5), (10.0, 10.0)])
    out = conv._clip_to_regions(df)
    assert out.height == df.height
    assert out.equals(df)


def test_clip_to_regions_drops_points_outside_sp(tmp_path: Path):
    """A point in Sao Paulo stays; one in the Atlantic ocean is dropped."""
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(clip_regions=["SP"]),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset="era5",
    )
    # Inside SP: city of Sao Paulo is roughly at (-23.5, -46.5);
    # snapped to ERA5 grid (2dp, 0.25-aligned) -> (-23.5, -46.5).
    # Outside SP: deep in the Atlantic (-23.5, -30.0).
    df = _frame_for_clip([(-23.5, -46.5), (-23.5, -30.0)])
    out = conv._clip_to_regions(df)
    assert out.height == 1
    assert float(out["latitude"][0]) == pytest.approx(-23.5)
    assert float(out["longitude"][0]) == pytest.approx(-46.5)


def test_clip_to_regions_union_keeps_both_states(tmp_path: Path):
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(clip_regions=["SP", "RJ"]),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset="era5",
    )
    # Picked from the actual SP/RJ membership cells (era5, 0.25 deg).
    # SP cell: (-23.5, -46.5); RJ cell: (-22.5, -42.5); ocean: (-23.5, -30.0)
    df = _frame_for_clip([(-23.5, -46.5), (-22.5, -42.5), (-23.5, -30.0)])
    out = conv._clip_to_regions(df)
    assert out.height == 2


def test_clip_to_regions_noop_without_dataset(tmp_path: Path):
    """Synthetic-frame path (dataset=None) must skip the clip even if configured."""
    conv = NetCDFToParquetConverter(
        transform_config=TransformConfig(clip_regions=["SP"]),
        storage_config=StorageConfig(database_dir=tmp_path),
        output_dir=tmp_path / "p",
        dataset=None,
    )
    df = _frame_for_clip([(-23.5, -46.5), (10.0, 10.0)])
    out = conv._clip_to_regions(df)
    assert out.height == df.height
