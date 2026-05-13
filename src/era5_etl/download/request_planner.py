"""Plan CDS API requests so each one fits inside the configured size budget.

The Copernicus CDS API rejects requests whose estimated size exceeds an
internal ceiling (the "Request size" limit). Estimated size grows with the
geographic area, the number of variables, and the number of time steps. We
split aggressively in a fixed order to avoid surprises:

1. Take one month at a time (the natural CDS slicing).
2. If the month still exceeds the budget, split the area into a 2x2 grid;
   keep splitting until each sub-area fits *or* further area splits would
   stop helping (sub-area collapsed to a single grid point).
3. If sub-areas alone aren't enough, split the time axis: try halves of the
   month (15+15 days), then thirds (10+10+10), etc.
4. If time slicing still isn't enough, fall back to one variable per request.
5. If even that fails, raise ``RequestTooLargeError`` with actionable advice.

The result is a list of immutable ``RequestChunk`` objects. ``CDSDownloader``
iterates the list and asks the manifest whether each one is already done.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from era5_etl.config import DownloadConfig
from era5_etl.datasets import DatasetRegistry
from era5_etl.download.grid import snap_area_to_grid
from era5_etl.download.size_estimator import (
    AreaSplit,
    estimate_grid_points,
    estimate_request_size,
    split_area,
)
from era5_etl.exceptions import DownloadSizeError

if TYPE_CHECKING:
    from era5_etl.storage.manifest import Manifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestChunk:
    """One CDS API call's worth of (year, month, days, vars, area, hours)."""

    dataset: str
    variables: tuple[str, ...]
    year: int
    month: int
    days: tuple[int, ...]
    hours: tuple[str, ...]
    area: tuple[float, float, float, float]  # N, W, S, E
    chunk_id: str

    @property
    def is_full_month(self) -> bool:
        last_day = calendar.monthrange(self.year, self.month)[1]
        return self.days == tuple(range(1, last_day + 1))


@dataclass
class _Slice:
    """Mutable workhorse used while planning. Frozen ``RequestChunk`` is built at the end."""

    year: int
    month: int
    days: list[int]
    variables: list[str]
    area: list[float]  # N, W, S, E
    hours: list[str]
    area_label: str = "full"
    days_label: str = "full"
    var_label: str = "full"
    extra: dict[str, str] = field(default_factory=dict)


def plan_requests(config: DownloadConfig) -> list[RequestChunk]:
    """Produce a list of size-bounded chunks covering everything in ``config``.

    The requested area is snapped outward to the dataset's grid resolution
    before chunking, so every produced ``RequestChunk.area`` lies on cell
    boundaries. This makes chunks comparable across runs and lets the
    manifest reason about coverage in terms of grid cells.
    """
    start_date = datetime.strptime(config.start_date, "%Y-%m-%d")
    end_date = (
        datetime.strptime(config.end_date, "%Y-%m-%d") if config.end_date else datetime.now()
    )
    months = _enumerate_months(start_date.year, start_date.month, end_date.year, end_date.month)

    resolution = DatasetRegistry.get(config.dataset).GRID_RESOLUTION_DEG
    snapped_area = snap_area_to_grid(list(config.area), resolution)

    chunks: list[RequestChunk] = []
    for year, month in months:
        days = list(range(1, calendar.monthrange(year, month)[1] + 1))
        seed = _Slice(
            year=year,
            month=month,
            days=days,
            variables=list(config.variables),
            area=list(snapped_area),
            hours=list(config.hours),
        )
        for sub in _split_to_fit(seed, config):
            chunks.append(_finalise(sub, config.dataset))

    logger.info("Planned %d chunk(s) across %d month(s)", len(chunks), len(months))
    return chunks


# ---------------------------------------------------------------------------
# Splitter cascade
# ---------------------------------------------------------------------------

def _split_to_fit(slice_: _Slice, config: DownloadConfig) -> list[_Slice]:
    """Return one or more slices that each individually fit the size budget."""
    if _fits(slice_, config):
        return [slice_]

    # Tier 1: split area
    area_slices = _try_area_split(slice_, config)
    out: list[_Slice] = []
    for sub in area_slices:
        if _fits(sub, config):
            out.append(sub)
            continue

        # Tier 2: split days
        day_slices = _try_day_split(sub, config)
        for day_sub in day_slices:
            if _fits(day_sub, config):
                out.append(day_sub)
                continue

            # Tier 3: one variable per request
            var_slices = _try_variable_split(day_sub, config)
            for vsub in var_slices:
                if _fits(vsub, config):
                    out.append(vsub)
                    continue
                raise DownloadSizeError(
                    "Cannot fit single-variable, single-day-block, single-sub-area request "
                    f"({_estimate(vsub, config).estimated_mb:.1f} MB) "
                    f"under the {config.max_request_bytes / (1024 * 1024):.0f} MB limit. "
                    "Reduce hours/day, raise max_request_bytes, or pick a smaller area."
                )
    return out


