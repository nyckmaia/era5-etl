"""Pydantic request/response models for the FastAPI app."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class DatasetVariableOut(BaseModel):
    api_name: str
    short_name: str
    friendly_name: str
    full_name: str
    description: str
    unit: str
    #: Wizard sections this variable belongs to. Empty for datasets
    #: without a grouped layout (UI then renders a flat list).
    groups: list[str] = Field(default_factory=list)


class VariableGroupOut(BaseModel):
    """A wizard section title; ``order`` matches its position in the YAML."""

    id: str
    label: str
    order: int


class DatasetOut(BaseModel):
    name: str
    cds_dataset_id: str
    grid_resolution_deg: float
    default_variables: list[str]
    variables: list[DatasetVariableOut]
    # Non-CDS/non-grid sources (e.g. INMET stations) report empty
    # ``cds_dataset_id`` and ``grid_resolution_deg == 0``; ``source_kind`` /
    # ``is_gridded`` let the SPA branch (e.g. hide the grid inventory map,
    # show the station map instead). Defaulted for backward compatibility.
    source_kind: str = "cds_grid"
    is_gridded: bool = True
    #: Sections (in display order) for the wizard variable picker. Empty
    #: list = ungrouped (flat) layout.
    variable_groups: list[VariableGroupOut] = Field(default_factory=list)
    #: Whether the dataset has any user-intentionally-downloaded parquet
    #: under ``<base>/climate_data_store_db/<dataset>/``. The bootstrap
    #: grid parquet at ``_grids/<dataset>_grid.parquet`` does NOT count —
    #: this lets the /query SCHEMA panel hide datasets that were only
    #: bootstrapped for INMET joins.
    has_data: bool = False


class InmetYearsOut(BaseModel):
    years: list[int]


InmetYearStatus = Literal["complete", "partial", "stale", "current"]


class InmetYearStatusItem(BaseModel):
    """Completeness summary for a single INMET year in the local database."""

    year: int
    status: InmetYearStatus
    n_stations: int
    n_stations_complete: int
    min_date_max: date | None
    max_date_max: date | None
    downloaded_at: datetime | None


class InmetYearStatusOut(BaseModel):
    items: list[InmetYearStatusItem]
    current_year: int
    #: INMET typically publishes a year's December data ~3 months later.
    expected_publish_lag_days: int = 90


class InmetUpdateYearsIn(BaseModel):
    years: list[int] = Field(..., min_length=1)


class NotebookCellOut(BaseModel):
    id: str
    type: Literal["code", "sql", "markdown"]
    source: str
    outputs: list[dict] = Field(default_factory=list)


class NotebookRunOut(BaseModel):
    id: str
    ts: int
    model_name: str
    params: dict
    metrics: dict
    duration_s: float
    notes: str


class NotebookOut(BaseModel):
    id: str
    name: str
    cells: list[NotebookCellOut]
    runs: list[NotebookRunOut]
    created_ts: int
    updated_ts: int


class NotebookListItemOut(BaseModel):
    id: str
    name: str
    updated_ts: int
    created_ts: int
    n_cells: int


class NotebookCreateIn(BaseModel):
    name: str = "Untitled notebook"
    template_id: str | None = None


class NotebookSaveIn(BaseModel):
    name: str | None = None
    cells: list[NotebookCellOut] | None = None


class NotebookRunCellIn(BaseModel):
    cell_id: str
    code: str
    lang: Literal["python", "sql"] = "python"


class NotebookTemplateOut(BaseModel):
    id: str
    name: str
    description: str


class NotebookRunRecordIn(BaseModel):
    """Body posted by the in-kernel ``log_model_run`` helper."""

    params: dict
    metrics: dict
    duration_s: float
    notes: str = ""
    model_name: str = "xgboost"


class NotebookKernelStatusOut(BaseModel):
    notebook_id: str
    status: Literal["idle", "busy", "dead"]


class StationPointOut(BaseModel):
    """One INMET station for the inventory map."""

    station_id: str
    latitude: float | None
    longitude: float | None
    altitude: float | None
    uf: str | None
    regiao: str | None
    nome: str | None
    year_min: int | None
    year_max: int | None
    n_years: int
    n_vars: int


class StationInventoryOut(BaseModel):
    dataset: str
    n_stations: int
    stations: list[StationPointOut]


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
    query_timeout_s: int = 10


class UserConfigIn(BaseModel):
    data_dir: str | None = None
    default_dataset: str | None = None
    query_timeout_s: int | None = None


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
    max_request_bytes: int = 300 * 1024 * 1024
    max_request_fields: int = Field(
        default=12_000,
        ge=1,
        description=(
            "Maximum CDS 'fields' (variables × hours × days) per request "
            "before auto-splitting kicks in. Independent of "
            "max_request_bytes; the planner splits on whichever ceiling "
            "is tighter for this particular selection."
        ),
    )
    clip_regions: list[str] | None = Field(
        default=None,
        description=(
            "Brazilian UF sigla(s) (e.g. ['SP','RJ']) or ['BR']. Echoed by "
            "/estimate for symmetry with /run; the size estimate itself is "
            "unaffected (clipping is post-download, disk-only)."
        ),
    )


class EstimateChunkOut(BaseModel):
    chunk_id: str
    year: int
    month: int
    days: list[int]
    variables: list[str]
    area: list[float]
    estimated_bytes: int
    estimated_mb: float
    #: CDS "fields" count for this chunk (variables × hours × days),
    #: independent of area/grid resolution. The UI uses this to render
    #: a "Request Size" gauge analogous to the one on the Copernicus
    #: site.
    fields_count: int = 0


class EstimateOut(BaseModel):
    dataset: str
    total_chunks: int
    total_estimated_bytes: int
    total_estimated_mb: float
    chunks: list[EstimateChunkOut]
    # Set for non-grid sources (e.g. INMET): the CDS area×days×vars size
    # estimate does not apply (acquisition is 1 ZIP per year, all stations).
    # ``total_chunks`` then holds the number of yearly ZIPs. Defaulted for
    # backward compatibility with the existing wizard.
    estimate_skipped: bool = False
    skip_reason: str | None = None


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
    years: list[int] | None = Field(
        default=None,
        description=(
            "Non-grid sources (INMET) only: exact yearly ZIPs to fetch "
            "(may be non-contiguous). Ignored by CDS/grid datasets."
        ),
    )
    clip_regions: list[str] | None = Field(
        default=None,
        description=(
            "Brazilian UF sigla(s) (e.g. ['SP','RJ']) or ['BR']. When set, "
            "only grid points whose center falls strictly inside the polygon "
            "are kept; all others are dropped before Parquet write. UF "
            "memberships are mutually exclusive. Gridded datasets only."
        ),
    )
    override: bool = Field(
        default=False,
        description=(
            "Force re-download even when the manifest already lists the "
            "request. Used to refresh INMET years whose ZIP has been "
            "updated upstream."
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
    # Set when the request is too large for a per-cell diff. The download
    # still proceeds via the size-bounded chunk plan; these fields let the
    # UI explain why and show the (arithmetic-only) size estimate so the
    # user can proceed with sequential chunks or narrow the selection.
    diff_skipped: bool = False
    skip_reason: str | None = None
    estimated_download_bytes: int | None = None  # full request total
    estimated_disk_bytes: int | None = None  # full request total
    estimated_chunks: int | None = None
    # What Smart Diff will actually fetch (full request scaled by the
    # missing fraction). Equals the totals above when nothing is cached.
    missing_download_bytes: int | None = None
    missing_disk_bytes: int | None = None


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
    row_count: int  # rows actually returned (== min(total_rows, limit))
    truncated: bool
    total_rows: int  # rows the query would return without the limit
    elapsed_ms: float  # server-side DuckDB execution time in milliseconds


class DatasetDeleteOut(BaseModel):
    """Result of wiping a dataset's on-disk storage."""

    dataset: str
    deleted: bool
    freed_bytes: int


