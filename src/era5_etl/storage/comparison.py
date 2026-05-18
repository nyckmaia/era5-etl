"""Cross-dataset comparison view: ``era5_inmet``.

Aligns INMET station observations with ERA5 and ERA5-LAND on the **same
date and hour**, in one flat table. Because INMET stations are points and
ERA5/ERA5-LAND are regular grids, the station almost never sits exactly on
a grid node: instead each INMET parquet already carries (from
``transform/inmet_to_parquet``) the four enclosing grid-cell corner
coordinates per grid and the great-circle distance to each corner. This
module joins INMET to the **four surrounding grid points** of each grid
(not a single snapped point), so a consumer can spatially interpolate
(IDW / bilinear) using the ``dist_*`` columns.

Result: one row per ``(station_id, date, hour_utc)``, with
``i.*`` (every INMET column, including the 8 ``dist_*`` weights) plus, for
each grid that exists on disk, the four corner observations prefixed
``era5_<corner>_<col>`` / ``era5_land_<corner>_<col>`` where ``<corner>``
is ``tl|tr|bl|br`` (top/bottom × left/right). Grids with no parquet on
disk are simply omitted (the view still builds from whatever exists).

The coordinate join uses a small epsilon (``1e-4``) rather than Float32
equality so grid-origin/representation micro-offsets never drop a match;
``date``/``hour_utc`` are matched exactly (both UTC).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from era5_etl.storage.paths import resolve_dataset_dir

logger = logging.getLogger(__name__)

ERA5_INMET_VIEW = "era5_inmet"

# (inmet dataset, era5-family grids to attach). Each grid contributes 4
# corner joins. Corner -> (inmet latitude-edge col, inmet longitude-edge col).
_GRIDS: tuple[tuple[str, str], ...] = (
    ("era5", "era5"),
    ("era5_land", "era5-land"),
)
_CORNERS: tuple[tuple[str, str, str], ...] = (
    ("tl", "lat_top", "lon_left"),
    ("tr", "lat_top", "lon_right"),
    ("bl", "lat_bottom", "lon_left"),
    ("br", "lat_bottom", "lon_right"),
)
_EPS = 1e-4
# Columns NOT re-projected from a grid corner (redundant with the INMET row
# or the partition path).
_GRID_DROP = {"date"}


def _glob(base_dir: str | Path, dataset: str) -> str:
    return str(resolve_dataset_dir(base_dir, dataset) / "**" / "*.parquet")


def _has_parquet(base_dir: str | Path, dataset: str) -> bool:
    d = resolve_dataset_dir(base_dir, dataset)
    return d.exists() and any(d.rglob("*.parquet"))


def _describe_columns(conn: duckdb.DuckDBPyConnection, sql: str) -> list[str]:
    """Column names of a relation, via ``DESCRIBE``."""
    return [r[0] for r in conn.execute(f"DESCRIBE {sql}").fetchall()]


def build_era5_inmet_sql(
    conn: duckdb.DuckDBPyConnection,
    base_dir: str | Path,
    view_name: str = ERA5_INMET_VIEW,
) -> str:
    """Build the ``CREATE OR REPLACE VIEW`` SQL for the comparison view.

    Introspects each grid's *actual* parquet schema (so only columns that
    exist are referenced -- the downloaded variable set may be a subset of
    ``variables.yaml``) and emits a prefixed projection per corner.

    Raises ``ValueError`` if there is no INMET parquet (the view is
    INMET-anchored).
    """
    if not _has_parquet(base_dir, "inmet"):
        raise ValueError(
            "No INMET parquet found; era5_inmet is INMET-anchored. "
            "Run `era5 pipeline --dataset inmet ...` first."
        )

    inmet_glob = _glob(base_dir, "inmet")
    inmet_rel = (
        f"read_parquet('{inmet_glob}', hive_partitioning=true, "
        f"union_by_name=true)"
    )

    select_parts: list[str] = ["i.*"]
    join_parts: list[str] = []
    grids_used: list[str] = []

    for prefix, ds_name in _GRIDS:
        if not _has_parquet(base_dir, ds_name):
            logger.info(
                "era5_inmet: %s has no parquet; skipping its joins.", ds_name
            )
            continue
        grids_used.append(ds_name)
        grid_glob = _glob(base_dir, ds_name)
        grid_rel = f"read_parquet('{grid_glob}', hive_partitioning=true)"
        cols = _describe_columns(conn, f"SELECT * FROM {grid_rel} LIMIT 0")
        proj_cols = [c for c in cols if c not in _GRID_DROP]

        for corner, lat_edge, lon_edge in _CORNERS:
            alias = f"{prefix}_{corner}"
            i_lat = f"i.{prefix}_{lat_edge}"
            i_lon = f"i.{prefix}_{lon_edge}"
            join_parts.append(
                f"LEFT JOIN {grid_rel} AS {alias} ON "
                f"{alias}.date = i.date AND "
                f"{alias}.hour_utc = i.hour_utc AND "
                f"abs({alias}.latitude - {i_lat}) < {_EPS} AND "
                f"abs({alias}.longitude - {i_lon}) < {_EPS}"
            )
            for c in proj_cols:
                select_parts.append(f'{alias}."{c}" AS "{alias}_{c}"')

    select_sql = ",\n            ".join(select_parts)
    joins_sql = "\n        ".join(join_parts)
    sql = (
        f"CREATE OR REPLACE VIEW {view_name} AS\n"
        f"        SELECT\n            {select_sql}\n"
        f"        FROM {inmet_rel} AS i\n"
        f"        {joins_sql}".rstrip()
    )
    logger.info(
        "era5_inmet SQL built (grids: %s)",
        ", ".join(grids_used) or "<none>",
    )
    return sql


def create_era5_inmet_view(
    conn: duckdb.DuckDBPyConnection,
    base_dir: str | Path,
    view_name: str = ERA5_INMET_VIEW,
) -> list[str]:
    """Create/replace the ``era5_inmet`` view on ``conn``.

    Returns the list of era5-family grids that were attached (those with
    parquet on disk).
    """
    sql = build_era5_inmet_sql(conn, base_dir, view_name)
    conn.execute(sql)
    grids = [
        ds
        for _, ds in _GRIDS
        if _has_parquet(base_dir, ds)
    ]
    logger.info(
        "Created VIEW %s (INMET + %s)",
        view_name,
        ", ".join(grids) or "no grids",
    )
    return grids


__all__ = [
    "ERA5_INMET_VIEW",
    "build_era5_inmet_sql",
    "create_era5_inmet_view",
]
