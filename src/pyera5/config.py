"""Configuration management for PyERA5 using Pydantic."""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from pyera5.constants import (
    BRAZIL_BBOX,
    DATASET_ERA5_LAND,
    DATASET_ERA5_SINGLE_LEVEL,
    GLOBAL_BBOX,
    HOURS_ALL,
)


class DownloadConfig(BaseModel):
    """Configuration for ERA5/ERA5-Land download from CDS."""

    output_dir: Path = Field(
        default=Path("./data/era5/netcdf"),
        description="Directory to save downloaded NetCDF files",
    )
    dataset: Literal["era5", "era5-land"] = Field(
        default="era5-land",
        description="Dataset to download (era5 or era5-land)",
    )
    variables: list[str] = Field(
        default=[
            "2m_temperature",
            "2m_dewpoint_temperature",
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            "surface_pressure",
            "total_precipitation",
        ],
        description="Variables to download",
    )
    start_date: str = Field(
        default="2020-01-01",
        description="Start date (YYYY-MM-DD)",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date (YYYY-MM-DD, None=today)",
    )
    area: list[float] = Field(
        default=BRAZIL_BBOX,
        description="Area bounds [North, West, South, East]",
    )
    hours: list[str] = Field(
        default=HOURS_ALL,
        description="Hours to download (e.g., ['00:00', '12:00'])",
    )
    override: bool = Field(
        default=False,
        description="Override existing files",
    )
    timeout: int = Field(
        default=3600,
        ge=60,
        description="Download timeout in seconds",
    )

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator("area")
    @classmethod
    def validate_area(cls, v: list[float]) -> list[float]:
        if len(v) != 4:
            raise ValueError("Area must have 4 values: [North, West, South, East]")
        north, west, south, east = v
        if not (-90 <= south <= north <= 90):
            raise ValueError("Invalid latitude bounds")
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            raise ValueError("Invalid longitude bounds")
        return v

    def get_cds_dataset_name(self) -> str:
        """Get the CDS API dataset name."""
        if self.dataset == "era5":
            return DATASET_ERA5_SINGLE_LEVEL
        else:
            return DATASET_ERA5_LAND


class ProcessingConfig(BaseModel):
    """Configuration for NetCDF processing."""

    input_dir: Path = Field(description="Directory with NetCDF files")
    output_dir: Path = Field(description="Directory for processed data")
    convert_kelvin_to_celsius: bool = Field(
        default=True,
        description="Convert temperature from Kelvin to Celsius",
    )
    calculate_wind_speed: bool = Field(
        default=True,
        description="Calculate wind speed from U/V components",
    )
    resample_frequency: Optional[str] = Field(
        default=None,
        description="Resample frequency (e.g., '1D', '1H', '3H')",
    )
    override: bool = Field(default=False, description="Override existing files")
    max_workers: Optional[int] = Field(
        default=None,
        description="Parallel workers (None=auto)",
    )


class StorageConfig(BaseModel):
    """Configuration for Parquet storage."""

    parquet_dir: Path = Field(description="Directory for Parquet files")
    partition_cols: list[str] = Field(
        default=["year", "month"],
        description="Partition columns",
    )
    compression: Literal["snappy", "gzip", "brotli", "zstd"] = Field(
        default="snappy",
        description="Compression codec",
    )
    row_group_size: int = Field(
        default=100_000,
        ge=1000,
        description="Row group size",
    )


class DatabaseConfig(BaseModel):
    """Configuration for DuckDB database."""

    db_path: Optional[Path] = Field(
        default=None,
        description="DuckDB file (None=memory)",
    )
    read_only: bool = Field(default=False, description="Read-only mode")
    threads: Optional[int] = Field(
        default=None,
        description="Number of threads (None=auto)",
    )


class PipelineConfig(BaseModel):
    """Complete pipeline configuration."""

    download: DownloadConfig
    processing: ProcessingConfig
    storage: StorageConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_dict(cls, config_dict: dict) -> "PipelineConfig":
        """Create configuration from dictionary."""
        return cls(**config_dict)
