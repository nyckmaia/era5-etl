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
from collections import deque
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

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
    from era5_etl.storage.coverage import CoverageIndex
    from era5_etl.storage.manifest import Manifest

logger = logging.getLogger(__name__)

# Above this many requested cells (n_lat × n_lon × n_date × n_var) the
# per-cell Smart-Diff expansion is infeasible in memory: building the dense
# Polars frame would allocate multiple GB and the Rust allocator aborts the
# *process* (not a catchable exception). Callers must bound the request
# arithmetically (see ``request_cell_count``) and skip the per-cell diff,
# falling back to the size-bounded ``plan_requests`` chunk plan, which never
# materialises a per-cell grid.
DIFF_MAX_CELLS = 20_000_000


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
        # Clip days to the requested [start_date, end_date] window. Only the
        # first/last month of a multi-month span is partial; interior months
        # use all their days. Previously this always seeded the FULL month,
        # so asking for 2 days downloaded the whole 31-day month.
        last_day = calendar.monthrange(year, month)[1]
        first = (
            start_date.day
            if (year, month) == (start_date.year, start_date.month)
            else 1
        )
        last = (
            end_date.day
            if (year, month) == (end_date.year, end_date.month)
            else last_day
        )
        days = list(range(first, last + 1))
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
    """Return one or more slices that each individually fit the size budget.

    Cascade order — **days → area → variables**:

    1. **Days** (greedy budget-packing). Keeps the full requested area
       and variable set in every chunk; each chunk fills the byte/field
       ceiling and writes to disjoint ``date=`` partitions. This is the
       primary tier — it produces the fewest, largest chunks.
    2. **Area** (2×2 doubling). A single day-block of the full area is
       still too large, so shrink the rectangle.
    3. **Variables** (one per request). Last resort — fragments the
       Parquet schema until the per-date partition merge reunifies it.
    """
    if _fits(slice_, config):
        return [slice_]

    # Tier 1: split days (greedy)
    day_slices = _try_day_split(slice_, config)
    out: list[_Slice] = []
    for day_sub in day_slices:
        if _fits(day_sub, config):
            out.append(day_sub)
            continue

        # Tier 2: split area
        area_slices = _try_area_split(day_sub, config)
        for sub in area_slices:
            if _fits(sub, config):
                out.append(sub)
                continue

            # Tier 3: one variable per request
            var_slices = _try_variable_split(sub, config)
            for vsub in var_slices:
                if _fits(vsub, config):
                    out.append(vsub)
                    continue
                est = _estimate(vsub, config)
                raise DownloadSizeError(
                    "Cannot fit single-variable, single-day-block, single-sub-area "
                    f"request under the configured limits: "
                    f"bytes={est.estimated_mb:.1f} MB / max={est.limit_mb:.0f} MB, "
                    f"fields={est.fields_count} / max={est.limit_fields}. "
                    "Reduce hours/day, raise max_request_bytes / max_request_fields, "
                    "or pick a smaller area."
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
    """Greedily pack consecutive days into blocks, each as large as the budget allows.

    Unlike an equal split (which would halve a 31-day month into two
    16-day blocks regardless of headroom), this fills each block right up
    to the byte/field ceiling and only opens a new block when the next
    day would overflow it — the fewest, largest day-blocks the CDS limits
    permit, each downloading close to the CDS per-request file cap.

    A block that is still too large on its own (a single day over budget)
    is handed downstream to area- then variable-splitting.
    """
    if len(slice_.days) <= 1:
        return [slice_]

    blocks: list[list[int]] = []
    current: list[int] = []
    for day in slice_.days:
        trial = [*current, day]
        if current and not _fits(_replace_days(slice_, trial, ""), config):
            blocks.append(current)
            current = [day]
        else:
            current = trial
    if current:
        blocks.append(current)

    return [
        _replace_days(slice_, days, f"d{days[0]:02d}-{days[-1]:02d}")
        for days in blocks
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
        max_fields=config.max_request_fields,
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
        # Same day-clipping as plan_requests: only the first/last month of a
        # multi-month span is partial; interior months use all their days.
        last_day = calendar.monthrange(year, month)[1]
        first = (
            start_date.day
            if (year, month) == (start_date.year, start_date.month)
            else 1
        )
        last = (
            end_date.day
            if (year, month) == (end_date.year, end_date.month)
            else last_day
        )
        requested_days = list(range(first, last + 1))
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


# ---------------------------------------------------------------------------
# Cell-level smart-diff planning (uses CoverageIndex)
# ---------------------------------------------------------------------------


def _hours_to_mask(hours: list[str]) -> int:
    """Convert ``["00:00", "12:00"]`` -> 24-bit UINTEGER mask."""
    mask = 0
    for h in hours:
        # Accept "HH:00" or "HH" or "HH:MM"
        hh = int(h.split(":")[0]) if ":" in h else int(h)
        if 0 <= hh <= 23:
            mask |= 1 << hh
    return mask


def _mask_to_hours(mask: int) -> list[str]:
    """Inverse of :func:`_hours_to_mask`. Output is sorted, ``["HH:00"]``."""
    return [f"{h:02d}:00" for h in range(24) if (mask >> h) & 1]


def _grid_axis(low: float, high: float, resolution: float) -> np.ndarray:
    """Return cell-center coordinates inside ``[low, high]`` at ``resolution`` step.

    The bbox is assumed pre-snapped to the grid (so ``low`` and ``high`` are
    multiples of ``resolution``); cell centers are at ``low + resolution/2``,
    ``low + 3*resolution/2``, ... up to (but not exceeding) ``high``.
    """
    if high <= low:
        return np.array([low + resolution / 2.0], dtype=float)
    n_cells = round((high - low) / resolution)
    if n_cells <= 0:
        return np.array([low + resolution / 2.0], dtype=float)
    centers = low + resolution / 2.0 + np.arange(n_cells) * resolution
    return np.round(centers, 6)


def _date_range(start: str, end: str | None) -> list[date_cls]:
    """Inclusive list of dates between ``start`` and ``end`` (or today)."""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = (
        datetime.strptime(end, "%Y-%m-%d").date()
        if end
        else datetime.now().date()
    )
    if e < s:
        return []
    days = (e - s).days
    return [s + timedelta(days=i) for i in range(days + 1)]


def request_cell_count(
    config: DownloadConfig,
    resolution: float,
    snapped_area: list[float],
) -> int:
    """Number of (lat, lon, date, variable) cells the request expands to.

    Pure arithmetic on the *axis* sizes only (each axis is tiny — a grid
    row/column count or a date list). It never builds the dense product,
    so it is safe to call before deciding whether the per-cell diff is
    feasible at all. ``0`` if any axis is empty.
    """
    n, w, s, e = snapped_area
    n_lat = int(_grid_axis(s, n, resolution).size)
    n_lon = int(_grid_axis(w, e, resolution).size)
    n_date = len(_date_range(config.start_date, config.end_date))
    n_var = len(config.variables)
    if not (n_lat and n_lon and n_date and n_var):
        return 0
    return n_lat * n_lon * n_date * n_var


def build_request_cells(
    config: DownloadConfig,
    resolution: float,
    snapped_area: list[float],
) -> pl.DataFrame:
    """Expand ``config`` into a (lat, lon, date, variable, requested_mask) DF.

    Public API consumed by the planner itself and by ``/api/pipeline/diff-preview``.
    Output schema: ``latitude (Float32), longitude (Float32), date (Date),
    variable (str), requested_mask (UInt32)`` — must stay stable since the
    coverage-index ``diff()`` JOIN relies on the dtypes matching exactly.

    Raises :class:`DownloadSizeError` if the request would expand to more
    than :data:`DIFF_MAX_CELLS` cells — materialising it would exhaust
    memory and abort the process. Callers must check
    :func:`request_cell_count` first and take the chunked fallback.
    """
    count = request_cell_count(config, resolution, snapped_area)
    if count > DIFF_MAX_CELLS:
        raise DownloadSizeError(
            f"Request expands to {count:,} cells (> {DIFF_MAX_CELLS:,}); "
            "the per-cell diff cannot be materialised. Use a chunked plan "
            "(plan_requests) instead."
        )

    n, w, s, e = snapped_area
    lats = _grid_axis(s, n, resolution)
    lons = _grid_axis(w, e, resolution)
    dates = _date_range(config.start_date, config.end_date)
    variables = list(config.variables)
    requested_mask = _hours_to_mask(list(config.hours))

    if not lats.size or not lons.size or not dates or not variables:
        return pl.DataFrame(
            schema={
                "latitude": pl.Float64,
                "longitude": pl.Float64,
                "date": pl.Date,
                "variable": pl.Utf8,
                "requested_mask": pl.UInt32,
            }
        )

    # Cartesian product via numpy broadcasting.
    n_lat, n_lon, n_date, n_var = len(lats), len(lons), len(dates), len(variables)
    total = n_lat * n_lon * n_date * n_var

    lat_arr = np.repeat(lats, n_lon * n_date * n_var).astype(float)
    lon_arr = np.tile(np.repeat(lons, n_date * n_var), n_lat).astype(float)

    # Build the date column as a Polars Date series directly (numpy object
    # arrays of python ``date`` instances cannot be cast through
    # ``pl.Series(..., dtype=pl.Date)`` reliably -- ComputeError 'cannot cast
    # Object type'). Constructing from a Python list of dates works.
    date_pattern = list(dates)  # length n_date
    # Tile to length total using Python list ops (n_lat * n_lon * n_date * n_var).
    # Layout: outer = n_lat*n_lon, then per-date repeated n_var times.
    date_list: list[date_cls] = []
    for d in date_pattern:
        date_list.extend([d] * n_var)
    date_full = date_list * (n_lat * n_lon)
    var_full = list(variables) * (n_lat * n_lon * n_date)

    return pl.DataFrame(
        {
            # CoverageIndex stores lat/lon as FLOAT (Float32). Match that type
            # so the LEFT JOIN in CoverageIndex.diff() compares apples to
            # apples -- a Float64/Float32 join would lose -49.95 to its
            # -49.950001 Float32 representation and treat the cell as missing.
            "latitude": pl.Series("latitude", lat_arr, dtype=pl.Float32),
            "longitude": pl.Series("longitude", lon_arr, dtype=pl.Float32),
            "date": pl.Series("date", date_full, dtype=pl.Date),
            "variable": pl.Series("variable", var_full, dtype=pl.Utf8),
            "requested_mask": pl.Series(
                "requested_mask", [requested_mask] * total, dtype=pl.UInt32
            ),
        }
    )


def _connected_components(grid: np.ndarray) -> list[np.ndarray]:
    """Return one boolean mask per 4-connected component of ``True`` cells.

    ``grid`` is a 2D boolean array. Returned masks have the same shape and
    are mutually disjoint; their OR equals ``grid``. 4-connectivity (N/S/E/W)
    is enough for our use case -- diagonal-only neighbours stay separate,
    which yields slightly more chunks but never misses cells.
    """
    if grid.size == 0 or not grid.any():
        return []
    visited = np.zeros_like(grid, dtype=bool)
    rows, cols = grid.shape
    components: list[np.ndarray] = []

    for r0 in range(rows):
        for c0 in range(cols):
            if not grid[r0, c0] or visited[r0, c0]:
                continue
            comp = np.zeros_like(grid, dtype=bool)
            queue: deque[tuple[int, int]] = deque()
            queue.append((r0, c0))
            visited[r0, c0] = True
            while queue:
                r, c = queue.popleft()
                comp[r, c] = True
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and grid[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        queue.append((nr, nc))
            components.append(comp)
    return components


def _bbox_from_cells(
    cell_lats: np.ndarray,
    cell_lons: np.ndarray,
    resolution: float,
) -> list[float]:
    """Return ``[N, W, S, E]`` bounding box for a set of cell-center coords.

    Each cell's footprint extends ``resolution/2`` from its center in every
    direction; the returned bbox encloses every cell footprint.
    """
    half = resolution / 2.0
    s = float(cell_lats.min()) - half
    n = float(cell_lats.max()) + half
    w = float(cell_lons.min()) - half
    e = float(cell_lons.max()) + half
    return [round(n, 6), round(w, 6), round(s, 6), round(e, 6)]


def plan_with_diff(
    config: DownloadConfig,
    base_dir: str | Path,
    coverage_index: CoverageIndex | None = None,
) -> list[RequestChunk]:
    """Plan chunks while subtracting cells already present in the coverage index.

    Algorithm:

    1. Snap the requested ``config.area`` to the dataset grid.
    2. Build a per-(lat, lon, date, variable) DataFrame with the requested
       hour bitmap.
    3. Ask :meth:`CoverageIndex.diff` what's missing (``missing_mask > 0``).
    4. Group missing cells by (year, month, variable). Within each group,
       project the missing cells onto a 2D (lat, lon) grid and compute
       4-connected components; one chunk per component, dates = union of
       dates that have any missing cell in the component, hours = union of
       missing-mask bits across the component restricted by the requested
       mask.
    5. Hand each seed slice to the existing :func:`_split_to_fit` cascade so
       size limits still apply.

    If the index is empty / non-existent, behaves identically to
    :func:`plan_requests`. If the index already covers everything, returns
    ``[]``.
    """
    # Local import avoids a circular import at module load.
    from era5_etl.storage.coverage import COVERAGE_DB_FILENAME, CoverageIndex
    from era5_etl.storage.paths import resolve_dataset_dir

    resolution = DatasetRegistry.get(config.dataset).GRID_RESOLUTION_DEG
    snapped_area = snap_area_to_grid(list(config.area), resolution)

    # Bound the per-cell diff arithmetically BEFORE materialising anything.
    # A state × decades request expands to 10^8+ cells; the dense frame
    # would OOM-abort the process. The size-bounded plan_requests cascade
    # is the designed memory-safe path for huge requests, so fall back to
    # it (the download still proceeds in full, just without the diff
    # optimisation).
    if request_cell_count(config, resolution, snapped_area) > DIFF_MAX_CELLS:
        logger.info(
            "plan_with_diff: request too large for a per-cell diff "
            "(> %d cells); falling back to plan_requests.",
            DIFF_MAX_CELLS,
        )
        return plan_requests(config)

    cells_df = build_request_cells(config, resolution, snapped_area)
    if cells_df.is_empty():
        return []

    # Short-circuit: no coverage DB yet -> behave like plan_requests.
    db_path = resolve_dataset_dir(base_dir, config.dataset) / COVERAGE_DB_FILENAME
    if coverage_index is None and not db_path.exists():
        logger.info(
            "plan_with_diff: no coverage index for %s; falling back to full plan_requests.",
            config.dataset,
        )
        return plan_requests(config)

    owns_cov = coverage_index is None
    cov = coverage_index if coverage_index is not None else CoverageIndex(
        config.dataset, base_dir
    )
    try:
        # If the (just-opened or passed-in) index has zero rows, treat as no diff.
        if cov.stats()["total_rows"] == 0:
            logger.info(
                "plan_with_diff: coverage index for %s is empty; "
                "falling back to full plan_requests.",
                config.dataset,
            )
            return plan_requests(config)
        missing_df = cov.diff(cells_df)
    finally:
        if owns_cov:
            cov.close()

    if missing_df.is_empty():
        logger.info("plan_with_diff: coverage already complete; nothing to download.")
        return []

    # Did diff change anything? If the missing mask equals the requested
    # mask for every requested cell, nothing is covered -- fall back to the
    # plain planner (saves regrouping overhead and yields identical chunks).
    if (
        missing_df.height == cells_df.height
        and missing_df["missing_mask"].eq(missing_df["requested_mask"]).all()
    ):
        logger.info(
            "plan_with_diff: zero overlap with coverage; using plan_requests output."
        )
        return plan_requests(config)

    # Add (year, month) columns for grouping.
    missing_df = missing_df.with_columns(
        pl.col("date").dt.year().alias("year"),
        pl.col("date").dt.month().alias("month"),
    )

    chunks: list[RequestChunk] = []
    grouped = missing_df.group_by(["year", "month", "variable"], maintain_order=True)
    for (year, month, variable), group in grouped:
        # Polars' ``group_by`` keys are typed ``object`` because the
        # group-key tuple is heterogeneous; cast to the concrete types
        # we know the schema produces.
        year_int = int(year)  # type: ignore[call-overload]
        month_int = int(month)  # type: ignore[call-overload]
        chunks.extend(
            _chunks_for_group(
                year=year_int,
                month=month_int,
                variable=str(variable),
                group=group,
                config=config,
                resolution=resolution,
                snapped_area=snapped_area,
            )
        )

    logger.info(
        "plan_with_diff: %d chunk(s) for %s (after diff vs coverage index).",
        len(chunks),
        config.dataset,
    )
    return chunks


def _chunks_for_group(
    *,
    year: int,
    month: int,
    variable: str,
    group: pl.DataFrame,
    config: DownloadConfig,
    resolution: float,
    snapped_area: list[float],
) -> list[RequestChunk]:
    """Build chunks for one (year, month, variable) slice of the missing-cells DF."""
    # Build a (lat, lon) presence grid covering the snapped bbox.
    n, w, s, e = snapped_area
    lats = _grid_axis(s, n, resolution)
    lons = _grid_axis(w, e, resolution)
    if lats.size == 0 or lons.size == 0:
        return []

    # Map an arbitrary lat/lon back to its nearest grid-cell index.
    # CoverageIndex stores Float32 so values come back as e.g. -49.950001;
    # rounding to a key would miss. Instead, compute the offset from the
    # bbox south/west edge and round to the nearest cell.
    def _lat_idx(v: float) -> int:
        idx = round((v - s - resolution / 2.0) / resolution)
        return idx if 0 <= idx < lats.size else -1

    def _lon_idx(v: float) -> int:
        idx = round((v - w - resolution / 2.0) / resolution)
        return idx if 0 <= idx < lons.size else -1

    # Mark every (lat, lon) that has at least one missing cell in this group.
    presence = np.zeros((lats.size, lons.size), dtype=bool)
    cell_lats = group["latitude"].to_numpy()
    cell_lons = group["longitude"].to_numpy()
    for la, lo in zip(cell_lats, cell_lons, strict=False):
        i = _lat_idx(float(la))
        j = _lon_idx(float(lo))
        if i >= 0 and j >= 0:
            presence[i, j] = True

    components = _connected_components(presence)
    if not components:
        return []

    # Pre-compute index columns on the group for fast filtering by component.
    group_with_idx = group.with_columns(
        pl.col("latitude").map_elements(
            lambda v: _lat_idx(float(v)),
            return_dtype=pl.Int64,
        ).alias("_lat_idx"),
        pl.col("longitude").map_elements(
            lambda v: _lon_idx(float(v)),
            return_dtype=pl.Int64,
        ).alias("_lon_idx"),
    )

    out: list[RequestChunk] = []
    for comp in components:
        comp_lat_idx, comp_lon_idx = np.where(comp)
        comp_lats = lats[comp_lat_idx]
        comp_lons = lons[comp_lon_idx]
        bbox = _bbox_from_cells(comp_lats, comp_lons, resolution)

        # Cells in this component.
        idx_pairs = set(zip(comp_lat_idx.tolist(), comp_lon_idx.tolist(), strict=False))
        # Filter group rows to this component.
        mask = [
            (int(li), int(lj)) in idx_pairs
            for li, lj in zip(
                group_with_idx["_lat_idx"].to_list(),
                group_with_idx["_lon_idx"].to_list(), strict=False,
            )
        ]
        sub = group_with_idx.filter(pl.Series(mask))
        if sub.is_empty():
            continue

        # Days = unique dates' day component within this (year, month).
        days = sorted({d.day for d in sub["date"].to_list()})
        # Hours = OR of missing_mask across the component, AND-ed with
        # requested_mask (defensive: missing_mask is already a subset).
        union_mask = 0
        for m in sub["missing_mask"].to_list():
            union_mask |= int(m)
        requested_mask = int(sub["requested_mask"][0])
        eff_mask = union_mask & requested_mask
        hours = _mask_to_hours(eff_mask)
        if not hours or not days:
            continue

        seed = _Slice(
            year=year,
            month=month,
            days=list(days),
            variables=[variable],
            area=list(bbox),
            hours=list(hours),
            var_label=variable,
        )
        for sub_slice in _split_to_fit(seed, config):
            out.append(_finalise(sub_slice, config.dataset))

    return out
