"""ERA5 variable definitions loader.

This module delegates to :class:`era5_etl.datasets.DatasetRegistry` for the
authoritative variable metadata. Each dataset (``era5``, ``era5-land``) keeps
its own ``variables.yaml`` next to its ``DatasetConfig`` subclass.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from era5_etl.datasets import DatasetRegistry


def list_variables(dataset: str | None = None) -> pl.DataFrame:
    """Return a Polars DataFrame listing available ERA5/ERA5-Land variables.

    Args:
        dataset: Filter by dataset name ('era5' or 'era5-land').
                 If None, returns all variables across all datasets, with the
                 ``datasets`` column reflecting which datasets each variable
                 belongs to (joined with ", ").

    Returns:
        DataFrame with columns: api_name, short_name, friendly_name,
        full_name, description, unit, datasets.
    """
    rows: list[dict[str, Any]] = []

    configs = (DatasetRegistry.get(dataset),) if dataset is not None else DatasetRegistry.all()

    # When listing all datasets we want one row per api_name with merged
    # provenance, so we walk by api_name -> set(datasets).
    if dataset is None:
        merged: dict[str, dict[str, Any]] = {}
        for cfg in configs:
            for var in cfg.variables:
                entry = merged.setdefault(
                    var.api_name,
                    {
                        "api_name": var.api_name,
                        "short_name": var.short_name,
                        "friendly_name": var.friendly_name,
                        "full_name": var.full_name,
                        "description": var.description,
                        "unit": var.unit,
                        "datasets": set(),
                    },
                )
                entry["datasets"].add(cfg.NAME)
        for entry in merged.values():
            entry["datasets"] = ", ".join(sorted(entry["datasets"]))
            rows.append(entry)
    else:
        cfg = configs[0]
        for var in cfg.variables:
            rows.append(
                {
                    "api_name": var.api_name,
                    "short_name": var.short_name,
                    "friendly_name": var.friendly_name,
                    "full_name": var.full_name,
                    "description": var.description,
                    "unit": var.unit,
                    "datasets": cfg.NAME,
                }
            )

    return pl.DataFrame(rows)


def get_default_variables(dataset: str = "era5-land") -> list[str]:
    """Return the API variable names that make up the default selection for ``dataset``."""
    return list(DatasetRegistry.get(dataset).default_variables)


def get_var_name_map(dataset: str | None = None) -> dict[str, str]:
    """Return the NetCDF short_name -> friendly_name map.

    Args:
        dataset: Restrict to one dataset, or merge across all datasets if None.
    """
    if dataset is not None:
        return dict(DatasetRegistry.get(dataset).var_name_map)

    merged: dict[str, str] = {}
    for cfg in DatasetRegistry.all():
        merged.update(cfg.var_name_map)
    return merged
