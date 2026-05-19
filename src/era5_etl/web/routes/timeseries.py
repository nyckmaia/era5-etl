"""Time-series charting endpoints.

``GET  /api/timeseries/meta`` drives the page's selectors (per available
view: numeric columns, location kind, date range, grid resolution).
``POST /api/timeseries`` runs one capped, SELECT-only query per series
(combining the separate ``date`` + ``hour_utc`` columns into one UTC
timestamp) and returns compact x/y arrays — different views in one chart
keep their own x (Plotly overlays heterogeneous x natively).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.datasets import DatasetRegistry
from era5_etl.storage.comparison import ERA5_INMET_VIEW, create_era5_inmet_view
from era5_etl.storage.coverage import COVERAGE_DB_FILENAME, CoverageIndex
from era5_etl.storage.paths import STATION_INDEX_FILENAME, resolve_dataset_dir
from era5_etl.storage.stations import StationIndex
from era5_etl.transform.inmet_to_parquet import NEIGHBOUR_COL_NAMES
from era5_etl.web._types import arrow_type_to_python
from era5_etl.web.models import (
    SchemaColumn,
    TimeseriesIn,
    TimeseriesMetaOut,
    TimeseriesOut,
    TSSeriesOut,
    TSViewMetaOut,
)
from era5_etl.web.routes.query import _validate_sql, register_all_views
from era5_etl.web.timeseries_sql import (
    location_where,
    run_series_with_cap,
    view_kind,
)

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])

# Columns that are never selectable as a Y variable (coords / time keys /
# the inmet grid-neighbour + distance bookkeeping columns).
_NON_VARIABLE_COLS = frozenset(
    {"latitude", "longitude", "altitude", "hour_utc"}
) | set(NEIGHBOUR_COL_NAMES)

# view name -> registered DatasetConfig name (era5_land view <-> era5-land).
_VIEW_DATASET = {"era5": "era5", "era5_land": "era5-land", "inmet": "inmet"}


def _register_timeseries_views(conn, data_dir: Path) -> set[str]:
    """Register era5/era5_land/inmet, plus era5_inmet when buildable."""
    names = set(register_all_views(conn, data_dir))
    try:
        create_era5_inmet_view(conn, data_dir)
        names.add(ERA5_INMET_VIEW)
    except Exception:  # noqa: BLE001 -- no inmet / not buildable -> skip view
        pass
    return names


def _view_columns(conn, view: str) -> list[tuple[str, str]]:
    """(name, python_type) for every column of a registered view."""
    schema = conn.execute(
        f'SELECT * FROM "{view}" LIMIT 0'  # noqa: S608 -- view is allowlisted
    ).fetch_arrow_table().schema
    return [
        (schema.field(i).name, arrow_type_to_python(schema.field(i).type))
        for i in range(len(schema))
    ]


def _date_range(data_dir: Path, view: str) -> tuple[str | None, str | None]:
    """Min/max ISO date for a view (coverage index for grids, station
    index for inmet/era5_inmet). ``(None, None)`` if unavailable."""
    if view in ("era5", "era5_land"):
        ds = _VIEW_DATASET[view]
        if not (resolve_dataset_dir(data_dir, ds) / COVERAGE_DB_FILENAME).exists():
            return (None, None)
        try:
            with CoverageIndex(ds, data_dir) as cov:
                lo, hi = cov.query_date_range()
            return (
                lo.isoformat() if lo else None,
                hi.isoformat() if hi else None,
            )
        except Exception:  # noqa: BLE001
            return (None, None)
    # inmet / era5_inmet -> inmet station index
    if not (resolve_dataset_dir(data_dir, "inmet") / STATION_INDEX_FILENAME).exists():
        return (None, None)
    try:
        with StationIndex("inmet", data_dir) as idx:
            df = idx.query_stations()
        if df.is_empty():
            return (None, None)
        lo = df.get_column("date_min").drop_nulls().min()
        hi = df.get_column("date_max").drop_nulls().max()
        return (
            lo.isoformat() if lo is not None else None,
            hi.isoformat() if hi is not None else None,
        )
    except Exception:  # noqa: BLE001
        return (None, None)


@router.get("/meta", response_model=TimeseriesMetaOut)
def meta(request: Request) -> TimeseriesMetaOut:
    """Per available view: numeric Y columns, location kind, date range,
    grid resolution. Empty (HTTP 200) before any data is downloaded."""
    import duckdb

    data_dir: Path = request.app.state.data_dir
    conn = duckdb.connect(":memory:")
    out: list[TSViewMetaOut] = []
    try:
        registered = _register_timeseries_views(conn, data_dir)
        for view in sorted(registered):
            cols = _view_columns(conn, view)
            numeric = [
                SchemaColumn(name=n, type=t)
                for (n, t) in cols
                if t in ("int", "float") and n not in _NON_VARIABLE_COLS
            ]
            kind = view_kind(view)
            lo, hi = _date_range(data_dir, view)
            grid_res: float | None = None
            if view in _VIEW_DATASET and kind == "grid":
                try:
                    grid_res = float(
                        DatasetRegistry.get(_VIEW_DATASET[view]).GRID_RESOLUTION_DEG
                    )
                except Exception:  # noqa: BLE001
                    grid_res = None
            out.append(
                TSViewMetaOut(
                    view=view,
                    location_kind=kind,
                    numeric_columns=numeric,
                    date_min=lo,
                    date_max=hi,
                    grid_resolution=grid_res,
                )
            )
    finally:
        conn.close()
    return TimeseriesMetaOut(views=out)


def _location_label(loc) -> str:
    if loc.kind == "point":
        if loc.station_id:
            return f"estação {loc.station_id}"
        if loc.lat is not None and loc.lon is not None:
            return f"lat {loc.lat}, lon {loc.lon}"
        return "ponto"
    if loc.uf:
        return f"UF={loc.uf}"
    if loc.station_ids:
        return f"{len(loc.station_ids)} estação(ões)"
    return "região"


@router.post("", response_model=TimeseriesOut)
def run(body: TimeseriesIn, request: Request) -> TimeseriesOut:
    import duckdb

    try:
        d_from = dt.date.fromisoformat(body.date_from)
        d_to = dt.date.fromisoformat(body.date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid date: {exc}"
        ) from exc

    data_dir: Path = request.app.state.data_dir
    conn = duckdb.connect(":memory:")
    series_out: list[TSSeriesOut] = []
    truncated = False
    try:
        registered = _register_timeseries_views(conn, data_dir)
        col_cache: dict[str, set[str]] = {}
        for s in body.series:
            label = _location_label(s.location)
            name = s.name or f"{s.view}.{s.y_column} ({label})"
            base = TSSeriesOut(
                name=name, view=s.view, y_column=s.y_column, agg=s.agg,
                axis=s.axis, x=[], y=[], n_points=0,
                bucket_used=body.bucket, downsampled=False,
                location_label=label,
            )
            if s.view not in registered:
                base.error = f"view '{s.view}' indisponível (sem dados)"
                series_out.append(base)
                continue
            if s.view not in col_cache:
                col_cache[s.view] = {n for (n, _) in _view_columns(conn, s.view)}
            if s.y_column not in col_cache[s.view]:
                base.error = f"coluna '{s.y_column}' não existe em {s.view}"
                series_out.append(base)
                continue
            try:
                where_sql, loc_params = location_where(
                    s.view, s.location.model_dump()
                )
            except ValueError as exc:
                base.error = str(exc)
                series_out.append(base)
                continue

            res = run_series_with_cap(
                conn,
                s.view,
                s.y_column,
                s.agg,
                where_sql,
                [*loc_params, d_from, d_to],
                body.bucket,
                body.max_points,
                validate_sql=_validate_sql,
            )
            base.x = res.x
            base.y = res.y
            base.n_points = res.n_points
            base.bucket_used = res.bucket_used
            base.downsampled = res.downsampled
            base.error = res.error
            truncated = truncated or res.downsampled
            series_out.append(base)
    finally:
        conn.close()

    return TimeseriesOut(
        series=series_out,
        bucket_requested=body.bucket,
        truncated=truncated,
    )
