"""era5_inmet cross-dataset comparison view."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import polars as pl
import pytest

from era5_etl.config import PipelineConfig, StorageConfig, TransformConfig
from era5_etl.storage.comparison import build_era5_inmet_sql, create_era5_inmet_view
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.transform.inmet_to_parquet import InmetToParquetConverter

# A001 Brasília. ERA5 0.25° cell: lat [-16.00,-15.75], lon [-48.00,-47.75].
_CSV = (
    "REGIAO:;CO\nUF:;DF\nESTACAO:;BRASILIA\nCODIGO (WMO):;A001\n"
    "LATITUDE:;-15,78944444\nLONGITUDE:;-47,92583332\nALTITUDE:;1159,54\n"
    "DATA DE FUNDACAO:;07/05/00\n"
    "Data;Hora UTC;A;B;C;D;E;TEMP;G;H;I;J;K;L;M;N;O;P;Q;\n"
    "2000-10-05;14:00;0;;;;;27,2;;;;;;;;;;;;\n"
)


def _make_inmet(base: Path) -> Path:
    conv = InmetToParquetConverter(
        TransformConfig(),
        StorageConfig(database_dir=base),
        resolve_dataset_dir(base, "inmet"),
        "inmet",
    )
    src = base / "raw"
    src.mkdir(parents=True, exist_ok=True)
    csv = src / "INMET_CO_DF_A001_BRASILIA_07-05-2000_A_31-12-2000.CSV"
    csv.write_bytes(_CSV.encode("latin-1"))
    return conv.convert_file(csv)


def _write_grid(base: Path, dataset: str, corners: list[tuple[float, float, float]]):
    """Write a grid parquet (date=2000-10-05 hive partition, hour 14)."""
    pdir = resolve_dataset_dir(base, dataset) / "date=2000-10-05"
    pdir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "latitude": pl.Series([c[0] for c in corners], dtype=pl.Float32),
            "longitude": pl.Series([c[1] for c in corners], dtype=pl.Float32),
            "hour_utc": pl.Series([14] * len(corners), dtype=pl.Int8),
            "temperature_2m": pl.Series(
                [c[2] for c in corners], dtype=pl.Float32
            ),
        }
    ).write_parquet(pdir / f"{dataset}_2000-10-05_part-001.parquet")


def test_era5_inmet_requires_inmet(tmp_path):
    conn = duckdb.connect(":memory:")
    with pytest.raises(ValueError, match="INMET"):
        build_era5_inmet_sql(conn, tmp_path)


def test_era5_inmet_joins_four_corners(tmp_path):
    _make_inmet(tmp_path)
    # ERA5 four corners with distinct temperatures.
    _write_grid(
        tmp_path,
        "era5",
        [
            (-15.75, -48.00, 10.0),  # top-left
            (-15.75, -47.75, 11.0),  # top-right
            (-16.00, -48.00, 12.0),  # bottom-left
            (-16.00, -47.75, 13.0),  # bottom-right
        ],
    )
    # ERA5-LAND 0.1° cell: lat [-15.8,-15.7], lon [-48.0,-47.9].
    _write_grid(
        tmp_path,
        "era5-land",
        [
            (-15.7, -48.0, 20.0),
            (-15.7, -47.9, 21.0),
            (-15.8, -48.0, 22.0),
            (-15.8, -47.9, 23.0),
        ],
    )

    conn = duckdb.connect(":memory:")
    grids = create_era5_inmet_view(conn, tmp_path)
    assert set(grids) == {"era5", "era5-land"}

    row = conn.execute(
        "SELECT * FROM era5_inmet WHERE station_id = 'A001' "
        "AND date = DATE '2000-10-05' AND hour_utc = 14"
    ).pl()
    assert row.height == 1
    r = row.row(0, named=True)

    # INMET value preserved.
    assert r["temp_ar"] == pytest.approx(27.2, rel=1e-4)
    # The four ERA5 corners landed in the right prefixed columns.
    assert r["era5_tl_temperature_2m"] == pytest.approx(10.0)
    assert r["era5_tr_temperature_2m"] == pytest.approx(11.0)
    assert r["era5_bl_temperature_2m"] == pytest.approx(12.0)
    assert r["era5_br_temperature_2m"] == pytest.approx(13.0)
    # ERA5-LAND corners too.
    assert r["era5_land_tl_temperature_2m"] == pytest.approx(20.0)
    assert r["era5_land_br_temperature_2m"] == pytest.approx(23.0)
    # Distances came along for IDW weighting.
    assert r["dist_era5_top_left"] > 0
    assert r["dist_era5_land_bottom_right"] > 0


def test_era5_inmet_without_grids_is_inmet_only(tmp_path):
    _make_inmet(tmp_path)
    conn = duckdb.connect(":memory:")
    grids = create_era5_inmet_view(conn, tmp_path)
    assert grids == []
    cols = [r[0] for r in conn.execute("DESCRIBE era5_inmet").fetchall()]
    assert "temp_ar" in cols
    assert not any(c.startswith("era5_tl_") for c in cols)
    n = conn.execute("SELECT count(*) FROM era5_inmet").fetchone()[0]
    assert n == 1
