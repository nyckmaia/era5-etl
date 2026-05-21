"""INMET CSV -> Parquet converter tests.

Exercises the two real-world format eras (2000 and 2026) with tiny embedded
fixtures written in latin-1, asserting the canonical schema is identical
across formats and that the year-varying formatting is normalised.
"""

from __future__ import annotations

import polars as pl
import pytest

from era5_etl.config import StorageConfig, TransformConfig
from era5_etl.exceptions import ProcessingError
from era5_etl.transform.inmet_to_parquet import InmetToParquetConverter

# 17 measurement values, in CSV column order (matches variables.yaml).
# precipitacao_total, pressao_estacao, pressao_max, pressao_min,
# radiacao_global, temp_ar, temp_orvalho, temp_max, temp_min,
# temp_orvalho_max, temp_orvalho_min, umidade_rel_max, umidade_rel_min,
# umidade_relativa, vento_direcao, vento_rajada_max, vento_velocidade

_CSV_2000 = (
    "REGIÃO:;CO\n"
    "UF:;DF\n"
    "ESTAÇÃO:;BRASILIA\n"
    "CODIGO (WMO):;A001\n"
    "LATITUDE:;-15,78944444\n"
    "LONGITUDE:;-47,92583332\n"
    "ALTITUDE:;1159,54\n"
    "DATA DE FUNDAÇÃO (YYYY-MM-DD):;2000-05-07\n"
    "DATA (YYYY-MM-DD);HORA (UTC);PRECIPITAÇÃO TOTAL, HORÁRIO (mm);"
    "PRESSAO;PRESSAO MAX;PRESSAO MIN;RADIACAO GLOBAL (KJ/m²);"
    "TEMPERATURA;ORVALHO;TMAX;TMIN;OMAX;OMIN;URMAX;URMIN;UR;DIR;RAJ;VEL;\n"
    "2000-05-07;00:00;-9999;-9999;-9999;-9999;-9999;-9999;-9999;-9999;"
    "-9999;-9999;-9999;-9999;-9999;-9999;-9999;-9999;-9999;\n"
    "2000-10-05;14:00;0;-9999;1008,1;1007,7;919;27,2;22,8;28,7;26,6;"
    "23,5;22,1;81;68;77;128;3,7;1,1;\n"
)

_CSV_2026 = (
    "REGIAO:;CO\n"
    "UF:;DF\n"
    "ESTACAO:;BRASILIA\n"
    "CODIGO (WMO):;A001\n"
    "LATITUDE:;-15,78944444\n"
    "LONGITUDE:;-47,92583332\n"
    "ALTITUDE:;1160,96\n"
    "DATA DE FUNDACAO:;07/05/00\n"
    "Data;Hora UTC;PRECIPITAÇÃO TOTAL, HORÁRIO (mm);PRESSAO;PRESSAO MAX;"
    "PRESSAO MIN;RADIACAO GLOBAL (Kj/m²);TEMPERATURA;ORVALHO;TMAX;TMIN;"
    "OMAX;OMIN;URMAX;URMIN;UR;DIR;RAJ;VEL;\n"
    "2026/01/01;0000 UTC;0;887,7;887,7;887,2;;19,9;18,5;20,8;19,8;18,6;"
    "18,1;92;85;92;9;4,5;,8;\n"
    "2026/01/01;0100 UTC;0;888,1;888,2;887,7;;18,5;17,7;19,8;18,5;18,4;"
    "17,7;95;92;95;305;1,8;1;\n"
)

_NEIGHBOUR_COLS = [
    "era5_lat_top",
    "era5_lat_bottom",
    "era5_lon_left",
    "era5_lon_right",
    "era5_land_lat_top",
    "era5_land_lat_bottom",
    "era5_land_lon_left",
    "era5_land_lon_right",
]

_META_COLS = [
    "station_id",
    "latitude",
    "longitude",
    "altitude",
    "uf",
    "regiao",
    "nome",
    "data_fundacao",
    "date",
    "hour_utc",
    *_NEIGHBOUR_COLS,
]
_VAR_COLS = [
    "precipitacao_total",
    "pressao_estacao",
    "pressao_max",
    "pressao_min",
    "radiacao_global",
    "temp_ar",
    "temp_orvalho",
    "temp_max",
    "temp_min",
    "temp_orvalho_max",
    "temp_orvalho_min",
    "umidade_rel_max",
    "umidade_rel_min",
    "umidade_relativa",
    "vento_direcao",
    "vento_rajada_max",
    "vento_velocidade",
]


@pytest.fixture
def converter(tmp_path):
    return InmetToParquetConverter(
        transform_config=TransformConfig(),
        storage_config=StorageConfig(database_dir=tmp_path / "base"),
        output_dir=tmp_path / "out",
        dataset="inmet",
    )


def _write(tmp_path, name: str, content: str):
    p = tmp_path / name
    p.write_bytes(content.encode("latin-1"))
    return p


