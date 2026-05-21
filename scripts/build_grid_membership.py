"""Build the grid_membership parquet from Brazilian IBGE shapefiles.

For each combination of (gridded ERA5 dataset, Brazilian region), this script
emits the set of CDS-native grid cells whose center falls inside the region
polygon expanded by a half-cell buffer. The result is a single Parquet file at:

    src/era5_etl/_data/regions/grid_membership.parquet

Schema:
    dataset    : Utf8   ("era5" | "era5-land")
    region     : Utf8   ("AC", "AL", ..., "TO", "BR")
    latitude   : Float32  (rounded to dataset.latlon_decimals, matches converter)
    longitude  : Float32

Why offline: the heavy GIS dependencies (geopandas, shapely, GDAL/libgeos) only
need to run once. At runtime the application reads this parquet with polars and
performs the clip via an INNER JOIN — no shapely required.

Run:
    py -3.12 -m pip install -e ".[regions-build]"
    py -3.12 scripts/build_grid_membership.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import polars as pl
from shapely.strtree import STRtree

if TYPE_CHECKING:
    from shapely.geometry import MultiPolygon, Polygon

REPO_ROOT = Path(__file__).resolve().parent.parent
SHAPEFILES_DIR = REPO_ROOT / "data-sources" / "shapefiles"
OUTPUT_PATH = (
    REPO_ROOT / "src" / "era5_etl" / "_data" / "regions" / "grid_membership.parquet"
)

UF_SHAPEFILE = SHAPEFILES_DIR / "BR_UF_2025" / "BR_UF_2025.shp"
BR_SHAPEFILE = SHAPEFILES_DIR / "BR_Pais_2025" / "BR_Pais_2025.shp"

WGS84 = "EPSG:4326"

# (dataset_name, grid_resolution_deg, latlon_decimals).
# Keep in sync with DatasetRegistry; the converter's _round_latlon
# uses these decimals on Float32 — runtime INNER JOIN depends on it.
DATASETS: tuple[tuple[str, float, int], ...] = (
    ("era5", 0.25, 2),
    ("era5-land", 0.1, 1),
)


def _setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("build_grid_membership")


def _snap_up(value: float, step: float) -> float:
    import math

    return math.ceil(value / step) * step


def _snap_down(value: float, step: float) -> float:
    import math

    return math.floor(value / step) * step


def _grid_points_in_bbox(
    bounds: tuple[float, float, float, float],
    resolution: float,
    decimals: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Enumerate CDS-native grid (lat, lon) inside the bounds.

    Grid alignment: integer multiples of ``resolution`` (matches the CDS
    convention used by ``snap_area_to_grid``). Returns flat arrays of equal
    length, rounded to ``decimals`` so they bit-match what
    ``NetCDFToParquetConverter._round_latlon`` writes.
    """
    minx, miny, maxx, maxy = bounds
    south = _snap_down(miny, resolution)
    north = _snap_up(maxy, resolution)
    west = _snap_down(minx, resolution)
    east = _snap_up(maxx, resolution)

    # ``arange`` is exclusive on the upper bound; add half-step for inclusive.
    lats = np.arange(south, north + resolution / 2.0, resolution)
    lons = np.arange(west, east + resolution / 2.0, resolution)
    lats = np.round(lats, decimals)
    lons = np.round(lons, decimals)
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    return lat_grid.ravel(), lon_grid.ravel()


def _points_inside(
    polygon: Polygon | MultiPolygon,
    lats: np.ndarray,
    lons: np.ndarray,
) -> np.ndarray:
    """Vectorised point-in-polygon via shapely STRtree.

    Returns a boolean mask of length ``len(lats)``.
    """
    from shapely.geometry import Point

    points = [Point(lon, lat) for lat, lon in zip(lats, lons, strict=True)]
    tree = STRtree([polygon])
    mask = np.zeros(len(points), dtype=bool)
    candidate_idx = tree.query(points, predicate="intersects")
    # query returns (input_idx_array, tree_idx_array). For a single polygon tree
    # we only care about the input indices.
    if candidate_idx.size > 0:
        input_indices = candidate_idx[0] if candidate_idx.ndim == 2 else candidate_idx
        mask[input_indices] = True
    return mask


