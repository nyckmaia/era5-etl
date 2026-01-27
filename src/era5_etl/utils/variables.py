"""ERA5 variable definitions loader.

Loads variable metadata from the bundled YAML configuration file and provides
filtering by dataset. Also exposes float precision settings from the same YAML.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)


def _get_variables_yaml_path() -> Path:
    """Get path to the bundled era5_variables.yaml file.

    Returns:
        Path to the YAML file.

    Raises:
        FileNotFoundError: If the YAML file is not found.
    """
    try:
        from importlib.resources import files

        data_path = files("era5_etl._data").joinpath("era5_variables.yaml")
        path = Path(str(data_path))
        if path.exists():
            return path
    except (ImportError, TypeError, AttributeError):
        pass

    package_dir = Path(__file__).parent.parent
    fallback = package_dir / "_data" / "era5_variables.yaml"
    if fallback.exists():
        return fallback

    raise FileNotFoundError(
        f"era5_variables.yaml not found. Expected at: {fallback}"
    )


@lru_cache(maxsize=1)
def _load_yaml_config() -> dict[str, Any]:
    """Load the full YAML config (variables + float_precision)."""
    yaml_path = _get_variables_yaml_path()
    logger.debug(f"Loading variables config from {yaml_path}")
    with open(yaml_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def get_float_precision_config() -> dict[str, Any]:
    """Get the float precision configuration from the YAML.

    Returns:
        Dict with keys: 'enabled' (bool), 'decimal_places' (int).
    """
    config = _load_yaml_config()
    return config.get("float_precision", {"enabled": True, "decimal_places": 4})


def list_variables(dataset: str | None = None) -> pl.DataFrame:
    """Return a Polars DataFrame listing available ERA5/ERA5-Land variables.

    Args:
        dataset: Filter by dataset name ('era5' or 'era5-land').
                 If None, returns all variables.

    Returns:
        DataFrame with columns: api_name, short_name, friendly_name,
        full_name, description, unit, datasets.
    """
    config = _load_yaml_config()
    variables: list[dict[str, Any]] = config.get("variables", [])

    if dataset:
        variables = [v for v in variables if dataset in v.get("datasets", [])]

    rows = []
    for v in variables:
        rows.append({
            "api_name": v["api_name"],
            "short_name": v.get("short_name", ""),
            "friendly_name": v.get("friendly_name", ""),
            "full_name": v.get("full_name", ""),
            "description": v.get("description", ""),
            "unit": v.get("unit", ""),
            "datasets": ", ".join(v.get("datasets", [])),
        })

    return pl.DataFrame(rows)


def get_default_variables(dataset: str = "era5-land") -> list[str]:
    """Get the list of API variable names available for a dataset.

    Args:
        dataset: Dataset name ('era5' or 'era5-land').

    Returns:
        List of API variable name strings.
    """
    config = _load_yaml_config()
    variables: list[dict[str, Any]] = config.get("variables", [])
    return [v["api_name"] for v in variables if dataset in v.get("datasets", [])]


def get_var_name_map() -> dict[str, str]:
    """Get mapping from NetCDF short_name to friendly_name.

    This replaces the VAR_NAME_MAP constant in constants.py.

    Returns:
        Dict mapping short variable names to friendly names.
    """
    config = _load_yaml_config()
    variables: list[dict[str, Any]] = config.get("variables", [])
    return {
        v["short_name"]: v["friendly_name"]
        for v in variables
        if v.get("short_name") and v.get("friendly_name")
    }
