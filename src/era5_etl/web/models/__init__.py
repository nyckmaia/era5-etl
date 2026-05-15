"""Pydantic request/response models for the FastAPI app."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class DatasetVariableOut(BaseModel):
    api_name: str
    short_name: str
    friendly_name: str
    full_name: str
    description: str
    unit: str


class DatasetOut(BaseModel):
    name: str
    cds_dataset_id: str
    grid_resolution_deg: float
    default_variables: list[str]
    variables: list[DatasetVariableOut]


class StorageStatsOut(BaseModel):
    dataset: str
    parquet_files: int
    total_size_bytes: int
    partitions: list[str]
    manifest_chunks: int
    parquet_dir: str


class PathValidationOut(BaseModel):
    path: str
    exists: bool
    is_dir: bool
    is_writable: bool
    is_empty: bool | None = None


class UserConfigOut(BaseModel):
    data_dir: str
    default_dataset: str


class UserConfigIn(BaseModel):
    data_dir: str | None = None
    default_dataset: str | None = None


class ColumnPrecision(BaseModel):
    decimals: Annotated[int, Field(ge=0, le=12)]
    method: Literal["round", "truncate"] = "round"


class DatasetPrecisionIn(BaseModel):
    dataset: str
    default_decimals: Annotated[int, Field(ge=0, le=12)] = 4
    default_method: Literal["round", "truncate"] = "round"
    columns: dict[str, ColumnPrecision] = Field(default_factory=dict)


class DatasetPrecisionOut(BaseModel):
    dataset: str
    default_decimals: int
    default_method: Literal["round", "truncate"]
    columns: dict[str, ColumnPrecision]


class EstimateIn(BaseModel):
    dataset: str
    variables: list[str]
    start_date: str
    end_date: str | None = None
    area: list[float] = Field(min_length=4, max_length=4)
    hours: list[str]
    max_request_bytes: int = 500 * 1024 * 1024


class EstimateChunkOut(BaseModel):
    chunk_id: str
    year: int
    month: int
    days: list[int]
    variables: list[str]
    area: list[float]
    estimated_bytes: int
    estimated_mb: float


class EstimateOut(BaseModel):
    dataset: str
    total_chunks: int
    total_estimated_bytes: int
    total_estimated_mb: float
    chunks: list[EstimateChunkOut]


class PipelineRunIn(BaseModel):
    dataset: str
    variables: list[str]
    start_date: str
    end_date: str | None = None
    area: list[float] = Field(min_length=4, max_length=4)
    hours: list[str]
    apply_diff: bool = Field(
        default=True,
        description=(
            "Skip already-covered cells via the coverage index (smart diff, v0.6.0+). "
            "Set False to plan the full request without subtraction."
        ),
    )


class PipelineRunOut(BaseModel):
    run_id: str
    dataset: str
    status: str


class DiffPreviewIn(BaseModel):
    dataset: str
    area: list[float] = Field(min_length=4, max_length=4)
    date_from: str
    date_to: str
    hours: list[Annotated[int, Field(ge=0, le=23)]] = Field(default_factory=list)
    variables: list[str]


class DiffPreviewSampleRow(BaseModel):
    lat: float
    lon: float
    date: str
    variable: str
    missing_mask: int


class DiffPreviewOut(BaseModel):
    requested_cells: int
    missing_cells: int
    savings_pct: float
    sample_missing: list[DiffPreviewSampleRow]


class DateRangeOut(BaseModel):
    # M06: drives the inventory date-input prefill. Both null = no coverage.
    min: str | None = None
    max: str | None = None


class QueryIn(BaseModel):
    # Optional (M02a): every dataset view is registered, so the SQL itself
    # picks the view (`FROM era5_land` / `FROM era5`, or a JOIN). Kept only
    # as a hint for schema/autocomplete context.
    dataset: str | None = None
    sql: str
    limit: int = 100


class QueryOut(BaseModel):
    columns: list[str]
    column_types: list[str]  # short Python type per column (str/int/float/...)
    rows: list[list]
    row_count: int
    truncated: bool


class SchemaColumn(BaseModel):
    name: str
    type: str  # short Python type (str/int/float/bool/datetime/date)


class QuerySchemaOut(BaseModel):
    view: str
    columns: list[SchemaColumn]


class QueryHistoryEntry(BaseModel):
    id: str
    sql: str
    ts: int  # epoch ms
    rows: int
    elapsed_ms: int
    name: str | None = None
    favorite: bool = False


class QueryHistoryAppendIn(BaseModel):
    sql: str
    rows: int = 0
    elapsed_ms: int = 0


class QueryHistoryPatch(BaseModel):
    name: str | None = None
    favorite: bool | None = None


class TemplateItem(BaseModel):
    id: str
    name: str
    sql: str
    category: str | None = None


class UfBboxOut(BaseModel):
    """A Brazilian state (UF) and its bounding box [N, W, S, E]."""

    uf: str
    north: float
    west: float
    south: float
    east: float


class VersionOut(BaseModel):
    version: str


class CredentialStatusOut(BaseModel):
    """Status of the CDS API credentials known to the running app.

    ``key`` is **never** returned. ``url`` is safe to surface so the UI can
    confirm which Copernicus endpoint is configured.
    """

    has_credentials: bool
    source: Literal["env", "file", "none"]
    url: str | None = None
    file_path: str


class CredentialsIn(BaseModel):
    url: str = Field(min_length=10)
    key: str = Field(min_length=8)


class CredentialTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    status_code: int | None = None


__all__ = [
    "DatasetVariableOut",
    "DatasetOut",
    "StorageStatsOut",
    "PathValidationOut",
    "UserConfigOut",
    "UserConfigIn",
    "EstimateIn",
    "EstimateChunkOut",
    "EstimateOut",
    "PipelineRunIn",
    "PipelineRunOut",
    "DiffPreviewIn",
    "DiffPreviewSampleRow",
    "DiffPreviewOut",
    "QueryIn",
    "QueryOut",
    "QueryHistoryEntry",
    "QueryHistoryAppendIn",
    "QueryHistoryPatch",
    "TemplateItem",
    "UfBboxOut",
    "VersionOut",
    "CredentialStatusOut",
    "CredentialsIn",
    "CredentialTestOut",
]
