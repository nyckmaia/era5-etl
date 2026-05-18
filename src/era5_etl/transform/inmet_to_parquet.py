"""INMET CSV to Parquet converter.

INMET publishes one CSV per station per year inside a yearly ZIP. The CSV is
**not** RFC-4180: latin-1 encoded, ``;`` separated, ``,`` decimal, 8
non-tabular metadata lines, then the tabular header on line 9, then hourly
rows.

The *formatting* evolves across years (see ``CLAUDE.md``): metadata keys
lose accents (``REGIÃO:`` -> ``REGIAO:``), the date syntax changes
(``2000-05-07`` vs ``2026/01/01``), the time syntax changes (``00:00`` vs
``0000 UTC``), the missing-value sentinel changes (``-9999`` vs empty). The
**17 measurement columns and their order are stable**, so this converter
maps them **positionally** (DATA, HORA, then the 17 variables in the order
declared in ``datasets/inmet/variables.yaml``) rather than by the
year-varying header text.

One CSV -> one Parquet at ``<output_dir>/station=<id>/<id>_<year>.parquet``
(no merge/dedup; each file is a self-contained station-year). Station
metadata (id, lat, lon, altitude, UF, region, name, foundation date) is
embedded as columns because it is per-file -- e.g. a station's recorded
altitude changes between years. ``date``/``hour_utc``/``latitude``/
``longitude`` are emitted in the same convention as ERA5 so the DuckDB
view and cross-dataset queries stay consistent. No columns are dropped and
no derived meteorological indices are computed.
"""

from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from era5_etl.config import StorageConfig, TransformConfig
from era5_etl.datasets import DatasetRegistry
from era5_etl.exceptions import ProcessingError

logger = logging.getLogger(__name__)

#: Mean Earth radius (km) for the haversine great-circle distance.
_EARTH_KM = 6371.0088

