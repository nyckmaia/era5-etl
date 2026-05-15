"""Inventory + coverage endpoints (v0.6.0).

Surfaces the per-dataset :class:`CoverageIndex` to the web UI:

* ``GET /api/inventory/grid-points`` -- list of distinct (lat, lon) cells
  with day/variable counts. Returned as JSON for small payloads, Apache
  Arrow IPC for large ones (configurable via ``format=`` query param).
* ``GET /api/inventory/cell-detail`` -- per-cell drill-down (dates ->
  variables -> hours).
* ``POST /api/inventory/region-summary`` -- polygon summary (cells inside,
  date range, gap analysis).

Empty inventory (no coverage DB yet) is a valid state and returns 200 OK
with an empty body -- the UI uses this to show a "no data yet" prompt
rather than an error.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.coverage import COVERAGE_DB_FILENAME, CoverageIndex
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.web.models import DateRangeOut

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

ARROW_MEDIA_TYPE = "application/vnd.apache.arrow.stream"
JSON_THRESHOLD = 5000  # rows; above this, "auto" returns Arrow.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(s: str | None, field_name: str) -> date_cls | None:
    if s is None or s == "":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: {s!r} (expected YYYY-MM-DD)",
        ) from exc


def _validate_dataset(dataset: str) -> None:
    if dataset not in DatasetRegistry.names():
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")


def _coverage_db_exists(base_dir, dataset: str) -> bool:
    return (resolve_dataset_dir(base_dir, dataset) / COVERAGE_DB_FILENAME).exists()


def _mask_to_hours(mask: int) -> list[int]:
    """Expand a 24-bit hour bitmap into a sorted list of hour integers."""
    return [h for h in range(24) if (int(mask) >> h) & 1]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RegionSummaryRequest(BaseModel):
    dataset: str
    polygon: list[tuple[float, float]] = Field(
        ...,
        min_length=3,
        description="List of (lat, lon) vertices, at least 3.",
    )


# ---------------------------------------------------------------------------
# GET /api/inventory/grid-points
# ---------------------------------------------------------------------------


@router.get("/grid-points")
def grid_points(
    request: Request,
    dataset: str = Query(..., description="Dataset name (era5 or era5-land)"),
    date_from: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: str | None = Query(None, description="ISO date YYYY-MM-DD"),
    variable: list[str] | None = Query(  # noqa: B008 - FastAPI Query default
        None,
        description="CDS variable name(s) to filter on. Repeat for multiple; "
        "omit for all (M07 multi-select).",
    ),
    format: Literal["json", "arrow", "auto"] = Query(  # noqa: A002 - matches public API
        "auto", description="Response format. 'auto' = arrow if rows > 5000."
    ),
):
    """Return distinct ``(lat, lon, days, vars)`` cells in the coverage index."""
    _validate_dataset(dataset)
    base_dir = request.app.state.data_dir
    df_from = _parse_iso_date(date_from, "date_from")
    df_to = _parse_iso_date(date_to, "date_to")

    # Empty-inventory short-circuit -- a valid state.
    if not _coverage_db_exists(base_dir, dataset):
        if format == "arrow":
            return Response(content=b"", media_type=ARROW_MEDIA_TYPE)
        return []

    with CoverageIndex(dataset, base_dir) as cov:
        df = cov.query_grid_points(
            date_from=df_from, date_to=df_to, variable=variable or None
        )

    # The frontend GridPoint contract is {lat, lon, days, vars} for BOTH
    # formats. query_grid_points yields latitude/longitude, so rename
    # here -- otherwise the Arrow path (used for >5000 cells, e.g. a
    # Brazil-wide ERA5 download) ships latitude/longitude and the map's
    # getPosition reads undefined => points render off-world (invisible).
    import polars as pl

    df = df.rename({"latitude": "lat", "longitude": "lon"})
    # days/vars come back as int64. The Arrow IPC path then decodes them
    # as JS BigInt, which blows up the map's getRadius (Math.max on a
    # BigInt throws) and leaves the whole ScatterplotLayer unrendered.
    # int32 round-trips as a plain JS number and also halves the bytes.
    df = df.with_columns(
        pl.col("lat").cast(pl.Float64),
        pl.col("lon").cast(pl.Float64),
        pl.col("days").cast(pl.Int32),
        pl.col("vars").cast(pl.Int32),
    )

    use_arrow = format == "arrow" or (format == "auto" and df.height > JSON_THRESHOLD)
    if use_arrow:
        # Use the Arrow IPC *stream* format (vs file format) so the client
        # can decode it incrementally with ``pyarrow.ipc.open_stream``.
        buf = df.write_ipc_stream(file=None, compression="uncompressed")
        return Response(content=buf.getvalue(), media_type=ARROW_MEDIA_TYPE)

    # JSON path -- short keys to save bytes over the wire.
    return [
        {
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "days": int(row["days"]),
            "vars": int(row["vars"]),
        }
        for row in df.iter_rows(named=True)
    ]


# ---------------------------------------------------------------------------
# GET /api/inventory/cell-detail
# ---------------------------------------------------------------------------


@router.get("/cell-detail")
def cell_detail(
    request: Request,
    dataset: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
):
    """Return the nested ``dates -> variables -> hours`` structure for one cell."""
    _validate_dataset(dataset)
    base_dir = request.app.state.data_dir

    if not _coverage_db_exists(base_dir, dataset):
        return {"latitude": lat, "longitude": lon, "dates": []}

    with CoverageIndex(dataset, base_dir) as cov:
        df = cov.query_cell_detail(lat, lon)

    if df.is_empty():
        return {"latitude": lat, "longitude": lon, "dates": []}

    # Group by date -> list of {name, hours[]}.
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in df.iter_rows(named=True):
        d = row["date"]
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        by_date.setdefault(d_str, []).append(
            {
                "name": str(row["variable"]),
                "hours": _mask_to_hours(row["hours_mask"]),
            }
        )

    dates = [
        {"date": d, "variables": variables}
        for d, variables in sorted(by_date.items())
    ]
    return {"latitude": lat, "longitude": lon, "dates": dates}


# ---------------------------------------------------------------------------
# POST /api/inventory/region-summary
# ---------------------------------------------------------------------------


@router.post("/region-summary")
def region_summary(body: RegionSummaryRequest, request: Request):
    """Summarise coverage inside a polygon (lat/lon vertices)."""
    _validate_dataset(body.dataset)
    base_dir = request.app.state.data_dir

    if not _coverage_db_exists(base_dir, body.dataset):
        return {
            "n_points": 0,
            "date_range": None,
            "vars_per_cell_avg": 0.0,
            "gaps": [],
        }

    polygon_lats = [v[0] for v in body.polygon]
    polygon_lons = [v[1] for v in body.polygon]
    with CoverageIndex(body.dataset, base_dir) as cov:
        result = cov.query_region_summary(polygon_lats, polygon_lons)

    # Convert dates -> ISO strings for JSON serialization.
    if result.get("date_range") is not None:
        result["date_range"] = [
            d.isoformat() if hasattr(d, "isoformat") else str(d)
            for d in result["date_range"]
        ]
    for gap in result.get("gaps", []):
        d = gap.get("date")
        if d is not None and hasattr(d, "isoformat"):
            gap["date"] = d.isoformat()
    return result


# ---------------------------------------------------------------------------
# GET /api/inventory/date-range  (M06 — prefill the inventory date inputs)
# ---------------------------------------------------------------------------


@router.get("/date-range", response_model=DateRangeOut)
def date_range(
    request: Request,
    dataset: str = Query(..., description="Dataset name (era5 or era5-land)"),
) -> DateRangeOut:
    """Min/max date present in the dataset's coverage index.

    Both ``null`` when there's no coverage yet (HTTP 200 — a valid state
    the UI handles by leaving the date inputs empty).
    """
    _validate_dataset(dataset)
    base_dir = request.app.state.data_dir
    if not _coverage_db_exists(base_dir, dataset):
        return DateRangeOut(min=None, max=None)
    with CoverageIndex(dataset, base_dir) as cov:
        lo, hi = cov.query_date_range()
    return DateRangeOut(
        min=lo.isoformat() if lo is not None else None,
        max=hi.isoformat() if hi is not None else None,
    )
