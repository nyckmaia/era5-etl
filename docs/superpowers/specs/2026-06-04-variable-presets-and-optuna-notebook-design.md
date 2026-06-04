# Design — Variable presets + "XGBoost with Optuna" notebook

Date: 2026-06-04

Two independent improvements to the `era5-etl` web UI.

## Melhoria 01 — Custom variable presets (ERA5 & ERA5-LAND wizards)

### Goal
On the Variables step of the download wizard (gridded datasets only), let the
user save the current checkbox selection as a **named preset**, load a preset
to re-apply that selection, update a preset, and delete it. Presets make it
easy to re-select the same variable set across downloads.

### Decisions (confirmed with user)
- **Scope: per-dataset.** ERA5 presets are separate from ERA5-LAND presets.
  A preset is only offered in the wizard of the dataset it was created for.
- **Persistence: backend JSON store**, mirroring `user_views_store.py`.

### Backend
- `src/era5_etl/web/variable_presets_store.py` — JSON at
  `_config_dir()/variable_presets.json` (next to `user_views.json`).
  Thread-locked, atomic temp-file replace. Record shape:
  `{id, dataset, name, variables: [api_name...], created_ts, updated_ts}`.
  Functions: `list_presets(dataset)`, `add_preset(dataset, name, variables)`,
  `update_preset(id, name, variables)`, `delete_preset(id)`,
  `find_by_name(dataset, name)`. Name uniqueness enforced per `(dataset, name)`
  (case-insensitive).
- `src/era5_etl/web/routes/variable_presets.py` — router prefix
  `/api/variable-presets`:
  - `GET /api/variable-presets?dataset=<name>` → list for that dataset.
  - `POST /api/variable-presets` → create (body: dataset, name, variables).
  - `PUT /api/variable-presets/{id}` → update name + variables.
  - `DELETE /api/variable-presets/{id}` → delete.
  Registered in `web/server.py`.
- Pydantic models in `web/models/__init__.py`: `VariablePresetIn`
  (`dataset`, `name`, `variables`) and `VariablePresetOut` (adds `id`,
  `created_ts`, `updated_ts`).
- Validation: `name` trimmed + non-empty; `dataset` must be a registered
  **gridded** dataset; incoming `variables` are filtered to that dataset's
  valid `api_name`s so a stale preset can never inject an unknown variable
  into a download request.

### Frontend (`web-ui/src/pages/DownloadWizard.tsx`, `StepVariables`)
- A "Presets" control row above the search filter:
  - `<select>` listing the dataset's saved presets; choosing one calls
    `onChange(preset.variables)` to apply it.
  - **Save as new** (prompts for a name → POST), **Update selected**
    (PUT the currently-loaded preset with the current selection),
    **Delete** (DELETE the selected preset, with confirm).
- `api.variablePresets.{list,create,update,del}` added to `lib/api.ts`;
  React Query keyed `["variable-presets", dataset]`, invalidated on mutation.
- Existing "Default preset / All / Clear" quick-links unchanged.
- i18n keys `wizard.variables.presets.*` added to `en.ts` and `pt.ts`.

### Tests
- `tests/test_variable_presets.py` — store CRUD + per-dataset isolation +
  unknown-variable filtering; route happy-path + validation via
  `TestClient`.

## Melhoria 02 — "XGBoost with Optuna" notebook template

### Goal
Duplicate the existing XGBoost template as **"XGBoost with Optuna"**, adding
Optuna hyperparameter/feature/lag/temporal-window search, an operational
forecast framing (predict day D+1 from data available up to D−6), cyclical
calendar features, and automatic GPU/CPU device selection.

### Decisions (confirmed with user)
- **Optuna budget:** `N_TRIALS = 30` default (editable at top).
- **Lag/forecast reconciliation:** keep short-lag naming
  (`temperature_2m_lag_1h`, …) but **offset every lag by the cutoff** so no
  future data leaks. `FORECAST_CUTOFF_HOURS = 168` (7 days = gap from D−6 to
  D+1); real shift for `_lag_Nh` is `168 + N` hours.

### Template file
`src/era5_etl/_data/notebook_templates/xgboost_optuna_forecast.json`, derived
from `xgboost_temperature_forecast.json`, keeping the inline helpers
(`inmet_with_era5_land`, `load_inmet_with_cache`, `plot_predictions`,
`log_model_run`). New/changed cells:

1. **GPU auto-detection (top).** `detect_xgb_device()` attempts a tiny
   `XGBRegressor(device="cuda", tree_method="hist").fit(...)` in `try/except`;
   sets `DEVICE = "cuda"` on success else `"cpu"`. Every XGBoost model uses
   `device=DEVICE`. Prints the chosen device.
2. **Forecast framing config.** Target = INMET temperature at each hour of day
   D+1; information cutoff = end of D−6 → `FORECAST_CUTOFF_HOURS = 168`.
   `LAG_HOURS = [0, 1, 2, 3, 6, 12, 24]` candidate short lags per meteo var.
3. **Lag feature construction.** For each active meteo variable and each lag L,
   build `<var>_lag_<L>h` = the bilinear ERA5-LAND value shifted by
   `(168 + L)` hours (group-shift within the time-ordered frame). Rows lacking
   full lag history are dropped.
4. **Cyclical calendar features** from the target timestamp (no leakage):
   `hora_sin`, `hora_cos`, `dia_ano_sin`, `dia_ano_cos`.
5. **Optuna study** (`direction="minimize"` on validation RMSE), searching:
   XGBoost hyperparams (`max_depth`, `learning_rate`, `n_estimators`,
   `subsample`, `colsample_bytree`, `min_child_weight`, `gamma`, `reg_alpha`,
   `reg_lambda`); **feature selection** (include each meteo var: bool);
   **lag selection** (include each lag: bool); **temporal window**
   (training-window length in days before the split — tunes effective start
   date). Temporal train/val split inside the objective (no shuffling).
6. **Refit + report.** Refit best config on train+val, evaluate on held-out
   test, report RMSE/MAE/R², `plot_predictions`, feature importance.
7. **Log run** via `log_model_run(model_name="xgboost_optuna", ...)` recording
   best params + chosen vars/lags/window + `test_fraction/n_train/n_test/
   num_days` so the Model runs panel reproduces it.

### Dependency
Add `optuna>=3.0` to `pyproject.toml` `[project].dependencies` (alongside the
notebook runtime stack) and install it in the dev environment.

### Tests
`tests/test_notebook_templates.py` — parallel guard test for
`xgboost_optuna_forecast`: asserts it logs the reproduction metrics, sets
`device=`, runs Optuna (`optuna.create_study` / `study.optimize`), builds the
cyclical features (`hora_sin`, `dia_ano_cos`, …) and the cutoff-offset lags.

## Out of scope
- INMET wizard (no variable checkboxes — unchanged).
- Sharing presets across datasets or exporting them.
- Distributed/parallel Optuna; GPU for anything other than XGBoost.
