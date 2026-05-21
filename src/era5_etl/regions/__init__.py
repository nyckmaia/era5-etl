"""Pre-computed grid-cell membership for Brazilian regions.

Used by the converter to drop NetCDF grid points that fall outside the
selected UF(s)/Brazil polygon before writing Parquet. See
:mod:`era5_etl.regions.membership` for the runtime loader and
``scripts/build_grid_membership.py`` for how the data is generated.
"""

from era5_etl.regions.membership import (
    available_regions,
    latlon_set,
    validate_regions,
)

__all__ = ["available_regions", "latlon_set", "validate_regions"]
