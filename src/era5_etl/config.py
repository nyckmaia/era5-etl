"""Configuration management for ERA5-ETL using Pydantic."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from era5_etl.constants import (
    BRAZIL_BBOX,
    DATASET_ERA5_LAND,
    DATASET_ERA5_SINGLE_LEVEL,
    DEFAULT_VARIABLES,
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
        default_factory=lambda: list(DEFAULT_VARIABLES),
        description="Variables to download",
    )
    start_date: str = Field(
        default="2020-01-01",
        description="Start date (YYYY-MM-DD)",
    )
    end_date: str | None = Field(
        default=None,
        description="End date (YYYY-MM-DD, None=today)",
    )
    area: list[float] = Field(
        default_factory=lambda: [float(x) for x in BRAZIL_BBOX],
        description="Area bounds [North, West, South, East]",
    )
    hours: list[str] = Field(
        default_factory=lambda: list(HOURS_ALL),
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
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of download retries per period",
    )
    retry_delay: float = Field(
        default=30.0,
        ge=1.0,
        description="Base delay between retries in seconds (exponential backoff)",
    )
    max_request_bytes: int = Field(
        default=500 * 1024 * 1024,
        ge=1024 * 1024,
        description="Maximum estimated request size in bytes before auto-splitting geographic area",
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
        return DATASET_ERA5_LAND


class TransformConfig(BaseModel):
    """Configuration for NetCDF-to-Parquet transformation.

    Handles the direct NetCDF -> Parquet pipeline, replacing the old
    ProcessingConfig + StorageConfig split.
    """

    convert_kelvin_to_celsius: bool = Field(
        default=True,
        description="Convert temperature from Kelvin to Celsius",
    )
    calculate_wind_speed: bool = Field(
        default=True,
        description="Calculate wind speed from U/V components",
    )
    override: bool = Field(default=False, description="Override existing files")
    max_workers: int | None = Field(
        default=None,
        description="Maximum number of worker processes for parallel conversion (None=auto)",
    )


class StorageConfig(BaseModel):
    """Configuration for Parquet storage."""

    database_dir: Path = Field(description="Base directory for data storage")
    parquet_compression: Literal["snappy", "zstd", "gzip"] = Field(
        default="zstd",
        description="Parquet compression algorithm",
    )
    partition_cols: list[str] = Field(
        default=["date"],
        description="Partition columns for Hive-style partitioning (date=YYYY-MM-DD)",
    )
    row_group_size: int = Field(
        default=100_000,
        ge=1000,
        description="Row group size for Parquet files",
    )

    @field_validator("database_dir")
    @classmethod
    def validate_database_dir(cls, v: Path) -> Path:
        return v.resolve()


class DatabaseConfig(BaseModel):
    """Configuration for DuckDB database."""

    db_path: Path | None = Field(
        default=None,
        description="DuckDB file path (None=in-memory)",
    )
    read_only: bool = Field(default=False, description="Read-only mode")
    threads: int | None = Field(
        default=None,
        description="Number of threads (None=auto)",
    )


class PipelineConfig(BaseModel):
    """Complete pipeline configuration for ERA5-ETL."""

    download: DownloadConfig
    transform: TransformConfig = Field(default_factory=TransformConfig)
    storage: StorageConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    dataset_name: str = Field(
        default="era5-land",
        description="Dataset name (era5, era5-land). Used to organize output directories.",
    )
    keep_temp_files: bool = Field(
        default=False,
        description="Keep temporary NetCDF files after Parquet export.",
    )

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def create(
        cls,
        base_dir: str | Path,
        dataset: Literal["era5", "era5-land"] = "era5-land",
        start_date: str = "2020-01-01",
        end_date: str | None = None,
        variables: list[str] | None = None,
        area: list[float] | None = None,
        hours: list[str] | None = None,
        override: bool = False,
        keep_temp_files: bool = False,
        compression: Literal["snappy", "zstd", "gzip"] = "zstd",
    ) -> "PipelineConfig":
        """Factory method to create PipelineConfig with automatic path configuration.

        Creates a standardized directory structure:
            base_dir/
            +-- {dataset}/
            |   +-- netcdf/    (downloaded files - temporary)
            +-- parquet/
            |   +-- {dataset}/ (output Parquet files, Hive-partitioned)

        Args:
            base_dir: Base directory for all data storage
            dataset: ERA5 dataset name (era5, era5-land)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format (None=today)
            variables: List of ERA5 variables to download
            area: Geographic bounds [North, West, South, East]
            hours: List of hours to download
            override: Whether to override existing files
            keep_temp_files: Keep NetCDF files after conversion
            compression: Parquet compression algorithm
        """
        base_dir = Path(base_dir)
        dataset_dir_name = dataset.replace("-", "")  # era5land, era5

        return cls(
            download=DownloadConfig(
                output_dir=base_dir / dataset_dir_name / "netcdf",
                dataset=dataset,
                variables=variables or list(DEFAULT_VARIABLES),
                start_date=start_date,
                end_date=end_date,
                area=area or [float(x) for x in BRAZIL_BBOX],
                hours=hours or list(HOURS_ALL),
                override=override,
            ),
            transform=TransformConfig(override=override),
            storage=StorageConfig(
                database_dir=base_dir,
                parquet_compression=compression,
            ),
            database=DatabaseConfig(
                db_path=base_dir / f"{dataset_dir_name}.duckdb",
            ),
            dataset_name=dataset,
            keep_temp_files=keep_temp_files,
        )

    def get_parquet_dir(self) -> Path:
        """Get the path to the Parquet output directory for this dataset."""
        dataset_dir_name = self.dataset_name.replace("-", "")
        return self.storage.database_dir / "parquet" / dataset_dir_name

    def get_netcdf_dir(self) -> Path:
        """Get the path to the NetCDF input directory."""
        return self.download.output_dir

    def get_database_path(self) -> Path:
        """Get the path to the DuckDB database file."""
        dataset_dir_name = self.dataset_name.replace("-", "")
        return self.storage.database_dir / f"{dataset_dir_name}.duckdb"
