# Notebooks: Optuna search cache, window-config sweep ("learning curves"), and MLflow comparison

**Date:** 2026-06-28
**Status:** Approved (brainstorm with user, 2026-06-28)

## Goal

Three improvements to the **"XGBoost With Optuna and Windows"** template
(`src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json`),
answering three user questions:

1. **(Q1) Cache the Optuna search** so re-running an identical configuration
   is instant and an interrupted long search can resume — instead of
   re-doing the whole search every time.
2. **(Q2) Make the sliding/expanding results transparent** with line charts
   of **test RMSE vs. months of training**, one panel per slide step, plus
   the expanding "learning curve" — so the user sees how many models were
   evaluated and each one's RMSE.
3. **(Q3) Represent (Q2) in MLflow** so the configurations can be compared
   natively (comparison table + parallel coordinates).

The original `xgboost_optuna_forecast` and `xgboost_temperature_forecast`
templates are **not** modified. Changes land in the Windows template and in
the user's existing notebook `6d1169c493984849a5e56e7ec7229128` (the latter
is runtime data under `<config_dir>/notebooks/`, not git-tracked).

## Guiding principle

Testable logic lives in modules under `src/era5_etl/notebooks/`; the template
JSON only orchestrates. This follows the CLAUDE.md anchor: "Backtest window
maths lives in `notebooks/backtest.py` (tested) — never inline it in template
JSON."

## Decisions made with the user

| Decision | Choice |
|---|---|
| Q2 scope | **Cheap sweep of the winner**: the Optuna search runs once; the sweep re-evaluates the *winning* hyperparameters across a grid of window configs (cost = n_configs × windows, no new search). Rejected: full search per config. |
| Q2 chart structure | X = months of training (integer); **one facet per slide step**; Y = mean test RMSE ± std across windows; **plus** the natural Expanding learning curve as its own panel. |
| Q1 cache key | **Config params + data fingerprint** (auto-invalidates when the underlying parquet changes). Rejected: config-only key; no persistent cache. |
| Q3 MLflow | **One nested child run per sweep config** (enables MLflow compare table + parallel coordinates) **plus** the faceted figure + a tidy CSV on the parent run. |

## Where the code lives

| New / changed | Location | Contents |
|---|---|---|
| **new** | `src/era5_etl/notebooks/optuna_cache.py` | `data_fingerprint()`, `config_fingerprint()`, `completed_trials()`, `remaining_trials()`, `open_cached_study()` |
| **changed** | `src/era5_etl/notebooks/backtest.py` | `build_sweep_grid()`, `summarize_sweep()` |
| **changed** | `src/era5_etl/notebooks/helpers_module.py` | `plot_learning_curves()` + inject into kernel namespace |
| **changed** | `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` | config additions; cache in the search cell; two new sweep cells; MLflow additions |
| **changed** | `<config_dir>/notebooks/6d1169c493984849a5e56e7ec7229128.json` | same cell changes applied to the existing notebook |
| **new tests** | `tests/test_optuna_cache.py`, additions to `tests/test_backtest.py` | unit tests for the module functions |

## 1. (Q1) Optuna search cache

**Mechanism.** Optuna's native SQLite storage at
`<config_dir>/optuna/nb_<id>.db`, with
`study_name = f"{method}__{FINGERPRINT}"` and `load_if_exists=True`. One DB
file per notebook experiment; one study per (method, fingerprint).

**`optuna_cache.py` API:**

- `data_fingerprint(df, target_col) -> str` — cheap, stable: combines
  `len(df)`, `df.index.min()`/`max()` (ISO), and a SHA-256 over the target
  column's raw bytes (`df[target_col].to_numpy().tobytes()`). Returns a short
  hex digest.
- `config_fingerprint(payload: dict, data_fp: str) -> str` — SHA-256 of
  `json.dumps(payload, sort_keys=True, default=str)` combined with `data_fp`;
  short hex. Stable under key reordering.
- `completed_trials(study) -> int` — count of trials with
  `state == TrialState.COMPLETE`.
- `remaining_trials(study, budget) -> int` — `max(0, budget - completed)`.
- `open_cached_study(method, fingerprint, storage_url, *, sampler,
  direction, reset=False) -> optuna.Study` — `create_study(..., storage,
  study_name, load_if_exists=True)`; when `reset`, `delete_study` first
  (ignore "not found"). Builds the SQLite URL via the file's absolute
  POSIX path (`sqlite:///<abspath>`), creating the parent dir.
- `load_json_cache(path) -> dict | None` / `save_json_cache(path, obj)` —
  small, reused for the feature-selection cache and the sweep-result CSV
  bookkeeping; `load` returns `None` on missing/corrupt file.