def _try_area_split(slice_: _Slice, config: DownloadConfig) -> list[_Slice]:
    """Split the area as many times as needed to (try to) bring each piece under the limit.

    Sub-areas are snapped to the dataset grid after splitting, which makes
    chunk boundaries cell-aligned and dedup-friendly (the cell-level
    manifest in :mod:`era5_etl.storage.manifest` relies on this).
    """
    resolution = DatasetRegistry.get(config.dataset).GRID_RESOLUTION_DEG
    grid_points = estimate_grid_points(slice_.area, resolution)
    if grid_points <= 1:
        return [slice_]  # cannot split further on the grid

    # Start with 2 and keep doubling until each piece fits or we run out of grid points.
    splits: list[AreaSplit] = []
    n = 2
    while True:
        splits = split_area(slice_.area, n)
        max_grid = max(
            estimate_grid_points(s.as_list(), resolution) for s in splits
        )
        if max_grid <= 1 or n >= 64:
            break
        # If the biggest piece still doesn't fit, double splits.
        candidate = _replace_area(
            slice_,
            snap_area_to_grid(splits[0].as_list(), resolution),
            f"{n}-part-1",
        )
        if _fits(candidate, config):
            break
        n *= 2

    out: list[_Slice] = []
    seen_areas: set[tuple[float, float, float, float]] = set()
    for idx, s in enumerate(splits, start=1):
        snapped = snap_area_to_grid(s.as_list(), resolution)
        key = (snapped[0], snapped[1], snapped[2], snapped[3])
        if key in seen_areas:
            # Two arithmetic sub-rectangles collapsed to the same grid-snapped
            # rectangle -- skip the duplicate to avoid re-downloading.
            continue
        seen_areas.add(key)
        sub = _replace_area(slice_, snapped, f"{len(splits)}-part-{idx}")
        out.append(sub)
    return out


def _try_day_split(slice_: _Slice, config: DownloadConfig) -> list[_Slice]:
    """Try halves, thirds, ..., down to single days, until each block fits."""
    n_days = len(slice_.days)
    if n_days <= 1:
        return [slice_]

    for n_blocks in range(2, n_days + 1):
        blocks = _chunk_list(slice_.days, n_blocks)
        candidates = [
            _replace_days(slice_, days, f"{slice_.days[0]:02d}-{slice_.days[-1]:02d}-of-{n_blocks}")
            for days in blocks
        ]
        # Use the worst-case (largest) block to decide.
        worst = max(candidates, key=lambda c: len(c.days))
        if _fits(worst, config):
            # Rename labels using the actual block range for nicer chunk_ids.
            renamed: list[_Slice] = []
            for i, c in enumerate(candidates, start=1):
                first, last = c.days[0], c.days[-1]
                c.days_label = f"d{first:02d}-{last:02d}"
                renamed.append(c)
            return renamed
    # As a last resort, single-day blocks
    return [
        _replace_days(slice_, [d], f"d{d:02d}-{d:02d}")
        for d in slice_.days
    ]


def _try_variable_split(slice_: _Slice, config: DownloadConfig) -> list[_Slice]:
    """Fall back to one variable per request."""
    if len(slice_.variables) <= 1:
        return [slice_]
    out: list[_Slice] = []
    for v in slice_.variables:
        new = _Slice(
            year=slice_.year,
            month=slice_.month,
            days=list(slice_.days),
            variables=[v],
            area=list(slice_.area),
            hours=list(slice_.hours),
            area_label=slice_.area_label,
            days_label=slice_.days_label,
            var_label=v,
        )
        out.append(new)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fits(slice_: _Slice, config: DownloadConfig) -> bool:
    return not _estimate(slice_, config).exceeds_limit


def _estimate(slice_: _Slice, config: DownloadConfig):
    return estimate_request_size(
        num_variables=len(slice_.variables),
        num_hours=len(slice_.hours),
        num_days=len(slice_.days),
        area=slice_.area,
        dataset=config.dataset,
        max_bytes=config.max_request_bytes,
    )


