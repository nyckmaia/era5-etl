"""Per-dataset station index for INMET (point) inventory.

The grid ``CoverageIndex`` models a regular lat/lon grid with per-hour
bitmaps -- it does not fit INMET, which is station-based and stored as one
Parquet per ``station=<id>/<id>_<year>.parquet`` (no ``date=`` partition).
``StationIndex`` is the analogous derived index for that layout, kept in a
small DuckDB file (``_stations.duckdb``) next to the parquet tree.

Schema (v1)::

    station(station_id, latitude, longitude, altitude, uf, regiao, nome)
        -- one row per station; metadata taken from the station's most
           recent year (INMET re-surveys altitude over time).
    station_coverage(station_id, year, n_rows, date_min, date_max, vars)
        -- one row per (station, year); ``vars`` lists the canonical
           variables that have at least one non-null value that year.
    station_meta(key, value)  -- schema_version

Derived state: nothing depends on it beyond inventory/status. Rebuilt from
parquet on demand; safe to delete. Mirrors ``coverage.py``'s
fresh-tmp-then-atomic-swap rebuild (DuckDB never shrinks a file in place).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import polars as pl

from era5_etl.storage.paths import STATION_INDEX_FILENAME, resolve_dataset_dir
from era5_etl.transform.inmet_to_parquet import NEIGHBOUR_COL_NAMES

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)

STATION_SCHEMA_VERSION = "1"

#: Non-measurement columns carried by an INMET parquet file. Includes the
#: grid-neighbour / distance columns so they are never mistaken for one of
#: the 17 measurement variables in the station index.
_META_COLS: frozenset[str] = frozenset(
    {
        "station_id",
        "latitude",
        "longitude",
        "altitude",
        "uf",
        "regiao",
        "nome",
        "data_fundacao",
        "date",
        "hour_utc",
        *NEIGHBOUR_COL_NAMES,
    }
)

_YEAR_RE = re.compile(r"_(\d{4})\.parquet$", re.IGNORECASE)


def _ddl() -> str:
    return """
    CREATE TABLE IF NOT EXISTS station (
        station_id VARCHAR NOT NULL,
        latitude   FLOAT,
        longitude  FLOAT,
        altitude   FLOAT,
        uf         VARCHAR,
        regiao     VARCHAR,
        nome       VARCHAR
    );

    CREATE TABLE IF NOT EXISTS station_coverage (
        station_id VARCHAR NOT NULL,
        year       INTEGER NOT NULL,
        n_rows     BIGINT  NOT NULL,
        date_min   DATE,
        date_max   DATE,
        vars       VARCHAR[]
    );

    CREATE TABLE IF NOT EXISTS station_meta (
        key   VARCHAR PRIMARY KEY,
        value VARCHAR
    );
    """


class StationIndex:
    """Per-dataset station index backed by a tiny DuckDB file.

    >>> with StationIndex("inmet", base_dir) as idx:
    ...     idx.query_stations()
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
        self._db_path = db_path_override or (
            self._dataset_dir / STATION_INDEX_FILENAME
        )
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def __enter__(self) -> StationIndex:
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
                logger.debug(
                    "Error closing station DB %s", self._db_path, exc_info=True
                )
            self._conn = None

    def _connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is not None:
            return self._conn
        self._dataset_dir.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_ddl())
        self._conn.execute(
            "INSERT OR IGNORE INTO station_meta VALUES (?, ?)",
            ["schema_version", STATION_SCHEMA_VERSION],
        )
        return self._conn

    # ---- writes ------------------------------------------------------

    def upsert_file_summary(self, parquet_file: Path) -> int:
        """Index one station-year parquet file.

        Returns the number of data rows accounted for (0 if unreadable).
        """
        try:
            df = pl.read_parquet(parquet_file)
        except (OSError, pl.exceptions.ComputeError) as exc:
            logger.warning("Skipping unreadable parquet %s: %s", parquet_file, exc)
            return 0
        if df.is_empty() or "station_id" not in df.columns:
            return 0

        station_id = str(df.get_column("station_id")[0])
        year = self._year_of(df, parquet_file)
        if year is None:
            logger.warning("Could not determine year for %s; skipping", parquet_file)
            return 0

        var_cols = [c for c in df.columns if c not in _META_COLS]
        present_vars = [
            c for c in var_cols if df.get_column(c).null_count() < df.height
        ]

        def _first(col: str) -> Any:
            return df.get_column(col)[0] if col in df.columns else None

        date_col = (
            df.get_column("date") if "date" in df.columns else pl.Series([], dtype=pl.Date)
        )
        date_min = date_col.min() if len(date_col) else None
        date_max = date_col.max() if len(date_col) else None

        conn = self._connect()
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute("DELETE FROM station WHERE station_id = ?", [station_id])
            conn.execute(
                "INSERT INTO station VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    station_id,
                    _first("latitude"),
                    _first("longitude"),
                    _first("altitude"),
                    _first("uf"),
                    _first("regiao"),
                    _first("nome"),
                ],
            )
            conn.execute(
                "DELETE FROM station_coverage WHERE station_id = ? AND year = ?",
                [station_id, year],
            )
            conn.execute(
                "INSERT INTO station_coverage VALUES (?, ?, ?, ?, ?, ?)",
                [
                    station_id,
                    year,
                    df.height,
                    date_min,
                    date_max,
                    present_vars,
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return df.height

    @staticmethod
    def _year_of(df: pl.DataFrame, parquet_file: Path) -> int | None:
        m = _YEAR_RE.search(parquet_file.name)
        if m:
            return int(m.group(1))
        if "date" in df.columns:
            years = df.get_column("date").dt.year().drop_nulls()
            if len(years):
                # Polars' ``Series.min`` is typed to return its inner
                # ``Any``; the column is Int32 here so casting to int is
                # safe.
                return int(years.min())  # type: ignore[arg-type]
        return None

    def _dedupe_station_metadata(self) -> None:
        """Keep one ``station`` row per id: the most-recent year's metadata.

        ``upsert_file_summary`` already overwrites a station on every file,
        so after a rebuild the surviving row is whichever file was indexed
        last. Make it deterministic: pick the station's max-year parquet.
        """
        conn = self._connect()
        conn.execute(
            """
            CREATE OR REPLACE TABLE station AS
            WITH latest AS (
                SELECT station_id, MAX(year) AS y
                FROM station_coverage GROUP BY station_id
            )
            SELECT s.* FROM station s
            SEMI JOIN latest l ON l.station_id = s.station_id
            ORDER BY s.station_id
            """
        )

    def checkpoint(self) -> None:
        self._connect().execute("CHECKPOINT")

    # ---- reads -------------------------------------------------------

    def query_stations(self) -> pl.DataFrame:
        """One row per station: location + aggregated availability.

        Columns: ``station_id, latitude, longitude, altitude, uf, regiao,
        nome, year_min, year_max, n_years, date_min, date_max, n_vars``.
        Powers the inventory map (station points + popup).
        """
        conn = self._connect()
        return conn.execute(
            """
            SELECT
                s.station_id,
                s.latitude,
                s.longitude,
                s.altitude,
                s.uf,
                s.regiao,
                s.nome,
                MIN(c.year)        AS year_min,
                MAX(c.year)        AS year_max,
                COUNT(DISTINCT c.year) AS n_years,
                MIN(c.date_min)    AS date_min,
                MAX(c.date_max)    AS date_max,
                COALESCE(MAX(len(c.vars)), 0) AS n_vars
            FROM station s
            LEFT JOIN station_coverage c USING (station_id)
            GROUP BY s.station_id, s.latitude, s.longitude, s.altitude,
                     s.uf, s.regiao, s.nome
            ORDER BY s.station_id
            """
        ).pl()

    def query_station_detail(self, station_id: str) -> pl.DataFrame:
        """Per-year breakdown for one station."""
        conn = self._connect()
        return conn.execute(
            """
            SELECT year, n_rows, date_min, date_max, vars
            FROM station_coverage
            WHERE station_id = ?
            ORDER BY year
            """,
            [station_id],
        ).pl()

    def schema_version_on_disk(self) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM station_meta WHERE key = 'schema_version'"
            ).fetchone()
        except duckdb.Error:
            return None
        return str(row[0]) if row and row[0] is not None else None

    def stats(self) -> dict[str, Any]:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM station),
                (SELECT COUNT(DISTINCT year) FROM station_coverage),
                (SELECT COALESCE(SUM(n_rows), 0) FROM station_coverage)
            """
        ).fetchone()
        n_stations, n_years, total_rows = row if row else (0, 0, 0)
        size = self._db_path.stat().st_size if self._db_path.exists() else 0
        return {
            "n_stations": int(n_stations or 0),
            "n_years": int(n_years or 0),
            "total_rows": int(total_rows or 0),
            "db_size_bytes": int(size),
        }


# ----------------------------------------------------------------------
# Rebuild from on-disk parquet
# ----------------------------------------------------------------------


def list_station_files(parquet_dir: Path) -> list[Path]:
    """Return every ``station=<id>/*.parquet`` file for one dataset dir."""
    if not parquet_dir.exists():
        return []
    out: list[Path] = []
    for station_dir in sorted(parquet_dir.iterdir()):
        if not station_dir.is_dir() or not station_dir.name.startswith("station="):
            continue
        out.extend(sorted(station_dir.glob("*.parquet")))
    return out


def rebuild_from_parquet(
    dataset: str,
    base_dir: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Rebuild ``_stations.duckdb`` from every station parquet on disk.

    Idempotent. Writes a fresh ``*.tmp`` and atomically swaps it in, same
    rationale as ``coverage.rebuild_from_parquet``.
    """
    log = logger or logging.getLogger(__name__)
    parquet_dir = resolve_dataset_dir(base_dir, dataset)
    files = list_station_files(parquet_dir)

    db_path = parquet_dir / STATION_INDEX_FILENAME
    tmp_path = parquet_dir / (STATION_INDEX_FILENAME + ".tmp")
    for p in (tmp_path, Path(str(tmp_path) + ".wal")):
        if p.exists():
            p.unlink()

    total_rows = 0
    n_files = 0
    with StationIndex(dataset, base_dir, db_path_override=tmp_path) as idx:
        for fpath in files:
            try:
                rows = idx.upsert_file_summary(fpath)
                if rows:
                    total_rows += rows
                    n_files += 1
            except (ValueError, duckdb.Error) as exc:
                log.warning("Skipping %s during station rebuild: %s", fpath, exc)
        idx._dedupe_station_metadata()
        idx.checkpoint()
        final_stats = idx.stats()

    try:
        os.replace(tmp_path, db_path)
    except OSError:
        try:
            if db_path.exists():
                db_path.unlink()
            os.replace(tmp_path, db_path)
        except OSError as exc:
            log.warning(
                "Could not swap rebuilt station DB into place (%s); "
                "leaving %s for next run.",
                exc,
                tmp_path,
            )
    final_stats["files_processed"] = n_files
    final_stats["rows_indexed"] = total_rows
    return final_stats


def ensure_station_index(
    dataset: str,
    base_dir: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> bool:
    """Rebuild the station index if missing, empty, or stale. Returns whether it ran."""
    log = logger or logging.getLogger(__name__)
    parquet_dir = resolve_dataset_dir(base_dir, dataset)
    files = list_station_files(parquet_dir)
    if not files:
        return False

    db_path = parquet_dir / STATION_INDEX_FILENAME
    if db_path.exists():
        with StationIndex(dataset, base_dir) as idx:
            on_disk = idx.schema_version_on_disk()
            if on_disk == STATION_SCHEMA_VERSION and idx.stats()["n_stations"] > 0:
                return False
    log.info(
        "Station index for %s missing/empty/stale; rebuilding from %d "
        "parquet file(s)...",
        dataset,
        len(files),
    )
    rebuild_from_parquet(dataset, base_dir, logger=log)
    return True


__all__ = [
    "STATION_INDEX_FILENAME",
    "STATION_SCHEMA_VERSION",
    "StationIndex",
    "ensure_station_index",
    "list_station_files",
    "rebuild_from_parquet",
]
