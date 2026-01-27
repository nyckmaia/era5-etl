"""Tests for configuration module."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from era5_etl.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    StorageConfig,
    TransformConfig,
)


def test_download_config_defaults():
    """Test DownloadConfig with default values."""
    config = DownloadConfig()

    assert config.dataset == "era5-land"
    assert config.output_dir.name == "netcdf"
    assert len(config.variables) == 6
    assert config.start_date == "2020-01-01"
    assert config.override is False


def test_download_config_custom_values():
    """Test DownloadConfig with custom values."""
    config = DownloadConfig(
        output_dir=Path("/tmp/data"),
        dataset="era5",
        variables=["2m_temperature"],
        start_date="2021-06-01",
        end_date="2021-06-30",
        override=True,
    )

    assert config.dataset == "era5"
    assert config.variables == ["2m_temperature"]
    assert config.start_date == "2021-06-01"
    assert config.end_date == "2021-06-30"
    assert config.override is True


def test_download_config_invalid_area():
    """Test DownloadConfig with invalid area."""
    with pytest.raises(ValidationError):
        DownloadConfig(area=[90, -180])  # Missing 2 values


def test_download_config_cds_dataset_name():
    """Test CDS dataset name generation."""
    config_land = DownloadConfig(dataset="era5-land")
    config_era5 = DownloadConfig(dataset="era5")

    assert config_land.get_cds_dataset_name() == "reanalysis-era5-land"
    assert config_era5.get_cds_dataset_name() == "reanalysis-era5-single-levels"


def test_transform_config_defaults():
    """Test TransformConfig with default values."""
    config = TransformConfig()

    assert config.convert_kelvin_to_celsius is True
    assert config.calculate_wind_speed is True
    assert config.override is False


def test_transform_config_custom():
    """Test TransformConfig with custom values."""
    config = TransformConfig(
        convert_kelvin_to_celsius=False,
        calculate_wind_speed=False,
        override=True,
    )

    assert config.convert_kelvin_to_celsius is False
    assert config.calculate_wind_speed is False
    assert config.override is True


def test_storage_config(temp_data_dir: Path):
    """Test StorageConfig."""
    config = StorageConfig(
        database_dir=temp_data_dir,
        partition_cols=["date"],
        parquet_compression="snappy",
    )

    assert config.database_dir == temp_data_dir.resolve()
    assert config.partition_cols == ["date"]
    assert config.parquet_compression == "snappy"


def test_storage_config_default_compression(temp_data_dir: Path):
    """Test StorageConfig defaults to zstd compression."""
    config = StorageConfig(database_dir=temp_data_dir)

    assert config.parquet_compression == "zstd"


def test_database_config():
    """Test DatabaseConfig."""
    config = DatabaseConfig(
        db_path=Path("/tmp/test.duckdb"),
        read_only=False,
        threads=4,
    )

    assert config.db_path == Path("/tmp/test.duckdb")
    assert config.read_only is False
    assert config.threads == 4


def test_database_config_memory():
    """Test DatabaseConfig with in-memory database."""
    config = DatabaseConfig()

    assert config.db_path is None
    assert config.read_only is False


def test_pipeline_config_create_factory(tmp_path: Path):
    """Test PipelineConfig.create() factory method."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        dataset="era5-land",
        start_date="2023-01-01",
        end_date="2023-01-31",
    )

    assert isinstance(config.download, DownloadConfig)
    assert isinstance(config.transform, TransformConfig)
    assert isinstance(config.storage, StorageConfig)
    assert isinstance(config.database, DatabaseConfig)
    assert config.dataset_name == "era5-land"
    assert config.download.dataset == "era5-land"
    assert config.download.start_date == "2023-01-01"
    assert config.download.end_date == "2023-01-31"


def test_pipeline_config_directory_structure(tmp_path: Path):
    """Test PipelineConfig creates correct directory paths."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        dataset="era5-land",
    )

    netcdf_dir = config.get_netcdf_dir()
    parquet_dir = config.get_parquet_dir()
    db_path = config.get_database_path()

    assert "era5land" in str(netcdf_dir)
    assert "netcdf" in str(netcdf_dir)
    assert "parquet" in str(parquet_dir)
    assert "era5land" in str(parquet_dir)
    assert str(db_path).endswith(".duckdb")


def test_pipeline_config_era5_dataset(tmp_path: Path):
    """Test PipelineConfig with era5 (not era5-land) dataset."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        dataset="era5",
    )

    assert config.dataset_name == "era5"
    assert "era5" in str(config.get_parquet_dir())
    assert config.download.dataset == "era5"


def test_pipeline_config_custom_variables(tmp_path: Path):
    """Test PipelineConfig with custom variables."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        variables=["2m_temperature", "total_precipitation"],
    )

    assert config.download.variables == ["2m_temperature", "total_precipitation"]


def test_pipeline_config_override_flag(tmp_path: Path):
    """Test PipelineConfig propagates override flag."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        override=True,
    )

    assert config.download.override is True
    assert config.transform.override is True


def test_pipeline_config_keep_temp_files(tmp_path: Path):
    """Test PipelineConfig keep_temp_files flag."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        keep_temp_files=True,
    )

    assert config.keep_temp_files is True


def test_pipeline_config_compression(tmp_path: Path):
    """Test PipelineConfig compression setting."""
    config = PipelineConfig.create(
        base_dir=tmp_path,
        compression="snappy",
    )

    assert config.storage.parquet_compression == "snappy"


def test_pipeline_config_fixture(pipeline_config: PipelineConfig):
    """Test that the pipeline_config fixture works."""
    assert isinstance(pipeline_config.download, DownloadConfig)
    assert isinstance(pipeline_config.transform, TransformConfig)
    assert isinstance(pipeline_config.storage, StorageConfig)
    assert isinstance(pipeline_config.database, DatabaseConfig)
