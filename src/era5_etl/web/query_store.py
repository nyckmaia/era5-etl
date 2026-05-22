"""Persisted SQL-editor query history (M03).

History is server-backed (survives across browsers/sessions), keyed by
*view name* (``era5`` / ``era5_land``) — the era5-etl analogue of the
datasus-etl per-subsystem history. Stored as JSON next to the user
config (reusing :func:`era5_etl.web.user_config._config_dir`) so it is
human-inspectable and trivially portable.

Templates are server-defined and read-only (no user authoring), matching
the datasus precedent. Favorites are a flag on history entries, not a
separate store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

#: Per-view cap. Oldest entries are evicted first; favourited entries are
#: never evicted (they are pinned, like datasus).
HISTORY_CAP = 200

_LOCK = threading.Lock()


def _store_path():
    return _config_dir() / "query_store.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"history": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s -- starting empty", path, exc)
        return {"history": {}}
    if not isinstance(data, dict):
        return {"history": {}}
    data.setdefault("history", {})
    if not isinstance(data["history"], dict):
        data["history"] = {}
    return data


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic on same volume


def list_history(view: str) -> list[dict[str, Any]]:
    """Return entries for ``view``, newest first."""
    with _LOCK:
        data = _load()
        entries = list(data["history"].get(view, []))
    # The bucket is stored in append order (oldest first). Reverse first so
    # that the stable ts-sort breaks same-millisecond ties newest-first.
    entries.reverse()
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return entries


def append_history(
    view: str, sql: str, rows: int, elapsed_ms: int
) -> list[dict[str, Any]]:
    """Append a run, evict to :data:`HISTORY_CAP`, return the new list."""
    entry = {
        "id": uuid.uuid4().hex,
        "sql": sql,
        "ts": int(time.time() * 1000),
        "rows": int(rows),
        "elapsed_ms": int(elapsed_ms),
        "name": None,
        "favorite": False,
    }
    with _LOCK:
        data = _load()
        bucket = list(data["history"].get(view, []))
        bucket.append(entry)
        # Evict oldest non-favorite entries past the cap.
        if len(bucket) > HISTORY_CAP:
            bucket.sort(key=lambda e: e.get("ts", 0))
            keep_favorites = [e for e in bucket if e.get("favorite")]
            others = [e for e in bucket if not e.get("favorite")]
            overflow = len(bucket) - HISTORY_CAP
            others = others[overflow:] if overflow < len(others) else []
            bucket = keep_favorites + others
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def patch_history(
    view: str, entry_id: str, *, name: Any = ..., favorite: Any = ...
) -> list[dict[str, Any]]:
    """Patch ``name`` / ``favorite`` on one entry. Unknown id is a no-op."""
    with _LOCK:
        data = _load()
        bucket = data["history"].get(view, [])
        for e in bucket:
            if e.get("id") == entry_id:
                if name is not ...:
                    e["name"] = name
                if favorite is not ...:
                    e["favorite"] = bool(favorite)
                break
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def delete_history(view: str, entry_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        bucket = [
            e for e in data["history"].get(view, []) if e.get("id") != entry_id
        ]
        data["history"][view] = bucket
        _save(data)
    return list_history(view)


def clear_history(view: str) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
        data["history"][view] = []
        _save(data)
    return []


# --- Templates (server-defined, read-only) --------------------------------

# Bilinear interpolation of every ERA5-LAND variable onto each INMET
# station, using the 4 enclosing grid corners and the built-in
# `bilinear_weights` macro. Exact-equality joins are safe here: the
# corner coords come straight from inmet's own `era5_land_*` columns.
_INMET_ERA5_LAND_INTERPOLATED_VIEW_SQL = """\
CREATE OR REPLACE VIEW vw_inmet_vs_era5_land_interpolated AS
WITH
  base AS (
    SELECT
      i.*,
      -- normalized longitude weight
      (
        (i.longitude - i.era5_land_lon_left) / NULLIF(i.era5_land_lon_right - i.era5_land_lon_left, 0)
      ) AS wx,
      -- normalized latitude weight
      (
        (i.era5_land_lat_top - i.latitude) / NULLIF(i.era5_land_lat_top - i.era5_land_lat_bottom, 0)
      ) AS wy
    FROM
      inmet i
  )
