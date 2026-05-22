"""Download size estimation and geographic area splitting for CDS API requests.

Estimates request size using heuristics based on:
- Number of variables
- Number of hours per day
- Number of days in the period
- Number of grid points (derived from area bounds and dataset resolution)
- Bytes per value (8 bytes for DOUBLE in NetCDF format)

When a request exceeds the configured limit, the geographic area is
automatically split into adjacent sub-rectangles that together cover
the original area.
"""

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Grid resolution in degrees
ERA5_RESOLUTION = 0.25
ERA5_LAND_RESOLUTION = 0.1

# NetCDF stores float variables as DOUBLE (8 bytes per value)
BYTES_PER_VALUE = 8

# Heuristic: after conversion to Hive-partitioned Parquet (zstd, values as
# Float64, coords as Float32) climate fields compress well. This conservative
# ratio (final on-disk bytes ≈ this × raw-double download bytes) is only used
# to give the user an order-of-magnitude disk-occupancy figure — it is
# explicitly an estimate, not a guarantee.
PARQUET_DISK_RATIO = 0.5

# The CDS "cost limit" scales with the *volume of requested values*
# (variables × hours × days × grid points), not the compressed download
# size. ``estimate_request_size`` reports that volume as
# ``total_values × BYTES_PER_VALUE`` (raw uncompressed double).
#
# The request planner greedily packs each chunk right up to this ceiling
# (see ``request_planner._try_day_split``), so the ceiling directly sets
# the chunk size. ERA5-LAND NetCDF compresses ~12× off the raw-double
# estimate, so a 300 MB estimate downloads as ~25 MB — the largest file
# CDS will prepare per request. Calibrated there to minimise the number
# of round-trips (each request carries non-trivial CDS prep time) while
# staying under both the cost reject (~46M values observed) and the
# 25 MB download cap. The adaptive split in ``CDSDownloader`` is the
# safety net for the occasional over-shoot.
DEFAULT_MAX_REQUEST_BYTES = 300 * 1024 * 1024

# CDS documents a ceiling of ~12,000 "fields" (variables × hours × days)
# per request. The byte/value ceiling above is the binding constraint
# for realistic requests; this field cap is the documented-limit
# backstop (it stops a many-variable request over a tiny area, where
# the value count — and thus the byte estimate — stays low).
DEFAULT_MAX_REQUEST_FIELDS = 12_000


def request_fields(num_variables: int, num_hours: int, num_days: int) -> int:
    """CDS "fields" count for a request: variables × hours × days.

    Independent of area or grid resolution — the CDS server uses this
    item count as a separate ceiling on top of the byte-size limit, so
    a large list of variables × full month × every hour can blow past
    the ceiling even when the on-the-wire bytes look modest.
    """
    return max(0, num_variables) * max(0, num_hours) * max(0, num_days)


@dataclass
class SizeEstimate:
    """Result of a download size estimation."""

    num_variables: int
    num_hours: int
    num_days: int
    num_grid_points: int
    estimated_bytes: int
    exceeds_limit: bool
    limit_bytes: int
    #: ``variables × hours × days`` — see :func:`request_fields`. Tracked
    #: alongside bytes so the planner can split on whichever limit is
    #: tighter for a given request.
    fields_count: int = 0
    limit_fields: int = DEFAULT_MAX_REQUEST_FIELDS

    @property
    def estimated_mb(self) -> float:
        """Estimated size in megabytes."""
        return self.estimated_bytes / (1024 * 1024)

    @property
    def limit_mb(self) -> float:
        """Limit in megabytes."""
        return self.limit_bytes / (1024 * 1024)

    @property
    def exceeds_bytes_limit(self) -> bool:
        """Whether the byte ceiling is the one being violated."""
        return self.estimated_bytes > self.limit_bytes

    @property
    def exceeds_field_limit(self) -> bool:
        """Whether the CDS field-count ceiling is the one being violated."""
        return self.fields_count > self.limit_fields


@dataclass
class AreaSplit:
    """A geographic sub-rectangle defined by bounding coordinates."""

    north: float
    west: float
    south: float
    east: float

    def as_list(self) -> list[float]:
        """Return as [North, West, South, East] list for CDS API."""
        return [self.north, self.west, self.south, self.east]