def _replace_area(slice_: _Slice, area: list[float], label: str) -> _Slice:
    return _Slice(
        year=slice_.year,
        month=slice_.month,
        days=list(slice_.days),
        variables=list(slice_.variables),
        area=list(area),
        hours=list(slice_.hours),
        area_label=label,
        days_label=slice_.days_label,
        var_label=slice_.var_label,
    )


def _replace_days(slice_: _Slice, days: list[int], label: str) -> _Slice:
    return _Slice(
        year=slice_.year,
        month=slice_.month,
        days=list(days),
        variables=list(slice_.variables),
        area=list(slice_.area),
        hours=list(slice_.hours),
        area_label=slice_.area_label,
        days_label=label,
        var_label=slice_.var_label,
    )


def _chunk_list(items: list[int], n_chunks: int) -> list[list[int]]:
    n_chunks = min(n_chunks, len(items))
    if n_chunks <= 1:
        return [list(items)]
    size = -(-len(items) // n_chunks)  # ceil division
    return [items[i : i + size] for i in range(0, len(items), size)]


def _enumerate_months(y0: int, m0: int, y1: int, m1: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _finalise(slice_: _Slice, dataset: str) -> RequestChunk:
    """Build the frozen ``RequestChunk`` with a deterministic chunk_id."""
    safe_dataset = dataset.replace("-", "")
    parts = [
        safe_dataset,
        f"{slice_.year:04d}{slice_.month:02d}",
    ]
    if slice_.area_label != "full":
        parts.append(f"a-{slice_.area_label}")
    if slice_.days_label != "full":
        parts.append(slice_.days_label)
    if slice_.var_label != "full":
        parts.append(f"v-{_safe(slice_.var_label)}")
    chunk_id = "_".join(parts)

    return RequestChunk(
        dataset=dataset,
        variables=tuple(slice_.variables),
        year=slice_.year,
        month=slice_.month,
        days=tuple(slice_.days),
        hours=tuple(slice_.hours),
        area=(slice_.area[0], slice_.area[1], slice_.area[2], slice_.area[3]),
        chunk_id=chunk_id,
    )


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s)[:40]


# ---------------------------------------------------------------------------
# Incremental planning (manifest-aware)
# ---------------------------------------------------------------------------


def plan_incremental_requests(
    config: DownloadConfig,
    manifest: Manifest,
) -> list[RequestChunk]:
    """Plan only the chunks needed to cover what the manifest is missing.

    Algorithm per ``(variable, year, month)``:

    1. Snap the requested ``config.area`` to the dataset grid.
    2. Subtract every covered rectangle (from manifest records that already
       span the requested ``(days, hours)`` for ``variable``).
    3. For each remaining sub-rectangle, generate a seed slice
       ``(year, month, requested_days, [variable], sub_area, requested_hours)``
       and run it through the size-based splitter cascade.

    Returns ``[]`` when the manifest already covers the request -- the
    expected fast path when ``era5 update`` is run repeatedly.
    """
    start_date = datetime.strptime(config.start_date, "%Y-%m-%d")
    end_date = (
        datetime.strptime(config.end_date, "%Y-%m-%d") if config.end_date else datetime.now()
    )
    months = _enumerate_months(start_date.year, start_date.month, end_date.year, end_date.month)

    resolution = DatasetRegistry.get(config.dataset).GRID_RESOLUTION_DEG
    requested_hours = list(config.hours)
    requested_variables = list(config.variables)

    chunks: list[RequestChunk] = []
    for year, month in months:
        requested_days = list(range(1, calendar.monthrange(year, month)[1] + 1))
        for variable in requested_variables:
            missing = manifest.missing_rects_for(
                target_area=list(config.area),
                variable=variable,
                year=year,
                month=month,
                days=requested_days,
                hours=requested_hours,
                resolution=resolution,
            )
            for rect in missing:
                seed = _Slice(
                    year=year,
                    month=month,
                    days=list(requested_days),
                    variables=[variable],
                    area=rect.as_area(),
                    hours=list(requested_hours),
                    var_label=variable,
                )
                for sub in _split_to_fit(seed, config):
                    chunks.append(_finalise(sub, config.dataset))

    logger.info(
        "Incremental plan: %d chunk(s) across %d month(s) (manifest has %d records)",
        len(chunks),
        len(months),
        len(manifest),
    )
    return chunks