class SchemaColumn(BaseModel):
    name: str
    type: str  # short Python type (str/int/float/bool/datetime/date)


class QuerySchemaOut(BaseModel):
    view: str
    columns: list[SchemaColumn]


# --- User-defined views / macros + visual builder ---------------------


class SourceSel(BaseModel):
    view: str
    alias: str
    columns: list[str]


class JoinPair(BaseModel):
    left: str  # "<alias>.<col>"
    right: str  # "<alias>.<col>"
    approx: bool = False
    epsilon: float = 1e-4


class BuildSpec(BaseModel):
    name: str
    join_type: str = "INNER"  # "INNER" | "LEFT"
    sources: list[SourceSel]
    joins: list[JoinPair] = []


class UserObjectIn(BaseModel):
    name: str
    kind: Literal["view", "macro"]
    sql: str
    #: Optional visual-builder snapshot (sources/columns/joins). When
    #: present, the builder modal re-hydrates from it on edit.
    builder_spec: BuildSpec | None = None


class UserObjectOut(BaseModel):
    id: str
    name: str
    kind: Literal["view", "macro"]
    sql: str
    builder_spec: BuildSpec | None = None
    ok: bool = True
    error: str | None = None
    columns: list[SchemaColumn] = []
    #: System-provided object (defined in code, not user-editable).
    builtin: bool = False


