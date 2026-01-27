"""Tests for ERA5 variable definitions loader."""

from era5_etl.utils.variables import (
    get_default_variables,
    get_float_precision_config,
    get_var_name_map,
    list_variables,
)


class TestListVariables:
    """Tests for list_variables()."""

    def test_returns_dataframe_with_expected_columns(self):
        df = list_variables()
        expected_cols = {
            "api_name", "short_name", "friendly_name",
            "full_name", "description", "unit", "datasets",
        }
        assert set(df.columns) == expected_cols

    def test_returns_all_variables_when_no_filter(self):
        df = list_variables()
        assert len(df) > 0

    def test_filter_era5_only(self):
        df = list_variables(dataset="era5")
        assert len(df) > 0
        for row in df.iter_rows(named=True):
            assert "era5" in row["datasets"]

    def test_filter_era5_land_only(self):
        df = list_variables(dataset="era5-land")
        assert len(df) > 0
        for row in df.iter_rows(named=True):
            assert "era5-land" in row["datasets"]

    def test_era5_land_has_soil_variables(self):
        df = list_variables(dataset="era5-land")
        api_names = df["api_name"].to_list()
        assert "soil_temperature_level_1" in api_names
        assert "volumetric_soil_water_layer_1" in api_names

    def test_era5_has_msl_pressure(self):
        df = list_variables(dataset="era5")
        api_names = df["api_name"].to_list()
        assert "mean_sea_level_pressure" in api_names

    def test_era5_land_does_not_have_era5_only_vars(self):
        df = list_variables(dataset="era5-land")
        api_names = df["api_name"].to_list()
        assert "mean_sea_level_pressure" not in api_names


class TestGetVarNameMap:
    """Tests for get_var_name_map()."""

    def test_returns_dict(self):
        name_map = get_var_name_map()
        assert isinstance(name_map, dict)
        assert len(name_map) > 0

    def test_maps_short_to_friendly(self):
        name_map = get_var_name_map()
        assert name_map["t2m"] == "temperature_2m"
        assert name_map["sp"] == "surface_pressure"
        assert name_map["tp"] == "total_precipitation"


class TestGetDefaultVariables:
    """Tests for get_default_variables()."""

    def test_era5_land_defaults(self):
        vars_list = get_default_variables("era5-land")
        assert isinstance(vars_list, list)
        assert len(vars_list) > 0
        assert "2m_temperature" in vars_list

    def test_era5_defaults(self):
        vars_list = get_default_variables("era5")
        assert isinstance(vars_list, list)
        assert "mean_sea_level_pressure" in vars_list


class TestGetFloatPrecisionConfig:
    """Tests for get_float_precision_config()."""

    def test_returns_expected_keys(self):
        config = get_float_precision_config()
        assert "enabled" in config
        assert "decimal_places" in config

    def test_default_values(self):
        config = get_float_precision_config()
        assert config["enabled"] is True
        assert config["decimal_places"] == 4
