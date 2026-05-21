"""Prerequisite checks for the INMET download flow.

INMET conversion needs to know where the ERA5/ERA5-LAND grid points are
so it can stamp each station with its 4 enclosing grid corners. The web
pipeline orchestrator auto-bootstraps any missing grid by downloading a
minimal CDS request (1 var x 1 day x 1 hour x Brazil), extracting just
the ``(latitude, longitude)`` columns, and writing the result to a
SEPARATE parquet under ``<base>/climate_data_store_db/_grids/
<dataset>_grid.parquet`` — the per-dataset folder stays untouched so
the user's actual ERA5/ERA5-LAND downloads remain pristine and the
``/inventory`` map shows only intentionally-fetched data.

The prerequisite signal is therefore "is the grid parquet present?" —
NOT "is there any parquet under climate_data_store_db/<dataset>/".
"""

from __future__ import annotations

from pathlib import Path

from era5_etl.constants import BRAZIL_BBOX
from era5_etl.storage.grid_index import grid_parquet_path

#: Datasets that must have a grid parquet before INMET ingestion can stamp
#: each station with its enclosing grid corners. Order matters: the
#: orchestrator bootstraps in this order so the user sees a stable phase
#: progression.
PREREQUISITE_GRIDS: tuple[str, ...] = ("era5", "era5-land")


#: Defaults for the auto-bootstrap sub-pipelines. A single variable, single
#: hour, single day, Brazil bbox. Cheapest CDS request that still produces
#: a complete Brazil-wide grid. ``clip_regions`` is set so the bootstrap
#: downloads through the same polygon-clip path as user requests, but the
#: result is then folded into a lat/lon-only parquet via the
#: ``ExtractGridStage`` (see ``pipeline/era5_pipeline.py``).
BOOTSTRAP_DATE: str = "2024-01-01"
BOOTSTRAP_HOURS: tuple[str, ...] = ("12:00",)
BOOTSTRAP_VARIABLES: tuple[str, ...] = ("2m_temperature",)
BOOTSTRAP_AREA: tuple[float, float, float, float] = tuple(  # type: ignore[assignment]
    float(x) for x in BRAZIL_BBOX
)
BOOTSTRAP_CLIP_REGIONS: tuple[str, ...] = ("BR",)


def grid_has_parquet(base_dir: str | Path, dataset: str) -> bool:
    """Whether a bootstrap grid parquet exists for ``dataset``.

    NB: this is intentionally NOT a check on the per-dataset folder
    (``<base>/climate_data_store_db/<dataset>/``) — the orchestrator
    writes bootstrap output to ``_grids/`` precisely so that folder
    stays empty until the user downloads real data on purpose.
    """
    return grid_parquet_path(base_dir, dataset).exists()


def missing_grids(base_dir: str | Path) -> list[str]:
    """Return the prerequisite grids that have no grid parquet yet."""
    return [d for d in PREREQUISITE_GRIDS if not grid_has_parquet(base_dir, d)]
