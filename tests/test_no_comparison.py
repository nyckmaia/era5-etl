"""era5_inmet is no longer generated in Python; it survives as a template."""

import importlib

import pytest
from typer.testing import CliRunner

from era5_etl.cli import app


def test_comparison_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("era5_etl.storage.comparison")


def test_era5_inmet_cli_command_removed():
    res = CliRunner().invoke(app, ["era5-inmet", "--help"])
    assert res.exit_code != 0


def test_era5_inmet_template_present():
    from era5_etl.web.query_store import list_templates

    tpl = next(
        (t for t in list_templates() if t["id"] == "era5-inmet-compare"),
        None,
    )
    assert tpl is not None
    assert "abs(" in tpl["sql"] and "era5_inmet" in tpl["sql"]
