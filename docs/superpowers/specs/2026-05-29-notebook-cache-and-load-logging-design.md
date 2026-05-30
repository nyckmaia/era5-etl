# Design — Notebook data cache + load-source logging (XGBoost example)

**Date:** 2026-05-29
**Scope:** `/notebooks` XGBoost template (cells #4 and #7), the `log_model_run`
helper (cell #6), the **Model runs** table, and a migration of the already-saved
example notebook. No backend Python changes.

## Problem

In the bundled XGBoost notebook:

1. Cell #7 calls `df = inmet_with_era5_land(STATION_ID, DATE_START, DATE_END)`,
   which always hits DuckDB. Re-running with the **same** parameters re-queries
   the database needlessly.
2. There is no record of **how** a run's data was loaded (DB vs cache) or **how
   long** that load took, so the *Model runs* panel can't show it.
3. In the *Model runs* table, `n_test` renders as `8760.0000` (formatted as a
   float) when it is conceptually an integer.
4. Cell #4's `inmet_with_era5_land` join is correct but not optimized: the
   epsilon corner-join does not bound `era5_land` by date or space, so DuckDB
   tends to scan the whole grid 4×. The user's prior approach also produced an
   explicit **bilinear** interpolation that the current cell does not.

## Goals

- Transparent **on-disk cache** of the loaded DataFrame keyed by
  `(station_id, start, end)`; reused when valid, rebuilt from DuckDB when not.
- `log_model_run` automatically records `load_source` and `load_duration_s`.
- *Model runs* table shows dedicated **Load** and **Load time** columns and
  renders `n_test` (and other integer metrics) without decimals.
- Cell #4 query optimized (date + bounding-box pre-filter) and augmented with
  bilinear interpolation features.

## Non-goals

- No new backend module/endpoint. The cache logic lives **inside the notebook
  cells** so the user can read and edit it (consistent with the inline-helpers
  decision from the previous iteration).
- No change to how the INMET parquet is written (the 4 ERA5 + 4 ERA5-LAND
  neighbour edge-coordinates are already stored as columns; see Appendix).

## Decisions (from brainstorming)

| Topic | Decision |
|-------|----------|
| Cache file format | **Parquet** (preserves dtypes, faster/smaller than CSV) |
| Cache location | **`<data_dir>/_nb_cache/`** (next to the app's data; `ERA5_NB_DATA_DIR`) |
| Invalidation | **Params + data freshness** — reuse only if the cache file is newer than the most recent source parquet under `inmet/station=<id>/` and `era5-land/` |
| Load-info plumbing | **Auto via global state** — loader stores `__last_load_info__`; `log_model_run` reads it; the user's calls don't change |
| Cell #4 | **Optimize the query AND add bilinear features** |

## Architecture

All runtime logic is in notebook cells (template JSON + a migration of the saved
notebook). Only the *Model runs* renderer changes in the SPA.

```
Cell #4  inmet_with_era5_land(...)         # optimized SQL + bilinear columns
Cell #7  load_inmet_with_cache(...)        # NEW: cache wrapper; sets __last_load_info__
Cell #6  log_model_run(...)                # reads __last_load_info__ automatically
ModelRunsPanel.tsx                         # Load / Load time columns; integer n_test
```

Files touched:

- `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`
- `web-ui/src/components/notebooks/ModelRunsPanel.tsx`
- `web-ui/src/i18n/locales/{pt,en}.ts` (new column labels)
- Migration of `%APPDATA%/era5-etl/notebooks/<id>.json` (idempotent, `.bak`)

## Component 1 — Cache (Melhoria 01)

New helper defined inline in cell #7 (editable):

```python
def load_inmet_with_cache(station_id, start, end):
    # cache dir: <ERA5_NB_DATA_DIR>/_nb_cache/
    # file:      inmet_era5land__<station>__<start>__<end>__v<N>.parquet
    #            (vN = query-definition version; bump to invalidate on SQL change)
    # valid iff: file exists AND mtime(file) > newest mtime among source parquet
    #            under <data_dir>/climate_data_store_db/inmet/station=<station>/
    #            and .../era5-land/**.parquet
    # hit  -> pd.read_parquet(cache)          ; source = "csv cache"
    # miss -> inmet_with_era5_land(...)        ; write cache ; source = "db query"
    # always measure wall-clock load_duration_s
    # store globals()["__last_load_info__"] = {"source": ..., "duration_s": ...}
    return df
```

- The textual label stays `"csv cache"` per the user's wording even though the
  file is Parquet.
- Cache misses on any read/write error fall back to a fresh DB query (cache is
  best-effort; never fatal).
- Cell #7 body becomes `df = load_inmet_with_cache(STATION_ID, DATE_START, DATE_END)`.

### Freshness check

Newest source mtime = `max(mtime)` over:
`resolve_dataset_dir(data_dir, "inmet")/station=<id>/*.parquet` and
`resolve_dataset_dir(data_dir, "era5-land")/**/*.parquet`. If the cache file's
mtime is **not** strictly greater, treat as stale and rebuild. (The notebook
computes paths with `os`/`glob` on `ERA5_NB_DATA_DIR`; it does not import
internal path helpers, to stay self-contained and editable.)

## Component 2 — Logging (Melhoria 02) + n_test (Melhoria 03)

- `log_model_run` (cell #6) reads `__last_load_info__` from globals (default
  `{"source": "unknown", "duration_s": 0.0}` if absent) and merges
  `load_source` and `load_duration_s` into the `metrics` dict before POSTing.
  The user's final-cell call is unchanged.
- `ModelRunsPanel.tsx`:
  - Pull `load_source` and `load_duration_s` **out** of the generic metric
    columns and the chart's metric dropdown; render them as two dedicated
    columns: **Load** (text) and **Load time** (`N.NNs`).
  - Render integer-valued metrics (e.g. `n_test`) with no decimals; keep
    `toFixed(4)` for floats. Rule: `Number.isInteger(v) ? String(v) : v.toFixed(4)`.

## Component 3 — Cell #4 optimization + bilinear (Melhoria 04)

Rewrite `inmet_with_era5_land` SQL to bound `era5_land` before the corner join:

- `WHERE el.date BETWEEN start AND end`
- bounding-box: `el.latitude BETWEEN <bottom> AND <top>` and
  `el.longitude BETWEEN <left> AND <right>` (the station's stored edge coords),
  which lets DuckDB prune row groups (tile-sorted writer, min/max stats).
- Keep the epsilon (`abs(diff) < 1e-4`) only to pick each of the 4 corners.
- Output keeps the existing `era5_land_temp_tl/tr/bl/br` columns AND adds
  bilinear-interpolated columns (e.g. `era5_land_temp_bilinear`) computed from
  the normalized weights `wx, wy`, mirroring the user's `bilinear_weights`
  MACRO. The feature-engineering cell adds the bilinear column(s) to
  `feature_cols`.

Correctness notes carried into the template comments: use `station_id` (not
`station`); use epsilon, not exact equality on Float32 coords.

## Error handling

- Cache read/write failures → log a message, fall back to DB query; never raise.
- Missing `__last_load_info__` → logging defaults, no crash.
- `ModelRunsPanel` tolerates older runs without the new keys (columns show `—`).

## Testing / verification

- `py -3.12 -c json.load(...)` on every template (valid JSON).
- `npx tsc --noEmit` (SPA typecheck) and `npm run build`.
- `py -3.12 -m pytest tests/test_notebook_*.py` (21 tests).
- Idempotent migration of the saved notebook with `.bak` backup; re-runnable.

## Appendix — Parquet neighbour metadata (answer to the user's question)

`inmet_to_parquet.py` already stores, per station-year, **8 columns** of grid
neighbour edge coordinates: `era5_lat_top/lat_bottom/lon_left/lon_right` and
`era5_land_lat_top/lat_bottom/lon_left/lon_right`. The 4 corners of each grid
are the combinations of these edges, so the 4 ERA5 + 4 ERA5-LAND points are
fully encoded. They are stored as **columns** (queryable in SQL), not key-value
file metadata — the correct choice for joins; constant-per-file values compress
to near-zero via dictionary/RLE.

**Gap:** there are **no** haversine `dist_*` columns in the code, despite
mentions in `CLAUDE.md` / helper docstrings. Adding them would be new work and
is out of scope here.
