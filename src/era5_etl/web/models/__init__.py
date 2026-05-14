"""Pydantic request/response models for the FastAPI app."""

from __future__ import annotations

from typing import Literal

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
    apply_diff: bool = True


class PipelineRunOut(BaseModel):
    run_id: str
    dataset: str
    status: str


class DiffPreviewIn(BaseModel):
    dataset: str
    area: list[float] = Field(min_length=4, max_length=4)
    date_from: str
    date_to: str
    hours: list[int] = Field(default_factory=list)
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


class QueryIn(BaseModel):
    dataset: str
    sql: str
    limit: int = 100


class QueryOut(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool


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
    "VersionOut",
    "CredentialStatusOut",
    "CredentialsIn",
    "CredentialTestOut",
]
