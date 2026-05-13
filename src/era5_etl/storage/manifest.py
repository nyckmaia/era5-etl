"""Per-dataset manifest of downloaded/converted chunks.

A manifest is a small JSON file (``_manifest.json``) that lives inside each
dataset's storage directory. It records, for every ``RequestChunk`` that has
been successfully downloaded and converted, the chunk_id, the source NetCDF
filename, the parquet partitions it produced, the days/hours/variables
covered, the grid-aligned area, and a timestamp.

Cell-level coverage queries (used by ``era5 update --incremental``) are
derived on the fly from these records via :meth:`Manifest.missing_rects_for`:
walk the records, filter to the ones that cover the requested
``(variable, year, month, days, hours)``, project their rectangles, subtract
from the requested target, return the residual.

File schema::

    {
      "version": 2,
      "dataset": "era5-land",
      "updated_at": "2026-01-15T10:30:00Z",
      "chunks": {
        "<chunk_id>": {
          "chunk_id": "...",
          "year": 2024,
          "month": 1,
          "days": [1, 2, ..., 31],
          "hours": ["00:00", ..., "23:00"],
          "variables": ["2m_temperature"],
          "area": [N, W, S, E],
          "netcdf_filename": "...",
          "parquet_partitions": ["date=2024-01-01", ...],
          "size_bytes": 12345,
          "completed_at": "2026-01-15T10:25:00Z"
        }
      }
    }

Version 1 records (no ``days`` / ``hours`` fields) are read transparently:
missing fields default to "the whole month" (days 1..31) and "all 24 hours".
"""

from __future__ import annotations

import calendar
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from era5_etl.storage.paths import resolve_dataset_dir, resolve_manifest_path

if TYPE_CHECKING:
    from era5_etl.download.grid import Rect

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 2


@dataclass
class ChunkRecord:
    """One row of the manifest -- a successfully completed chunk."""

    chunk_id: str
    year: int
    month: int
    variables: list[str]
    area: list[float]
    days: list[int] = field(default_factory=list)
    hours: list[str] = field(default_factory=list)
    netcdf_filename: str = ""
    parquet_partitions: list[str] = field(default_factory=list)
    size_bytes: int = 0
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkRecord:
        year = int(data["year"])
        month = int(data["month"])
        # Back-compat: pre-v2 records assumed full-month, full-day coverage.
        days = list(data["days"]) if "days" in data else _full_month_days(year, month)
        hours = list(data["hours"]) if "hours" in data else _all_hours()
        return cls(
            chunk_id=data["chunk_id"],
            year=year,
            month=month,
            variables=list(data.get("variables", [])),
            area=list(data.get("area", [])),
            days=days,
            hours=hours,
            netcdf_filename=data.get("netcdf_filename", ""),
            parquet_partitions=list(data.get("parquet_partitions", [])),
            size_bytes=int(data.get("size_bytes", 0)),
            completed_at=data.get("completed_at", ""),
        )

    @classmethod
    def from_request_chunk(cls, chunk: Any) -> ChunkRecord:
        """Build a record from a :class:`RequestChunk` (planner output).

        Days, hours, variables, and area are captured verbatim so the manifest
        can answer "did we cover (variable, year, month, day, hour, cell)?"
        without consulting the planner again.
        """
        return cls(
            chunk_id=chunk.chunk_id,
            year=chunk.year,
            month=chunk.month,
            variables=list(chunk.variables),
            area=list(chunk.area),
            days=list(chunk.days),
            hours=list(chunk.hours),
        )


def _full_month_days(year: int, month: int) -> list[int]:
    return list(range(1, calendar.monthrange(year, month)[1] + 1))


def _all_hours() -> list[str]:
    return [f"{h:02d}:00" for h in range(24)]


