"""CLI smoke tests for the INMET dataset (no network)."""

from pathlib import Path

from typer.testing import CliRunner

from era5_etl.cli import app

runner = CliRunner()


def test_variables_lists_inmet():
    result = runner.invoke(app, ["variables", "--dataset", "inmet"])
    assert result.exit_code == 0
    assert "temp_ar" in result.stdout
    assert "vento_velocidade" in result.stdout


def test_pipeline_dry_run_inmet_no_network(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "pipeline",
            "--dataset",
            "inmet",
            "--data-dir",
            str(tmp_path),
            "--start-date",
            "2000-01-01",
            "--end-date",
            "2001-12-31",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "2000" in result.stdout and "2001" in result.stdout
    # Must not have tried the CDS plan path.
    assert "size estimate" not in result.stdout.lower()


def test_download_dry_run_inmet(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "download",
            "--dataset",
            "inmet",
            "--data-dir",
            str(tmp_path),
            "--start-date",
            "2000-01-01",
            "--end-date",
            "2000-12-31",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "INMET yearly ZIP" in result.stdout


def test_update_inmet_is_noop(tmp_path: Path):
    result = runner.invoke(
        app, ["update", "--dataset", "inmet", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.stdout
    assert "station source" in result.stdout
