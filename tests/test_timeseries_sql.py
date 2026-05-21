"""Unit tests for the pure time-series SQL builder (no HTTP)."""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from era5_etl.web.timeseries_sql import (
    BUCKET_ORDER,
    bucket_expr,
    build_series_sql,
    location_where,
    run_series_with_cap,
    ts_expr,
    view_kind,
)


def test_view_kind():
    assert view_kind("era5") == "grid"
    assert view_kind("era5_land") == "grid"
    assert view_kind("inmet") == "station"
    assert view_kind("era5_inmet") == "station"


def test_ts_and_bucket_expr():
    ts = ts_expr()
    assert "CAST(\"date\" AS TIMESTAMP)" in ts
    assert "INTERVAL 1 HOUR" in ts
    assert bucket_expr(ts, "raw") == ts
    assert bucket_expr(ts, "day") == f"date_trunc('day', {ts})"
    with pytest.raises(ValueError):
        bucket_expr(ts, "bogus")


def test_location_where_grid_point_and_region():
    sql, params = location_where("era5", {"kind": "point", "lat": -15.5, "lon": -47.9})
    assert 'abs("latitude" - ?)' in sql and 'abs("longitude" - ?)' in sql
    assert params[0] == -15.5 and params[2] == -47.9

    sql, params = location_where(
        "era5", {"kind": "region", "south": -20, "north": -10, "west": -50, "east": -40}
    )
    assert '"latitude" BETWEEN ? AND ?' in sql
    assert params == [-20.0, -10.0, -50.0, -40.0]


def test_location_where_station():
    sql, params = location_where("inmet", {"kind": "point", "station_id": "A001"})
    assert sql == '"station_id" = ?' and params == ["A001"]

    sql, params = location_where("inmet", {"kind": "region", "uf": "DF"})
    assert sql == '"uf" = ?' and params == ["DF"]

    sql, params = location_where(
        "inmet", {"kind": "region", "station_ids": ["A001", "A002"]}
    )
    assert sql == '"station_id" IN (?, ?)' and params == ["A001", "A002"]


def test_location_where_kind_mismatch_raises():
    with pytest.raises(ValueError):
        location_where("era5", {"kind": "point", "station_id": "A001"})
    with pytest.raises(ValueError):
        location_where("inmet", {"kind": "point", "lat": 1.0, "lon": 2.0})
    with pytest.raises(ValueError):
        location_where("era5", {"kind": "point", "lat": 1.0})  # missing lon


def test_build_series_sql_shape_and_agg_validation():
    sql = build_series_sql("era5", "temp", "avg", '"station_id" = ?', "day")
    assert sql.startswith("SELECT date_trunc('day'")
    assert 'avg("temp") AS y' in sql
    assert 'FROM "era5"' in sql
    assert '"date" BETWEEN ? AND ?' in sql
    with pytest.raises(ValueError):
        build_series_sql("era5", "temp", "median", "1=1", "raw")


def _seed(conn):
    conn.execute(
        'CREATE TABLE "era5" (latitude DOUBLE, longitude DOUBLE, '
        '"date" DATE, hour_utc TINYINT, temp DOUBLE)'
    )
    rows = []
    base = dt.date(2024, 1, 1)
    for d in range(10):  # 10 days
        for h in range(24):  # hourly
            day = base + dt.timedelta(days=d)
            # point A (-15,-47) and a second point so region != point
            rows.append((-15.0, -47.0, day, h, 20.0 + h + d))
            rows.append((-16.0, -48.0, day, h, 30.0 + h + d))
    conn.executemany(
        'INSERT INTO "era5" VALUES (?, ?, ?, ?, ?)', rows
    )


def test_run_series_point_raw():
    conn = duckdb.connect(":memory:")
    _seed(conn)
    where, params = location_where("era5", {"kind": "point", "lat": -15.0, "lon": -47.0})
    res = run_series_with_cap(
        conn, "era5", "temp", "avg", where,
        [*params, dt.date(2024, 1, 1), dt.date(2024, 1, 10)],
        "raw", max_points=10_000,
    )
    assert res.error is None
    assert res.bucket_used == "raw"
    assert res.n_points == 240  # 10 days * 24 h
    assert res.x[0].startswith("2024-01-01T00:00:00")
    assert res.y[0] == pytest.approx(20.0)


def test_run_series_region_mean():
    conn = duckdb.connect(":memory:")
    _seed(conn)
    where, params = location_where(
        "era5", {"kind": "region", "south": -20, "north": -10, "west": -50, "east": -40}
    )
    res = run_series_with_cap(
        conn, "era5", "temp", "avg", where,
        [*params, dt.date(2024, 1, 1), dt.date(2024, 1, 1)],
        "raw", max_points=10_000,
    )
    # day 0, hour 0: mean(20, 30) = 25
    assert res.y[0] == pytest.approx(25.0)


def test_run_series_coarsens_when_over_cap():
    conn = duckdb.connect(":memory:")
    _seed(conn)
    where, params = location_where("era5", {"kind": "point", "lat": -15.0, "lon": -47.0})
    res = run_series_with_cap(
        conn, "era5", "temp", "avg", where,
        [*params, dt.date(2024, 1, 1), dt.date(2024, 1, 10)],
        "raw", max_points=15,  # 240 raw > 15 -> coarsen
    )
    assert res.error is None
    assert res.downsampled is True
    # raw(240) -> hour(240) -> day(10) <= 15
    assert res.bucket_used == "day"
    assert res.n_points == 10


def test_bucket_order_constant():
    assert BUCKET_ORDER == ["raw", "hour", "day", "month"]