def test_2000_format_parsed(converter, tmp_path):
    csv = _write(
        tmp_path,
        "INMET_CO_DF_A001_BRASILIA_07-05-2000_A_31-12-2000.CSV",
        _CSV_2000,
    )
    out = converter.convert_file(csv)

    assert out.name == "A001_2000.parquet"
    assert out.parent.name == "station=A001"

    df = pl.read_parquet(out)
    assert df.columns == _META_COLS + _VAR_COLS

    # 2 data rows, both date-valid.
    assert df.height == 2
    row = df.filter(pl.col("hour_utc") == 14).row(0, named=True)
    assert row["station_id"] == "A001"
    assert row["uf"] == "DF"
    assert row["regiao"] == "CO"
    assert row["nome"] == "BRASILIA"
    assert row["date"].isoformat() == "2000-10-05"
    assert row["temp_ar"] == pytest.approx(27.2, rel=1e-4)
    assert row["vento_velocidade"] == pytest.approx(1.1, rel=1e-4)
    # -9999 sentinel -> null
    assert row["pressao_estacao"] is None
    # latitude kept at full precision (not grid-snapped)
    assert row["latitude"] == pytest.approx(-15.789444, rel=1e-5)
    assert row["altitude"] == pytest.approx(1159.54, rel=1e-5)


def test_2026_format_parsed(converter, tmp_path):
    csv = _write(
        tmp_path,
        "INMET_CO_DF_A001_BRASILIA_01-01-2026_A_30-04-2026.CSV",
        _CSV_2026,
    )
    out = converter.convert_file(csv)

    assert out.name == "A001_2026.parquet"
    df = pl.read_parquet(out)
    assert df.columns == _META_COLS + _VAR_COLS
    assert df.height == 2

    row = df.row(0, named=True)
    assert row["date"].isoformat() == "2026-01-01"
    assert row["hour_utc"] == 0
    # empty field -> null
    assert row["radiacao_global"] is None
    # leading-comma decimal ",8" -> 0.8
    assert row["vento_velocidade"] == pytest.approx(0.8, rel=1e-4)
    assert row["altitude"] == pytest.approx(1160.96, rel=1e-5)
    assert row["data_fundacao"] == "07/05/00"


def test_schema_identical_across_eras(converter, tmp_path):
    a = converter.convert_file(
        _write(tmp_path, "INMET_CO_DF_A001_X_07-05-2000_A_31-12-2000.CSV", _CSV_2000)
    )
    b = converter.convert_file(
        _write(tmp_path, "INMET_CO_DF_A001_Y_01-01-2026_A_30-04-2026.CSV", _CSV_2026)
    )
    sa = pl.read_parquet(a).schema
    sb = pl.read_parquet(b).schema
    assert sa == sb, f"schema drift between 2000 and 2026: {sa} != {sb}"


def test_convert_directory_recurses_year_subdirs(converter, tmp_path):
    # Downloader extracts CSVs into <input>/<year>/ subfolders.
    src = tmp_path / "raw"
    (src / "2000").mkdir(parents=True)
    (src / "2026").mkdir(parents=True)
    (src / "2000" / "INMET_CO_DF_A001_B_07-05-2000_A_31-12-2000.CSV").write_bytes(
        _CSV_2000.encode("latin-1")
    )
    (src / "2026" / "INMET_CO_DF_A001_B_01-01-2026_A_30-04-2026.CSV").write_bytes(
        _CSV_2026.encode("latin-1")
    )
    stats = converter.convert_directory(src)
    assert stats["total"] == 2
    assert stats["converted"] == 2
    assert stats["failed"] == 0
    assert stats["errors"] == []
    assert (converter.output_dir / "station=A001" / "A001_2000.parquet").exists()
    assert (converter.output_dir / "station=A001" / "A001_2026.parquet").exists()


def test_convert_directory_reports_errors(converter, tmp_path):
    """A malformed CSV must NOT be swallowed: it raises an aggregated error."""
    src = tmp_path / "raw"
    src.mkdir()
    (src / "INMET_CO_DF_A001_OK_07-05-2000_A_31-12-2000.CSV").write_bytes(
        _CSV_2000.encode("latin-1")
    )
    # No line-9 DATA;HORA header -> _find_header_index raises.
    (src / "INMET_XX_YY_BAD0_Z_01-01-2030_A_31-12-2030.CSV").write_bytes(
        "garbage;line\nnot;a;header\n".encode("latin-1")
    )

    with pytest.raises(ProcessingError) as exc:
        converter.convert_directory(src)
    msg = str(exc.value)
    assert "1/2 file(s)" in msg
    assert "BAD0" in msg
    # The good file was still written before the aggregated raise.
    assert (converter.output_dir / "station=A001" / "A001_2000.parquet").exists()


