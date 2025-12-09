"""Tests for configuration module."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from pyera5.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    ProcessingConfig,
    StorageConfig,
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


def test_processing_config(temp_data_dir: Path):
    """Test ProcessingConfig."""
    config = ProcessingConfig(
        input_dir=temp_data_dir / "netcdf",
        output_dir=temp_data_dir / "processed",
        convert_kelvin_to_celsius=True,
        calculate_wind_speed=True,
    )

    assert config.input_dir == temp_data_dir / "netcdf"
    assert config.output_dir == temp_data_dir / "processed"
    assert config.convert_kelvin_to_celsius is True
    assert config.calculate_wind_speed is True


def test_storage_config(temp_data_dir: Path):
    """Test StorageConfig."""
    config = StorageConfig(
        parquet_dir=temp_data_dir / "parquet",
        partition_cols=["year", "month"],
        compression="snappy",
    )

    assert config.parquet_dir == temp_data_dir / "parquet"
    assert config.partition_cols == ["year", "month"]
    assert config.compression == "snappy"


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


def test_pipeline_config(pipeline_config: PipelineConfig):
    """Test complete PipelineConfig."""
    assert isinstance(pipeline_config.download, DownloadConfig)
    assert isinstance(pipeline_config.processing, ProcessingConfig)
    assert isinstance(pipeline_config.storage, StorageConfig)
    assert isinstance(pipeline_config.database, DatabaseConfig)


def test_pipeline_config_from_dict(temp_data_dir: Path):
    """Test PipelineConfig creation from dictionary."""
    config_dict = {
        "download": {
            "output_dir": str(temp_data_dir / "netcdf"),
            "dataset": "era5-land",
            "start_date": "2020-01-01",
        },
        "processing": {
            "input_dir": str(temp_data_dir / "netcdf"),
            "output_dir": str(temp_data_dir / "processed"),
        },
        "storage": {
            "parquet_dir": str(temp_data_dir / "parquet"),
        },
        "database": {},
    }

    config = PipelineConfig.from_dict(config_dict)

    assert config.download.dataset == "era5-land"
    assert isinstance(config.database, DatabaseConfig)