#: Grids the station is located within. Each INMET station gets, per grid,
#: the four enclosing grid-cell corner coordinates and the great-circle
#: distance (km) from the station to each corner -- enough to spatially
#: interpolate (e.g. IDW / bilinear) instead of snapping to one point.
#: ``(prefix, dataset_name)``; resolution + decimals come from the registry.
_GRID_NEIGHBOURS = (
    ("era5", "era5"),
    ("era5_land", "era5-land"),
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlat = rl2 - rl1
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rl1) * math.cos(rl2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _grid_block(lat: float, lon: float, res: float, decimals: int) -> dict[str, float]:
    """Enclosing grid cell + station→corner distances for one grid.

    Returns the four cell-edge coordinates (``lat_top`` = North/higher
    latitude, ``lat_bottom`` = South, ``lon_left`` = West/lower longitude,
    ``lon_right`` = East) and the great-circle distance from the station to
    each of the four corners. Edge coordinates are snapped to the grid and
    rounded exactly like the stored ERA5 coordinates (``decimals``) so an
    equality/epsilon join in the ``era5_inmet`` view lines up.
    """
    lat_bottom = round(math.floor(lat / res) * res, decimals)
    lat_top = round(lat_bottom + res, decimals)
    lon_left = round(math.floor(lon / res) * res, decimals)
    lon_right = round(lon_left + res, decimals)
    return {
        "lat_top": lat_top,
        "lat_bottom": lat_bottom,
        "lon_left": lon_left,
        "lon_right": lon_right,
        "top_left": _haversine_km(lat, lon, lat_top, lon_left),
        "top_right": _haversine_km(lat, lon, lat_top, lon_right),
        "bottom_left": _haversine_km(lat, lon, lat_bottom, lon_left),
        "bottom_right": _haversine_km(lat, lon, lat_bottom, lon_right),
    }


def _neighbour_columns(lat: float | None, lon: float | None) -> list[pl.Expr]:
    """Build the per-station grid-neighbour / distance literal columns.

    8 corner coordinates (4 per grid) + 8 distances (4 per grid) = 16
    columns. All NULL when the station has no coordinates.
    """
    exprs: list[pl.Expr] = []
    for prefix, ds_name in _GRID_NEIGHBOURS:
        cfg = DatasetRegistry.get(ds_name)
        res = float(cfg.GRID_RESOLUTION_DEG)
        dec = cfg.latlon_decimals
        block = (
            _grid_block(lat, lon, res, dec)
            if lat is not None and lon is not None
            else None
        )

        def _v(key: str) -> float | None:
            return None if block is None else block[key]

        exprs += [
            pl.lit(_v("lat_top")).cast(pl.Float32).alias(f"{prefix}_lat_top"),
            pl.lit(_v("lat_bottom")).cast(pl.Float32).alias(f"{prefix}_lat_bottom"),
            pl.lit(_v("lon_left")).cast(pl.Float32).alias(f"{prefix}_lon_left"),
            pl.lit(_v("lon_right")).cast(pl.Float32).alias(f"{prefix}_lon_right"),
            pl.lit(_v("top_left")).cast(pl.Float32).alias(f"dist_{prefix}_top_left"),
            pl.lit(_v("top_right")).cast(pl.Float32).alias(f"dist_{prefix}_top_right"),
            pl.lit(_v("bottom_left"))
            .cast(pl.Float32)
            .alias(f"dist_{prefix}_bottom_left"),
            pl.lit(_v("bottom_right"))
            .cast(pl.Float32)
            .alias(f"dist_{prefix}_bottom_right"),
        ]
    return exprs


#: Metadata/identity columns (everything that is NOT one of the 17
#: measurement variables). Kept in sync with :data:`_NEIGHBOUR_COL_NAMES`.
def _neighbour_col_names() -> list[str]:
    names: list[str] = []
    for prefix, _ in _GRID_NEIGHBOURS:
        names += [
            f"{prefix}_lat_top",
            f"{prefix}_lat_bottom",
            f"{prefix}_lon_left",
            f"{prefix}_lon_right",
            f"dist_{prefix}_top_left",
            f"dist_{prefix}_top_right",
            f"dist_{prefix}_bottom_left",
            f"dist_{prefix}_bottom_right",
        ]
    return names


NEIGHBOUR_COL_NAMES: tuple[str, ...] = tuple(_neighbour_col_names())

#: Encodings tried in order when decoding an INMET CSV.
_ENCODINGS = ("latin-1",)

#: A line is the tabular header if it starts with DATA/Data and the next
#: ``;``-delimited field is HORA/Hora (case/accent/spacing tolerant).
_HEADER_RE = re.compile(r"^\s*DATA[^;]*;\s*HORA", re.IGNORECASE)

#: Filename token fallback for the WMO code, e.g.
#: ``INMET_CO_DF_A001_BRASILIA_07-05-2000_A_31-12-2000.CSV`` -> ``A001``.
_FNAME_CODE_RE = re.compile(r"INMET_[^_]+_[^_]+_([A-Z0-9]+)_", re.IGNORECASE)


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _norm_key(raw: str) -> str:
    """Accent-insensitive, upper-cased metadata key (``REGIÃO`` -> ``REGIAO``)."""
    return _strip_accents(raw).strip().upper().replace(":", "").strip()


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort: never fail the whole file on one bad byte.
    return data.decode("latin-1", errors="replace")


def _extract_metadata(lines: list[str]) -> dict[str, str | None]:
    """Pull station metadata from the pre-header lines.

    Keys are matched accent-insensitively so the same code works for the
    2000-era (``REGIÃO:``, ``ESTAÇÃO:``, ``DATA DE FUNDAÇÃO (YYYY-MM-DD):``)
    and the 2026-era (``REGIAO:``, ``ESTACAO:``, ``DATA DE FUNDACAO:``)
    spellings.
    """
    meta: dict[str, str | None] = {
        "station_id": None,
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "uf": None,
        "regiao": None,
        "nome": None,
        "data_fundacao": None,
    }
    for line in lines:
        if ";" not in line:
            continue
        raw_key, _, raw_val = line.partition(";")
        key = _norm_key(raw_key)
        val = raw_val.strip()
        if not val:
            continue
        if "CODIGO" in key and "WMO" in key:
            meta["station_id"] = val
        elif key.startswith("LATITUDE"):
            meta["latitude"] = val
        elif key.startswith("LONGITUDE"):
            meta["longitude"] = val
        elif key.startswith("ALTITUDE"):
            meta["altitude"] = val
        elif key.startswith("REGIAO"):
            meta["regiao"] = val
        elif key == "UF":
            meta["uf"] = val
        elif key.startswith("ESTACAO"):
            meta["nome"] = val
        elif "FUNDACAO" in key:
            meta["data_fundacao"] = val
    return meta


def _find_header_index(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if _HEADER_RE.match(line):
            return i
    raise ProcessingError("INMET tabular header (DATA;HORA;...) not found")


def _num_expr(col: str, alias: str) -> pl.Expr:
    """Parse one INMET numeric column.

    Handles comma decimals (``3,7``), leading-comma decimals (``,8`` ->
    ``0.8``), the ``-9999`` sentinel and empty strings -> null. Output is
    Float32.
    """
    s = pl.col(col).cast(pl.Utf8).str.strip_chars()
    s = s.str.replace_all(",", ".")
    # ",8" -> "0.8" ; "-,8" -> "-0.8"
    s = s.str.replace(r"^(-?)\.", r"${1}0.")
    v = s.cast(pl.Float64, strict=False)
    return (
        pl.when(v == -9999.0).then(None).otherwise(v).cast(pl.Float32).alias(alias)
    )


class InmetToParquetConverter:
    """Convert INMET station CSVs to one Parquet file per station-year.

    Constructor mirrors :class:`NetCDFToParquetConverter` so the pipeline's
    source-handler dispatch can treat the two interchangeably.
    """

    def __init__(
        self,
        transform_config: TransformConfig,
        storage_config: StorageConfig,
        output_dir: Path,
        dataset: str | None = None,
    ) -> None:
        self.transform_config = transform_config
        self.storage_config = storage_config
        self.output_dir = Path(output_dir)
        self.dataset = dataset or "inmet"
        self.logger = logging.getLogger(__name__)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Canonical 17 measurement names, in CSV column order. The YAML is
        # the single source of truth for naming.
        self._var_names = [
            v.friendly_name or v.api_name
            for v in DatasetRegistry.get("inmet").variables
        ]

    # -- single file -----------------------------------------------------

    def convert_file(self, csv_path: Path) -> Path:
        """Convert one INMET CSV to a Parquet file; return its path."""
        try:
            text = _read_text(csv_path)
            lines = text.splitlines()
            header_idx = _find_header_index(lines)
            meta = _extract_metadata(lines[:header_idx])

            station_id = meta["station_id"] or self._station_from_name(csv_path)
            if not station_id:
                raise ProcessingError(
                    f"Could not determine station id for {csv_path.name}"
                )

            df = pl.read_csv(
                io.StringIO(text),
                separator=";",
                has_header=False,
                skip_rows=header_idx + 1,
                infer_schema_length=0,  # everything as Utf8; we parse explicitly
                truncate_ragged_lines=True,
            )
            df = self._shape(df, meta, station_id)

            year = self._year_of(df, csv_path)
            out_path = (
                self.output_dir / f"station={station_id}" / f"{station_id}_{year}.parquet"
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # `statistics=True` (default, made explicit) writes per
            # row-group min/max; combined with the (date, hour_utc) sort
            # in `_shape` this is what lets DuckDB prune row groups.
            df.write_parquet(
                out_path,
                compression=self.storage_config.parquet_compression,
                statistics=True,
            )
            self.logger.info(
                "Converted %s -> %s (%d rows)", csv_path.name, out_path.name, len(df)
            )
            return out_path
        except ProcessingError:
            raise
        except Exception as e:  # noqa: BLE001 -- wrap with file context
            raise ProcessingError(
                f"INMET CSV to Parquet conversion failed for {csv_path}: {e}"
            ) from e

    def _station_from_name(self, csv_path: Path) -> str | None:
        m = _FNAME_CODE_RE.search(csv_path.name)
        return m.group(1).upper() if m else None

    def _shape(
        self, df: pl.DataFrame, meta: dict[str, str | None], station_id: str
    ) -> pl.DataFrame:
        """Positional column mapping + value/time normalisation."""
        n_expected = 2 + len(self._var_names)  # DATA, HORA, + 17 vars
        if df.width < n_expected:
            raise ProcessingError(
                f"Expected >= {n_expected} columns, got {df.width}"
            )
        # Take the first n_expected columns positionally (a trailing ';'
        # produces an extra empty column we ignore).
        cols = df.columns[:n_expected]
        df = df.select(cols)
        df.columns = ["_data", "_hora", *self._var_names]

        lat = _parse_float(meta["latitude"])
        lon = _parse_float(meta["longitude"])
        alt = _parse_float(meta["altitude"])

        out = df.select(
            [
                pl.lit(station_id).alias("station_id"),
                pl.lit(lat).cast(pl.Float32).alias("latitude"),
                pl.lit(lon).cast(pl.Float32).alias("longitude"),
                pl.lit(alt).cast(pl.Float32).alias("altitude"),
                pl.lit(meta["uf"]).cast(pl.Utf8).alias("uf"),
                pl.lit(meta["regiao"]).cast(pl.Utf8).alias("regiao"),
                pl.lit(meta["nome"]).cast(pl.Utf8).alias("nome"),
                pl.lit(meta["data_fundacao"]).cast(pl.Utf8).alias("data_fundacao"),
                pl.coalesce(
                    [
                        pl.col("_data").str.strptime(
                            pl.Date, "%Y-%m-%d", strict=False
                        ),
                        pl.col("_data").str.strptime(
                            pl.Date, "%Y/%m/%d", strict=False
                        ),
                        pl.col("_data").str.strptime(
                            pl.Date, "%d/%m/%Y", strict=False
                        ),
                    ]
                ).alias("date"),
                pl.col("_hora")
                .cast(pl.Utf8)
                .str.replace("UTC", "")
                .str.strip_chars()
                .str.slice(0, 2)
                .cast(pl.Int8, strict=False)
                .alias("hour_utc"),
                *_neighbour_columns(lat, lon),
                *[_num_expr(name, name) for name in self._var_names],
            ]
        )
        # Drop rows whose date failed every format (defensive; INMET files
        # occasionally carry a stray blank trailing line), then sort
        # explicitly by (date, hour_utc). INMET CSVs are already
        # chronological, but an explicit sort *guarantees* monotonic
        # row-group min/max stats so DuckDB prunes row groups on
        # `WHERE date BETWEEN ... AND hour_utc IN (...)` (M03).
        return (
            out.filter(pl.col("date").is_not_null())
            .sort(["date", "hour_utc"])
        )

    def _year_of(self, df: pl.DataFrame, csv_path: Path) -> int:
        years = df.get_column("date").dt.year().drop_nulls()
        if len(years) > 0:
            return int(years.min())
        m = re.search(r"_A_\d{2}-\d{2}-(\d{4})", csv_path.name)
        if m:
            return int(m.group(1))
        raise ProcessingError(f"Could not determine year for {csv_path.name}")

    # -- directory -------------------------------------------------------

    def convert_directory(
        self,
        input_dir: Path,
        max_workers: int | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        cleanup: bool = False,
        raise_on_error: bool = True,
    ) -> dict[str, Any]:
        """Convert every INMET CSV under ``input_dir`` (recursively).

        Signature matches :meth:`NetCDFToParquetConverter.convert_directory`
        (``max_workers`` accepted for parity; INMET conversion is I/O-light
        and runs sequentially -- one small CSV -> one Parquet).

        **No error is swallowed.** Every per-file failure is logged *and*
        accumulated; the returned stats carry an ``errors`` list of
        ``{"file", "error"}``. When ``raise_on_error`` is True (the
        default, used by the pipeline/CLI) a single aggregated
        :class:`ProcessingError` listing *every* failed file is raised
        after the whole directory is processed -- so the user sees all
        problems at once and a partial/corrupt dataset never passes
        silently. Successfully converted parquet written before a failure
        stays on disk.
        """
        input_dir = Path(input_dir)
        csv_files = sorted(
            {*input_dir.rglob("*.CSV"), *input_dir.rglob("*.csv")}
        )
        total = len(csv_files)
        errors: list[dict[str, str]] = []
        stats: dict[str, Any] = {
            "total": total,
            "converted": 0,
            "skipped": 0,
            "failed": 0,
            "errors": errors,
        }
        if total == 0:
            self.logger.warning("No INMET CSV files found in %s", input_dir)
            if on_progress is not None:
                on_progress(0, 0, "No INMET CSV files to convert")
            return stats

        if on_progress is not None:
            on_progress(0, total, f"Converting {total} INMET CSV(s) to Parquet")

        for i, csv_file in enumerate(csv_files, start=1):
            try:
                self.convert_file(csv_file)
                stats["converted"] += 1
                if cleanup:
                    try:
                        csv_file.unlink()
                    except OSError as exc:
                        self.logger.warning(
                            "Could not delete %s: %s", csv_file.name, exc
                        )
            except Exception as e:  # noqa: BLE001 -- collect ALL, report at end
                stats["failed"] += 1
                errors.append({"file": str(csv_file), "error": str(e)})
                self.logger.error("Failed: %s: %s", csv_file.name, e)
            if on_progress is not None:
                on_progress(i, total, f"Converted {i}/{total}: {csv_file.name}")

        self.logger.info(
            "INMET conversion complete: %d converted, %d failed",
            stats["converted"],
            stats["failed"],
        )
        if errors and raise_on_error:
            detail = "\n".join(
                f"  - {e['file']}: {e['error']}" for e in errors
            )
            raise ProcessingError(
                f"INMET conversion failed for {len(errors)}/{total} file(s):\n"
                f"{detail}"
            )
        return stats