SELECT
  -- =====================================================
  -- IDENTIFICATION
  -- =====================================================
  b.station,
  b.date,
  b.hour_utc,
  -- =====================================================
  -- STATION LOCATION
  -- =====================================================
  b.latitude AS station_lat,
  b.longitude AS station_lon,
  -- =====================================================
  -- ORIGINAL OBSERVATION
  -- =====================================================
  b.temp_ar AS inmet_temperature,
  b.temp_orvalho AS inmet_temp_orvalho,
  b.umidade_relativa AS inmet_umidade_relativa,
  b.vento_direcao AS inmet_vento_direcao,
  b.vento_velocidade AS inmet_vento_velocidade,
  b.radiacao_global AS inmet_radicao_global,
  -- =====================================================
  -- INTERPOLATED ERA5 VARIABLES
  -- =====================================================
  -- ---------------------------------
  -- TEMPERATURE
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.temperature_2m,
    e_tr.temperature_2m,
    e_bl.temperature_2m,
    e_br.temperature_2m
  ) AS era5_temperature_2m_bilinear,
  -- ---------------------------------
  -- DEWPOINT
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.dewpoint_2m,
    e_tr.dewpoint_2m,
    e_bl.dewpoint_2m,
    e_br.dewpoint_2m
  ) AS era5_dewpoint_2m_bilinear,
  -- ---------------------------------
  -- WIND U
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.wind_u_10m,
    e_tr.wind_u_10m,
    e_bl.wind_u_10m,
    e_br.wind_u_10m
  ) AS era5_wind_u_10m_bilinear,
  -- ---------------------------------
  -- WIND V
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.wind_v_10m,
    e_tr.wind_v_10m,
    e_bl.wind_v_10m,
    e_br.wind_v_10m
  ) AS era5_wind_v_10m_bilinear,
  -- ---------------------------------
  -- SKIN TEMPERATURE
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.skin_temperature,
    e_tr.skin_temperature,
    e_bl.skin_temperature,
    e_br.skin_temperature
  ) AS era5_skin_temperature_bilinear,
  -- ---------------------------------
  -- TOTAL EVAPORATION
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.total_evaporation,
    e_tr.total_evaporation,
    e_bl.total_evaporation,
    e_br.total_evaporation
  ) AS era5_total_evaporation_bilinear,
  -- ---------------------------------
  -- FORECAST ALBEDO
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.forecast_albedo,
    e_tr.forecast_albedo,
    e_bl.forecast_albedo,
    e_br.forecast_albedo
  ) AS era5_forecast_albedo_bilinear,
  -- ---------------------------------
  -- NET SOLAR RADIATION
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.surface_net_solar_radiation,
    e_tr.surface_net_solar_radiation,
    e_bl.surface_net_solar_radiation,
    e_br.surface_net_solar_radiation
  ) AS era5_surface_net_solar_radiation_bilinear,
  -- ---------------------------------
  -- NET THERMAL RADIATION
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.surface_net_thermal_radiation,
    e_tr.surface_net_thermal_radiation,
    e_bl.surface_net_thermal_radiation,
    e_br.surface_net_thermal_radiation
  ) AS era5_surface_net_thermal_radiation_bilinear,
  -- ---------------------------------
  -- SENSIBLE HEAT FLUX
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.surface_sensible_heat_flux,
    e_tr.surface_sensible_heat_flux,
    e_bl.surface_sensible_heat_flux,
    e_br.surface_sensible_heat_flux
  ) AS era5_surface_sensible_heat_flux_bilinear,
  -- ---------------------------------
  -- LAI HIGH VEGETATION
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.leaf_area_index_high_vegetation,
    e_tr.leaf_area_index_high_vegetation,
    e_bl.leaf_area_index_high_vegetation,
    e_br.leaf_area_index_high_vegetation
  ) AS era5_leaf_area_index_high_vegetation_bilinear,
  -- ---------------------------------
  -- LAI LOW VEGETATION
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.leaf_area_index_low_vegetation,
    e_tr.leaf_area_index_low_vegetation,
    e_bl.leaf_area_index_low_vegetation,
    e_br.leaf_area_index_low_vegetation
  ) AS era5_leaf_area_index_low_vegetation_bilinear,
  -- ---------------------------------
  -- WIND SPEED
  -- ---------------------------------
  bilinear_weights (
    b.wx,
    b.wy,
    e_tl.wind_speed_10m,
    e_tr.wind_speed_10m,
    e_bl.wind_speed_10m,
    e_br.wind_speed_10m
  ) AS era5_wind_speed_10m_bilinear
