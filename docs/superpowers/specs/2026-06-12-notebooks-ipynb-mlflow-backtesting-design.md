# Notebooks: .ipynb export, cell collapse, MLflow tracking, experiment repeat, and backtesting

**Date:** 2026-06-12
**Status:** Approved (brainstorm with user, 2026-06-12)

## Goal

Five improvements to the `/notebooks` feature:

1. Export any notebook to a Jupyter `.ipynb` file.
2. Collapse/expand each cell individually.
3. Professional experiment tracking with MLflow (replacing the manual
   `log_model_run()` flow) in a **new** template.
4. Repeat a past experiment stored in MLflow.
5. Backtesting (Expanding Window + Sliding Window) managed by Optuna,
   with statistics and comparison charts logged to MLflow.

Improvements 3–5 land in a **copy** of the "XGBoost with Optuna" template
named **"XGBoost With Optuna and Windows"**
(`src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json`).
The original template and the `xgboost_temperature_forecast` template are
**not modified**; the manual `POST /api/notebooks/{id}/runs` callback and
`log_model_run()` helper keep working for them.

## Decisions made with the user

| Decision | Choice |
|---|---|
| MLflow backend | Local file store at `<config_dir>/mlruns/`; on-demand `mlflow ui` subprocess + button in the web UI |
| Model runs panel | Kept; backend merges legacy JSON runs + MLflow runs (single panel, MLflow is the source of truth for the new template) |
| Optuna × backtesting | Backtest **inside** the Optuna objective (temporal CV per trial) |
| Two methods | Two **full sequential Optuna studies** — one with Expanding-window CV, one with Sliding-window CV |
| Template strategy | New template "XGBoost With Optuna and Windows"; original untouched |
| Repeat semantics | Repeat = skip the searches, re-evaluate windows + final refit with stored params, new run tagged `repeat_of=<run_id>` |

## 1. Export to .ipynb

**Backend** — new endpoint in `src/era5_etl/web/routes/notebooks.py`:

- `GET /api/notebooks/{notebook_id}/export/ipynb` → `Response` with
  `media_type="application/x-ipynb+json"` and
  `Content-Disposition: attachment; filename="<slug>.ipynb"`, following the
  pattern of `web/routes/export.py`.
- Conversion lives in a new module `src/era5_etl/notebooks/ipynb_export.py`
  (pure function `notebook_to_ipynb(doc: dict) -> nbformat.NotebookNode`),
  using the `nbformat` library (new core dependency, `nbformat>=5.9`).

**Cell mapping** (internal JSON → nbformat v4):

| Internal | ipynb |
|---|---|
| `markdown` cell | markdown cell |
| `code` cell | code cell + outputs (below) |
| `sql` cell | code cell, first line `%%sql` (jupysql convention), then the SQL source |
| output `stream` (stdout/stderr/warning) | `stream` output (warning → stderr) |
| output `display` plotly (`application/vnd.plotly.v1+json`) | `display_data` with same mime (renders natively in JupyterLab) |
| output `display` dataframe (`application/vnd.dataframe+json`) | `display_data` with `text/html` (static `<table>` built from stored schema/rows, ellipsis row preserved) + `text/plain` fallback |
| output `display` `text/plain` | `display_data` with `text/plain` |
| output `error` | `error` output (ename, evalue, traceback) |
| output `done` | dropped (internal bookkeeping) |

Filename slug: notebook name lowercased, non-alphanumerics → `-`, fallback
`notebook` when empty.

**Frontend:**

- Download button (Download icon) on each notebook card in
  `web-ui/src/pages/Notebooks.tsx`.
- Same button in the editor header (`web-ui/src/pages/NotebookEditor.tsx`).
- Both use the existing blob-download pattern from `lib/api.ts`
  (`exportQuery`).

## 2. Per-cell collapse/expand

- Cell model gains an **additive** optional field `collapsed: bool = False`:
  - `notebook_store.make_cell()` and `web/models/NotebookCellOut`.
  - `schema_version` stays `1` (old notebooks valid; missing field reads
    as `False`). The field round-trips through `PUT /{id}` like any other
    cell attribute, so it persists with the normal Save.
- **Frontend** (`NotebookEditor.tsx`): chevron toggle button in each cell
  header. Collapsed state: editor and outputs hidden; show a one-line
  preview (first non-empty source line, truncated) + a badge with the
  output count. No "collapse all" (not requested).
- Exported `.ipynb` carries the standard Jupyter metadata
  (`metadata.collapsed`) for collapsed cells.

## 3. MLflow infrastructure

**Dependency:** `mlflow>=2.10` added to core dependencies in
`pyproject.toml` (full distribution — includes the UI server — per user
request), in the notebook-runtime block.

**Tracking store:** `file:///<config_dir>/mlruns` where `<config_dir>` is
the same directory that holds `notebooks/` (resolved by the web layer's
existing config-dir logic). `kernel_manager.py` adds
`MLFLOW_TRACKING_URI` to the kernel subprocess environment alongside the
existing `ERA5_NB_*` variables.

