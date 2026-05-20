# ERA5-ETL

Pipeline for downloading, processing, and analyzing climate data —
**ERA5** and **ERA5-Land** from the Copernicus Climate Data Store (CDS) and
**INMET** (Brazilian weather stations) — with a CLI, Python API, and
local web UI (inventory map, download wizard, SQL, and time-series
charts).

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](#)

## Overview

ERA5-ETL treats each product (`era5`, `era5-land`, `inmet`) as an
**independent plug-in dataset**. Each `DatasetConfig` has a
`SOURCE_KIND` (`cds_grid` or `inmet_zip`) and `pipeline/source_handlers.py`
dispatches the correct downloader/converter/refresh — with no
`if dataset == …` scattered across the codebase. Everything is written to
**Parquet** and exposed via DuckDB, the CLI, and a **local SPA**
(FastAPI + React + Vite).

```
   CDS API (ERA5 / ERA5-LAND)            portal.inmet.gov.br (INMET)
        │                                         │
 ┌──────▼───────┐  area 2x2→days→var       ┌───────▼──────────┐  1 ZIP/year
 │request_planner│                          │InmetPortalDownloader│ (1 CSV/station)
 └──────┬───────┘                          └───────┬──────────┘
 ┌──────▼───────┐  skip ready chunks        ┌──────▼───────────┐ latin-1, ;/,
 │ CDSDownloader │  (manifest)              │ InmetToParquet…  │ 17 vars + metadata
 └──────┬───────┘                          └──────┬───────────┘
  NetCDF in _tmp_netcdf/<ds>/               CSVs in _tmp_netcdf/inmet/<year>/
 ┌──────▼────────────────┐                  (1 CSV → 1 Parquet)
 │NetCDFToParquetConverter│                          │
 └──────┬────────────────┘                           │
        ▼                                             ▼
 climate_data_store_db/era5[-land]/        climate_data_store_db/inmet/
   date=YYYY-MM-DD/…part-001.parquet         station=<id>/<id>_<year>.parquet
   _manifest.json · _coverage.duckdb         _manifest.json · _stations.duckdb
        └───────────────────┬─────────────────────────┘
                  ┌─────────▼─────────┐
                  │ CLI · Web UI      │  + user VIEWs/MACROs
                  │ DuckDB · Python   │  (created on the /query page)
                  └───────────────────┘
```

## Features

- **Datasets as plug-ins** — each one lives in
  `src/era5_etl/datasets/<name>/` with its own `variables.yaml`, registered
  via `@DatasetRegistry.register`. Adding a new dataset requires no changes
  to the CLI, UI, or planner.
- **Source drives the pipeline** — `DatasetConfig.SOURCE_KIND` (`cds_grid` |
  `inmet_zip`) + `pipeline/source_handlers.py` select the
  downloader/converter/refresh. ERA5/ERA5-LAND come from the CDS
  (NetCDF → Parquet partitioned by `date=`, coverage index in
  `_coverage.duckdb`). INMET comes from the portal (yearly ZIP → 1 Parquet
  per station/year in `station=<id>/`, station index in `_stations.duckdb`).
- **INMET integrated** — `era5 pipeline --dataset inmet` downloads the
  yearly ZIP from the INMET portal, normalizes the CSV (latin-1, `;`/`,`,
  format that varies per year), maps the 17 variables positionally, and
  writes Parquet with `date`/`hour_utc`/`latitude`/`longitude` following
  the ERA5 convention. Each Parquet also carries the 4 ERA5/ERA5-LAND
  grid neighbours + distances for spatial comparison. Prerequisite: both
  ERA5 **and** ERA5-LAND must have at least the minimum data downloaded
  beforehand.
- **User-defined VIEWs/MACROs** — on the `/query` page, the user creates
  their own VIEWs/MACROs combining the base views (ERA5, ERA5-LAND,
  INMET) via the SQL editor ("Save VIEW") or the visual builder
  (columns/JOINs with epsilon-based coordinate joins). Definitions are
  persisted as SQL and replayed on every query; they show up in the
  SCHEMA menu. There is no longer an `era5_inmet` VIEW generated in
  Python — it survives as a one-click template
  (`era5-inmet-compare`) that the user reviews and saves.
- **Unified path layout** — `storage/paths.py` is the single source of
  truth: `climate_data_store_db/<dataset>/` for Parquet+manifest+DuckDB,
  `_tmp_netcdf/<dataset>/` for raw downloads. No scattered path-joining.
- **Hierarchical request planner** — `download/request_planner.py` splits
  requests with a fixed cascade: **area 2x2 → day blocks → per variable**,
  with each chunk fitting under `max_request_bytes`. Raises
  `DownloadSizeError` rather than issuing a request that would be rejected.
- **Per-dataset manifest** — `storage/manifest.py` keeps a JSON
  (`_manifest.json`) indexed by `chunk_id`. Both the download and the
  `era5 update` command consult the manifest to skip work already done.
- **Local Web UI** — Vite + React + TypeScript + Tailwind + TanStack
  Router/Query. Pages: **Dashboard**, **Inventory** (overlaid
  multi-system map — color/size/opacity/marker per system,
  ERA5/ERA5-LAND grid points, and INMET stations), **Download Wizard**
  (with a dedicated flow for INMET), **Query** (SQL/DuckDB), **Time
  Series** (Plotly chart notebook), **Settings**. Served by
  `era5 ui` (FastAPI).
- **Time Series** — `/timeseries`: chart-cell notebook (Plotly). Per
  series: view + variable + point/region (selectable on the map) +
  Y/Y2 axis; X = timestamp (date + UTC hour). Unit conversion
  **visualization-only** (K↔°C/°F presets or custom formula; raw data
  untouched), per-series statistics (min/max/mean/std/variance/IQR), and
  optional mean line.
- **IBGE geographic filters** — `--municipio`, `--uf`,
  `--regiao-imediata`, `--regiao-intermediaria` resolve `area` from the
  bundled IBGE shapefile.
- **Dry-run everywhere** — `era5 pipeline --dry-run` and
  `era5 download --dry-run` print the chunk plan + size estimate without
  contacting the CDS.
- **`--dataset all`** — runs CLI commands against `era5` and `era5-land`
  sequentially.
- **CDS strictly NetCDF4** — every CDS request uses
  `data_format="netcdf"` (GRIB was deliberately deferred). INMET arrives
  as CSV inside a ZIP — its own ingestion path, no CDS involved.

## Installation

### Prerequisites

- **Python 3.11+** (3.12 recommended).
- A [Copernicus CDS](https://cds.climate.copernicus.eu) account with an
  active API key.
- **For the Web UI:** `bun` (recommended) or `pnpm`/`npm`. The Hatch
  build hook auto-detects the available runner; with none, the SPA
  bundle is skipped and the UI is unavailable in the wheel (but the HTTP
  APIs still work).

### From source

```bash
git clone https://github.com/your-user/era5-etl.git
cd era5-etl
pip install -e ".[dev]"
```

On Windows with an isolated Python 3.12:

```powershell
py -3.12 -m pip install -e ".[dev]"
```

### CDS credentials

1. Create a `~/.cdsapirc` file (Linux/macOS) or `%USERPROFILE%\.cdsapirc`
   (Windows):

```ini
url: https://cds.climate.copernicus.eu/api
key: <YOUR-UID>:<YOUR-API-KEY>
```

2. Accept the dataset terms on the product page (e.g., ERA5-Land) before
   your first download.

## Quick start (CLI)

The main command is `era5` (alias: `era5-etl`).

### Inspect available variables

```bash
era5 variables --dataset era5-land
```

### Full pipeline (download + convert)

```bash
era5 pipeline \
  --data-dir ./data \
  --dataset era5-land \
  --start-date 2023-01-01 \
  --end-date 2023-01-31 \
  --var 2m_temperature \
  --var total_precipitation
```

Default geographic coverage: Brazil's bounding box. Use `--municipio`,
`--uf`, `--regiao-imediata`, or `--regiao-intermediaria` to restrict it.

### Dry-run (plan without downloading)

```bash
era5 pipeline --dataset era5-land \
  --start-date 2024-01-01 --end-date 2024-12-31 --dry-run
```

Prints the list of `chunk_id`s, days covered, area (N,W,S,E), and total
estimated size in MB.

### Run for all datasets

```bash
era5 pipeline --dataset all --start-date 2024-01-01 --end-date 2024-01-31
```

`all` includes `era5`, `era5-land`, and `inmet`. CDS-specific commands
(`update`/smart-diff) are a **no-op** for `inmet` with a clear message.

### INMET (Brazilian weather stations)

INMET is neither a grid nor CDS: 1 ZIP per year from the portal, 1 CSV
per station. The download requires that ERA5 **and** ERA5-LAND already
have the minimum on disk (needed for the INMET × grid comparison and the
per-station distances).

```bash
# first download the grid minimum
era5 pipeline --dataset era5      --start-date 2024-01-01 --end-date 2024-01-01 --var 2m_temperature
era5 pipeline --dataset era5-land --start-date 2024-01-01 --end-date 2024-01-01 --var 2m_temperature

# then INMET (the date range is translated to years)
era5 pipeline --dataset inmet --start-date 2000-01-01 --end-date 2026-12-31
```

### ERA5 × INMET comparison

There is no longer an `era5 era5-inmet` command. The comparison is
created by the user on the `/query` page: open the **era5_inmet**
template (Templates tab), review the SQL, and click **Save VIEW**, or
build it via the visual builder (epsilon-based JOIN on coordinates).
Then query it normally, e.g., `SELECT * FROM era5_inmet WHERE station_id = 'A001'`.

### Incremental update

`era5 update` computes, per `(variable, year-month)`, the **cell-level
coverage diff** between the requested area and what the manifest records
as already downloaded, and only issues a CDS request for the missing
rectangles — crontab-ready:

```bash
era5 update --dataset era5-land --start-date 2020-01-01 --uf SP
```

The next run with `--uf RJ` (whose bbox overlaps SP's) downloads
**only the disjoint region**. Add `--dry-run` to list the missing
rectangles without contacting the CDS. `update` is CDS-only — for
`inmet` it simply warns and does nothing (per-year reuse is via the
manifest).

### Country and IBGE regions

`--pais` is the top-level flag for geographic scope (default:
`Brasil`). With no other flags, it returns the country's bbox:

```bash
era5 pipeline --pais Brasil --start-date 2024-01-01 --end-date 2024-01-31
```

Combined with IBGE subregion flags, it restricts inside the country:

```bash
era5 pipeline --pais Brasil --uf SP   # SP bbox
era5 pipeline --pais Brasil --municipio Campinas --uf SP  # municipio + UF (disambiguates)
```

The flags `--municipio`, `--regiao-imediata`, `--regiao-intermediaria`,
`--uf` are mutually exclusive (except `--municipio + --uf`). Unsupported
countries raise an error — add a line to
`src/era5_etl/_data/ibge/pais.csv` to enable.

### Deduping pre-existing data

For datasets created before v0.3.0 (which could write overlapping files
within the same partition):

```bash
era5 dedup --dataset all
```

Reads each `date=YYYY-MM-DD/` partition, collapses duplicate rows by
`(latitude, longitude, hour_utc)`, and rewrites. Idempotent.

### Status

```bash
era5 status --dataset all
```

Reports, per dataset: number of Parquet files, total size, partitions
(`date=` for grid, `station=` for INMET), first/last partition, and how
many records are in the manifest.

### SQL query

```bash
era5 query \
  "SELECT date, AVG(temperature_2m) FROM era5_land GROUP BY 1 ORDER BY 1" \
  --dataset era5-land --limit 50
```

The DuckDB view (`<dataset>` (hyphens become underscores: `era5-land` → view `era5_land`)) is created on demand, pointing to the
dataset's Parquet directory.

**Two-layer automatic pruning:**

1. **Hive directory** — `WHERE date BETWEEN ...` prunes partitions
   before opening any file (the `date` column is in the folder name).
2. **Row-group statistics** — `WHERE latitude BETWEEN ...` leverages the
   internal `(latitude, longitude, hour_utc)` sort applied on write.
   Per-row-group min/max are tight → DuckDB skips entire row groups
   that don't intersect the spatial filter. **No auxiliary Hive
   columns** (such as `lat_bucket` or `lon_bucket`) are needed; the
   query is natural over real `latitude`/`longitude`.

Example of a natural query that leverages both layers:

```sql
SELECT *
FROM era5_land
WHERE date BETWEEN '2024-06-01' AND '2024-08-31'   -- partition pruning
  AND latitude  BETWEEN -25.0 AND -22.0            -- row-group pruning
  AND longitude BETWEEN -48.0 AND -45.0            -- row-group pruning
  AND hour_utc IN (12, 13, 14);                    -- row-group pruning
```

### Web UI

```bash
era5 ui --data-dir ./data --port 8788
```

Opens the browser at `http://127.0.0.1:8788/`. The SPA is served by
FastAPI from `src/era5_etl/web/static/` (generated at build time).

### Auxiliary commands

```bash
era5 convert   --dataset era5-land           # convert only (NetCDF/CSV -> Parquet)
era5 download  --dataset inmet               # download only (INMET portal ZIP)
era5 dedup     --dataset all                 # migration: dedupe old parquets
era5 ibge      -o ./data/ibge_locais.parquet # generate the IBGE Parquet
```

`era5 --help` or `era5 <command> --help` lists every flag.

## On-disk layout

```
<data_dir>/
├── climate_data_store_db/
│   ├── era5/
│   │   ├── date=2024-01-01/era5_2024-01-01_part-001.parquet
│   │   ├── ...
│   │   ├── _manifest.json
│   │   ├── _coverage.duckdb            # coverage index (grid)
│   │   └── era5.duckdb
│   ├── era5-land/
│   │   ├── date=YYYY-MM-DD/era5-land_YYYY-MM-DD_part-001.parquet
│   │   ├── _manifest.json · _coverage.duckdb · era5-land.duckdb
│   ├── inmet/
│   │   ├── station=A001/A001_2000.parquet   # 1 Parquet per station/year
│   │   ├── station=A001/A001_2001.parquet
│   │   ├── ...
│   │   ├── _manifest.json
│   │   ├── _stations.duckdb            # station index (not grid)
│   │   └── inmet.duckdb
│   └── _tmp_netcdf/
│       ├── era5/<chunk_id>.nc          # raw NetCDF (disposable)
│       └── inmet/<year>/*.CSV          # extracted CSVs (removed after conversion)
```

- Folder names are **literal** — `era5-land` keeps the hyphen (same
  as CDS / `variables.yaml`).
- The DuckDB file lives **inside** the dataset directory, keeping each
  dataset self-contained.
- `_tmp_netcdf/` (inside `climate_data_store_db/`) is disposable;
  re-running the pipeline re-downloads from the CDS / INMET portal.
  The `_coverage.duckdb` / `_stations.duckdb` indexes are derived state
  — rebuilt from Parquet.

## Programmatic usage

```python
from pathlib import Path
from era5_etl.config import PipelineConfig
from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

config = PipelineConfig.create(
    base_dir=Path("./data"),
    dataset="era5-land",
    start_date="2024-01-01",
    end_date="2024-01-31",
    variables=["2m_temperature", "total_precipitation"],
)

context = ERA5Pipeline(config).run()
print(context.get_metadata("converted_count"))
```

`PipelineConfig.create()` is the only sanctioned way to assemble config:
it resolves paths via `storage.paths`, pulls default variables from the
dataset's `variables.yaml`, and consistently wires `download.output_dir`,
`storage`, and `database.db_path`.

### Querying directly via DuckDB

```python
import duckdb
from era5_etl.storage.parquet_manager import ParquetManager

mgr = ParquetManager(base_dir=Path("./data"), dataset="era5-land")
conn = duckdb.connect(":memory:")
mgr.create_duckdb_view(conn, "era5_land")

df = conn.execute("""
    SELECT date, AVG(temperature_2m) AS avg_t2m
    FROM era5_land
    WHERE date BETWEEN '2024-01-01' AND '2024-01-31'
    GROUP BY 1 ORDER BY 1
""").pl()
```

## Web UI (`web-ui/`)

Stack:

- **Vite + React 18 + TypeScript** (strict)
- **Tailwind CSS** with a theme inspired by scientific interfaces
- **TanStack Query** (server state) + **TanStack Router** (routing)
- **deck.gl + maplibre-gl** (inventory maps and point picker)
- **Plotly** (`plotly.js-dist-min` + `react-plotly.js`, lazy-loaded in
  a separate chunk) for time-series charts
- **apache-arrow** (decodes large responses), **monaco** (SQL editor),
  **@dnd-kit** (reorder tabs), **sonner** (toasts),
  **lucide-react** (icons)

Pages:

| Route         | Purpose                                                                       |
|---------------|-------------------------------------------------------------------------------|
| `/dashboard`  | Per-dataset cards with size, partitions, coverage                             |
| `/inventory`  | Overlaid multi-system map — ERA5/ERA5-LAND grid points and INMET stations; color/size/opacity/marker per system |
| `/download`   | Wizard (dataset → vars → area → dates → estimate → run + SSE); dedicated flow for INMET (portal years) |
| `/query`      | DuckDB SQL editor with preview and CSV/Parquet export                         |
| `/timeseries` | Plotly chart notebook: multi-view series, point/region via map, Y/Y2, visual unit conversion, statistics |
| `/settings`   | `data_dir` config persisted to `~/.config/era5-etl/config.toml`               |

### Dev mode

Backend and frontend in parallel:

```bash
# Terminal 1 — FastAPI on :8788
make api-dev
# (or) py -3.12 -m uvicorn era5_etl.web.server:create_app --factory --reload --port 8788

# Terminal 2 — Vite on :5173 with proxy /api -> :8788
make ui-dev
# (or) cd web-ui && bun run dev
```

### SPA build

```bash
make ui-build           # bun install && bun run build
# output: src/era5_etl/web/static/
```

When the Python package is built (`pip install .` / `hatch build`), the
`hatch_build.py` hook runs this build automatically. Set
`ERA5_ETL_SKIP_UI_BUILD=1` to skip it (CI without Node/Bun).

## Architecture

```
src/era5_etl/
├── cli.py                       # Typer + Rich; dispatches to modules
├── config.py                    # PipelineConfig.create(), DownloadConfig, ...
├── datasets/                    # plug-ins
│   ├── base.py                  # DatasetConfig (NAME, SOURCE_KIND, is_gridded)
│   ├── era5/ · era5_land/       # config.py + variables.yaml (cds_grid)
│   └── inmet/                   # config.py + variables.yaml (inmet_zip)
├── download/
│   ├── request_planner.py       # plan_requests() -> RequestChunk[]
│   ├── size_estimator.py        # estimate_request_size, split_area
│   ├── cds_downloader.py        # iterates chunks + cdsapi
│   └── inmet_portal.py          # portal scrape + yearly ZIP + extraction
├── transform/
│   ├── netcdf_to_parquet.py     # xarray -> polars -> Parquet (date=)
│   └── inmet_to_parquet.py      # CSV latin-1 -> Parquet (station=)
├── storage/
│   ├── paths.py                 # resolve_*_dir / resolve_*_path
│   ├── manifest.py              # ChunkRecord, Manifest
│   ├── parquet_manager.py       # Parquet writing, DuckDB view
│   ├── coverage.py              # _coverage.duckdb (grid)
│   └── stations.py              # _stations.duckdb (INMET)
├── pipeline/
│   ├── era5_pipeline.py         # Template Method (download → convert → refresh)
│   └── source_handlers.py       # SOURCE_KIND → (downloader, converter, refresh)
├── web/
│   ├── server.py                # create_app(data_dir)
│   ├── routes/                  # version, datasets, stats, settings,
│   │                            # credentials, pipeline, query, query_store,
│   │                            # regions, export, inventory, inmet, timeseries
│   ├── timeseries_sql.py        # SELECT-only builder for time series
│   ├── runtime.py               # background pipeline jobs + SSE
│   ├── user_config.py           # ~/.config/era5-etl/config.toml
│   └── static/                  # generated SPA (gitignored)
├── utils/
│   ├── variables.py             # list_variables() via registry
│   └── ibge_loader.py           # bbox by municipio/UF/region
└── _data/                       # bundled IBGE CSV/shapefile
```

### Invariants worth preserving

1. **`DownloadConfig.dataset` is validated by the registry**, not by
   `Literal`. Adding a dataset = `@DatasetRegistry.register`.
2. **Every path decision goes through `storage.paths`.** Never write
   `base / "parquet" / dataset` by hand — call `resolve_dataset_dir`.
3. **CDS downloads are always `netcdf`** (GRIB would change
   converter/estimator/manifest). Non-CDS sources (INMET) have their own
   downloader/converter via `source_handlers`.
4. **The size budget comes from the planner.** `request_planner` is
   where size is negotiated; downstream trusts it.
5. **The manifest is the source of truth for "done"**, not the
   presence of a Parquet file — re-runs with `--override` rewrite it.

## Adding a new dataset

1. Create `src/era5_etl/datasets/<new>/{__init__.py, config.py, variables.yaml}`.
2. Subclass `DatasetConfig` and decorate with `@DatasetRegistry.register`,
   setting `NAME`, `_variables_yaml_path`, and — for a CDS grid source —
   `CDS_DATASET_ID`/`GRID_RESOLUTION_DEG`. For a non-grid source,
   set your own `SOURCE_KIND` (e.g., `inmet_zip`).
3. Import the sub-package from `era5_etl.datasets.__init__:ensure_loaded`.
4. If `SOURCE_KIND` is new, register the handler in
   `pipeline/source_handlers.py` (downloader, converter, refresh stage).
5. Add an assertion in `tests/test_datasets_registry.py`.

The CLI, Web UI, planner, and manifest pick up the new name automatically.

## Versioning

- **`VERSION`** is the single source of truth.
- `hatch_build.py` materializes its content into
  `src/era5_etl/__version__.py` at build time (don't edit by hand).
- `web-ui/package.json` is updated manually to reflect major releases
  (no functional impact, but exposed in the SPA).

## Development

```bash
# Setup
pip install -e ".[dev]"

# Tests (424 tests; none require network)
make test          # or: py -3.12 -m pytest

# HTML coverage
py -3.12 -m pytest --cov-report=html

# Lint / type-check
make lint          # ruff check src tests
make typecheck     # mypy src/era5_etl

# Format
ruff format .

# Run API + UI in dev mode (parallel)
make dev
```

Web UI tests use FastAPI's `TestClient` — no network required.
The request planner tests use artificially low `max_request_bytes`
to force every split tier (the field is set after construction to bypass
Pydantic's 1-MiB floor).

## Single-point time-series download (ARCO/Zarr) — when NOT to use this project

> This section is about the **CDS ARCO endpoint** for downloading a single
> point over many years — not to be confused with the `/timeseries`
> page (which plots what is already in local Parquet).

Copernicus maintains experimental endpoints in
**Analysis Ready Cloud Optimized (ARCO / Zarr)** format optimized for
**single-point time series** over very long periods:

- `reanalysis-era5-land-timeseries`
- `reanalysis-era5-single-levels-timeseries`

They are the most efficient path when the use case is:
> "extract one or a few variables at **a single grid point** over
> **many years**" (without needing the whole rectangle).

For that case, go directly via `cdsapi` — this project does not cover
the ARCO endpoint because the pipeline is optimized for **area-based**
downloads with daily Parquet partitioning (different format and schema).
By default `cdsapi` logs a note about the ARCO endpoint on every request;
ERA5-ETL silences that message (`install_cdsapi_log_filter`) to reduce
noise. To re-enable it: remove the filter from
`logging.getLogger("cdsapi")`.

Minimal example (out of scope for this package):

```python
import cdsapi
c = cdsapi.Client()
c.retrieve(
    "reanalysis-era5-land-timeseries",
    {
        "variable": "2m_temperature",
        "location": {"latitude": -23.55, "longitude": -46.63},  # single point
        "date": ["2000-01-01/2024-12-31"],
        "data_format": "netcdf",
    },
    "sao_paulo_t2m.nc",
)
```

## INMET × ERA5/ERA5-LAND — units of measure

INMET is a **station-based** source (non-grid): yearly ZIP from the
portal, 1 CSV per station, written as
`inmet/station=<code>/<code>_<year>.parquet`. The **units differ** from
ERA5/ERA5-LAND and need to be harmonized before any numerical comparison:

| Quantity | ERA5 / ERA5-LAND (native CDS) | INMET | Conversion / note |
|---|---|---|---|
| Air temperature (2 m) | **K** — `temperature_2m` | **°C** — `temp_ar` | `°C = K − 273.15`. The transform converts by default (`convert_kelvin_to_celsius=True`) → ERA5 Parquet is already written in °C |
| Dew point (2 m) | **K** — `dewpoint_2m` | **°C** — `temp_orvalho` | same (K → °C) |
| Atmospheric pressure | **Pa** — `surface_pressure` (and `msl_pressure`, ERA5 SL only) | **hPa = mB** — `pressao_estacao`/`pressao_max`/`pressao_min` | `1 hPa = 1 mB = 100 Pa` → `Pa = mB × 100` |
| Precipitation | **m**, accumulated — `total_precipitation` | **mm**, hourly total — `precipitacao_total` | `1 m = 1000 mm`; semantics differ: ERA5 is accumulated since the previous step |
| Wind | **U/V components in m/s** — `wind_u_10m`/`wind_v_10m` | **speed m/s** + gust + direction (°) — `vento_velocidade`/`vento_rajada_max`/`vento_direcao` | ERA5 speed `= √(u²+v²)`; the transform derives `wind_speed` by default (`calculate_wind_speed=True`) |
| Relative humidity | **%** — `relative_humidity` (ERA5 SL only) | **%** — `umidade_relativa`/`umidade_rel_max`/`umidade_rel_min` | same unit |
| Global solar radiation | **J/m²**, accumulated — `solar_radiation` (ERA5 SL) | **kJ/m²** — `radiacao_global` | `1 kJ/m² = 1000 J/m²`; accumulation differs |
| Thermal radiation | **J/m²** — `thermal_radiation` (ERA5 SL) | — | INMET does not measure |
| Cloud cover | **fraction 0–1** — `cloud_cover` (ERA5 SL) | — | INMET does not measure |
| Evaporation | **m** — `evaporation` (ERA5 SL) | — | INMET does not measure |
| Skin/soil temperature | **K** — `skin_temperature`, `soil_temperature_level_1..4` | — | only ERA5-LAND has a soil profile |
| Soil moisture | **m³/m³** — `volumetric_soil_water_layer_1..4` | — | ERA5-LAND only |
| Time | **UTC hour** — `hour_utc` | **UTC hour** — `hour_utc` | both UTC — **no timezone adjustment** |

> The "native units" are what the CDS delivers. The flags in
> `TransformConfig` (`convert_kelvin_to_celsius`, `calculate_wind_speed`)
> change what actually ends up in the ERA5 Parquet (defaults: °C and
> derived `wind_speed`). INMET is written in the portal's original units.

### Grid neighbours per station (no snap to a single point)

Each INMET Parquet carries, per station, the **enclosing grid cell**
of each product and the distance (km, haversine) from the station to the
**4 vertices** of that cell — instead of rounding to the nearest point.
Columns: `era5_lat_top/lat_bottom/lon_left/lon_right` +
`dist_era5_top_left/top_right/bottom_left/bottom_right` (same for
`era5_land_*`). This enables spatial interpolation (IDW/bilinear) at
comparison time, rather than assuming the nearest point. The Parquet is
written sorted by `(date, hour_utc)` for DuckDB row-group pruning.

### `era5_inmet` VIEW (user-defined)

`era5_inmet` is no longer generated in Python. To create it, open the
`/query` page, load the **era5_inmet** template (`era5-inmet-compare`,
Templates tab), review the SQL, and click **Save VIEW** — or build it in
the visual builder. It aligns each INMET station observation with the
**4 neighbour grid points** of ERA5 and ERA5-LAND at the **same date and
hour (UTC)** via an epsilon-based coordinate join
(`abs(a-b) < 1e-4`, since Float32 coords are never exactly equal).
Once saved, it appears in the SCHEMA menu and can be queried like any
view:

```sql
SELECT station_id, date, hour_utc,
       temp_ar AS inmet_t2m,
       era5_tl_value, era5_tr_value,
       era5_bl_value, era5_br_value,
       dist_era5_top_left, dist_era5_top_right,
       dist_era5_bottom_left, dist_era5_bottom_right
FROM era5_inmet
WHERE station_id = 'A001' AND date = DATE '2000-10-05';
```

### Time-series screen (`/timeseries`)

Chart notebook for analyzing/correlating time series across ERA5,
ERA5-LAND, INMET, and any user VIEWs (a view named `era5_inmet`, if
created, is treated as a per-station source). Backend:
`POST /api/timeseries` (1 capped query per series; combines `date` +
`hour_utc` into a UTC timestamp; bucket `raw|hour|day|month` with
auto-coarsen if the point limit is exceeded) and `GET /api/timeseries/meta`
(views, numeric columns, location type, date range).

Per **chart cell**: date range (capped to actual coverage), bucket,
max points. Per **series**: view + variable + aggregation + Y/Y2 axis +
**point/region** (typed or clicked on the map — coordinates are
"snapped" to the grid resolution) + **visualization-only unit
conversion** (K↔°C/°F presets or custom formula; the Parquet data does
not change) + optional **mean line**. Each series shows statistics
(min, max, mean, std, variance, IQR). Add/duplicate/remove/reorder
cells; state persists in `localStorage`.

> **Watch the units:** ERA5/ERA5-LAND are already written in **°C** by
> the pipeline (`convert_kelvin_to_celsius=True` by default —
> conversion done at Parquet write time, not on the screen). So, to
> compare temperature with INMET (also °C), **do not** apply the K→°C
> preset. Visual conversion is for units that actually differ
> (pressure Pa↔mB, precipitation m↔mm, radiation J/m²↔kJ/m²) or if
> Kelvin was kept (the `--no` flag in programmatic use).

## Troubleshooting

### `Unknown dataset 'era5land'`

Use the canonical name **with hyphen**: `era5-land`. The hyphen is
literal in the CDS API, the directory, and the YAML.

### `DownloadSizeError`

Happened even after the planner split the request down to the minimum
(1 var × 1 day × 1 grid point). Increase `max_request_bytes` or reduce
`area`/`hours`.

### `era5 ui` opens but only shows JSON / `404`

The SPA was not built. Run `make ui-build` or `pip install .`
(which triggers the Hatch hook). Make sure
`src/era5_etl/web/static/index.html` exists.

### `bun: command not found` at build time

Use `pnpm` or `npm` — the hook detects the first one available. Or
`ERA5_ETL_SKIP_UI_BUILD=1 pip install .` to install without the SPA
(CLI and HTTP API keep working).

### CDS returns `Your request is queued`

Normal behavior — large requests wait in the Copernicus queue. The
downloader long-polls with exponential retry (`max_retries`,
`retry_delay`).

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## External resources

- [Copernicus CDS](https://cds.climate.copernicus.eu)
- [ERA5 documentation](https://confluence.ecmwf.int/display/CKB/ERA5)
- [ERA5-Land documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land)
- [CDS API how-to](https://cds.climate.copernicus.eu/api-how-to)
