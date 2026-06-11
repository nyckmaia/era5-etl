"""Per-dataset display-precision defaults and fallbacks."""

import importlib

import pytest


@pytest.fixture
def cfg_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path))
    import era5_etl.web.user_config as uc
    importlib.reload(uc)
    return uc


def test_global_default_used_for_unknown_dataset(cfg_mod):
    # A dataset without a built-in entry falls back to the global value.
    cfg_mod.update_user_config(display_decimal_places=2)
    p = cfg_mod.get_dataset_precision("some-future-dataset")
    assert p["default_decimals"] == 2  # veio do global


def test_dataset_specific_overrides_builtin(cfg_mod):
    cfg_mod.set_dataset_precision(
        "era5-land",
        {"default_decimals": 6, "default_method": "round", "columns": {}},
    )
    p = cfg_mod.get_dataset_precision("era5-land")
    assert p["default_decimals"] == 6  # config salva do dataset vence
    assert p["columns"] == {}  # e zera os defaults de coluna embutidos


def test_builtin_era5_defaults(cfg_mod):
    p = cfg_mod.get_dataset_precision("era5")
    assert p["default_decimals"] == 3
    assert p["default_method"] == "round"
    assert p["columns"]["latitude"] == {"decimals": 2, "method": "round"}
    assert p["columns"]["longitude"] == {"decimals": 2, "method": "round"}


def test_builtin_era5_land_defaults(cfg_mod):
    p = cfg_mod.get_dataset_precision("era5-land")
    assert p["default_decimals"] == 3
    assert p["columns"]["latitude"] == {"decimals": 1, "method": "round"}
    assert p["columns"]["longitude"] == {"decimals": 1, "method": "round"}


def test_builtin_inmet_defaults(cfg_mod):
    p = cfg_mod.get_dataset_precision("inmet")
    assert p["default_decimals"] == 2
    assert p["default_method"] == "round"
    assert p["columns"] == {}


def test_get_does_not_mutate_builtin_defaults(cfg_mod):
    # Returned columns are a deepcopy — mutating them must not leak into the
    # module-level defaults shared by the next caller.
    p = cfg_mod.get_dataset_precision("era5")
    p["columns"]["latitude"]["decimals"] = 99
    fresh = cfg_mod.get_dataset_precision("era5")
    assert fresh["columns"]["latitude"]["decimals"] == 2
