"""Read-only lookup of CDS grid points stored as a separate parquet.

The bootstrap sub-pipeline (see :class:`BootstrapGridPipeline`) writes one
parquet per gridded dataset to ``<base>/climate_data_store_db/_grids/
<dataset>_grid.parquet`` containing just the ``(latitude, longitude)``
columns — the bare minimum needed to know "where the grid points are"
without polluting the user's downloaded data.

The INMET converter consults this file to find the 4 enclosing grid points
of each station (replacing the math-only ``floor(lat/res)*res``). For
axis-aligned regular grids the result is identical to the math approach;
loading the parquet is a few KB and happens once per converter.
"""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path

import polars as pl

from era5_etl.storage.paths import resolve_storage_root

GRIDS_DIRNAME = "_grids"


def grid_parquet_path(base_dir: str | Path, dataset: str) -> Path:
    """``<base>/climate_data_store_db/_grids/<dataset>_grid.parquet``.

    Lives under ``climate_data_store_db`` (next to per-dataset folders) so
    a user inspecting their storage sees the grid bookkeeping in one place.
    """
    return resolve_storage_root(base_dir) / GRIDS_DIRNAME / f"{dataset}_grid.parquet"


class GridIndex:
    """Sorted ``(lat, lon)`` lookup over a regular grid.

    Built from a parquet whose only required columns are ``latitude`` and
    ``longitude`` (other columns are ignored). Provides
    :meth:`enclosing` returning the four edge coordinates surrounding a
    point — the same four numbers that the legacy math-only path computed.
    """

    def __init__(self, lats: list[float], lons: list[float]) -> None:
        self._lats = sorted(set(lats))
        self._lons = sorted(set(lons))

    @classmethod
    def from_parquet(cls, parquet_path: Path) -> GridIndex:
        df = pl.read_parquet(
            parquet_path, columns=["latitude", "longitude"]
        )
        return cls(
            lats=df["latitude"].to_list(),
            lons=df["longitude"].to_list(),
        )

    @classmethod
    def try_load(cls, base_dir: str | Path, dataset: str) -> GridIndex | None:
        """Return a GridIndex if a grid parquet exists for ``dataset``, else None."""
        path = grid_parquet_path(base_dir, dataset)
        if not path.exists():
            return None
        return cls.from_parquet(path)

    @property
    def lats(self) -> list[float]:
        return self._lats

    @property
    def lons(self) -> list[float]:
        return self._lons

    def enclosing(
        self, lat: float, lon: float
    ) -> dict[str, float | None]:
        """Return the four edge coordinates surrounding ``(lat, lon)``.

        Keys: ``lat_top`` (N), ``lat_bottom`` (S), ``lon_left`` (W),
        ``lon_right`` (E). Any edge that falls outside the grid extent
        (point past the last cell) is returned as ``None``.
        """
        return {
            "lat_top": _smallest_above(self._lats, lat),
            "lat_bottom": _largest_at_or_below(self._lats, lat),
            "lon_left": _largest_at_or_below(self._lons, lon),
            "lon_right": _smallest_above(self._lons, lon),
        }


def _largest_at_or_below(values: list[float], target: float) -> float | None:
    """The largest entry ``v`` such that ``v <= target``, else ``None``."""
    idx = bisect_right(values, target) - 1
    return values[idx] if idx >= 0 else None


def _smallest_above(values: list[float], target: float) -> float | None:
    """The smallest entry ``v`` such that ``v > target``, else ``None``."""
    idx = bisect_right(values, target)
    return values[idx] if idx < len(values) else None