**Fingerprint payload** (everything that affects the search result):
station, dates, target, `TEST_FRACTION`, `ERA5_LAND_CUTOFF_HOURS`,
`LAG_HOURS`, the **feature-selection config** (`FEATURE_SELECTION`,
`FS_TOP_K`, `FS_PERM_N_REPEATS`, `FS_PERM_MIN_SIGMA`, `FS_PERM_SEED`,
`FIXED_LAGS`, `ACTIVE_VARS`), all `EXPANDING_*`/`SLIDING_*`/`MAX_WINDOWS`,
`OPTUNA_SEED`, `TARGET_METRIC`, `N_SEEDS_PER_WINDOW`, `BASE_SEEDS` used,
`USE_EARLY_STOPPING` + early-stopping params,
`SHARE_HYPERPARAMS_ACROSS_METHODS`, `STOP_MODE` + budget, and the
hyperparameter search space (a static version string bumped if `_suggest_hyper`
changes). Plus `data_fingerprint(trainval, TARGET_VAR)`.

**Why config, not resolved features.** The fingerprint deliberately uses the
feature-selection *config* and **not** the resolved `SELECTED_FEATS`.
`_select_features()` trains a baseline XGBoost (and, in `"permutation"` mode,
runs permutation importance); on GPU this is not perfectly deterministic, so
the resolved feature list can wiggle run-to-run. Hashing it would bust the
cache on every run. Hashing the deterministic config (which, with the data
fingerprint, fully determines the *intended* selection) keeps the key stable.

**Feature-selection cache (correctness + speed).** To make `SELECTED_FEATS`
actually stable across runs — so the resumed search reuses trials computed on
the *same* feature set, and to avoid re-running the slow permutation-importance
pass — the selection result is itself cached under the same `FINGERPRINT`:
`<config_dir>/optuna/features_<nb_id>_<FINGERPRINT>.json` storing
`SELECTED_FEATS` + the ranking. On a cache hit, `_select_features()` loads it
instead of recomputing (unless `OPTUNA_CACHE_RESET`). This closes the
nondeterminism gap and speeds re-runs further.

**Resume.** `_run_search` opens the cached study and runs only
`remaining_trials(study, _budget_trials)`. Identical re-run ⇒ 0 new trials ⇒
instant; interrupted search ⇒ resumes; raising `N_TRIALS` ⇒ runs only the
delta. The per-window `rows` already stored in `trial.user_attrs` persist in
SQLite, so `study.best_trial.user_attrs["rows"]` round-trips. Threshold mode
(`STOP_MODE="threshold"`) also resumes: if the cached `best_value` already
meets `TARGET_METRIC_VALUE`, skip; otherwise continue up to `N_TRIALS_CAP`.

**Config flags (new):**
```python
USE_OPTUNA_CACHE   = True    # SQLite resume keyed by config + data fingerprint
OPTUNA_CACHE_RESET = False   # True = ignore/delete cached studies, search from scratch
```

**Interactions.** `REPEAT_RUN_ID` is unaffected (it already skips the search
and re-evaluates stored hyperparameters). When `USE_OPTUNA_CACHE=False`, the
search uses an in-memory study (current behavior).

**Sweep-result cache (Q1 ∩ Q2).** The sweep (§2) is much cheaper than the
search but still re-runs on every execution, which reintroduces the slowness
that motivated Q1. So the sweep's tidy result DataFrame is cached as
`<config_dir>/optuna/sweep_<nb_id>_<FINGERPRINT>_<GRID_HASH>.csv` (GRID_HASH
over `SWEEP_TRAIN_MONTHS`, `SWEEP_SLIDE_STEPS_DAYS`, `SWEEP_TEST_DAYS`,
`SWEEP_MAX_WINDOWS`, and the winner hyperparameters). Loaded when present
unless `OPTUNA_CACHE_RESET`. Same fingerprint machinery as the search cache.

**Trade-offs (documented in the notebook markdown):** ✅ instant identical
re-run, crash-safe, incremental budget, persisted history. ⚠️ correctness
relies on the key (mitigated by the data fingerprint); GPU training is not
perfectly deterministic (cached objective values may differ from a fresh run
by epsilon — acceptable for caching); `.db`/`.csv` files accumulate (manual
cleanup or `OPTUNA_CACHE_RESET`).

## 2. (Q2) Window-config sweep + learning-curve charts

**Cost model.** The expensive Optuna search runs **once**. The sweep
re-evaluates the **winning** hyperparameters (`BACKTEST[winner]["best_params"]`)
across a grid, reusing the existing `_eval_windows(method, hyper)` — the same
per-window fit/early-stopping/multi-seed path. No new search.

**`backtest.py` additions:**

