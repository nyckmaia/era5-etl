# Changelog

## [0.6.0] - 2026-05-14

### Added

- **Cell-level coverage index** (`<base>/climate_data_store_db/<dataset>/_coverage.duckdb`).
  One row per `(latitude, longitude, date, variable)` with a 24-bit
  `hours_mask`. Backed by `CoverageIndex` in `storage/coverage.py`. New
  CLI `era5 coverage rebuild --dataset {era5,era5-land,all}` populates
  it from existing parquet; `download` and `update` auto-rebuild on
  first use if the file is missing.
- **Smart-diff downloads.** `request_planner.plan_with_diff` expands a
  request into cells, joins the coverage index, regroups missing cells
  (4-connected components for non-contiguous holes), and runs the
  existing area→days→variable cascade only on the leftovers.
  Default ON: `era5 download --apply-diff/--no-apply-diff` (defaults
  true). Same behavior surfaced on `POST /api/pipeline/run` via the new
  `apply_diff` field.
- **Inventory web API** (`src/era5_etl/web/routes/inventory.py`):
  - `GET /api/inventory/grid-points?dataset=&date_from=&date_to=&variable=&format=auto|json|arrow`
    returns one row per cell with `days` and `vars` counts. Decimates
    to Apache Arrow IPC for >5000 points.
  - `GET /api/inventory/cell-detail?dataset=&lat=&lon=` returns nested
    `dates -> variables -> hours[]`.
  - `POST /api/inventory/region-summary` aggregates a polygon to
    `n_points`, `date_range`, `vars_per_cell_avg`, `gaps[]`.
  - `POST /api/pipeline/diff-preview` returns
    `{requested_cells, missing_cells, savings_pct, sample_missing[≤100]}`
    so the wizard can show "87% already cached".
- **Inventory page (Web UI)** at `/inventory` — Deck.gl + MapLibre map
  focused on Brazil with grid-point overlay, hover popups, click
  detail, rectangle/lasso/click selection, region summary panel,
  binary/intensity colormap toggle, "Baixar dados faltantes para esta
  região" CTA that hands off to the Download Wizard.
- **Smart Diff step in Download Wizard.** New step between Period and
  Confirm shows total/missing/savings cards plus a toggle between
  "Baixar apenas o que falta (recomendado)" and "Baixar tudo
  (sobrescrever)".

### Changed

- **Tile-based parquet sort.** `_sort_for_storage` now uses transient
  `_lat_tile = floor(lat/5)` / `_lon_tile = floor(lon/5)` columns for
  ordering, then drops them before writing. Row-group min/max
  statistics become tight on **both** lat and lon → DuckDB prunes
  row-groups for `WHERE lat BETWEEN ... AND lon BETWEEN ...` queries.
  No change to the parquet schema (latitude/longitude column names
  preserved); no change to the Hive partition layout (`date=` only).
- **`merge_into_partitioned_parquet` upserts the coverage index** at
  the end of every successful write. Failures are logged and
  non-fatal: the parquet on disk is canonical, coverage is derived
  state and can be rebuilt from it.
- **`paths.py` gains `base_dir_from_dataset_dir` and
  `base_dir_from_netcdf_dir`** so writers and downloaders never have
  to walk parents inline.

### Test status

- 306 tests passing (was 259). 47 new tests covering coverage index,
  tile-sort, smart-diff planner, inventory routes, diff preview, and
  the apply_diff wiring.

---

## [0.5.0] - 2026-05-14

### Changed

- **Semantic Parquet filenames.** Files are now named
  `<dataset>_<YYYY-MM-DD>_part-NNN.parquet` (e.g.,
  `era5-land_2024-01-15_part-001.parquet`) instead of the opaque
  `part-<32-hex-uuid>.parquet`. Built by `_compute_part_name` from the
  parquet directory name; merge-on-write always produces `_part-001` in
  normal flow. `dedup_existing_partitions` rewrites legacy uuid files
  to the new naming.
- **Intra-file sort by `(latitude, longitude, hour_utc)`** applied
  before every Parquet write. Centralised in `_sort_for_storage` in
  `parquet_manager`. Row-group min/max statistics become tight on
  spatial columns → DuckDB prunes row-groups for `WHERE latitude
  BETWEEN ...` queries even though there is no spatial Hive partition.
  Two-camera pruning (directory `date=` + intra-file row-groups) gives
  query performance equivalent to a four-level Hive layout without
  exposing helper columns like `lat_bucket`/`lon_bucket` to consumers.

### Fixed

