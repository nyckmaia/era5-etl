"""Global display-decimal-places fallback for per-dataset precision."""

import importlib

import pytest


@pytest.fixture
def cfg_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path))
    import era5_etl.web.user_config as uc
    importlib.reload(uc)
    return uc


def test_global_default_used_when_dataset_unconfigured(cfg_mod):
    cfg_mod.update_user_config(display_decimal_places=2)
    p = cfg_mod.get_dataset_precision("era5-land")
    assert p["default_decimals"] == 2  # veio do global


def test_dataset_specific_overrides_global(cfg_mod):
    cfg_mod.update_user_config(display_decimal_places=2)
    cfg_mod.set_dataset_precision(
        "era5-land",
        {"default_decimals": 6, "default_method": "round", "columns": {}},
    )
    p = cfg_mod.get_dataset_precision("era5-land")
    assert p["default_decimals"] == 6  # config do dataset vence


def test_global_defaults_to_four(cfg_mod):
    p = cfg_mod.get_dataset_precision("era5")
    assert p["default_decimals"] == 4
