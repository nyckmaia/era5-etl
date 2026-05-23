"""Runtime loader for the pre-computed grid_membership parquet.

The bundled ``grid_membership.parquet`` (one row per ``(dataset, region,
latitude, longitude)``) is produced offline by
``scripts/build_grid_membership.py`` from IBGE shapefiles. At runtime we
only need polars + ``importlib.resources`` — no shapely/geopandas.

The converter performs the clip as an ``INNER JOIN`` on
``(latitude, longitude)``. The join works because the membership table
stores lat/lon as ``Float32`` rounded to the dataset's grid precision —
exactly what :meth:`NetCDFToParquetConverter._round_latlon` produces.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import as_file, files

import polars as pl

_VALID_DATASETS: frozenset[str] = frozenset({"era5", "era5-land"})


@lru_cache(maxsize=4)
def _load_all(dataset: str) -> pl.DataFrame:
    """Load all rows for a dataset. Cached: parquet read happens once per process."""
    if dataset not in _VALID_DATASETS:
        raise ValueError(
            f"Unknown dataset for clipping: {dataset!r}. "
            f"Expected one of {sorted(_VALID_DATASETS)}."
        )
    resource = files("era5_etl._data.regions").joinpath("grid_membership.parquet")
    with as_file(resource) as path:
        df = pl.read_parquet(path).filter(pl.col("dataset") == dataset)
    if df.schema["latitude"] != pl.Float32 or df.schema["longitude"] != pl.Float32:
        raise RuntimeError(
            "grid_membership.parquet has wrong dtype for latitude/longitude "
            "— must be Float32 to bit-match the converter's rounded grid. "
            "Regenerate it with scripts/build_grid_membership.py."
        )
    return df


def available_regions(dataset: str) -> list[str]:
    """Return the regions that have membership pre-computed for ``dataset``."""
    return sorted(_load_all(dataset)["region"].unique().to_list())


def region_counts(dataset: str) -> dict[str, int]:
    """Return ``{region: cell_count}`` for ``dataset``.

    Regions with zero grid cells (too small for the dataset's resolution)
    are not present in the parquet and therefore not in the dict — callers
    should treat a missing key as zero.
    """
    df = _load_all(dataset)
    grouped = df.group_by("region").len().to_dicts()
    return {str(r["region"]): int(r["len"]) for r in grouped}


def validate_regions(dataset: str, regions: list[str]) -> None:
    """Raise ValueError if any region is not available for ``dataset``."""
    known = set(available_regions(dataset))
    unknown = sorted(set(regions) - known)
    if unknown:
        raise ValueError(
            f"Unknown region(s) for dataset {dataset!r}: {unknown}. "
            f"Known: {sorted(known)}."
        )


def latlon_set(dataset: str, regions: list[str]) -> pl.DataFrame:
    """Return the deduped ``(latitude, longitude)`` Float32 frame for the union of regions.

    Use as the right side of an ``INNER JOIN`` on the converter's DataFrame
    to drop rows whose grid point lies outside the polygon(s).
    """
    if not regions:
        raise ValueError("latlon_set() requires at least one region")
    validate_regions(dataset, regions)
    df = _load_all(dataset)
    return (
        df.filter(pl.col("region").is_in(regions))
        .select("latitude", "longitude")
        .unique()
    )