class BuildSqlOut(BaseModel):
    sql: str


# --- Time-series charting (notebook page) -----------------------------


class TSLocationIn(BaseModel):
    """Where to sample a series. Grid views use lat/lon; station views
    use station_id/uf. ``kind`` selects point vs region."""

    kind: Literal["point", "region"]
    # grid point
    lat: float | None = None
    lon: float | None = None
    # grid region (bbox)
    south: float | None = None
    north: float | None = None
    west: float | None = None
    east: float | None = None
    # station point / region
    station_id: str | None = None
    uf: str | None = None
    station_ids: list[str] | None = None


class TSSeriesIn(BaseModel):
    view: str  # era5 | era5_land | inmet | era5_inmet
    y_column: str
    agg: Literal["avg", "min", "max", "sum"] = "avg"
    location: TSLocationIn
    axis: Literal["y", "y2"] = "y"
    name: str | None = None


class TimeseriesIn(BaseModel):
    date_from: str  # YYYY-MM-DD
    date_to: str
    bucket: Literal["raw", "hour", "day", "month"] = "raw"
    max_points: Annotated[int, Field(ge=100, le=200_000)] = 20_000
    series: list[TSSeriesIn] = Field(min_length=1, max_length=12)


class TSSeriesOut(BaseModel):
    name: str
    view: str
    y_column: str
    agg: str
    axis: Literal["y", "y2"]
    x: list[str]  # ISO-8601 UTC timestamps
    y: list[float | None]
    n_points: int
    bucket_used: str
    downsampled: bool
    location_label: str
    error: str | None = None


class TimeseriesOut(BaseModel):
    series: list[TSSeriesOut]
    bucket_requested: str
    truncated: bool  # any series coarsened/downsampled


class TSViewMetaOut(BaseModel):
    view: str
    location_kind: Literal["grid", "station"]
    numeric_columns: list[SchemaColumn]
    date_min: str | None = None
    date_max: str | None = None
    grid_resolution: float | None = None  # for lat/lon snapping; null = station


class TimeseriesMetaOut(BaseModel):
    views: list[TSViewMetaOut]


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
    "CredentialStatusOut",
    "CredentialTestOut",
    "CredentialsIn",
    "DatasetDeleteOut",
    "DatasetOut",
    "DatasetVariableOut",
    "DiffPreviewIn",
    "DiffPreviewOut",
    "DiffPreviewSampleRow",
    "EstimateChunkOut",
    "EstimateIn",
    "EstimateOut",
    "InmetUpdateYearsIn",
    "InmetYearStatusItem",
    "InmetYearStatusOut",
    "InmetYearsOut",
    "NotebookCellOut",
    "NotebookCreateIn",
    "NotebookKernelStatusOut",
    "NotebookListItemOut",
    "NotebookOut",
    "NotebookRunCellIn",
    "NotebookRunOut",
    "NotebookRunRecordIn",
    "NotebookSaveIn",
    "NotebookTemplateOut",
    "PathValidationOut",
    "PipelineRunIn",
    "PipelineRunOut",
    "QueryHistoryAppendIn",
    "QueryHistoryEntry",
    "QueryHistoryPatch",
    "QueryIn",
    "QueryOut",
    "StationInventoryOut",
    "StationPointOut",
    "StorageStatsOut",
    "TSLocationIn",
    "TSSeriesIn",
    "TSSeriesOut",
    "TSViewMetaOut",
    "TemplateItem",
    "TimeseriesIn",
    "TimeseriesMetaOut",
    "TimeseriesOut",
    "UfBboxOut",
    "UserConfigIn",
    "UserConfigOut",
    "VariableGroupOut",
    "VersionOut",
]
