"""Tests for the DatasetRegistry and the bundled DatasetConfig instances."""

import pytest

from era5_etl.datasets import DatasetRegistry
from era5_etl.datasets.base import DatasetConfig
from era5_etl.datasets.era5.config import Era5Config
from era5_etl.datasets.era5_land.config import Era5LandConfig


def test_registry_lists_both_datasets():
    names = DatasetRegistry.names()
    assert names == ("era5", "era5-land")


def test_registry_get_returns_config_instance():
    cfg = DatasetRegistry.get("era5")
    assert isinstance(cfg, DatasetConfig)
    assert isinstance(cfg, Era5Config)


def test_registry_unknown_dataset_raises():
    with pytest.raises(KeyError):
        DatasetRegistry.get("does-not-exist")


def test_era5_metadata():
    cfg = DatasetRegistry.get("era5")
    assert cfg.NAME == "era5"
    assert cfg.CDS_DATASET_ID == "reanalysis-era5-single-levels"
    assert cfg.GRID_RESOLUTION_DEG == 0.25
    assert cfg.parquet_dir_name == "era5"


def test_era5_land_metadata():
    cfg = DatasetRegistry.get("era5-land")
    assert isinstance(cfg, Era5LandConfig)
    assert cfg.NAME == "era5-land"
    assert cfg.CDS_DATASET_ID == "reanalysis-era5-land"
    assert cfg.GRID_RESOLUTION_DEG == 0.1
    assert cfg.parquet_dir_name == "era5-land"


def test_era5_variables_load_from_yaml():
    cfg = DatasetRegistry.get("era5")
    api_names = [v.api_name for v in cfg.variables]
    assert "2m_temperature" in api_names
    assert "mean_sea_level_pressure" in api_names


def test_era5_land_variables_load_from_yaml():
    cfg = DatasetRegistry.get("era5-land")
    api_names = [v.api_name for v in cfg.variables]
    assert "2m_temperature" in api_names
    assert "soil_temperature_level_1" in api_names
    assert "volumetric_soil_water_layer_1" in api_names


def test_era5_land_does_not_have_pressure_levels():
    cfg = DatasetRegistry.get("era5-land")
    api_names = [v.api_name for v in cfg.variables]
    # mean_sea_level_pressure is single-level-only
    assert "mean_sea_level_pressure" not in api_names


def test_defaults_subset_of_variables():
    for cfg in DatasetRegistry.all():
        api_names = {v.api_name for v in cfg.variables}
        for d in cfg.default_variables:
            assert d in api_names, f"{cfg.NAME} default '{d}' not in variables.yaml"


def test_var_name_map_contains_t2m():
    cfg = DatasetRegistry.get("era5")
    assert cfg.var_name_map["t2m"] == "temperature_2m"


def test_each_dataset_config_is_a_singleton():
    a = DatasetRegistry.get("era5")
    b = DatasetRegistry.get("era5")
    assert a is b