FROM
  base b
  -- =====================================================
  -- TOP LEFT
  -- =====================================================
  LEFT JOIN era5_land e_tl ON e_tl.date = b.date
  AND e_tl.hour_utc = b.hour_utc
  AND e_tl.latitude = b.era5_land_lat_top
  AND e_tl.longitude = b.era5_land_lon_left
  -- =====================================================
  -- TOP RIGHT
  -- =====================================================
  LEFT JOIN era5_land e_tr ON e_tr.date = b.date
  AND e_tr.hour_utc = b.hour_utc
  AND e_tr.latitude = b.era5_land_lat_top
  AND e_tr.longitude = b.era5_land_lon_right
  -- =====================================================
  -- BOTTOM LEFT
  -- =====================================================
  LEFT JOIN era5_land e_bl ON e_bl.date = b.date
  AND e_bl.hour_utc = b.hour_utc
  AND e_bl.latitude = b.era5_land_lat_bottom
  AND e_bl.longitude = b.era5_land_lon_left
  -- =====================================================
  -- BOTTOM RIGHT
  -- =====================================================
  LEFT JOIN era5_land e_br ON e_br.date = b.date
  AND e_br.hour_utc = b.hour_utc
  AND e_br.latitude = b.era5_land_lat_bottom
  AND e_br.longitude = b.era5_land_lon_right;"""

# Companion query: read the interpolated view back, compute the INMET vs
# ERA5-LAND temperature gap for one station + year.
_INMET_ERA5_LAND_INTERPOLATED_QUERY_SQL = """\
SELECT
  station,
  "date",
  hour_utc,
  station_lat,
  station_lon,
  -- INMET
  inmet_temperature,
  inmet_temp_orvalho,
  inmet_umidade_relativa,
  inmet_vento_direcao,
  inmet_vento_velocidade,
  inmet_radicao_global,
  -- ERA5-LAND
  era5_temperature_2m_bilinear,
  era5_dewpoint_2m_bilinear,
  era5_wind_u_10m_bilinear,
  era5_wind_v_10m_bilinear,
  era5_skin_temperature_bilinear,
  era5_total_evaporation_bilinear,
  era5_forecast_albedo_bilinear,
  era5_surface_net_solar_radiation_bilinear,
  era5_surface_net_thermal_radiation_bilinear,
  era5_surface_sensible_heat_flux_bilinear,
  era5_leaf_area_index_high_vegetation_bilinear,
  era5_leaf_area_index_low_vegetation_bilinear,
  era5_wind_speed_10m_bilinear,
  -- DIFFERENCES
  (inmet_temperature - era5_temperature_2m_bilinear) AS temp_diff
FROM
  vw_inmet_vs_era5_land_interpolated
WHERE
  temp_diff IS NOT NULL
  AND date BETWEEN '2025-01-01' AND '2025-12-31'
  AND station = 'A726'
