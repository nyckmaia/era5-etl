"""Smoke tests for the Typer CLI.

These tests exercise the public CLI surface without touching the network or
the CDS API. They use Typer's built-in ``CliRunner``.
"""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from era5_etl.cli import app

runner = CliRunner()


def test_version_flag_shows_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ERA5-ETL version" in result.stdout


def test_variables_filter_by_dataset():
    result = runner.invoke(app, ["variables", "--dataset", "era5-land"])
    assert result.exit_code == 0
    out = result.stdout
    # era5-land has soil variables, era5 has msl pressure -- so msl should NOT appear here.
    assert "soil_temperature_level_1" in out
    assert "mean_sea_level_pressure" not in out


def test_variables_full_list():
    result = runner.invoke(app, ["variables"])
    assert result.exit_code == 0
    assert "mean_sea_level_pressure" in result.stdout
    assert "soil_temperature_level_1" in result.stdout


def test_status_empty_data_dir(tmp_path: Path):
    result = runner.invoke(app, ["status", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    # Both datasets should show up with zero state.
    assert "era5" in result.stdout
    assert "era5-land" in result.stdout


def test_status_single_dataset(tmp_path: Path):
    result = runner.invoke(app, ["status", "--data-dir", str(tmp_path), "--dataset", "era5"])
    assert result.exit_code == 0
    assert "era5" in result.stdout


def test_pipeline_dry_run_prints_chunks(tmp_path: Path):
    # dry-run must NOT contact CDS -- so it should succeed without credentials.
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5-land",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Plan" in result.stdout
    assert "planned chunks" in result.stdout or "Total planned chunks" in result.stdout


def test_unknown_dataset_is_rejected(tmp_path: Path):
    result = runner.invoke(
        app, ["status", "--data-dir", str(tmp_path), "--dataset", "nope"]
    )
    assert result.exit_code != 0


@patch("era5_etl.cli.CDSDownloader", create=True)
@patch("era5_etl.cli.plan_requests", create=True)
def test_update_dry_run_does_not_call_cds(_pr_mock, _dl_mock, tmp_path: Path):
    # Without --dry-run the command would build a downloader, which requires CDS creds.
    # With --dry-run it must short-circuit.
    result = runner.invoke(
        app,
        [
            "update",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5-land",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Manifest records" in result.stdout


# ---------------------------------------------------------------------------
# --pais and region exclusivity (Melhoria 01)
# ---------------------------------------------------------------------------


def test_pais_default_brasil_resolves_country_bbox():
    from era5_etl.cli import _resolve_area

    area = _resolve_area("Brasil")
    # pais.csv contains: Brasil,5.272,-73.983,-33.751,-34.793
    assert area[0] > 0  # north positive (above equator)
    assert area[2] < 0  # south negative
    assert area[1] < 0  # west negative
    assert len(area) == 4


def test_pais_with_uf_resolves_uf_bbox():
    from era5_etl.cli import _resolve_area

    area_pais = _resolve_area("Brasil")
    area_sp = _resolve_area("Brasil", uf="SP")
    # SP must be strictly inside Brazil's bbox
    assert area_sp != area_pais
    assert area_sp[0] <= area_pais[0]
    assert area_sp[2] >= area_pais[2]


def test_pais_unknown_raises():
    import typer

    from era5_etl.cli import _resolve_area

    try:
        _resolve_area("Argentina")
    except typer.BadParameter:
        pass
    else:
        raise AssertionError("expected BadParameter for unknown country")


def test_pais_foreign_with_region_flag_raises():
    import typer

    from era5_etl.cli import _resolve_area

    try:
        _resolve_area("Argentina", uf="SP")
    except typer.BadParameter:
        pass
    else:
        raise AssertionError("expected BadParameter for foreign country + region")


def test_multiple_region_flags_raise():
    import typer

    from era5_etl.cli import _resolve_area

    try:
        _resolve_area("Brasil", uf="SP", regiao_imediata="Campinas")
    except typer.BadParameter:
        pass
    else:
        raise AssertionError("expected BadParameter for multiple sub-region flags")


def test_municipio_plus_uf_is_allowed():
    """The single permitted multi-flag combo: --municipio + --uf (disambiguator)."""
    from era5_etl.cli import _resolve_area

    # Should not raise; uf scopes the municipio lookup.
    area = _resolve_area("Brasil", municipio="São Paulo", uf="SP")
    assert len(area) == 4


def test_dedup_on_empty_dataset_is_noop(tmp_path: Path):
    """`era5 dedup` should not error when there is no data."""
    result = runner.invoke(
        app,
        ["dedup", "--data-dir", str(tmp_path), "--dataset", "era5-land"],
    )
    assert result.exit_code == 0
    assert "No Parquet data" in result.stdout


def test_dedup_collapses_duplicates(tmp_path: Path):
    """End-to-end: place dup files in a partition, run `era5 dedup`, verify collapse."""
    import polars as pl

    from era5_etl.storage.parquet_manager import ParquetManager

    manager = ParquetManager(tmp_path, "era5-land")
    partition_dir = manager.parquet_dir / "date=2024-01-01"
    partition_dir.mkdir(parents=True)
    df = pl.DataFrame({
        "latitude": [-22.0, -22.0],
        "longitude": [-44.0, -44.0],
        "hour_utc": [12, 12],
        "t2m": [300.0, 300.0],
    })
    df.write_parquet(partition_dir / "part-a.parquet")
    df.write_parquet(partition_dir / "part-b.parquet")

    result = runner.invoke(
        app,
        ["dedup", "--data-dir", str(tmp_path), "--dataset", "era5-land"],
    )
    assert result.exit_code == 0, result.stdout
    assert "Duplicates removed" in result.stdout

    final_files = list(partition_dir.glob("*.parquet"))
    assert len(final_files) == 1
    final = pl.read_parquet(final_files[0])
    assert len(final) == 1


def test_arco_notice_is_filtered():
    """The ARCO/Zarr notice from cdsapi must be suppressed after install_cdsapi_log_filter."""
    import logging

    from era5_etl.cli import install_cdsapi_log_filter

    install_cdsapi_log_filter()
    cdsapi_logger = logging.getLogger("cdsapi")

    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture(level=logging.INFO)
    cdsapi_logger.addHandler(handler)
    prev_level = cdsapi_logger.level
    cdsapi_logger.setLevel(logging.INFO)
    try:
        cdsapi_logger.info(
            "Please note that a dedicated catalogue entry for this dataset, "
            "post-processed and stored in Analysis Ready Cloud Optimized (ARCO) "
            "format (Zarr), is available... reanalysis-era5-land-timeseries..."
        )
        cdsapi_logger.info("Request is queued")
        cdsapi_logger.info("Downloading https://example/file.nc to /tmp/x (12.34 MB)")
    finally:
        cdsapi_logger.removeHandler(handler)
        cdsapi_logger.setLevel(prev_level)

    assert all("Analysis Ready Cloud Optimized" not in m for m in captured)
    assert all("reanalysis-era5-land-timeseries" not in m for m in captured)
    assert any("Request is queued" in m for m in captured)
    assert any("Downloading https" in m for m in captured)


def test_pipeline_with_pais_flag_dry_run(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5-land",
            "--pais",
            "Brasil",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-02",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "country 'Brasil'" in result.stdout or "Brasil" in result.stdout


# --- --region / --no-clip ---------------------------------------------


def test_pipeline_region_single_uf_sets_clip_and_bbox(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5-land",
            "--region",
            "SP",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-02",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "region(s)" in result.stdout
    assert "SP" in result.stdout


def test_pipeline_multi_region_unions_bbox(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5",
            "--region",
            "SP",
            "--region",
            "RJ",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-02",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "SP+RJ" in result.stdout


def test_convert_no_clip_disables_clipping(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "convert",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5",
            "--region",
            "SP",
            "--no-clip",
        ],
    )
    # No NetCDF to convert → command still exits 0, but the --no-clip notice
    # must have been printed.
    assert result.exit_code == 0
    assert "no-clip" in result.stdout.lower()


def test_pipeline_unknown_region_errors(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5",
            "--region",
            "XX",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0


def test_pipeline_region_br_uses_country_bbox(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--data-dir",
            str(tmp_path),
            "--dataset",
            "era5",
            "--region",
            "BR",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-02",
            "--var",
            "2m_temperature",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "region(s)" in result.stdout
    assert "BR" in result.stdout
