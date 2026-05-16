"""Per-dataset coverage index for cell-level inventory + smart-diff downloads.

A ``CoverageIndex`` wraps a small DuckDB file
(``<base>/climate_data_store_db/<dataset>/_coverage.duckdb``) that tracks,
for every (latitude, longitude, date, variable) tuple, *which hours of the
day* are present in local Parquet storage. Hours are stored as a 24-bit
bitmap (``UINTEGER``): bit ``h`` set means hour ``h`` UTC is on disk.

Schema v3 — storage-optimised layout. Instead of one flat row per
``(latitude, longitude, date, variable)`` with an enforced composite
PRIMARY KEY (whose ART index dominated the file), the data is stored as:

* ``cell(cell_id, latitude, longitude)`` — the per-dataset (lat, lon)
  dimension. Each distinct grid point is stored once; the two FLOAT
  columns no longer repeat on every date/variable row.
* ``coverage(cell_id, date, vars MAP(VARCHAR, UINTEGER))`` — **one row
  per (cell, date)**, with every variable's 24-bit hours bitmap nested
  in a ``MAP``. This removes the ``×n_var`` row blow-up and carries **no
  PRIMARY KEY and no secondary index** (no ART on the large table).

OR-merge semantics are unchanged (a cell's hours accumulate by bitwise
OR). They are produced by a ``GROUP BY ... BIT_OR(...)`` at write time and
a delete-affected-then-insert-merged transaction for incremental upserts.

The index is **derived state**: nothing depends on it beyond performance
and UI features. ``ensure_coverage_index`` rebuilds it from the parquet
files on disk if it's missing, empty, or an older schema -- safe to
delete and regenerate.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import polars as pl

from era5_etl.storage.paths import resolve_dataset_dir

if TYPE_CHECKING:
    from datetime import date
    from types import TracebackType

logger = logging.getLogger(__name__)

COVERAGE_DB_FILENAME = "_coverage.duckdb"
# v3: (lat, lon) dimension table + one MAP-nested row per (cell, date),
# no PRIMARY KEY / secondary index on the large table. A DB written by an
# older schema is detected on open and rebuilt from parquet from scratch.
COVERAGE_SCHEMA_VERSION = "3"

# Columns we never count as "variables" in upsert_from_dataframe.
_RESERVED_COLS: frozenset[str] = frozenset({"latitude", "longitude", "hour_utc", "date"})

# A partition directory is named ``date=YYYY-MM-DD``.
_PARTITION_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _ddl() -> str:
    """Return the CREATE statements for the coverage schema (v3).

    No PRIMARY KEY or index on ``coverage``: the composite-key ART was
    the single largest on-disk component, and the table is always
    rebuilt deduped from parquet so uniqueness is a property of the
    write path, not an enforced constraint. ``cell`` is tiny (one row
    per distinct grid point) and joined by hash, so it needs no index
    either.
    """
    return """
    CREATE TABLE IF NOT EXISTS cell (
        cell_id   INTEGER  NOT NULL,
        latitude  FLOAT    NOT NULL,
        longitude FLOAT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS coverage (
        cell_id INTEGER NOT NULL,
        date    DATE    NOT NULL,
        vars    MAP(VARCHAR, UINTEGER) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS coverage_meta (
        key   VARCHAR PRIMARY KEY,
        value VARCHAR
    );
    """


def _point_in_polygon(
    lat: float, lon: float, poly_lats: list[float], poly_lons: list[float]
) -> bool:
    """Ray-casting point-in-polygon test (no external deps).

    The polygon is given as parallel vertex lists. A closing vertex
    (first == last) is tolerated but not required.
    """
    n = len(poly_lats)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        lat_i, lon_i = poly_lats[i], poly_lons[i]
        lat_j, lon_j = poly_lats[j], poly_lons[j]
        # Standard PNPOLY: edge (i, j) crosses horizontal ray to the east of the point.
        if (lat_i > lat) != (lat_j > lat):
            x_intersect = (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


# ----------------------------------------------------------------------
# CoverageIndex
# ----------------------------------------------------------------------


class CoverageIndex:
    """Per-dataset coverage index backed by a tiny DuckDB file.

    Lifecycle:

    >>> with CoverageIndex("era5-land", base_dir) as cov:
    ...     cov.upsert_from_dataframe(df)
    ...     cov.query_grid_points()

    A single connection is held per instance. DuckDB serializes per-
    connection access, so reusing one ``CoverageIndex`` from multiple
    threads is safe; what is *not* safe is opening multiple
    ``CoverageIndex`` instances against the same file concurrently in
    write mode -- that's a user error.
    """

    def __init__(
        self,
        dataset: str,
        base_dir: str | Path,
        *,
        db_path_override: Path | None = None,
    ) -> None:
        self.dataset = dataset
        self.base_dir = Path(base_dir)
        self._dataset_dir = resolve_dataset_dir(base_dir, dataset)
        # ``db_path_override`` lets ``rebuild_from_parquet`` target a fresh
        # ``*.tmp`` file (built then atomically swapped) so the on-disk DB
        # is never grown in place -- DuckDB DELETE/CHECKPOINT do NOT shrink
        # an existing file.
        self._db_path = db_path_override or (
            self._dataset_dir / COVERAGE_DB_FILENAME
        )
        self._conn: duckdb.DuckDBPyConnection | None = None

    # ---- lifecycle ---------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self._db_path

    def __enter__(self) -> CoverageIndex:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except duckdb.Error:
                logger.debug("Error closing coverage DB %s", self._db_path, exc_info=True)
            self._conn = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        """Lazily open the connection and create the schema on first use."""
        if self._conn is not None:
            return self._conn
        self._dataset_dir.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_ddl())
        self._conn.execute(
            "INSERT OR IGNORE INTO coverage_meta VALUES (?, ?)",
            ["schema_version", COVERAGE_SCHEMA_VERSION],
        )
        return self._conn

    # ---- writes ------------------------------------------------------

    def upsert_from_dataframe(self, df: pl.DataFrame) -> int:
        """OR-merge each cell's per-variable hours bitmap into ``coverage``.

        ``df`` must have columns ``latitude``, ``longitude``, ``hour_utc``,
        ``date``, and one or more variable columns (any column not in the
        reserved set is treated as a variable). For each variable, the
        per-(lat, lon, date) bitmap ``BIT_OR(1 << hour_utc)`` is computed,
        new grid points are assigned a ``cell_id``, and the affected
        ``(cell_id, date)`` rows are recomputed as the OR-merge of any
        existing ``vars`` MAP with the staged masks (delete-then-insert
        inside one transaction, so the result is exactly the old behaviour
        without an enforced unique constraint).

        Returns the number of distinct ``(cell, date, variable)`` entries
        contributed by ``df`` (so a rebuild can sum "rows upserted").
        """
        required = {"latitude", "longitude", "hour_utc", "date"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"upsert_from_dataframe: DataFrame missing required columns: {sorted(missing)}"
            )

        var_cols = [c for c in df.columns if c not in _RESERVED_COLS]
        if not var_cols:
            return 0

        conn = self._connect()
        # Cast date to a real DATE type at staging time (CSVs/parquet may give us strings).
        # Polars' ``cast(pl.Date)`` accepts both Utf8 ("YYYY-MM-DD") and Date inputs.
        if df.schema["date"] != pl.Date:
            df = df.with_columns(pl.col("date").cast(pl.Date))

        total = 0
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE _stage (
                    latitude   FLOAT,
                    longitude  FLOAT,
                    date       DATE,
                    variable   VARCHAR,
                    hours_mask UINTEGER
                )
                """
            )
            for var in var_cols:
                # One row per (lat, lon, date, hour) for this var, nulls dropped.
                staging = df.select(
                    ["latitude", "longitude", "date", "hour_utc", var]
                ).filter(pl.col(var).is_not_null())
                if staging.is_empty():
                    continue
                conn.register("coverage_staging", staging.to_arrow())
                try:
                    conn.execute(
                        """
                        INSERT INTO _stage
                        SELECT
                            latitude,
                            longitude,
                            date,
                            ? AS variable,
                            CAST(BIT_OR(CAST((1::UINTEGER << hour_utc) AS UINTEGER))
                                 AS UINTEGER) AS hours_mask
                        FROM coverage_staging
                        WHERE hour_utc BETWEEN 0 AND 23
                        GROUP BY latitude, longitude, date
                        """,
                        [var],
                    )
                finally:
                    conn.unregister("coverage_staging")

            staged_n = conn.execute("SELECT COUNT(*) FROM _stage").fetchone()
            if not staged_n or staged_n[0] == 0:
                conn.execute("COMMIT")
                return 0

            # Assign cell_id to any (lat, lon) not seen before. ROW_NUMBER
            # is 1-based, so on an empty ``cell`` table (MAX = -1) the
            # first id is 0 and ids stay contiguous thereafter.
            conn.execute(
                """
                INSERT INTO cell (cell_id, latitude, longitude)
                SELECT
                    (SELECT COALESCE(MAX(cell_id), -1) FROM cell)
                        + ROW_NUMBER() OVER (ORDER BY latitude, longitude),
                    latitude,
                    longitude
                FROM (
                    SELECT DISTINCT s.latitude, s.longitude
                    FROM _stage s
                    LEFT JOIN cell c
                      ON c.latitude = s.latitude AND c.longitude = s.longitude
                    WHERE c.cell_id IS NULL
                ) d
                """
            )

            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE _se AS
                SELECT cl.cell_id, s.date, s.variable, s.hours_mask
                FROM _stage s
                JOIN cell cl
                  ON cl.latitude = s.latitude AND cl.longitude = s.longitude
                """
            )
            total_row = conn.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT cell_id, date, variable FROM _se)"
            ).fetchone()
            total = int(total_row[0]) if total_row else 0

            # OR-merge: existing MAP entries for the affected (cell, date)
            # keys + the staged masks, BIT_OR-folded per variable, then
            # re-packed into a MAP. Delete the affected rows and insert the
            # merged ones (one row per (cell, date)).
            conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE _merged AS
                WITH affected AS (
                    SELECT DISTINCT cell_id, date FROM _se
                ),
                existing AS (
                    SELECT
                        cov.cell_id,
                        cov.date,
                        unnest(map_keys(cov.vars))   AS variable,
                        unnest(map_values(cov.vars)) AS hours_mask
                    FROM coverage cov
                    SEMI JOIN affected a
                      ON a.cell_id = cov.cell_id AND a.date = cov.date
                ),
                all_e AS (
                    SELECT cell_id, date, variable, hours_mask FROM existing
                    UNION ALL
                    SELECT cell_id, date, variable, hours_mask FROM _se
                ),
                folded AS (
                    SELECT
                        cell_id, date, variable,
                        CAST(BIT_OR(hours_mask) AS UINTEGER) AS hours_mask
                    FROM all_e
                    GROUP BY cell_id, date, variable
                )
                SELECT
                    cell_id,
                    date,
                    map_from_entries(
                        list({'key': variable, 'value': hours_mask})
                    ) AS vars
                FROM folded
                GROUP BY cell_id, date
                """
            )
            conn.execute(
                """
                DELETE FROM coverage
                WHERE (cell_id, date) IN (SELECT cell_id, date FROM _merged)
                """
            )
            conn.execute(
                "INSERT INTO coverage SELECT cell_id, date, vars FROM _merged"
            )
            conn.execute("DROP TABLE IF EXISTS _merged")
            conn.execute("DROP TABLE IF EXISTS _se")
            conn.execute("DROP TABLE IF EXISTS _stage")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return total

    # ---- reads -------------------------------------------------------

    def query_grid_points(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        variable: str | list[str] | None = None,
        hours: list[int] | None = None,
    ) -> pl.DataFrame:
        """Return ``(latitude, longitude, days, vars)`` for every distinct cell.

        Optional filters:

        - ``date_from`` / ``date_to`` (inclusive on both ends)
        - ``variable``: a single name, OR a list of names (``IN (...)``).
          ``None`` / empty list = all variables (M07 multi-select).
        - ``hours``: list of hour integers (0-23). A cell is kept only if
          at least one of its (date, variable) entries has every selected
          hour set in its bitmap. ``None`` / empty list = no hour filter.
        """
        conn = self._connect()
        # Date filter is applied before the MAP is unnested (cheap, on the
        # narrow coverage row); variable/hours filters apply per entry.
        pre: list[str] = []
        params: list[Any] = []
        if date_from is not None:
            pre.append("cov.date >= ?")
            params.append(date_from)
        if date_to is not None:
            pre.append("cov.date <= ?")
            params.append(date_to)
        pre_where = f"WHERE {' AND '.join(pre)}" if pre else ""

        post: list[str] = []
        if isinstance(variable, str):
            post.append("ex.variable = ?")
            params.append(variable)
        elif variable:  # non-empty list
            placeholders = ", ".join("?" for _ in variable)
            post.append(f"ex.variable IN ({placeholders})")
            params.extend(variable)
        if hours:
            mask = 0
            for h in hours:
                mask |= 1 << int(h)
            post.append("(ex.hours_mask & ?) = ?")
            params.append(mask)
            params.append(mask)
        post_where = f"WHERE {' AND '.join(post)}" if post else ""

        sql = f"""
            WITH ex AS (
                SELECT
                    cov.cell_id,
                    cov.date,
                    unnest(map_keys(cov.vars))   AS variable,
                    unnest(map_values(cov.vars)) AS hours_mask
                FROM coverage cov
                {pre_where}
            )
            SELECT
                cl.latitude,
                cl.longitude,
                COUNT(DISTINCT ex.date)     AS days,
                COUNT(DISTINCT ex.variable) AS vars
            FROM ex
            JOIN cell cl USING (cell_id)
            {post_where}
            GROUP BY cl.latitude, cl.longitude
            ORDER BY cl.latitude, cl.longitude
        """
        return conn.execute(sql, params).pl()

    def query_cell_detail(self, latitude: float, longitude: float) -> pl.DataFrame:
        """Return ``(date, variable, hours_mask)`` for one specific cell.

        Uses exact float equality, matching what was stored. Returns an empty
        DataFrame (with the right columns) if the cell is unknown.
        """
        conn = self._connect()
        return conn.execute(
            """
            SELECT date, variable, hours_mask
            FROM (
                SELECT
                    cov.date,
                    unnest(map_keys(cov.vars))   AS variable,
                    unnest(map_values(cov.vars)) AS hours_mask
                FROM coverage cov
                JOIN cell cl USING (cell_id)
                WHERE cl.latitude = ? AND cl.longitude = ?
            )
            ORDER BY date, variable
            """,
            [latitude, longitude],
        ).pl()

    def query_region_summary(
        self,
        polygon_lats: list[float],
        polygon_lons: list[float],
    ) -> dict[str, Any]:
        """Summarise coverage inside a polygon (parallel lat/lon vertex lists).

        Polygon containment is computed in Python via a ray-casting test --
        this avoids depending on the DuckDB spatial extension which is not
        bundled in every wheel.

        Returns::

            {
                "n_points":           int,
                "date_range":         [min_date, max_date] | None,
                "vars_per_cell_avg":  float,
                "gaps":               [{"date": date, "missing_pct": float}, ...]
            }

        ``gaps`` lists dates for which < 100% of points-inside-polygon have
        any data (missing_pct = fraction of polygon cells with zero rows for
        that date). It's always ``[]`` for empty polygons or empty coverage.
        """
        if len(polygon_lats) != len(polygon_lons):
            raise ValueError("polygon_lats and polygon_lons must have the same length")
        if len(polygon_lats) < 3:
            return {
                "n_points": 0,
                "date_range": None,
                "vars_per_cell_avg": 0.0,
                "gaps": [],
            }

        conn = self._connect()
        # Distinct grid points that actually have coverage (cells with data).
        all_points = conn.execute(
            """
            SELECT DISTINCT cl.latitude, cl.longitude
            FROM cell cl
            SEMI JOIN coverage cov ON cov.cell_id = cl.cell_id
            """
        ).fetchall()

        inside: list[tuple[float, float]] = [
            (lat, lon)
            for lat, lon in all_points
            if _point_in_polygon(lat, lon, polygon_lats, polygon_lons)
        ]
        n_points = len(inside)
        if n_points == 0:
            return {
                "n_points": 0,
                "date_range": None,
                "vars_per_cell_avg": 0.0,
                "gaps": [],
            }

        inside_df = pl.DataFrame(
            {"latitude": [p[0] for p in inside], "longitude": [p[1] for p in inside]}
        )
        conn.register("region_cells", inside_df.to_arrow())
        try:
            row = conn.execute(
                """
                WITH rc AS (
                    SELECT cl.cell_id
                    FROM region_cells r
                    JOIN cell cl USING (latitude, longitude)
                ),
                ucov AS (
                    SELECT
                        cov.cell_id,
                        cov.date,
                        unnest(map_keys(cov.vars)) AS variable
                    FROM coverage cov
                    SEMI JOIN rc ON rc.cell_id = cov.cell_id
                )
                SELECT
                    (SELECT MIN(date) FROM ucov)                       AS min_date,
                    (SELECT MAX(date) FROM ucov)                       AS max_date,
                    (SELECT COALESCE(AVG(nv), 0.0) FROM (
                        SELECT cell_id, COUNT(DISTINCT variable) AS nv
                        FROM ucov GROUP BY cell_id
                    ))                                                 AS vars_avg
                """
            ).fetchone()
            min_date, max_date, vars_avg = row if row is not None else (None, None, 0.0)
            vars_avg = float(vars_avg) if vars_avg is not None else 0.0

            gaps_rows = conn.execute(
                """
                WITH rc AS (
                    SELECT cl.cell_id
                    FROM region_cells r
                    JOIN cell cl USING (latitude, longitude)
                ),
                per_date AS (
                    SELECT cov.date, COUNT(DISTINCT cov.cell_id) AS cells_with_data
                    FROM coverage cov
                    SEMI JOIN rc ON rc.cell_id = cov.cell_id
                    GROUP BY cov.date
                )
                SELECT date, cells_with_data
                FROM per_date
                ORDER BY date
                """
            ).fetchall()

            gaps: list[dict[str, Any]] = []
            for d, cells_with_data in gaps_rows:
                if cells_with_data >= n_points:
                    continue
                missing_pct = 1.0 - (cells_with_data / n_points)
                gaps.append({"date": d, "missing_pct": missing_pct})
        finally:
            conn.unregister("region_cells")

        return {
            "n_points": n_points,
            "date_range": [min_date, max_date] if min_date is not None else None,
            "vars_per_cell_avg": vars_avg,
            "gaps": gaps,
        }

    def diff(self, cells_df: pl.DataFrame) -> pl.DataFrame:
        """Cell-level diff: which hours are still missing per requested cell.

        ``cells_df`` columns:

            - ``latitude``, ``longitude`` (float)
            - ``date``                    (Date)
            - ``variable``                (str)
            - ``requested_mask``          (UINTEGER, 24 bits)

        Returns the same columns plus ``missing_mask`` =
        ``requested_mask & ~COALESCE(stored_mask, 0)``, filtered to
        ``missing_mask <> 0``. ``stored_mask`` is the per-variable value
        pulled out of the ``coverage.vars`` MAP for the matching
        ``(cell, date)``; an unknown cell/date yields the full request.
        """
        required = {"latitude", "longitude", "date", "variable", "requested_mask"}
        missing = required - set(cells_df.columns)
        if missing:
            raise ValueError(
                f"diff: cells_df missing required columns: {sorted(missing)}"
            )

        conn = self._connect()
        if cells_df.schema["date"] != pl.Date:
            cells_df = cells_df.with_columns(pl.col("date").cast(pl.Date))
        # Force requested_mask to UINTEGER so the bitwise ops type-check.
        cells_df = cells_df.with_columns(pl.col("requested_mask").cast(pl.UInt32))

        conn.register("diff_request", cells_df.to_arrow())
        try:
            return conn.execute(
                """
                WITH req AS (
                    SELECT
                        r.latitude,
                        r.longitude,
                        r.date,
                        r.variable,
                        r.requested_mask,
                        CAST(
                            COALESCE(cov.vars[r.variable], 0::UINTEGER)
                            AS UINTEGER
                        ) AS stored_mask
                    FROM diff_request r
                    LEFT JOIN cell cl
                      ON cl.latitude = r.latitude AND cl.longitude = r.longitude
                    LEFT JOIN coverage cov
                      ON cov.cell_id = cl.cell_id AND cov.date = r.date
                )
                SELECT
                    latitude,
                    longitude,
                    date,
                    variable,
                    requested_mask,
                    CAST(requested_mask & (~stored_mask) AS UINTEGER) AS missing_mask
                FROM req
                WHERE (requested_mask & (~stored_mask)) <> 0
                ORDER BY latitude, longitude, date, variable
                """
            ).pl()
        finally:
            conn.unregister("diff_request")

    def _compact_sorted(self) -> None:
        """Rewrite both tables in a compression-friendly order.

        Called once at the end of a rebuild (the tmp file is fresh and
        atomically swapped in, so recreating the tables here yields a
        clean, tightly RLE/dictionary-packed layout). ``date`` leads so
        the date column collapses to near-constant runs; ``cell_id``
        within a date keeps the small integer key contiguous.
        """
        conn = self._connect()
        conn.execute(
            "CREATE OR REPLACE TABLE coverage AS "
            "SELECT cell_id, date, vars FROM coverage ORDER BY date, cell_id"
        )
        conn.execute(
            "CREATE OR REPLACE TABLE cell AS "
            "SELECT cell_id, latitude, longitude FROM cell ORDER BY cell_id"
        )

    def checkpoint(self) -> None:
        """Flush the WAL and compact the database file.

        DuckDB does not auto-compact: without an explicit CHECKPOINT the
        on-disk file keeps growing as superseded row versions pile up.
        Called once at the end of a rebuild.
        """
        conn = self._connect()
        conn.execute("CHECKPOINT")

    def query_date_range(self) -> tuple[date | None, date | None]:
        """Return ``(min_date, max_date)`` across all coverage rows.

        ``(None, None)`` when the index is empty. Powers the inventory
        date-input prefill (M06).
        """
        conn = self._connect()
        row = conn.execute(
            "SELECT MIN(date), MAX(date) FROM coverage"
        ).fetchone()
        if not row or row[0] is None:
            return (None, None)
        return (row[0], row[1])

    def schema_version_on_disk(self) -> str | None:
        """Return the persisted schema version, or ``None`` if absent.

        An older-schema DB (pre-v3) either lacks the row or carries an
        older value, so callers can detect it and trigger a fresh
        rebuild.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM coverage_meta WHERE key = 'schema_version'"
            ).fetchone()
        except duckdb.Error:
            return None
        return str(row[0]) if row and row[0] is not None else None

    def stats(self) -> dict[str, Any]:
        """Return small summary stats for status reports + the auto-rebuild hook.

        ``total_rows`` keeps its historical meaning: the number of
        logical ``(cell, date, variable)`` entries (sum of MAP sizes),
        not the physical row count.
        """
        conn = self._connect()
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(len(map_keys(vars))), 0)            AS total_rows,
                COUNT(DISTINCT cell_id)                          AS n_cells,
                COUNT(DISTINCT date)                             AS n_dates
            FROM coverage
            """
        ).fetchone()
        total_rows, n_cells, n_dates = row if row else (0, 0, 0)
        nvar_row = conn.execute(
            """
            SELECT COUNT(DISTINCT v) FROM (
                SELECT unnest(map_keys(vars)) AS v FROM coverage
            )
            """
        ).fetchone()
        n_variables = nvar_row[0] if nvar_row else 0
        size = self._db_path.stat().st_size if self._db_path.exists() else 0
        return {
            "n_cells": int(n_cells or 0),
            "n_dates": int(n_dates or 0),
            "n_variables": int(n_variables or 0),
            "total_rows": int(total_rows or 0),
            "db_size_bytes": int(size),
        }


