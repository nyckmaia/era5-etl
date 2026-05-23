"""query_year_status + classify_year coverage for the INMET completeness UI."""

from __future__ import annotations

import datetime as dt

import polars as pl

from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.storage.stations import StationIndex, rebuild_from_parquet
from era5_etl.web.routes.inmet import _classify_year


def _station_parquet(
    base,
    station_id: str,
    year: int,
    *,
    last_day: dt.date,
    lat: float = -15.0,
    lon: float = -47.0,
    alt: float = 1.0,
):
    """Write a station parquet that goes from Jan 1 of ``year`` to ``last_day``."""
    pdir = resolve_dataset_dir(base, "inmet") / f"station={station_id}"
    pdir.mkdir(parents=True, exist_ok=True)
    rows = (last_day - dt.date(year, 1, 1)).days + 1
    df = pl.DataFrame(
        {
            "station_id": [station_id] * rows,
            "latitude": [lat] * rows,
            "longitude": [lon] * rows,
            "altitude": [alt] * rows,
            "uf": ["DF"] * rows,
            "regiao": ["CO"] * rows,
            "nome": ["TEST"] * rows,
            "data_fundacao": ["2000-05-07"] * rows,
            "date": [dt.date(year, 1, 1) + dt.timedelta(days=i) for i in range(rows)],
            "hour_utc": [0] * rows,
            "temp_ar": [20.0] * rows,
        }
    )
    df.write_parquet(pdir / f"{station_id}_{year}.parquet")


def test_query_year_status_aggregates_per_year(tmp_path):
    # Year 2023: both stations went to Dec 31 -> "complete" candidate.
    _station_parquet(tmp_path, "A001", 2023, last_day=dt.date(2023, 12, 31))
    _station_parquet(tmp_path, "A002", 2023, last_day=dt.date(2023, 12, 31))
    # Year 2024: one station to Dec 31, one stopped in June -> "partial" candidate.
    _station_parquet(tmp_path, "A001", 2024, last_day=dt.date(2024, 12, 31))
    _station_parquet(tmp_path, "A002", 2024, last_day=dt.date(2024, 6, 30))
    # Year 2025: nobody reached Dec 31 -> "stale" candidate.
    _station_parquet(tmp_path, "A001", 2025, last_day=dt.date(2025, 4, 10))

    rebuild_from_parquet("inmet", tmp_path)
    with StationIndex("inmet", tmp_path) as idx:
        df = idx.query_year_status().sort("year")

    rows = {int(r["year"]): r for r in df.iter_rows(named=True)}
    assert rows[2023]["n_stations"] == 2
    assert rows[2023]["n_stations_complete"] == 2
    assert rows[2023]["min_date_max"] == dt.date(2023, 12, 31)
    assert rows[2023]["max_date_max"] == dt.date(2023, 12, 31)

    assert rows[2024]["n_stations"] == 2
    assert rows[2024]["n_stations_complete"] == 1
    assert rows[2024]["min_date_max"] == dt.date(2024, 6, 30)
    assert rows[2024]["max_date_max"] == dt.date(2024, 12, 31)

    assert rows[2025]["n_stations"] == 1
    assert rows[2025]["n_stations_complete"] == 0


def test_classify_year_complete():
    # All stations reached Dec 31 of a closed year.
    assert _classify_year(2023, n_stations=5, n_complete=5, current_year=2026) == "complete"


def test_classify_year_partial():
    assert _classify_year(2024, n_stations=5, n_complete=3, current_year=2026) == "partial"


def test_classify_year_stale_no_one_reached_dec():
    assert _classify_year(2025, n_stations=4, n_complete=0, current_year=2026) == "stale"


def test_classify_year_current_always_current():
    # Even if every station happens to have data up to Dec 31, the calendar
    # year is in progress until the year actually ends.
    assert _classify_year(2026, n_stations=5, n_complete=5, current_year=2026) == "current"
    assert _classify_year(2026, n_stations=5, n_complete=0, current_year=2026) == "current"


def test_classify_year_stale_when_no_stations_at_all():
    # Safety net: if the row got into station_coverage with 0 station rows
    # (shouldn't happen in practice), don't crash and don't claim complete.
    assert _classify_year(2023, n_stations=0, n_complete=0, current_year=2026) == "stale"
