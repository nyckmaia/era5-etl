"""Base classes for ERA5 dataset definitions.

A ``DatasetConfig`` describes everything needed to talk to one CDS dataset:
its CDS API name, native grid resolution, the set of available variables and
their metadata, and a few presentation helpers. Each concrete dataset
(ERA5 single-level, ERA5-LAND) lives in its own sub-package and registers
itself with the ``DatasetRegistry``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class VariableSpec:
    """Metadata for a single ERA5 variable."""

    api_name: str
    short_name: str
    friendly_name: str
    full_name: str
    description: str
    unit: str
    datasets: tuple[str, ...]


class DatasetConfig(ABC):
    """Abstract description of an ERA5-family dataset.

    Subclasses set the class attributes ``NAME``, ``CDS_DATASET_ID``,
    ``GRID_RESOLUTION_DEG`` and ``VARIABLES_YAML`` (a path relative to the
    subclass module's directory) and the registry/utility helpers do the rest.
    """

    NAME: str = ""
    CDS_DATASET_ID: str = ""
    GRID_RESOLUTION_DEG: float = 0.0
    VARIABLES_YAML: str = "variables.yaml"

    @cached_property
    def _yaml_data(self) -> dict[str, Any]:
        return _load_variables_yaml(self._variables_yaml_path())

    @cached_property
    def variables(self) -> tuple[VariableSpec, ...]:
        """All variables defined for this dataset."""
        raw = self._yaml_data.get("variables", [])
        return tuple(
            VariableSpec(
                api_name=v["api_name"],
                short_name=v.get("short_name", ""),
                friendly_name=v.get("friendly_name", ""),
                full_name=v.get("full_name", ""),
                description=v.get("description", ""),
                unit=v.get("unit", ""),
                datasets=(self.NAME,),
            )
            for v in raw
        )

    @cached_property
    def default_variables(self) -> tuple[str, ...]:
        """API names of variables in the default selection."""
        raw = self._yaml_data.get("defaults", [])
        if raw:
            return tuple(raw)
        return tuple(v.api_name for v in self.variables)

    @cached_property
    def var_name_map(self) -> dict[str, str]:
        """Mapping from NetCDF short_name -> friendly_name."""
        return {v.short_name: v.friendly_name for v in self.variables if v.short_name and v.friendly_name}

    @property
    def parquet_dir_name(self) -> str:
        """Folder name used under ``climate_data_store_db/``."""
        return self.NAME

    @abstractmethod
    def _variables_yaml_path(self) -> Path:
        """Return the absolute path to this dataset's ``variables.yaml``."""


def _load_variables_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Variables YAML not found at {path}")
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return data


def _resource_path(package: str, resource: str) -> Path:
    """Resolve a packaged resource to an absolute Path.

    Handles both installed-wheel and editable-source layouts.
    """
    try:
        return Path(str(files(package).joinpath(resource)))
    except (ModuleNotFoundError, TypeError, AttributeError):
        # Fall back to the source tree
        module_dir = Path(__file__).parent.parent
        relative = package.replace("era5_etl.", "").replace(".", "/")
        return module_dir / relative / resource