**Experiment naming:** one MLflow experiment per notebook, stable name
`nb_<notebook_id>`; the human-readable notebook name goes in the
experiment tag `notebook_name`. `kernel_manager.py` passes a new
`ERA5_NB_NAME` env var (alongside `MLFLOW_TRACKING_URI`) so the
template's setup cell can set that tag; renames don't break linkage
because the experiment key is the id.

**MLflow UI launcher** — new `src/era5_etl/web/routes/mlflow_ui.py`:

- `POST /api/mlflow/ui/start` → starts a singleton subprocess
  `mlflow ui --backend-store-uri <uri> --host 127.0.0.1 --port <free port>`
  (port picked by binding port 0, then released); returns `{url}`.
  Idempotent: if already running, returns the existing URL.
- `GET /api/mlflow/ui/status` → `{running: bool, url: str | null}`.
- Process terminated on FastAPI shutdown (lifespan hook), mirroring the
  kernel-manager teardown.
- Frontend: "MLflow UI" button in the notebook editor header → calls
  start, opens returned URL in a new tab.

**Model runs panel fed from MLflow:**

- `GET /api/notebooks/{notebook_id}` merges two run sources into the
  existing `runs` list (shape `NotebookRunOut` unchanged):
  1. Legacy runs from the notebook JSON (other templates keep writing
     these via `POST /{id}/runs`).
  2. Top-level MLflow runs of experiment `nb_<notebook_id>` (child runs
     filtered out via the `mlflow.parentRunId` tag), mapped:
     `id=run_id`, `ts=start_time`, `model_name` from tag `model_name`,
     `duration_s` from run duration, `params`/`metrics` straight through,
     selected string tags (`load_source`, `device`) folded back into the
     dicts the panel reads, `notes` from tag `notes`.
- Mapping lives in a new module `src/era5_etl/web/mlflow_runs.py` using
  `mlflow.client.MlflowClient` against the file-store URI. A missing
  `mlruns/` dir or experiment yields `[]` (no error).
- Sorted by `ts`; frontend `ModelRunsPanel.tsx` unchanged.

## 4. New template "XGBoost With Optuna and Windows"

Copy of `xgboost_optuna_forecast.json` with these changes:

- **MLflow setup cell** replaces the `log_model_run()` helper cell:
  reads `MLFLOW_TRACKING_URI` + `ERA5_NB_ID` from env, calls
  `mlflow.set_tracking_uri` / `mlflow.set_experiment(f"nb_{ERA5_NB_ID}")`,
  defines small logging helpers.
- **Everything currently shown in the Model runs table is logged:**
  numeric values (`rmse`, `mae`, `r2`, `best_val_rmse`, `test_fraction`,
  `n_train`, `n_test`, `num_days`, `n_features`, `n_trials`,
  `load_duration_s`) as MLflow **metrics**; strings (`load_source`,
  `device`) as **tags**; all user inputs (station, dates, target, cutoff,
  lags, etc.) and XGBoost hyperparameters + `best_vars`/`best_lags`
  as **params** (`best_window_days` no longer exists — see Section 5); every Plotly figure produced by the
  run (predictions+residuals, Optuna optimization history, backtest
  comparison charts) via `mlflow.log_figure(fig, "plots/<name>.html")`;
  Optuna trials dataframe as CSV artifact.
- **Repeat-experiment switch** in the config cell:

  ```python
  REPEAT_RUN_ID = ""  # Cole aqui um run_id do MLflow para REPETIR aquele
                      # experimento (pula a busca Optuna e re-treina com os
                      # parâmetros salvos). Vazio ("") = experimento NOVO
                      # "do zero" (busca completa).
  ```

  Helper `load_experiment_config(run_id)` (defined in the MLflow setup
  cell) fetches the stored run's params via `MlflowClient`, overrides the
  config constants and best hyperparameters, and the search cells skip
  themselves when `REPEAT_RUN_ID` is set. The new run gets tag
  `repeat_of=<run_id>`.

## 5. Backtesting (Expanding + Sliding) managed by Optuna

**Template flow** (single-holdout Optuna search cell is replaced):

```
config → data load → features →
  STUDY 1: Optuna, objective = mean RMSE over EXPANDING windows →
  STUDY 2: Optuna, objective = mean RMSE over SLIDING windows →
  per-method statistics + comparison charts →
  final refit (winner method's best params) + holdout test evaluation →
  all logged to MLflow
```

The final temporal holdout (last `TEST_FRACTION`) is **excluded** from the
backtest windows — windows are cut from the training span only, so the
holdout stays untouched until the final refit.

**Config-cell parameters** (CAPS, descriptive comments, user-customizable):