# ----------------------------------------------------------------------
# Rebuild from on-disk parquet
# ----------------------------------------------------------------------


def _list_partition_files(parquet_dir: Path) -> list[tuple[str, Path]]:
    """Return ``[(date_str, parquet_file), ...]`` for one dataset directory.

    Each ``date=YYYY-MM-DD`` subdir may contain one or more parquet files
    (one is the steady state; multiple is a transient mid-write artifact).
    """
    if not parquet_dir.exists():
        return []
    out: list[tuple[str, Path]] = []
    for partition_dir in sorted(parquet_dir.iterdir()):
        if not partition_dir.is_dir():
            continue
        m = _PARTITION_RE.match(partition_dir.name)
        if not m:
            continue
        date_str = m.group(1)
        for f in sorted(partition_dir.glob("*.parquet")):
            out.append((date_str, f))
    return out


def rebuild_from_parquet(
    dataset: str,
    base_dir: str | Path,
    *,
    progress: Any | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Rebuild ``_coverage.duckdb`` from every parquet file under the dataset.

    Idempotent. Writes into a fresh ``_coverage.duckdb.tmp`` and atomically
    swaps it into place: DuckDB never shrinks a file via DELETE/CHECKPOINT,
    so rebuilding in place would let the file grow without bound across
    runs. A pristine file is the only reliable way to keep it minimal
    (and it transparently replaces any older-schema DB).

    ``progress`` is an optional ``rich.progress.Progress`` instance. If
    provided, the function adds a per-file task and updates it. The function
    does **not** start/stop the Progress -- the caller controls its lifetime.
    """
    log = logger or logging.getLogger(__name__)
    parquet_dir = resolve_dataset_dir(base_dir, dataset)
    files = _list_partition_files(parquet_dir)

    task_id = None
    if progress is not None and files:
        task_id = progress.add_task(f"Rebuilding {dataset}", total=len(files))

    db_path = parquet_dir / COVERAGE_DB_FILENAME
    tmp_path = parquet_dir / (COVERAGE_DB_FILENAME + ".tmp")
    # Clear any stale tmp (+ its WAL) from a previously interrupted rebuild.
    for p in (tmp_path, Path(str(tmp_path) + ".wal")):
        if p.exists():
            p.unlink()

    total_rows = 0
    n_files = 0
    with CoverageIndex(dataset, base_dir, db_path_override=tmp_path) as cov:
        for date_str, fpath in files:
            try:
                df = pl.read_parquet(fpath)
            except (OSError, pl.exceptions.ComputeError) as exc:
                log.warning("Skipping unreadable parquet %s: %s", fpath, exc)
                if progress is not None and task_id is not None:
                    progress.advance(task_id)
                continue
            # Partition file does NOT carry the ``date`` column (it lives in
            # the directory name); re-inject it before upsert.
            if "date" not in df.columns:
                df = df.with_columns(pl.lit(date_str).alias("date"))
            try:
                rows = cov.upsert_from_dataframe(df)
                total_rows += rows
                n_files += 1
            except (ValueError, duckdb.Error) as exc:
                log.warning("Skipping %s during coverage rebuild: %s", fpath, exc)
            if progress is not None and task_id is not None:
                progress.advance(task_id)

        cov._compact_sorted()
        cov.checkpoint()
        final_stats = cov.stats()

    # Atomic swap. On Windows os.replace fails if a reader still holds the
    # destination; retry once, then fall back to a non-atomic replace so a
    # rebuild is never silently lost.
    try:
        os.replace(tmp_path, db_path)
    except OSError:
        try:
            if db_path.exists():
                db_path.unlink()
            os.replace(tmp_path, db_path)
        except OSError as exc:
            log.warning(
                "Could not swap rebuilt coverage DB into place "
                "(%s); leaving %s for next run.",
                exc,
                tmp_path,
            )
    final_stats["files_processed"] = n_files
    final_stats["rows_upserted"] = total_rows
    return final_stats


def ensure_coverage_index(
    dataset: str,
    base_dir: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    """Rebuild the coverage index if it is missing, empty, or stale.

    Returns ``True`` if a rebuild ran, ``False`` if the existing index was
    already populated at the current schema (or there was nothing to index
    in the first place).

    Intended to be called as a one-line guard at the start of ``download``
    and ``update`` flows: if the user has parquet data on disk but no
    coverage index (or an older-schema one), build it transparently before
    planning.
    """
    log = logger or logging.getLogger(__name__)
    parquet_dir = resolve_dataset_dir(base_dir, dataset)
    files = _list_partition_files(parquet_dir)
    if not files:
        return False  # Nothing to index.

    db_path = parquet_dir / COVERAGE_DB_FILENAME
    if db_path.exists():
        # Check the schema version FIRST and short-circuit to a rebuild on
        # mismatch -- the read queries (stats) assume the v3 layout and
        # would error against an older-schema table.
        with CoverageIndex(dataset, base_dir) as cov:
            on_disk = cov.schema_version_on_disk()
            if on_disk == COVERAGE_SCHEMA_VERSION:
                populated = cov.stats()["total_rows"] > 0
                if populated:
                    return False  # Already populated and current schema.
        if on_disk != COVERAGE_SCHEMA_VERSION:
            log.info(
                "Coverage index for %s is schema %s (want %s); rebuilding.",
                dataset,
                on_disk,
                COVERAGE_SCHEMA_VERSION,
            )

    log.info(
        "Coverage index for %s missing/empty/stale; rebuilding from %d "
        "parquet file(s)...",
        dataset,
        len(files),
    )
    rebuild_from_parquet(dataset, base_dir, logger=log)
    return True


__all__ = [
    "COVERAGE_DB_FILENAME",
    "COVERAGE_SCHEMA_VERSION",
    "CoverageIndex",
    "ensure_coverage_index",
    "rebuild_from_parquet",
]