def test_grid_neighbours(converter, tmp_path):
    csv = _write(
        tmp_path,
        "INMET_CO_DF_A001_BRASILIA_07-05-2000_A_31-12-2000.CSV",
        _CSV_2000,
    )
    df = pl.read_parquet(converter.convert_file(csv))
    r = df.row(0, named=True)

    # A001 = (-15.78944, -47.92583).
    # ERA5 0.25° enclosing cell: lat in [-16.00, -15.75], lon in [-48.00, -47.75]
    assert r["era5_lat_top"] == pytest.approx(-15.75, abs=1e-3)
    assert r["era5_lat_bottom"] == pytest.approx(-16.00, abs=1e-3)
    assert r["era5_lon_left"] == pytest.approx(-48.00, abs=1e-3)
    assert r["era5_lon_right"] == pytest.approx(-47.75, abs=1e-3)
    # ERA5-LAND 0.1° enclosing cell: lat in [-15.8, -15.7], lon in [-48.0, -47.9]
    assert r["era5_land_lat_top"] == pytest.approx(-15.7, abs=1e-3)
    assert r["era5_land_lat_bottom"] == pytest.approx(-15.8, abs=1e-3)
    assert r["era5_land_lon_left"] == pytest.approx(-48.0, abs=1e-3)
    assert r["era5_land_lon_right"] == pytest.approx(-47.9, abs=1e-3)


def test_neighbour_col_names_count():
    """4 edges × 2 grids = 8 neighbour columns (no distances)."""
    from era5_etl.transform.inmet_to_parquet import NEIGHBOUR_COL_NAMES

    assert len(NEIGHBOUR_COL_NAMES) == 8
    assert not any(c.startswith("dist_") for c in NEIGHBOUR_COL_NAMES)


def test_parquet_sorted_by_date_hour(converter, tmp_path):
    # Rows deliberately out of chronological order in the CSV.
    body = (
        "REGIAO:;CO\nUF:;DF\nESTACAO:;X\nCODIGO (WMO):;A001\n"
        "LATITUDE:;-15,5\nLONGITUDE:;-47,5\nALTITUDE:;1,0\n"
        "DATA DE FUNDACAO:;01/01/00\n"
        "Data;Hora UTC;A;B;C;D;E;F;G;H;I;J;K;L;M;N;O;P;Q;\n"
        "2000-03-02;05:00;1;;;;;;;;;;;;;;;;;\n"
        "2000-03-01;23:00;1;;;;;;;;;;;;;;;;;\n"
        "2000-03-01;00:00;1;;;;;;;;;;;;;;;;;\n"
        "2000-03-02;01:00;1;;;;;;;;;;;;;;;;;\n"
    )
    csv = _write(tmp_path, "INMET_CO_DF_A001_X_01-01-2000_A_31-12-2000.CSV", body)
    df = pl.read_parquet(converter.convert_file(csv))
    keys = list(zip(df["date"].to_list(), df["hour_utc"].to_list(), strict=False))
    assert keys == sorted(keys), f"parquet not sorted by (date, hour_utc): {keys}"


def test_cleanup_removes_empty_temp_tree(converter, tmp_path):
    """After cleanup, _tmp_netcdf/inmet/<year>/ and parents are gone."""
    tmp_tree = tmp_path / "_tmp_netcdf" / "inmet"
    year_dir = tmp_tree / "2026"
    year_dir.mkdir(parents=True)
    (year_dir / "INMET_CO_DF_A001_X_01-01-2026_A_30-04-2026.CSV").write_bytes(
        _CSV_2026.encode("latin-1")
    )

    stats = converter.convert_directory(tmp_tree, cleanup=True)
    assert stats["converted"] == 1 and stats["failed"] == 0
    # Parquet written to the (separate) output dir.
    assert (converter.output_dir / "station=A001" / "A001_2026.parquet").exists()
    # The whole temp tree is removed.
    assert not year_dir.exists()
    assert not tmp_tree.exists()
    assert not (tmp_path / "_tmp_netcdf").exists()


def test_cleanup_keeps_temp_tree_when_a_file_fails(converter, tmp_path):
    tmp_tree = tmp_path / "_tmp_netcdf" / "inmet"
    year_dir = tmp_tree / "2026"
    year_dir.mkdir(parents=True)
    (year_dir / "INMET_CO_DF_A001_X_01-01-2026_A_30-04-2026.CSV").write_bytes(
        _CSV_2026.encode("latin-1")
    )
    (year_dir / "INMET_XX_YY_BAD0_Z_01-01-2099_A_31-12-2099.CSV").write_bytes(
        b"junk\n"
    )
    with pytest.raises(ProcessingError):
        converter.convert_directory(tmp_tree, cleanup=True)
    # Failure -> the temp tree (with the bad file) is kept for inspection.
    assert year_dir.exists()
    assert (year_dir / "INMET_XX_YY_BAD0_Z_01-01-2099_A_31-12-2099.CSV").exists()


def test_convert_directory_can_collect_without_raising(converter, tmp_path):
    src = tmp_path / "raw"
    src.mkdir()
    (src / "INMET_XX_YY_BAD0_Z_01-01-2030_A_31-12-2030.CSV").write_bytes(
        b"garbage\n"
    )
    stats = converter.convert_directory(src, raise_on_error=False)
    assert stats["failed"] == 1
    assert len(stats["errors"]) == 1
    assert "BAD0" in stats["errors"][0]["file"]