- **`StorageConfig.row_group_size` was being ignored.** The parquet
  writer now plumbs the value through to `df.write_parquet(...,
  row_group_size=...)`. Default stays at 100 000 (matches the existing
  config default); callers can override via
  `ParquetManager.write_dataframe(..., row_group_size=...)`.

### Test status

- 259 tests passing (was 253). New cases: filename pattern for both
  datasets, intra-file sort verification, row-group statistics
  tightness, dedup converts legacy uuid filenames, natural date query
  via DuckDB.

---

## [0.4.0] - 2026-05-13

### Added

- **Onboarding gate (Web UI)** — first-run users are forced through a
  three-step setup (data directory → CDS credentials → ready) before
  Dashboard/Download/Query become usable. Implemented as
  ``OnboardingGate`` wrapping the routed content in ``Layout.tsx``.
- **CDS credentials API** — new ``/api/credentials/{status,,test}``
  endpoints. ``POST /api/credentials`` writes ``~/.cdsapirc`` (chmod 0600
  on POSIX) from a form payload. ``POST /api/credentials/test`` probes
  the CDS catalogue endpoint with a 15s timeout and returns a structured
  result. The status endpoint never returns the key, only the URL +
  source (env / file / none).
- **Per-chunk lifecycle events** — ``ProgressEvent`` gains optional
  ``chunk_id``, ``chunk_index``, ``chunks_total``, ``phase``,
  ``bytes_downloaded``, ``bytes_total``. The downloader emits
  ``submitting → queued → running → downloading → completed`` for every
  chunk, surfaced via the existing SSE channel.
- **``CDSEventCapture`` log handler** —
  ``src/era5_etl/download/cds_log_capture.py`` parses cdsapi INFO
  messages into structured events. Attached to the ``cdsapi`` logger only
  while a download is in flight; never silences the underlying logger.
- **``RunProgress`` component (Web UI)** — live progress view shown
  after starting a download. Renders an overall bar + per-chunk badges
  (submitting, queued, running, downloading, completed, failed) + a
  rolling event feed. Consumes ``/api/pipeline/runs/{run_id}/progress``.

### Changed

- **CDS ARCO notice filtered** — the cdsapi INFO log about the
  ``reanalysis-era5-land-timeseries`` ARCO/Zarr endpoint is suppressed
  by ``install_cdsapi_log_filter`` (installed by ``setup_logging`` and
  ``create_app``). README §"Time-series (ARCO/Zarr)" explains when that
  endpoint matters (it isn't this project's use case).
- **``CDSDownloader.__init__``** accepts an optional ``on_event``
  callback; ``ERA5Pipeline.__init__`` accepts ``progress_callback`` and
  threads it through the ``DownloadStage``. The web runtime wires
  ``run.emit_chunk_event`` here so the SSE stream carries per-chunk
  events end-to-end.
- **DownloadWizard** mounts ``<RunProgress />`` after the user clicks
  Start, replacing the previous bare "run started" text.

### Test status

- 253 tests passing (was 236). New coverage: 8 for credentials API,
  8 for ``CDSEventCapture``, 1 for the ARCO log filter.

---

## [0.3.0] - 2026-05-13

### Added

- **`--pais` flag** on `pipeline`, `download`, and `update`. Default `Brasil`
  resolves to the country bbox (via the bundled IBGE ``pais.csv``). Without
  any sub-region flag, the country bbox replaces the previously hardcoded
  default. Foundation for future multi-country support — add a row to
  ``pais.csv`` to enable a new country.
- **Region-flag mutual exclusivity validation.** `_resolve_area` now
  enforces that at most one of ``{--municipio, --regiao-imediata,
  --regiao-intermediaria, --uf}`` is set per invocation (``--municipio +
  --uf`` is the only permitted combo, for municipality disambiguation).
- **Grid alignment (Layer 1)** — new ``era5_etl.download.grid`` module:
  ``snap_area_to_grid`` (ceil/floor to dataset resolution; always contains
  the user's bbox), ``Rect`` algebra (``rect_intersect``, ``rect_subtract``,
  ``merge_rects_horizontal``, ``rect_union_area``), ``iter_grid_cells``.
  The planner snaps the requested area and every sub-area split, so all
  ``RequestChunk.area`` values lie on cell boundaries and are comparable
  across runs.
