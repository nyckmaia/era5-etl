# Notes for AI agents working on era5-etl

This file gives a working agent the minimum context to make safe changes.

## What this project is

`era5-etl` downloads ERA5 (single-level) and ERA5-LAND climate reanalysis data
from the Copernicus CDS, converts NetCDF4 to Hive-partitioned Parquet, and
exposes it via DuckDB views, a Typer CLI, and a FastAPI + React/Vite web UI.

## Architectural anchors

- **Datasets are plug-ins.** Each lives in
  `src/era5_etl/datasets/{era5,era5_land}/` and registers itself via
  `@DatasetRegistry.register`. Never hard-code a dataset literal anywhere
  other than tests; ask `DatasetRegistry.get(name)`.
- **All paths go through `src/era5_etl/storage/paths.py`.** Layout::

      <base>/
        climate_data_store_db/<dataset>/  -> parquet + manifest + duckdb
        _tmp_netcdf/<dataset>/              -> raw netcdf downloads

  Folder names are literal (`era5`, `era5-land`). Don't strip hyphens.
- **NetCDF4 is invariant.** Every CDS request uses `data_format="netcdf"`.
  Adding GRIB support would mean changing the converter, the size estimator,
  and the manifest -- and was deliberately deferred.
- **Request size is bounded by `request_planner.py`.** It applies a fixed
  cascade: area 2x2 -> day blocks -> per-variable. Never bypass it -- raise
  `DownloadSizeError` instead of issuing an unsplit request.
- **Manifest is the source of truth for "chunk done".** `storage/manifest.py`
  stores chunk_id -> ChunkRecord. The `update` command and the download
  stage both consult it via `Manifest.has(chunk_id)`. Manifest tracks
  rectangles, not cells.
- **Coverage index is the source of truth for "cell done".** `storage/coverage.py`
  exposes `CoverageIndex` over per-dataset `_coverage.duckdb`. One row per
  `(latitude, longitude, date, variable)` with a 24-bit `hours_mask`.
  `merge_into_partitioned_parquet` upserts on every successful write
  (failure non-fatal — the parquet on disk is canonical, coverage is
  derived). Read by `plan_with_diff`, `/api/inventory/*`, and the
  `/inventory` web page.
- **Tile-based parquet sort is part of the writer contract.** `_sort_for_storage`
  computes transient `_lat_tile = floor(lat/PARQUET_TILE_DEG)` /
  `_lon_tile = floor(lon/PARQUET_TILE_DEG)` (`PARQUET_TILE_DEG = 5`),
  sorts by `(lat_tile, lon_tile, latitude, longitude, hour_utc)`, then
  drops the tile columns before writing. Row groups end up spatially
  contiguous so DuckDB's row-group min/max stats prune for
  `WHERE latitude BETWEEN ... AND longitude BETWEEN ...` queries.
  Removing it would silently regress spatial query performance.
- **Parquet filenames are semantic.** Pattern:
  `<dataset>_<YYYY-MM-DD>_part-NNN.parquet`. `NNN` is virtually always
  `001` because `merge_into_partitioned_parquet` collapses each partition
  to one file. Built by `_compute_part_name` from `parquet_dir.name`
  (which equals the dataset name by `resolve_dataset_dir` convention).
- **`build_request_cells` is public planner contract.** Both
  `plan_with_diff` and `POST /api/pipeline/diff-preview` call it.
  Output schema must stay stable: `latitude (Float32), longitude (Float32),
  date (Date), variable (str), requested_mask (UInt32)` — the
  `CoverageIndex.diff()` JOIN relies on dtype match exactly.

## Common pitfalls

1. **Don't rename `era5-land` -> `era5land` anywhere.** The hyphen is the
   public dataset name (matches CDS and our YAML registry).
2. **Don't write paths by string-joining `base_dir`.** Call
   `resolve_dataset_dir(base_dir, dataset)`.
3. **The SPA in `web-ui/` is gitignored after build.** Editing TSX won't
   change `era5 ui` output until the SPA is rebuilt (`bun run build` or
   `make ui-build`).
4. **The web UI uses TanStack Router.** Use `<Link to=...>`, not raw `<a>`.
5. **Configuration goes through `PipelineConfig.create()`.** That's the only
   sanctioned way to assemble paths + dataset + variables consistently.

## Tests

- 178 tests at last count. Run with `py -3.12 -m pytest` (no venv was set up
  during initial implementation; adapt to your environment).
- Fixtures live in `tests/conftest.py`.
- The web tests use FastAPI `TestClient` -- no network required.
- The request planner tests intentionally use absurdly tight
  `max_request_bytes` values to force every split tier. They set the field
  after construction to bypass the 1-MiB Pydantic floor.

## Adding a new dataset

1. Create `src/era5_etl/datasets/<new>/{__init__.py, config.py, variables.yaml}`.
2. Subclass `DatasetConfig` and decorate with `@DatasetRegistry.register`.
3. Import the sub-package from `era5_etl.datasets.__init__:ensure_loaded`.
4. Add a `test_datasets_registry.py` assertion for the new name.

That's it -- the CLI, web UI, manifest, and planner all pick it up
automatically.

## Versioning

- `VERSION` is the single source of truth.
- `hatch_build.py` mirrors it into `src/era5_etl/__version__.py` at build
  time.
- Don't edit `__version__.py` by hand; edit `VERSION` and rebuild (or run
  `python hatch_build.py`-equivalent flow).
