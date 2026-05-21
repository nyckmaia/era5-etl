"""Configuration management for ERA5-ETL using Pydantic.

All on-disk path decisions go through :mod:`era5_etl.storage.paths`; dataset
identity goes through :class:`era5_etl.datasets.DatasetRegistry`. The factory
:meth:`PipelineConfig.create` is the recommended entry point for assembling a
full configuration from a single ``base_dir`` and a handful of user options.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from era5_etl.constants import BRAZIL_BBOX, HOURS_ALL
from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.paths import (
    resolve_base_dir,
    resolve_dataset_dir,
    resolve_duckdb_path,
    resolve_netcdf_temp_dir,
)


def _default_variables_for(dataset: str) -> list[str]:
    """Return the default variable list for a registered dataset."""
    try:
        return list(DatasetRegistry.get(dataset).default_variables)
    except KeyError:
        # During config construction we may not have a registered name yet
        # (e.g. when a test instantiates DownloadConfig with a custom dataset
        # for validation paths). Fall back to a small, sane default.
        from era5_etl.constants import DEFAULT_VARIABLES

        return list(DEFAULT_VARIABLES)


class DownloadConfig(BaseModel):
    """Configuration for ERA5/ERA5-Land download from CDS."""

    output_dir: Path = Field(
        default=Path("./data/era5/netcdf"),
        description="Directory to save downloaded NetCDF files",
    )
    dataset: str = Field(
        default="era5-land",
        description="Dataset name. Must be a registered DatasetConfig name (era5, era5-land).",
    )
    variables: list[str] = Field(
        default_factory=lambda: _default_variables_for("era5-land"),
        description="Variables to download (CDS API names)",
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
        description="Maximum estimated request size in bytes before auto-splitting",
    )
    years: list[int] | None = Field(
        default=None,
        description=(
            "Explicit list of years to acquire. Only used by non-grid "
            "sources (INMET): when set, exactly these yearly ZIPs are "
            "fetched (the user may pick a non-contiguous subset); when "
            "None, the year range is derived from start_date/end_date. "
            "Ignored by CDS/grid datasets."
        ),
    )

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator("dataset")
    @classmethod
    def validate_dataset(cls, v: str) -> str:
        if v not in DatasetRegistry.names():
            valid = ", ".join(DatasetRegistry.names())
            raise ValueError(f"Unknown dataset '{v}'. Available: {valid}")
        return v

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
        """Return the CDS API dataset identifier for this download."""
        return DatasetRegistry.get(self.dataset).CDS_DATASET_ID


class TransformConfig(BaseModel):
    """Configuration for NetCDF-to-Parquet transformation."""

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
    clip_regions: list[str] | None = Field(
        default=None,
        description=(
            "Brazilian UF sigla(s) (e.g. ['SP', 'RJ']) or ['BR']. When set, "
            "grid points outside the polygon (with half-cell buffer) are dropped "
            "before writing Parquet. Gridded CDS datasets only. See "
            ":mod:`era5_etl.regions.membership` for the pre-computed lookup."
        ),
    )


class StorageConfig(BaseModel):
    """Configuration for Parquet storage.

    ``database_dir`` is the user-facing base directory. The actual on-disk
    layout under it is computed by :mod:`era5_etl.storage.paths`.
    """

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
        description="Dataset name (era5, era5-land). Drives output directory layout.",
    )
    keep_temp_files: bool = Field(
        default=False,
        description="Keep temporary NetCDF files after Parquet export.",
    )

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("dataset_name")
    @classmethod
    def validate_dataset_name(cls, v: str) -> str:
        if v not in DatasetRegistry.names():
            valid = ", ".join(DatasetRegistry.names())
            raise ValueError(f"Unknown dataset '{v}'. Available: {valid}")
        return v

    @classmethod
    def create(
        cls,
        base_dir: str | Path,
        dataset: str = "era5-land",
        start_date: str = "2020-01-01",
        end_date: str | None = None,
        variables: list[str] | None = None,
        area: list[float] | None = None,
        hours: list[str] | None = None,
        override: bool = False,
        keep_temp_files: bool = False,
        compression: Literal["snappy", "zstd", "gzip"] = "zstd",
        years: list[int] | None = None,
        clip_regions: list[str] | None = None,
    ) -> PipelineConfig:
        """Assemble a full ``PipelineConfig`` from a ``base_dir`` and options.

        On-disk layout::

            <base_dir>/
              climate_data_store_db/
                <dataset>/                    -> Parquet partitions + manifest + DuckDB
                _tmp_netcdf/
                  <dataset>/                  -> raw NetCDF (temporary; removed
                                                 after a successful conversion)

        ``clip_regions`` activates polygon clipping at conversion time.
        Only gridded datasets (``cds_grid``) support clipping; passing
        regions for a station source (e.g. INMET) raises ``ValueError``.
        """
        base = resolve_base_dir(base_dir)
        netcdf_dir = resolve_netcdf_temp_dir(base, dataset)
        db_path = resolve_duckdb_path(base, dataset)

        # Default variables come from the dataset's own YAML if none provided.
        if variables is None:
            variables = list(DatasetRegistry.get(dataset).default_variables)

        if clip_regions:
            ds_cfg = DatasetRegistry.get(dataset)
            if not ds_cfg.is_gridded:
                raise ValueError(
                    f"clip_regions={clip_regions!r} is only supported for "
                    f"gridded CDS datasets; {dataset!r} is a "
                    f"{ds_cfg.SOURCE_KIND!r} source."
                )
            from era5_etl.regions.membership import validate_regions

            validate_regions(dataset, clip_regions)

        return cls(
            download=DownloadConfig(
                output_dir=netcdf_dir,
                dataset=dataset,
                variables=variables,
                start_date=start_date,
                end_date=end_date,
                area=area if area is not None else [float(x) for x in BRAZIL_BBOX],
                hours=hours if hours is not None else list(HOURS_ALL),
                years=years,
                override=override,
            ),
            transform=TransformConfig(override=override, clip_regions=clip_regions),
            storage=StorageConfig(
                database_dir=base,
                parquet_compression=compression,
            ),
            database=DatabaseConfig(db_path=db_path),
            dataset_name=dataset,
            keep_temp_files=keep_temp_files,
        )

    def get_parquet_dir(self) -> Path:
        """Per-dataset Parquet output directory."""
        return resolve_dataset_dir(self.storage.database_dir, self.dataset_name)

    def get_netcdf_dir(self) -> Path:
        """Temporary NetCDF directory for this dataset (matches ``download.output_dir``)."""
        return self.download.output_dir

    def get_database_path(self) -> Path:
        """DuckDB file path for this dataset."""
        return resolve_duckdb_path(self.storage.database_dir, self.dataset_name)
