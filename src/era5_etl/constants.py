"""Constants for ERA5-ETL."""

# CDS API Configuration
CDS_URL = "https://cds.climate.copernicus.eu/api/v2"

# ERA5 Datasets
DATASET_ERA5_SINGLE_LEVEL = "reanalysis-era5-single-levels"
DATASET_ERA5_PRESSURE_LEVEL = "reanalysis-era5-pressure-levels"
DATASET_ERA5_LAND = "reanalysis-era5-land"

# DEPRECATED: Variable definitions are now sourced from _data/era5_variables.yaml.
# These constants are kept for backward compatibility.
# Use era5_etl.utils.variables.list_variables() or get_var_name_map() instead.
# Common ERA5 variables (single level)
ERA5_SINGLE_LEVEL_VARS = {
    # Temperature
    "2m_temperature": "2m_temperature",
    "2m_dewpoint_temperature": "2m_dewpoint_temperature",
    "skin_temperature": "skin_temperature",
    # Pressure
    "surface_pressure": "surface_pressure",
    "mean_sea_level_pressure": "mean_sea_level_pressure",
    # Wind
    "10m_u_component_of_wind": "10m_u_component_of_wind",
    "10m_v_component_of_wind": "10m_v_component_of_wind",
    # Precipitation & Humidity
    "total_precipitation": "total_precipitation",
    "relative_humidity": "relative_humidity",
    # Radiation
    "surface_solar_radiation_downwards": "surface_solar_radiation_downwards",
    "surface_thermal_radiation_downwards": "surface_thermal_radiation_downwards",
    # Other
    "total_cloud_cover": "total_cloud_cover",
    "evaporation": "evaporation",
}

# DEPRECATED: Variable definitions are now sourced from _data/era5_variables.yaml.
# These constants are kept for backward compatibility.
# Use era5_etl.utils.variables.list_variables() or get_var_name_map() instead.
# ERA5-Land specific variables
ERA5_LAND_VARS = {
    "2m_temperature": "2m_temperature",
    "2m_dewpoint_temperature": "2m_dewpoint_temperature",
    "10m_u_component_of_wind": "10m_u_component_of_wind",
    "10m_v_component_of_wind": "10m_v_component_of_wind",
    "surface_pressure": "surface_pressure",
    "total_precipitation": "total_precipitation",
    "soil_temperature_level_1": "soil_temperature_level_1",
    "volumetric_soil_water_layer_1": "volumetric_soil_water_layer_1",
}

# Time parameters
HOURS_ALL = [f"{h:02d}:00" for h in range(24)]
HOURS_SYNOPTIC = ["00:00", "06:00", "12:00", "18:00"]
HOURS_3H = [f"{h:02d}:00" for h in range(0, 24, 3)]

# Pressure levels (hPa)
PRESSURE_LEVELS = [
    1000, 975, 950, 925, 900,
    850, 800, 750, 700, 650,
    600, 550, 500, 450, 400,
    350, 300, 250, 200, 150,
    100, 70, 50, 30, 20, 10,
]

# Area bounds (North, West, South, East)
# Brazil bounding box
BRAZIL_BBOX = [6, -74, -34, -34]

# Global
GLOBAL_BBOX = [90, -180, -90, 180]

# NetCDF compression settings
NETCDF_COMPRESSION = {
    "zlib": True,
    "complevel": 5,
}

# DEPRECATED: Variable definitions are now sourced from _data/era5_variables.yaml.
# These constants are kept for backward compatibility.
# Use era5_etl.utils.variables.list_variables() or get_var_name_map() instead.
# Variable name mappings (NetCDF short names to friendly names)
VAR_NAME_MAP = {
    "t2m": "temperature_2m",
    "d2m": "dewpoint_2m",
    "u10": "wind_u_10m",
    "v10": "wind_v_10m",
    "sp": "surface_pressure",
    "msl": "msl_pressure",
    "tp": "total_precipitation",
    "ssrd": "solar_radiation",
    "strd": "thermal_radiation",
    "tcc": "cloud_cover",
}

# Unit conversions
KELVIN_TO_CELSIUS = -273.15

# File formats
NETCDF_EXTENSION = ".nc"
PARQUET_EXTENSION = ".parquet"
CSV_EXTENSION = ".csv"

# DEPRECATED: Variable definitions are now sourced from _data/era5_variables.yaml.
# These constants are kept for backward compatibility.
# Use era5_etl.utils.variables.list_variables() or get_var_name_map() instead.
# Default variables for download
DEFAULT_VARIABLES = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "surface_pressure",
    "total_precipitation",
]
