"""StationIndex rebuild + read tests."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import (
    STATION_SCHEMA_VERSION,
    StationIndex,
    ensure_station_index,
    rebuild_from_parquet,
)


def _station_parquet(base, station_id: str, year: int, *, lat, lon, alt, rows):
    """Write a minimal INMET-shaped parquet at station=<id>/<id>_<year>.parquet."""
    pdir = resolve_dataset_dir(base, "inmet") / f"station={station_id}"
    pdir.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        {
            "station_id": [station_id] * rows,
            "latitude": [lat] * rows,
            "longitude": [lon] * rows,
            "altitude": [alt] * rows,
            "uf": ["DF"] * rows,
            "regiao": ["CO"] * rows,
            "nome": ["BRASILIA"] * rows,
            "data_fundacao": ["2000-05-07"] * rows,
            "date": [dt.date(year, 1, 1) + dt.timedelta(days=i) for i in range(rows)],
            "hour_utc": [0] * rows,
            "temp_ar": [20.0 + i for i in range(rows)],
            "vento_velocidade": [None] * rows,  # all-null -> not "present"
        }
    )
    df.write_parquet(pdir / f"{station_id}_{year}.parquet")


def test_rebuild_indexes_stations_and_years(tmp_path):
    _station_parquet(tmp_path, "A001", 2000, lat=-15.78, lon=-47.92, alt=1159.54, rows=3)
    _station_parquet(tmp_path, "A001", 2026, lat=-15.78, lon=-47.92, alt=1160.96, rows=5)
    _station_parquet(tmp_path, "A401", 2000, lat=-13.01, lon=-38.51, alt=51.41, rows=2)

    stats = rebuild_from_parquet("inmet", tmp_path)
    assert stats["n_stations"] == 2
    assert stats["files_processed"] == 3
    assert stats["total_rows"] == 10

    with StationIndex("inmet", tmp_path) as idx:
        stations = idx.query_stations().sort("station_id")
        assert stations["station_id"].to_list() == ["A001", "A401"]
        a001 = stations.filter(pl.col("station_id") == "A001").row(0, named=True)
        assert a001["year_min"] == 2000
        assert a001["year_max"] == 2026
        assert a001["n_years"] == 2
        # Metadata comes from the most-recent year (altitude was re-surveyed).
        assert a001["altitude"] == pytest.approx(1160.96, rel=1e-5)
        # temp_ar has values, vento_velocidade is all-null -> 1 present var.
        assert a001["n_vars"] == 1

        detail = idx.query_station_detail("A001").sort("year")
        assert detail["year"].to_list() == [2000, 2026]
        assert detail["n_rows"].to_list() == [3, 5]
        assert detail.row(0, named=True)["vars"] == ["temp_ar"]


def test_schema_version_persisted(tmp_path):
    _station_parquet(tmp_path, "A001", 2000, lat=-15.0, lon=-47.0, alt=1.0, rows=1)
    rebuild_from_parquet("inmet", tmp_path)
    with StationIndex("inmet", tmp_path) as idx:
        assert idx.schema_version_on_disk() == STATION_SCHEMA_VERSION


def test_ensure_station_index_is_idempotent(tmp_path):
    _station_parquet(tmp_path, "A001", 2000, lat=-15.0, lon=-47.0, alt=1.0, rows=1)
    assert ensure_station_index("inmet", tmp_path) is True
    # Already populated + current schema -> no rebuild.
    assert ensure_station_index("inmet", tmp_path) is False


def test_ensure_station_index_no_files(tmp_path):
    assert ensure_station_index("inmet", tmp_path) is False