- **Write-time dedup (Layer 2)** — ``ParquetManager.write_dataframe``
  and ``merge_into_partitioned_parquet`` now read existing partition data,
  outer-join with the incoming batch on ``(latitude, longitude, hour_utc)``,
  coalesce variable columns (new values win on conflict, old fills column
  gaps), and atomically replace the partition. Overlapping downloads
  (e.g., adjacent IBGE regions) no longer produce duplicate rows. The
  previous ``pq.write_to_dataset(existing_data_behavior="overwrite_or_ignore")``
  path -- which left both files in the partition and silently duplicated
  on read -- is gone.
- **`era5 dedup`** — one-off migration command that rewrites every
  ``date=YYYY-MM-DD`` partition with duplicates collapsed. Idempotent.
- **Cell-level manifest (Layer 3)** — manifest schema bumped to v2:
  ``ChunkRecord`` now carries ``days`` and ``hours``, captured via the new
  ``ChunkRecord.from_request_chunk`` factory. ``CDSDownloader`` records
  each successfully downloaded chunk to the manifest. Two new
  ``Manifest`` APIs: ``covered_rects_for`` and ``missing_rects_for``
  power cell-level coverage queries.
- **`plan_incremental_requests(config, manifest)`** — the new entry point
  used by ``era5 update``. Per ``(variable, year, month)``, subtracts
  already-covered rectangles from the requested target and only plans
  chunks for the residual. Returns ``[]`` when fully covered (fast path
  for cron use). v1 manifest records (no days/hours) are read as
  full-month, all-hours coverage for back-compat.

### Changed

- **`era5 update`** uses ``plan_incremental_requests`` instead of the
  brittle ``chunk_id``-based diff. Robust to area changes between runs.
  ``--dry-run`` now lists missing chunks with their variables and area
  for clarity.
- **Manifest schema version is now 2.** v1 files load transparently;
  on next save they are persisted as v2 with synthesised ``days``/``hours``.

### Test status

- 236 tests passing (was 178). New coverage: grid algebra (27 tests),
  dedup write path (8 tests), cell-level manifest (8 tests), incremental
  planning (4 tests), --pais flag and region exclusivity (7 tests),
  dedup CLI command (2 tests).

---

## [0.2.0] - 2026-05-13

### Breaking

- **Storage layout reorganised.** Parquet now lives at
  `<base>/climate_data_store_db/<dataset>/` (was `<base>/parquet/<dataset>/`).
  NetCDF downloads now live at `<base>/_tmp_netcdf/<dataset>/`. Dataset folder
  names preserve the hyphen (`era5-land`, not `era5land`). No migration helper
  is provided; recreate the dataset by re-running the pipeline.
- `era5 info` renamed to `era5 status`, with richer per-dataset output.
- `DownloadConfig.dataset` is no longer a `Literal`; any name registered with
  `DatasetRegistry` is accepted (currently `era5`, `era5-land`).

### Added

- **DatasetRegistry plug-in pattern.** Each ERA5-family dataset lives in
  `era5_etl/datasets/<name>/` with its own `variables.yaml`.
- **Centralised path resolution** in `era5_etl/storage/paths.py`
  (`resolve_dataset_dir`, `resolve_netcdf_temp_dir`, `resolve_manifest_path`,
  `resolve_duckdb_path`, `ensure_dataset_dirs`).
- **Hierarchical request planner** (`era5_etl/download/request_planner.py`).
  Splits oversize requests in fixed order: area 2x2 → day blocks → per-variable.
  Raises `DownloadSizeError` only when even single var / single day / single
  grid point exceeds the budget.
- **Per-dataset manifest** (`era5_etl/storage/manifest.py`) keyed by chunk_id.
- **`era5 update`** — incremental fetch driven by manifest diff.
- **`era5 status`** — per-dataset stats (size, partitions, coverage).
- **`era5 pipeline --dry-run` / `era5 download --dry-run`** — preview chunks
  and total estimated size without contacting CDS.
- **`era5 pipeline --dataset all`** — run a command for both datasets.
- **Web UI** under `web-ui/` (Vite + React + TypeScript + Tailwind + TanStack
  Query/Router + Radix). Pages: Dashboard, Download wizard, SQL query, Settings.
- **`era5 ui`** — launch FastAPI + open browser.
- **FastAPI app** (`era5_etl.web.server.create_app`) with routes for datasets,
  stats, settings, pipeline estimate/run/progress (SSE), read-only SQL, export.
- **`hatch_build.py`** custom hook that bundles the SPA and syncs the version.

### Changed

- `NetCDFToParquetConverter._rename_variables` now uses the registry-backed
  `get_var_name_map()`.
- `CDSDownloader.download()` now iterates over `RequestChunk[]` from the
  planner instead of `(year, month)` tuples.