def estimate_grid_points(area: list[float], resolution: float) -> int:
    """Estimate the number of grid points in a geographic area.

    Args:
        area: Bounding box [North, West, South, East].
        resolution: Grid resolution in degrees.

    Returns:
        Estimated number of grid points.
    """
    north, west, south, east = area
    lat_points = max(1, math.ceil(abs(north - south) / resolution) + 1)
    lon_points = max(1, math.ceil(abs(east - west) / resolution) + 1)
    return lat_points * lon_points


def estimate_request_size(
    num_variables: int,
    num_hours: int,
    num_days: int,
    area: list[float],
    dataset: str = "era5-land",
    max_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_fields: int = DEFAULT_MAX_REQUEST_FIELDS,
) -> SizeEstimate:
    """Estimate the download size for a CDS API request.

    Two independent ceilings are reported:

    - **Bytes**: ``total_values × BYTES_PER_VALUE`` where ``total_values
      = num_variables × num_hours × num_days × grid_points``. The CDS
      API stores numeric variables as DOUBLE (8 bytes).
    - **Fields**: ``num_variables × num_hours × num_days`` — the CDS
      server item count, independent of area/grid resolution.

    The returned ``SizeEstimate.exceeds_limit`` is True if *either*
    ceiling is breached, so callers (e.g. the request planner) can
    treat both uniformly while still inspecting the per-axis flags
    (``exceeds_bytes_limit`` / ``exceeds_field_limit``) for diagnostics.
    """
    resolution = ERA5_LAND_RESOLUTION if "land" in dataset else ERA5_RESOLUTION
    grid_points = estimate_grid_points(area, resolution)
    total_values = num_variables * num_hours * num_days * grid_points
    estimated_bytes = total_values * BYTES_PER_VALUE
    fields_count = request_fields(num_variables, num_hours, num_days)

    over_bytes = estimated_bytes > max_bytes
    over_fields = fields_count > max_fields
    return SizeEstimate(
        num_variables=num_variables,
        num_hours=num_hours,
        num_days=num_days,
        num_grid_points=grid_points,
        estimated_bytes=estimated_bytes,
        exceeds_limit=over_bytes or over_fields,
        limit_bytes=max_bytes,
        fields_count=fields_count,
        limit_fields=max_fields,
    )


def split_area(area: list[float], num_splits: int) -> list[AreaSplit]:
    """Split a geographic area into adjacent sub-rectangles.

    The area is divided into a grid. Splits are allocated by alternating
    between the latitude and longitude axes, always splitting the
    longer remaining dimension first.

    Args:
        area: Original bounding box [North, West, South, East].
        num_splits: Minimum number of sub-rectangles to produce.

    Returns:
        List of AreaSplit sub-rectangles covering the original area.
    """
    north, west, south, east = area
    lat_range = abs(north - south)
    lon_range = abs(east - west)

    # Determine grid dimensions (n_lat x n_lon >= num_splits)
    n_lat = 1
    n_lon = 1
    while n_lat * n_lon < num_splits:
        if lat_range / n_lat >= lon_range / n_lon:
            n_lat += 1
        else:
            n_lon += 1

    lat_step = lat_range / n_lat
    lon_step = lon_range / n_lon

    splits: list[AreaSplit] = []
    for i in range(n_lat):
        for j in range(n_lon):
            sub_north = north - i * lat_step
            sub_south = north - (i + 1) * lat_step
            sub_west = west + j * lon_step
            sub_east = west + (j + 1) * lon_step
            splits.append(AreaSplit(
                north=round(sub_north, 6),
                west=round(sub_west, 6),
                south=round(sub_south, 6),
                east=round(sub_east, 6),
            ))

    return splits


def calculate_splits_needed(estimate: SizeEstimate) -> int:
    """Calculate how many geographic splits are needed to stay under the limit.

    Args:
        estimate: A SizeEstimate that exceeds the limit.

    Returns:
        Number of splits needed (minimum 2 if limit exceeded, 1 otherwise).
    """
    if not estimate.exceeds_limit:
        return 1
    ratio = estimate.estimated_bytes / estimate.limit_bytes
    # Add safety margin of 20% to be conservative
    return max(2, math.ceil(ratio * 1.2))