ORDER BY
  date,
  hour_utc;"""

_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "era5-land-recent",
        "name": "ERA5-LAND — latest 100 rows",
        "category": "era5_land",
        "sql": "SELECT * FROM era5_land\nORDER BY date DESC\nLIMIT 100;",
    },
    {
        "id": "era5-land-daily-mean",
        "name": "ERA5-LAND — daily mean per variable",
        "category": "era5_land",
        "sql": (
            "SELECT date, variable, AVG(value) AS mean_value\n"
            "FROM era5_land\n"
            "GROUP BY date, variable\n"
            "ORDER BY date, variable;"
        ),
    },
    {
        "id": "era5-recent",
        "name": "ERA5 — latest 100 rows",
        "category": "era5",
        "sql": "SELECT * FROM era5\nORDER BY date DESC\nLIMIT 100;",
    },
    {
        "id": "era5-grid-coverage",
        "name": "ERA5 — distinct grid points",
        "category": "era5",
        "sql": (
            "SELECT DISTINCT latitude, longitude\n"
            "FROM era5\n"
            "ORDER BY latitude, longitude;"
        ),
    },
    {
        "id": "join-era5-vs-land",
        "name": "Compare ERA5 vs ERA5-LAND at a point",
        "category": "join",
        "sql": (
            "SELECT a.date, a.variable,\n"
            "       a.value AS era5_value,\n"
            "       b.value AS era5_land_value\n"
            "FROM era5 a\n"
            "JOIN era5_land b\n"
            "  ON a.date = b.date\n"
            " AND a.variable = b.variable\n"
            " AND a.latitude = b.latitude\n"
            " AND a.longitude = b.longitude\n"
            "LIMIT 100;"
        ),
    },
    {
        "id": "era5-inmet-compare",
        "name": "era5_inmet — INMET vs ERA5/ERA5-LAND (4-corner, epsilon)",
        "category": "join",
        "sql": (
            "-- INMET stations aligned to their 4 enclosing ERA5 &\n"
            "-- ERA5-LAND grid corners on the same date+hour. Grid\n"
            "-- Float32 coords need an epsilon join (never '=').\n"
            "-- Review/edit, then Save as VIEW to persist as era5_inmet.\n"
            "CREATE OR REPLACE VIEW era5_inmet AS\n"
            "SELECT i.*,\n"
            "       e_tl.value AS era5_tl_value,\n"
            "       e_tr.value AS era5_tr_value,\n"
            "       e_bl.value AS era5_bl_value,\n"
            "       e_br.value AS era5_br_value,\n"
            "       l_tl.value AS era5_land_tl_value,\n"
            "       l_tr.value AS era5_land_tr_value,\n"
            "       l_bl.value AS era5_land_bl_value,\n"
            "       l_br.value AS era5_land_br_value\n"
            "FROM inmet i\n"
            "LEFT JOIN era5 e_tl ON e_tl.date=i.date "
            "AND e_tl.hour_utc=i.hour_utc\n"
            "  AND abs(e_tl.latitude-i.era5_lat_top)<1e-4\n"
            "  AND abs(e_tl.longitude-i.era5_lon_left)<1e-4\n"
            "LEFT JOIN era5 e_tr ON e_tr.date=i.date "
            "AND e_tr.hour_utc=i.hour_utc\n"
            "  AND abs(e_tr.latitude-i.era5_lat_top)<1e-4\n"
            "  AND abs(e_tr.longitude-i.era5_lon_right)<1e-4\n"
            "LEFT JOIN era5 e_bl ON e_bl.date=i.date "
            "AND e_bl.hour_utc=i.hour_utc\n"
            "  AND abs(e_bl.latitude-i.era5_lat_bottom)<1e-4\n"
            "  AND abs(e_bl.longitude-i.era5_lon_left)<1e-4\n"
            "LEFT JOIN era5 e_br ON e_br.date=i.date "
            "AND e_br.hour_utc=i.hour_utc\n"
            "  AND abs(e_br.latitude-i.era5_lat_bottom)<1e-4\n"
            "  AND abs(e_br.longitude-i.era5_lon_right)<1e-4\n"
            "LEFT JOIN era5_land l_tl ON l_tl.date=i.date "
            "AND l_tl.hour_utc=i.hour_utc\n"
            "  AND abs(l_tl.latitude-i.era5_land_lat_top)<1e-4\n"
            "  AND abs(l_tl.longitude-i.era5_land_lon_left)<1e-4\n"
            "LEFT JOIN era5_land l_tr ON l_tr.date=i.date "
            "AND l_tr.hour_utc=i.hour_utc\n"
            "  AND abs(l_tr.latitude-i.era5_land_lat_top)<1e-4\n"
            "  AND abs(l_tr.longitude-i.era5_land_lon_right)<1e-4\n"
            "LEFT JOIN era5_land l_bl ON l_bl.date=i.date "
            "AND l_bl.hour_utc=i.hour_utc\n"
            "  AND abs(l_bl.latitude-i.era5_land_lat_bottom)<1e-4\n"
            "  AND abs(l_bl.longitude-i.era5_land_lon_left)<1e-4\n"
            "LEFT JOIN era5_land l_br ON l_br.date=i.date "
            "AND l_br.hour_utc=i.hour_utc\n"
            "  AND abs(l_br.latitude-i.era5_land_lat_bottom)<1e-4\n"
            "  AND abs(l_br.longitude-i.era5_land_lon_right)<1e-4;"
        ),
    },
    {
        "id": "inmet-era5-land-interpolated-view",
        "name": (
            "vw_inmet_vs_era5_land_interpolated — INMET vs ERA5-LAND "
            "(bilinear)"
        ),
        "category": "join",
        "sql": _INMET_ERA5_LAND_INTERPOLATED_VIEW_SQL,
    },
    {
        "id": "inmet-era5-land-interpolated-query",
        "name": (
            "Query vw_inmet_vs_era5_land_interpolated — temp diff "
            "(station A726)"
        ),
        "category": "join",
        "sql": _INMET_ERA5_LAND_INTERPOLATED_QUERY_SQL,
    },
]


def list_templates() -> list[dict[str, Any]]:
    return [dict(t) for t in _TEMPLATES]


__all__ = [
    "HISTORY_CAP",
    "append_history",
    "clear_history",
    "delete_history",
    "list_history",
    "list_templates",
    "patch_history",
]