- Versioning is now driven by the `VERSION` file; `__version__.py` is
  generated by `hatch_build.py`.

### Test status

- 178 tests passing (was 117).

---

## [0.1.0] - 2024-12-09

### Implementação Completa do ERA5-ETL

#### Adicionado
- **Interface CLI completa** (`cli.py`)
  - Comando `run`: Pipeline completo end-to-end
  - Comando `download`: Download de dados ERA5/ERA5-Land
  - Comando `process`: Processamento de NetCDF para CSV
  - Comando `convert`: Conversão de CSV para Parquet
  - Comando `query`: Consultas SQL no DuckDB
  - Comando `info`: Informações sobre o banco de dados
  - Comando `export`: Exportação para CSV
  - Rich output formatado no terminal
  - Logging configurável (verbose mode)

- **Estrutura de Testes** (`tests/`)
  - `test_config.py`: Testes para configurações (10 testes)
  - `test_core.py`: Testes para componentes core (11 testes)
  - `test_processor.py`: Testes para processamento NetCDF (7 testes)
  - `test_storage.py`: Testes para storage e DuckDB (10 testes)
  - `conftest.py`: Fixtures compartilhadas
  - **38 testes passando**

- **Documentação Expandida**
  - README.md completo com:
    - Guia de instalação
    - Exemplos de uso
    - Documentação da API
    - Guia de desenvolvimento
    - Troubleshooting
  - Badges de status
  - Instruções de configuração CDS API

- **Exemplos de Configuração** (`examples/`)
  - `config_simple.py`: Configuração básica para iniciantes
  - `config_advanced.py`: Configuração avançada com todas as features
  - `query_examples.py`: 8 exemplos de consultas SQL
  - `README.md`: Documentação dos exemplos

#### Componentes Core (já existentes)
- `core/pipeline.py`: Pipeline base com Template Method pattern
- `core/stage.py`: Stages abstratos com Chain of Responsibility
- `core/context.py`: Context object para compartilhar estado
- `download/cds_downloader.py`: Download via CDS API
- `transform/netcdf_to_parquet.py`: Processamento NetCDF com xarray
- `storage/parquet_manager.py`: Escrita de Parquet particionado
- `storage/duckdb_manager.py`: Gerenciamento DuckDB
- `pipeline/era5_pipeline.py`: Pipeline ERA5 completo
- `config.py`: Configurações com Pydantic
- `constants.py`: Constantes e mapeamentos
- `types.py`: Type aliases
- `exceptions.py`: Exceções customizadas

#### Melhorias
- Instalação funcionando com `pip install -e .`
- Comando CLI `era5` disponível globalmente
- Todos os testes passando (38/38)
- Documentação completa e profissional
- Exemplos práticos prontos para uso

#### Recursos Técnicos
- **Design Patterns**: Template Method, Chain of Responsibility, Context Object
- **Type Safety**: Type hints completos, validação Pydantic
- **Testing**: 38 testes com pytest, fixtures compartilhadas
- **CLI**: Typer com Rich para output formatado
- **Data Processing**: Polars, xarray, DuckDB
- **Code Quality**: Configuração ruff e mypy

### Status do Projeto

**Totalmente funcional e pronto para uso!**

#### Testado
- Instalação via pip
- CLI funcionando
- Imports corretos
- 38 testes passando
- Exemplos executáveis

#### Para Produção
- [ ] Publicar no PyPI
- [ ] CI/CD com GitHub Actions
- [ ] Documentação online (ReadTheDocs)
- [ ] Mais exemplos de casos de uso
- [ ] Integração com outros formatos (GeoTIFF, Zarr)

### Como Usar

```bash
# Instalar
pip install -e .

# Executar pipeline completo
era5 run --data-dir ./data --dataset era5-land --start-date 2023-01-01 --end-date 2023-01-31

# Ver ajuda
era5 --help

# Executar testes
pytest tests/ -v
```

### Arquitetura

```
era5_etl/
├── cli.py              # Interface CLI completa
├── core/               # Pipeline base
├── download/           # Download CDS
├── transform/          # Processamento NetCDF
├── storage/            # Storage (Parquet, DuckDB)
└── pipeline/           # Pipeline ERA5

tests/                  # 38 testes
examples/               # Exemplos práticos
```

### Dependências

- Python 3.11+
- polars, xarray, netCDF4
- duckdb, pyarrow
- pydantic, typer, rich
- cdsapi, cfgrib

### Autor

Developer <dev@example.com>

### Licença

Apache License 2.0