class Manifest:
    """Mutable manifest for one dataset, backed by ``_manifest.json``.

    The class is intentionally small: load on init, mutate via ``record`` /
    ``forget`` / ``clear``, persist with ``save``. ``has(chunk_id)`` is the
    primary read API used by the download and convert stages.
    """

    def __init__(self, base_dir: str | Path, dataset: str) -> None:
        self.dataset = dataset
        self.base_dir = Path(base_dir)
        self.path = resolve_manifest_path(base_dir, dataset)
        self._chunks: dict[str, ChunkRecord] = {}
        self._load()

    # ---- read --------------------------------------------------------------

    def has(self, chunk_id: str) -> bool:
        return chunk_id in self._chunks

    def get(self, chunk_id: str) -> ChunkRecord | None:
        return self._chunks.get(chunk_id)

    def chunks(self) -> list[ChunkRecord]:
        return list(self._chunks.values())

    def chunk_ids(self) -> set[str]:
        return set(self._chunks.keys())

    def __len__(self) -> int:
        return len(self._chunks)

    def __contains__(self, chunk_id: object) -> bool:
        return isinstance(chunk_id, str) and chunk_id in self._chunks

    # ---- cell-level coverage ----------------------------------------------

    def covered_rects_for(
        self,
        variable: str,
        year: int,
        month: int,
        days: list[int] | tuple[int, ...],
        hours: list[str] | tuple[str, ...],
    ) -> list[Rect]:
        """Return the grid-aligned rectangles already covered for the request.

        A chunk record contributes its area iff it covers every day in
        ``days`` and every hour in ``hours`` for ``variable``. Partial
        coverage on the day/hour axis is treated as not covering -- a
        conservative choice that re-downloads rather than silently leaving
        gaps. Most user workflows pass identical day/hour patterns across
        runs, so this is rarely a problem.
        """
        from era5_etl.download.grid import Rect

        days_set = set(days)
        hours_set = set(hours)
        out: list[Rect] = []
        for chunk in self._chunks.values():
            if chunk.year != year or chunk.month != month:
                continue
            if variable not in chunk.variables:
                continue
            if not chunk.days or not chunk.hours or not chunk.area:
                # Legacy / partial record without enough info -- skip.
                continue
            if not days_set.issubset(set(chunk.days)):
                continue
            if not hours_set.issubset(set(chunk.hours)):
                continue
            try:
                out.append(Rect.from_area(chunk.area))
            except (ValueError, TypeError):
                continue
        return out

    def missing_rects_for(
        self,
        target_area: list[float],
        variable: str,
        year: int,
        month: int,
        days: list[int] | tuple[int, ...],
        hours: list[str] | tuple[str, ...],
        resolution: float,
    ) -> list[Rect]:
        """Compute ``target_area`` minus already-covered rectangles.

        Output rectangles are grid-aligned (``resolution``) and disjoint.
        Empty list means everything is already covered for that
        ``(variable, year, month, days, hours)`` tuple.
        """
        from era5_etl.download.grid import (
            Rect,
            merge_rects_horizontal,
            rect_subtract,
            snap_area_to_grid,
        )

        snapped = snap_area_to_grid(list(target_area), resolution)
        target = Rect.from_area(snapped)
        covered = self.covered_rects_for(variable, year, month, days, hours)
        if not covered:
            return [target]
        missing = rect_subtract(target, covered)
        return merge_rects_horizontal(missing)

    # ---- mutate ------------------------------------------------------------

    def record(self, chunk: ChunkRecord) -> None:
        if not chunk.completed_at:
            chunk.completed_at = _now_iso()
        self._chunks[chunk.chunk_id] = chunk

    def forget(self, chunk_id: str) -> None:
        self._chunks.pop(chunk_id, None)

    def clear(self) -> None:
        self._chunks.clear()

    # ---- persist -----------------------------------------------------------

    def save(self) -> None:
        # Ensure the dataset directory exists before writing.
        resolve_dataset_dir(self.base_dir, self.dataset).mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MANIFEST_VERSION,
            "dataset": self.dataset,
            "updated_at": _now_iso(),
            "chunks": {cid: asdict(rec) for cid, rec in self._chunks.items()},
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.debug("Saved manifest for %s (%d chunks) -> %s", self.dataset, len(self._chunks), self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load manifest %s (%s); starting empty", self.path, exc)
            return

        chunks_in = data.get("chunks", {})
        if isinstance(chunks_in, list):
            # Forward-compat: tolerate a list payload, key by chunk_id.
            chunks_in = {entry["chunk_id"]: entry for entry in chunks_in if "chunk_id" in entry}

        for chunk_id, entry in chunks_in.items():
            try:
                self._chunks[chunk_id] = ChunkRecord.from_dict(entry)
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed manifest entry %s: %s", chunk_id, exc)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