```python
# ===== BACKTESTING — validação temporal =====
# Expanding Window: o treino começa no início do período e CRESCE a cada
# janela; o teste é sempre o bloco seguinte. Simula "re-treinar com todo
# o histórico disponível".
EXPANDING_INITIAL_TRAIN_DAYS = 365   # tamanho inicial do treino (dias)
EXPANDING_TEST_DAYS          = 30    # tamanho de cada bloco de teste (dias)
EXPANDING_STEP_DAYS          = 30    # avanço entre janelas (dias)

# Sliding Window: o treino tem tamanho FIXO e desliza junto com o teste.
# Simula "re-treinar apenas com o histórico recente".
SLIDING_TRAIN_DAYS = 365
SLIDING_TEST_DAYS  = 30
SLIDING_STEP_DAYS  = 30

MAX_WINDOWS = 6   # teto de janelas por método (controla o custo da busca)
```

Cost is called out in a comment: `N_TRIALS × MAX_WINDOWS` model fits per
method (e.g. 30 × 6 × 2 = 360 fits + final refit); defaults stay modest.

The original template's search dimension for the training-window size
(`best_window_days`) is **removed** in the new template: the temporal
structure is governed by the backtest CAPS parameters (an expanding
window by definition grows, so a searched fixed window contradicts it).
The search space keeps hyperparameters + variable/lag selection.

**Window generators** — new module `src/era5_etl/notebooks/backtest.py`:

- `expanding_windows(index, *, initial_train_days, test_days, step_days,
  max_windows)` and `sliding_windows(index, *, train_days, test_days,
  step_days, max_windows)`; both take a sorted datetime index and return
  `list[BacktestWindow]` (named tuple of train/test boolean masks or
  positional slices + window metadata).
- Pure functions, no leakage by construction (`max(train) < min(test)`),
  raise `ValueError` with an explanatory message (days available vs. days
  required) when no valid window fits.
- The template imports them (`from era5_etl.notebooks.backtest import …`)
  — the kernel subprocess runs in the same environment, so the import
  works; logic stays pytest-testable instead of living in template JSON.

**MLflow run hierarchy** (avoids `N_TRIALS × windows` run explosion):

- **1 parent run** per template execution — this is the row shown in the
  Model runs panel. Carries final holdout metrics (`rmse`, `mae`, `r2`),
  per-method aggregates (`expanding_rmse_mean`, `sliding_rmse_mean`, …),
  the comparison artifacts, and all params/tags.
- **2 nested child runs** (`expanding`, `sliding`), one per study. Each
  logs: the method's CAPS params, best hyperparameters found, per-window
  `rmse`/`mae`/`r2` logged with `step=<window index>`, aggregate
  statistics as metrics (`rmse_mean`, `rmse_std`, `rmse_min`, `rmse_max`,
  `rmse_median`, `rmse_cv` — same set for mae/r2), the full Optuna trials
  table as CSV artifact, and the optimization-history figure.
- **Parent-run artifacts:** Plotly comparison charts (per-window RMSE
  line chart with both methods; box plot of the per-window distribution
  per method; bar chart mean ± std), statistics table CSV, final
  predictions figure. All charts are also displayed as cell outputs in
  the notebook.
- Winner = method with lower mean window RMSE; its best hyperparameters
  are used for the final refit.

**Sequential execution:** STUDY 1 then STUDY 2 in the same cell block,
with progress prints in the style of the existing `_progress_and_stop()`
callback. When `REPEAT_RUN_ID` is set, both studies are skipped and the
stored per-method best params are re-evaluated on the windows + final
refit (Section 4).

## Error handling

- Window generation with insufficient data → `ValueError` from
  `backtest.py` with available vs. required days; surfaces as a normal
  cell error output.
- MLflow file store unreadable/missing → panel merge returns only legacy
  JSON runs; no 500.
- `mlflow ui` subprocess fails to start → `POST /start` returns 502 with
  stderr excerpt; button shows toast.
- `.ipynb` export of unknown output types → degrade to `text/plain`,
  never fail the export.

## Testing

- `tests/test_notebook_backtest.py` — expanding/sliding generators: no
  train/test overlap, ordering, `max_windows` cap, step arithmetic,
  short-period `ValueError`.
- `tests/test_notebook_ipynb_export.py` — `nbformat.validate` passes;
  each cell/output mapping; `%%sql` first line; slug filename; endpoint
  returns attachment headers (FastAPI `TestClient`).
- `tests/test_notebook_store.py` (extend) — `collapsed` round-trip
  through store and `PUT`/`GET` API.
- `tests/test_notebook_mlflow_runs.py` — temp file-store seeded with
  `MlflowClient`; merge of legacy + MLflow runs; child-run filtering;
  missing store → legacy only.
- Templates test (extend) — registry lists "XGBoost With Optuna and
  Windows"; JSON parses; cells reference `era5_etl.notebooks.backtest`.
- Web UI: no JS test infra; validated via `bun run build` + manual run.
  (Pitfall: SPA is gitignored after build — rebuild before checking
  `era5 ui`.)

## Out of scope

- GRIB support, changes to the original two templates' logic, MLflow
  model registry / model serving, remote tracking servers, "collapse all"
  UI, migrating legacy JSON runs into MLflow.
