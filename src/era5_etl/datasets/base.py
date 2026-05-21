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
    #: Group ids the variable appears under in the wizard (CDS-style
    #: sections). A variable may belong to multiple groups (e.g. ``2m
    #: temperature`` is in both "Popular" and "Temperature and pressure").
    #: Empty tuple means "ungrouped" — the wizard renders such datasets
    #: as a flat list.
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class VariableGroup:
    """A wizard section grouping related variables.

    Mirrors the CDS web form's section layout. The list of groups (in
    display order) lives at the top of each dataset's ``variables.yaml``.
    """

    id: str
    label: str
    order: int


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

    #: How this dataset's data is acquired and shaped. ``"cds_grid"`` (the
    #: default, used by ERA5/ERA5-LAND) means a gridded NetCDF source pulled
    #: from the Copernicus CDS. Non-grid sources (e.g. INMET station ZIPs)
    #: override this; the pipeline dispatches the downloader/converter/refresh
    #: stage on this value via ``pipeline.source_handlers``.
    SOURCE_KIND: str = "cds_grid"

    @property
    def is_gridded(self) -> bool:
        """Whether this dataset is on a regular lat/lon grid.

        Grid-aware machinery (request splitting by area, the per-cell
        coverage index, lat/lon snapping) only applies to gridded sources.
        """
        return self.SOURCE_KIND == "cds_grid"

    @property
    def latlon_decimals(self) -> int:
        """Decimal places lat/lon should be rounded to for this dataset.

        Derived from the native grid resolution: ERA5 ``0.25`` -> 2 dp,
        ERA5-LAND ``0.1`` -> 1 dp. Counts the significant fractional digits
        of ``GRID_RESOLUTION_DEG`` (``0.25`` -> ``"25"`` -> 2; ``0.1`` ->
        ``"1"`` -> 1). Floor of 1 so a coordinate never collapses to an
        integer grid.

        Non-gridded sources (station data) keep full coordinate precision
        -- station latitude/longitude must never be snapped to a grid.
        """
        if not self.is_gridded:
            return 6
        s = repr(float(self.GRID_RESOLUTION_DEG))
        if "." not in s:
            return 1
        frac = s.split(".", 1)[1].rstrip("0")
        return len(frac) or 1

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
                groups=tuple(v.get("groups", ())),
            )
            for v in raw
        )

    @cached_property
    def variable_groups(self) -> tuple[VariableGroup, ...]:
        """Wizard sections for this dataset, in display order.

        Empty when the YAML has no ``groups:`` key (older datasets like
        ERA5-LAND keep a flat variable list). The UI falls back to a
        flat render in that case.
        """
        raw = self._yaml_data.get("groups", [])
        return tuple(
            VariableGroup(id=g["id"], label=g["label"], order=i)
            for i, g in enumerate(raw)
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
