"""SQL builder + capped runner for the time-series charting page.

Pure module (no FastAPI): builds *parametrised, SELECT-only* SQL that
turns the separate ``date`` (DATE) + ``hour_utc`` (Int8) columns into one
synthetic UTC timestamp, filters by a point/region location and a date
range, aggregates one value per (bucketed) timestamp, and bounds the
number of points returned (coarsen the time bucket, then stride-downsample
as a last resort).

User-supplied *values* always flow through DuckDB ``?`` parameters; only
allowlisted identifiers (view name verified against the registered set,
``y_column`` verified against the view's introspected schema, a fixed
``agg`` token, an int stride we compute) are ever interpolated. The final
string is additionally passed through ``query._validate_sql`` by the route
as defence-in-depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Gridded reanalysis views filter by lat/lon; station views by station_id.
_GRID_VIEWS = {"era5", "era5_land"}
_STATION_VIEWS = {"inmet", "era5_inmet"}

_AGGS = {"avg", "min", "max", "sum"}
#: Coarsening order: a raw request that exceeds the point cap steps down
#: this list (raw -> hour -> day -> month) before any stride downsample.
BUCKET_ORDER = ["raw", "hour", "day", "month"]
_TRUNC = {"hour": "hour", "day": "day", "month": "month"}

#: Float32 grid coords are not exactly equal to a typed literal; match with
#: the same epsilon the era5_inmet join uses (storage/comparison._EPS).
_EPS = 1e-4


def view_kind(view: str) -> str:
    """``"grid"`` for era5/era5_land, ``"station"`` for inmet/era5_inmet."""
    if view in _STATION_VIEWS:
        return "station"
    if view in _GRID_VIEWS:
        return "grid"
    # Unknown view: default to grid (caller validates the view exists).
    return "grid"


def ts_expr(col_date: str = "date", col_hour: str = "hour_utc") -> str:
    """SQL for the synthetic UTC timestamp from the date + hour columns."""
    return (
        f'(CAST("{col_date}" AS TIMESTAMP) '
        f'+ (CAST("{col_hour}" AS INTEGER) * INTERVAL 1 HOUR))'
    )


def bucket_expr(ts: str, bucket: str) -> str:
    """``raw`` keeps the full timestamp; else ``date_trunc`` to the bucket."""
    if bucket == "raw":
        return ts
    if bucket not in _TRUNC:
        raise ValueError(f"invalid bucket: {bucket!r}")
    return f"date_trunc('{_TRUNC[bucket]}', {ts})"


def location_where(view: str, loc: dict[str, Any]) -> tuple[str, list[Any]]:
    """Build the parametrised location filter for one series.

    ``loc`` is the validated ``TSLocationIn`` as a dict. Returns
    ``(sql_fragment, params)``. Raises ``ValueError`` if the location does
    not match the view kind (e.g. a lat/lon point on a station view).
    """
    kind = loc.get("kind")
    vk = view_kind(view)

    if vk == "grid":
        if kind == "point":
            lat, lon = loc.get("lat"), loc.get("lon")
            if lat is None or lon is None:
                raise ValueError("grid point requires lat and lon")
            return (
                '(abs("latitude" - ?) < ? AND abs("longitude" - ?) < ?)',
                [float(lat), _EPS, float(lon), _EPS],
            )
        if kind == "region":
            s, n = loc.get("south"), loc.get("north")
            w, e = loc.get("west"), loc.get("east")
            if None in (s, n, w, e):
                raise ValueError("grid region requires south/north/west/east")
            return (
                '("latitude" BETWEEN ? AND ? AND "longitude" BETWEEN ? AND ?)',
                [float(s), float(n), float(w), float(e)],
            )
        raise ValueError(f"invalid location kind for grid view: {kind!r}")

    # station kind (inmet / era5_inmet)
    if kind == "point":
        sid = loc.get("station_id")
        if not sid:
            raise ValueError("station point requires station_id")
        return ('"station_id" = ?', [str(sid)])
    if kind == "region":
        uf = loc.get("uf")
        sids = loc.get("station_ids")
        if uf:
            return ('"uf" = ?', [str(uf)])
        if sids:
            ph = ", ".join("?" for _ in sids)
            return (f'"station_id" IN ({ph})', [str(x) for x in sids])
        raise ValueError("station region requires uf or station_ids")
    raise ValueError(f"invalid location kind for station view: {kind!r}")


def build_series_sql(view: str, y_col: str, agg: str, where_sql: str, bucket: str) -> str:
    """One series query. Param order downstream: location params, then
    ``date_from``, ``date_to`` (the two date-range placeholders here)."""
    if agg not in _AGGS:
        raise ValueError(f"invalid agg: {agg!r}")
    ts = ts_expr()
    b = bucket_expr(ts, bucket)
    # view + y_col are allowlisted/schema-checked by the caller; quoting
    # guards identifiers. Values are bound via ? only.
    return (
        f'SELECT {b} AS ts, {agg}("{y_col}") AS y '
        f'FROM "{view}" '
        f'WHERE {where_sql} AND "date" BETWEEN ? AND ? '
        f"GROUP BY 1 ORDER BY 1"
    )


@dataclass
class SeriesResult:
    x: list[str] = field(default_factory=list)  # ISO-8601 UTC timestamps
    y: list[float | None] = field(default_factory=list)
    n_points: int = 0
    bucket_used: str = "raw"
    downsampled: bool = False
    error: str | None = None


def _count_points(conn: Any, series_sql: str, params: list[Any]) -> int:
    row = conn.execute(
        f"SELECT count(*) FROM ({series_sql})", params
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def run_series_with_cap(
    conn: Any,
    view: str,
    y_col: str,
    agg: str,
    where_sql: str,
    params: list[Any],
    bucket_requested: str,
    max_points: int,
    validate_sql: Any = None,
) -> SeriesResult:
    """Run a series, coarsening the bucket then stride-downsampling so the
    result never exceeds ``max_points``. Per-series DuckDB errors are
    captured into ``SeriesResult.error`` (never raised) so one bad series
    does not break the whole chart."""
    try:
        start = (
            BUCKET_ORDER.index(bucket_requested)
            if bucket_requested in BUCKET_ORDER
            else 0
        )
        chosen = bucket_requested
        n = 0
        for i in range(start, len(BUCKET_ORDER)):
            chosen = BUCKET_ORDER[i]
            sql = build_series_sql(view, y_col, agg, where_sql, chosen)
            if validate_sql is not None:
                validate_sql(sql)
            n = _count_points(conn, sql, params)
            if n <= max_points:
                rows = conn.execute(sql, params).fetchall()
                return SeriesResult(
                    x=[_iso(r[0]) for r in rows],
                    y=[None if r[1] is None else float(r[1]) for r in rows],
                    n_points=len(rows),
                    bucket_used=chosen,
                    downsampled=chosen != bucket_requested,
                )

        # Already at the coarsest bucket and still too big: stride sample.
        sql = build_series_sql(view, y_col, agg, where_sql, "month")
        if validate_sql is not None:
            validate_sql(sql)
        stride = max(2, -(-n // max_points))  # ceil(n / max_points)
        strided = (
            f"SELECT ts, y FROM ("
            f"SELECT ts, y, row_number() OVER (ORDER BY ts) - 1 AS rn "
            f"FROM ({sql})) WHERE rn % {int(stride)} = 0 ORDER BY ts"
        )
        rows = conn.execute(strided, params).fetchall()
        return SeriesResult(
            x=[_iso(r[0]) for r in rows],
            y=[None if r[1] is None else float(r[1]) for r in rows],
            n_points=len(rows),
            bucket_used="month",
            downsampled=True,
        )
    except Exception as exc:  # noqa: BLE001 -- surface per-series, never 500
        return SeriesResult(error=str(exc))


def _iso(value: Any) -> str:
    """Timestamp -> ISO-8601 string (UTC, no tz conversion)."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


__all__ = [
    "BUCKET_ORDER",
    "SeriesResult",
    "build_series_sql",
    "bucket_expr",
    "location_where",
    "run_series_with_cap",
    "ts_expr",
    "view_kind",
]
