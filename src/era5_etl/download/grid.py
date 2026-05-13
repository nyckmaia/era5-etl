"""Grid alignment and rectangle algebra for size-bounded request planning.

This module provides the geometric primitives the planner needs to make
downloads deterministic and overlap-free:

- ``snap_area_to_grid`` rounds a bbox to the dataset's grid resolution so
  every chunk's coordinates are stable and comparable across runs.
- ``Rect`` + ``rect_intersect`` + ``rect_subtract`` let the manifest reason
  about which grid cells are already covered: ``rect_subtract(target,
  covered)`` returns the remaining sub-rectangles that still need to be
  downloaded.
- ``iter_grid_cells`` iterates the cell-center coordinates inside an area
  for diagnostics and tests.

All inputs use the ``[N, W, S, E]`` order that CDS API and the rest of
this codebase already use, with ``N >= S`` and ``W <= E``.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in (N, W, S, E) form.

    ``n >= s`` and ``w <= e`` are class invariants. An "empty" rectangle
    (n == s or w == e) is allowed and answers ``is_empty()``.
    """

    n: float
    w: float
    s: float
    e: float

    def __post_init__(self) -> None:
        if self.n < self.s:
            raise ValueError(f"n ({self.n}) must be >= s ({self.s})")
        if self.w > self.e:
            raise ValueError(f"w ({self.w}) must be <= e ({self.e})")

    @classmethod
    def from_area(cls, area: list[float] | tuple[float, ...]) -> Rect:
        """Build from a ``[N, W, S, E]`` list."""
        n, w, s, e = area
        return cls(n=float(n), w=float(w), s=float(s), e=float(e))

    def as_area(self) -> list[float]:
        """Return as ``[N, W, S, E]`` list."""
        return [self.n, self.w, self.s, self.e]

    def is_empty(self) -> bool:
        return self.n == self.s or self.w == self.e

    def area_deg2(self) -> float:
        """Area in degrees squared (planar approximation; fine for comparisons)."""
        return (self.n - self.s) * (self.e - self.w)


def _snap_down(value: float, step: float) -> float:
    """Round ``value`` down to the nearest multiple of ``step``."""
    return math.floor(value / step) * step


def _snap_up(value: float, step: float) -> float:
    """Round ``value`` up to the nearest multiple of ``step``."""
    return math.ceil(value / step) * step


def snap_area_to_grid(area: list[float], resolution: float) -> list[float]:
    """Expand ``[N, W, S, E]`` to multiples of ``resolution``.

    Snap rule: ``N -> ceil``, ``S -> floor``, ``W -> floor``, ``E -> ceil``.
    This guarantees the snapped bbox *contains* the original (no border
    cells lost). Idempotent on already-aligned input.

    Snapped values are rounded to 6 decimal places to absorb floating
    point drift from ``math.ceil(x / step) * step``.
    """
    if resolution <= 0:
        raise ValueError(f"resolution must be positive, got {resolution}")
    n, w, s, e = area
    return [
        round(_snap_up(n, resolution), 6),
        round(_snap_down(w, resolution), 6),
        round(_snap_down(s, resolution), 6),
        round(_snap_up(e, resolution), 6),
    ]


def snap_rect_to_grid(rect: Rect, resolution: float) -> Rect:
    """Same as :func:`snap_area_to_grid` but typed for :class:`Rect`."""
    return Rect.from_area(snap_area_to_grid(rect.as_area(), resolution))


def iter_grid_cells(area: list[float], resolution: float) -> Iterator[tuple[float, float]]:
    """Yield ``(lat, lon)`` cell centers inside ``area`` at ``resolution``.

    Iteration walks south->north, west->east. Useful for tests and for
    materialising the cell set of a rectangle when needed.
    """
    n, w, s, e = area
    lat = s + resolution / 2.0
    while lat <= n + 1e-9:
        lon = w + resolution / 2.0
        while lon <= e + 1e-9:
            yield (round(lat, 6), round(lon, 6))
            lon += resolution
        lat += resolution