- `build_sweep_grid(*, train_months, slide_steps_days, test_days, max_windows,
  days_per_month=30) -> list[SweepConfig]` — Cartesian product of
  `train_months × slide_steps_days`. Each `SweepConfig` is a frozen
  dataclass `(train_months, train_days, step_days, test_days, max_windows,
  label)` where `train_days = train_months * days_per_month` and `label`
  is e.g. `"slide=7d, train=3m"`. Pure enumeration; does not touch data.
- `summarize_sweep(records) -> pandas.DataFrame` — given a list of
  `{slide_step_days, train_months, n_windows, rmse, mae, r2}` per-window
  records, returns the tidy aggregated DataFrame:
  `slide_step_days, train_months, n_windows, rmse_mean, rmse_std,
  mae_mean, r2_mean` (one row per config).

**Template sweep cell (new, after the refit cell).** For each
`SweepConfig`: build sliding windows via `sliding_windows(...)` and evaluate
with `_eval_windows`. A config that does not fit the period raises
`ValueError` from `backtest.py` → caught, printed as a skip warning, and
excluded. Aggregates into the tidy DataFrame `sweep_df` (via
`summarize_sweep`). Cached per §2's sweep-result cache.

**Config flags (new):**
```python
RUN_WINDOW_SWEEP       = True
SWEEP_TRAIN_MONTHS     = [1, 2, 3, 4, 5, 6]   # X axis (integer months, ×30 days)
SWEEP_SLIDE_STEPS_DAYS = [1, 7, 30]           # one facet per step
SWEEP_TEST_DAYS        = SLIDING_TEST_DAYS
SWEEP_MAX_WINDOWS      = MAX_WINDOWS
```

**Figure (`helpers_module.plot_learning_curves`).** Plotly figure with
subplots = one panel per slide step (X = training months, Y = mean test RMSE,
± std band) **plus** one panel `"expanding (treino cresce)"` built for free
from `BACKTEST["expanding"]["rows"]` (X = `n_train` hours → months, Y = per-
window RMSE). Injected into the kernel namespace alongside `plot_predictions`.
Returns the figure; the sweep-plot cell displays it and keeps a handle
(`fig_learning`) for MLflow.

**Notebook order:** two new code cells (compute, then plot) inserted **after
the final-refit cell** (so `winner` / winning hyperparameters exist).

## 3. (Q3) MLflow representation

In the existing MLflow logging cell (idx 19), inside the **parent** run:

1. **One nested child run per sweep config** (`mlflow.start_run(nested=True)`):
   - tags: `sweep="true"`, `method="sliding"`
   - params: `slide_step_days`, `train_months`, `n_windows`
   - metrics: `test_rmse_mean`, `test_rmse_std`, `test_mae_mean`,
     `test_r2_mean`
   These power MLflow's compare table + parallel-coordinates across configs.
2. **On the parent run:** the faceted figure
   `mlflow.log_figure(fig_learning, "plots/learning_curves.html")` and the
   tidy CSV `mlflow.log_text(sweep_df.to_csv(index=False), "sweep_results.csv")`.

The two existing per-method child runs (expanding/sliding) are unchanged.
Guarded by `if RUN_WINDOW_SWEEP and not sweep_df.empty`.

**Trade-off (documented):** N extra runs per execution (more runs in the
experiment) in exchange for native MLflow comparison — which the user
explicitly wants.

## 4. Testing

New / extended unit tests (`py -3.12 -m pytest`):

- `data_fingerprint` is deterministic for identical input and **changes**
  when the target values, length, or time span change.
- `config_fingerprint` is stable under key reordering and changes when any
  payload value changes; incorporates the data fingerprint.
- `remaining_trials` / `completed_trials` math, including over-budget.
- `open_cached_study` round-trips a study across two opens on the same
  SQLite file (second open sees the first open's completed trials);
  `reset=True` discards them.
- `save_json_cache` then `load_json_cache` round-trips an object; `load`
  returns `None` for a missing or corrupt file.
- `build_sweep_grid` enumerates the full product, computes `train_days`
  correctly, and labels configs; `summarize_sweep` aggregates mean/std per
  config.
- Re-run the existing `tests/test_notebook_templates.py`,
  `tests/test_notebook_mlflow_runs.py`, `tests/test_notebook_mlflow_ui.py`,
  and `tests/test_backtest.py`.

`plot_learning_curves` is validated structurally (returns a Plotly figure
with the expected number of panels); no rendering assertions.

## 5. Out of scope (YAGNI)

- Full Optuna search per sweep config (rejected in Q2 — too slow).
- Parallelizing the sweep across processes/GPUs.
- New SPA/UI surface or new FastAPI endpoints — everything flows through the
  existing MLflow tracking + notebook cells.
- Sweeping over anything other than train size × slide step (e.g. test size,
  feature sets) — can be added later by extending `build_sweep_grid`.