def _build_membership_for_region(
    region_code: str,
    geometry: Polygon | MultiPolygon,
    log: logging.Logger,
) -> list[pl.DataFrame]:
    """Generate one DataFrame per dataset for the given region.

    The polygon is buffered by half a grid cell so coastal/border cells
    whose footprint overlaps the region are kept (matches the spec).
    """
    minx, miny, maxx, maxy = geometry.bounds
    # Add a small safety margin to the bounds to capture buffered border points.
    bounds = (minx - 0.5, miny - 0.5, maxx + 0.5, maxy + 0.5)

    out: list[pl.DataFrame] = []
    for dataset_name, resolution, decimals in DATASETS:
        half_cell = resolution / 2.0
        buffered = geometry.buffer(half_cell)
        lats, lons = _grid_points_in_bbox(bounds, resolution, decimals)
        mask = _points_inside(buffered, lats, lons)
        kept_lats = lats[mask].astype(np.float32)
        kept_lons = lons[mask].astype(np.float32)
        if kept_lats.size == 0:
            log.warning(
                "Region %s (%s) produced 0 grid cells — verify polygon geometry.",
                region_code,
                dataset_name,
            )
        else:
            log.info(
                "  %-9s  %-3s  %6d cells", dataset_name, region_code, kept_lats.size
            )
        df = pl.DataFrame(
            {
                "dataset": pl.Series(
                    [dataset_name] * kept_lats.size, dtype=pl.Utf8
                ),
                "region": pl.Series(
                    [region_code] * kept_lats.size, dtype=pl.Utf8
                ),
                "latitude": pl.Series(kept_lats, dtype=pl.Float32),
                "longitude": pl.Series(kept_lons, dtype=pl.Float32),
            }
        )
        out.append(df)
    return out


def main() -> int:
    log = _setup_logging()

    if not UF_SHAPEFILE.exists():
        log.error("UF shapefile not found at %s", UF_SHAPEFILE)
        return 1
    if not BR_SHAPEFILE.exists():
        log.error("Brazil shapefile not found at %s", BR_SHAPEFILE)
        return 1

    log.info("Loading UF shapefile: %s", UF_SHAPEFILE)
    gdf_uf = gpd.read_file(UF_SHAPEFILE).to_crs(WGS84)
    log.info("  %d UF features, CRS=%s", len(gdf_uf), gdf_uf.crs)

    log.info("Loading Brazil shapefile: %s", BR_SHAPEFILE)
    gdf_br = gpd.read_file(BR_SHAPEFILE).to_crs(WGS84)
    log.info("  %d country features, CRS=%s", len(gdf_br), gdf_br.crs)

    if "SIGLA_UF" not in gdf_uf.columns:
        log.error(
            "UF shapefile lacks SIGLA_UF column. Found: %s",
            sorted(gdf_uf.columns.tolist()),
        )
        return 1

    parts: list[pl.DataFrame] = []

    # UFs (27): one row per state.
    for row in gdf_uf.itertuples(index=False):
        sigla = row.SIGLA_UF
        geom = row.geometry
        log.info("Region: %s", sigla)
        parts.extend(_build_membership_for_region(sigla, geom, log))

    # Brazil (BR): union of all country features (handles islands as MultiPolygon).
    log.info("Region: BR (whole country)")
    br_geom = gdf_br.geometry.union_all()
    parts.extend(_build_membership_for_region("BR", br_geom, log))

    full = pl.concat(parts, how="vertical")

    # Sanity: every (dataset, region, lat, lon) row must be unique.
    before = full.height
    full = full.unique(subset=["dataset", "region", "latitude", "longitude"])
    if full.height != before:
        log.warning(
            "Dropped %d duplicate (dataset, region, lat, lon) rows",
            before - full.height,
        )

    # Sort for cache-friendly reads at runtime.
    full = full.sort(["dataset", "region", "latitude", "longitude"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full.write_parquet(OUTPUT_PATH, compression="zstd", compression_level=9)

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    log.info("Wrote %s (%d rows, %.1f KB)", OUTPUT_PATH, full.height, size_kb)
    log.info(
        "Distinct (dataset, region) combos: %d",
        full.select(["dataset", "region"]).unique().height,
    )

    summary = (
        full.group_by(["dataset", "region"])
        .agg(pl.len().alias("cells"))
        .sort(["dataset", "region"])
    )
    log.info("Per-region cell counts:\n%s", summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