def rect_intersect(a: Rect, b: Rect) -> Rect | None:
    """Return the intersection of two rectangles, or ``None`` if disjoint.

    Edge-touching rectangles (zero-area intersection) return ``None`` --
    intersection must have positive area to be reported.
    """
    n = min(a.n, b.n)
    s = max(a.s, b.s)
    w = max(a.w, b.w)
    e = min(a.e, b.e)
    if n <= s or w >= e:
        return None
    return Rect(n=n, w=w, s=s, e=e)


def rect_subtract(target: Rect, holes: list[Rect]) -> list[Rect]:
    """Return ``target`` minus the union of ``holes`` as a list of sub-rectangles.

    Algorithm: for each unique vertical strip between consecutive distinct
    ``w/e`` boundaries inside ``target``, find the set of y-intervals
    inside ``target`` not covered by any clipped hole, and emit one sub-rect
    per gap. Output rectangles are disjoint and their union equals
    ``target \\ union(holes)``.

    Complexity is O(N^2) in the number of holes -- fine for our use case
    (a handful of past chunks per (variable, date, hour) tile).

    Adjacent output rectangles are not merged; callers that want a minimum
    representation can apply :func:`merge_rects_horizontal` after.
    """
    if target.is_empty():
        return []
    relevant = [r for r in (rect_intersect(target, h) for h in holes) if r is not None]
    if not relevant:
        return [target]

    # Vertical sweep boundaries within target.
    xs = sorted({target.w, target.e, *(r.w for r in relevant), *(r.e for r in relevant)})
    xs = [x for x in xs if target.w <= x <= target.e]

    out: list[Rect] = []
    for x0, x1 in pairwise(xs):
        if x0 >= x1:
            continue
        # Holes that fully cover this vertical strip.
        strip_holes = [(r.s, r.n) for r in relevant if r.w <= x0 and r.e >= x1]
        strip_holes.sort()

        # Compute y-gaps inside [target.s, target.n] not covered by any strip_hole.
        cur = target.s
        gaps: list[tuple[float, float]] = []
        for hs, hn in strip_holes:
            if hn <= cur:
                continue
            if hs > cur:
                gaps.append((cur, min(hs, target.n)))
            cur = max(cur, hn)
            if cur >= target.n:
                break
        if cur < target.n:
            gaps.append((cur, target.n))

        for gs, gn in gaps:
            if gn > gs:
                out.append(Rect(n=gn, w=x0, s=gs, e=x1))

    return out


def merge_rects_horizontal(rects: list[Rect]) -> list[Rect]:
    """Merge rectangles that share the same ``(s, n)`` and abutting ``e/w``.

    Cheap pass to collapse the horizontal slabs produced by ``rect_subtract``.
    Not a full polygon-merger; just enough to keep chunk counts manageable.
    """
    if not rects:
        return []
    # Group by (s, n); within each group, sort by w and merge abutting.
    groups: dict[tuple[float, float], list[Rect]] = {}
    for r in rects:
        groups.setdefault((r.s, r.n), []).append(r)

    out: list[Rect] = []
    for (s, n), group in groups.items():
        group.sort(key=lambda r: r.w)
        cur = group[0]
        for r in group[1:]:
            if math.isclose(cur.e, r.w, abs_tol=1e-9):
                cur = Rect(n=n, w=cur.w, s=s, e=r.e)
            else:
                out.append(cur)
                cur = r
        out.append(cur)
    return out


def rect_union_area(rects: list[Rect]) -> float:
    """Total area covered by the union of ``rects`` (degrees squared).

    Computed via inclusion-exclusion on the sweep-line decomposition --
    each cell is counted once even if multiple rectangles cover it.
    """
    if not rects:
        return 0.0
    xs = sorted({r.w for r in rects} | {r.e for r in rects})
    total = 0.0
    for x0, x1 in pairwise(xs):
        if x0 >= x1:
            continue
        active = [(r.s, r.n) for r in rects if r.w <= x0 and r.e >= x1]
        if not active:
            continue
        active.sort()
        # Merge y-intervals.
        cur_s, cur_n = active[0]
        merged = 0.0
        for s, n in active[1:]:
            if s > cur_n:
                merged += cur_n - cur_s
                cur_s, cur_n = s, n
            else:
                cur_n = max(cur_n, n)
        merged += cur_n - cur_s
        total += merged * (x1 - x0)
    return total
