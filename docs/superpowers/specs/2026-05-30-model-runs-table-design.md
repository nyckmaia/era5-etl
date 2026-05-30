# Model runs table enhancements — design

**Date:** 2026-05-30
**Status:** Approved (design)
**Area:** Web UI — `/notebooks` → notebook editor → **Model runs** panel

## Problem

The **Model runs** table shown under each notebook (component
`web-ui/src/components/notebooks/ModelRunsPanel.tsx`) currently shows:

```
When · Model · Duration · Load · Load time · rmse · mae · r2 · n_test · Notes
```

The metric columns (`rmse`, `mae`, `r2`, `n_test`) are rendered **dynamically**
from whatever keys each run logged via `log_model_run(metrics=...)`. The
XGBoost template (`src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`)
logs exactly `{"rmse", "mae", "r2", "n_test"}` plus the auto-attached
`load_source` / `load_duration_s` (which feed the Load / Load time columns).

The user wants:

- a) `When` → **Start**
- b) `Duration` → **Training Duration**
- c) `Load` → **Data Source**
- d) `rmse` / `mae` / `r2` → **RMSE** / **MAE** / **R2** (uppercase)
- e) After **R2**, add **Test Fraction** (0–1, 2 decimals)
- f) Add **n_train** (training point count) between R2 and `n_test`; after
  `n_test` add **Num of Days** (number of days in the selected period)
- g) Make the table sortable by any column; improve the visual with
  alternating row coloring (zebra striping)

## Key finding / constraint

`Test Fraction`, `n_train`, and `Num of Days` are **not present in run records
today** and cannot be derived on the frontend:

- `n_train` and `test_fraction` need the total row count `n`, which is never
  logged (only `n_test` is).
- `Num of Days` only survives as free text inside the `notes` field
  (`period=DATE_START..DATE_END`).

Therefore real values require logging the new metrics at training time in the
notebook template. This is a data-flow change, not just a rendering change.

## Decisions (confirmed with user)

1. **Data source:** log the three new values in the template's
   `log_model_run(metrics=...)`. Existing logged runs will show `—` for the
   new columns until the notebook is re-run. *(Accepted.)*
2. **Generic fallback retained:** known metric keys get friendly headers in a
   fixed order; any *other* metric a notebook logs still appears as an extra
   column. Preserves the existing plug-in rendering. *(Accepted.)*
3. **Num of Days =** calendar days of the selected period,
   `DATE_END − DATE_START + 1` (e.g. `2022-01-01..2024-12-31` = 1096).
   *(Accepted.)*
4. **Test Fraction =** the configured `TEST_FRACTION` value (e.g. `0.20`), not
   the realized split ratio. *(Accepted.)*

## Approach

**Frontend rendering model: column-descriptor refactor.** Replace the
hand-written `<th>`/`<td>` cells with a single `columns` array. Each column
declares:

```ts
type Col = {
  id: string;                              // stable id, used as sort key
  label: string;                           // header text (already translated)
  align: "left" | "right";
  sortValue: (r: NotebookRun) => number | string | null;
  render: (r: NotebookRun) => React.ReactNode;
};
```

The header row, the sort handler, and the body rows all derive from this one
array. The generic-metric fallback is just "extra `Col` entries appended after
the known ones."

Alternative considered and rejected: a minimal patch keeping inline cells plus
a `switch` for sort values — sorting and rendering would drift apart and every
column change would touch three places.

## Design detail

### 1. Template change — `xgboost_temperature_forecast.json`

In the metrics cell, extend the logged dict. All inputs are already in scope
(`train`, `test` from the split cell; `TEST_FRACTION`, `DATE_START`,
`DATE_END` from the config cell; `pd` imported):

```python
metrics = {
    "rmse": rmse,
    "mae": mae,
    "r2": r2,
    "test_fraction": float(TEST_FRACTION),
    "n_train": int(len(train)),
    "n_test": int(len(test)),
    "num_days": int((pd.to_datetime(DATE_END) - pd.to_datetime(DATE_START)).days) + 1,
}
```

No change to `log_model_run` itself or the run-storage backend — `metrics` is
already a free-form map.

### 2. Column model & order — `ModelRunsPanel.tsx`

Fixed metric order (always rendered; missing values show `—`):

```
["rmse", "mae", "r2", "test_fraction", "n_train", "n_test", "num_days"]
```

Full left-to-right column order:

```
Start · Model · Training Duration · Data Source · Load time ·
RMSE · MAE · R2 · Test Fraction · n_train · n_test · Num of Days ·
[extra logged metrics…] · Notes
```

Extra (unknown) metric keys present in any run — anything not in the fixed
list and not a LOAD key (`load_source`, `load_duration_s`) — are appended as
generic columns rendered with the raw key as header (current behavior).

Per-column formatting:

| Column         | Format                              |
|----------------|-------------------------------------|
| Start          | `new Date(r.ts).toLocaleString()`   |
| Model          | `r.model_name`                      |
| Training Duration | `r.duration_s.toFixed(2)`s       |
| Data Source    | `loadInfo(r).source`                |
| Load time      | `…s` or `—`                         |
| RMSE/MAE/R2    | 4 decimals (existing `fmtMetric`)   |
| Test Fraction  | 2 decimals (`0.20`); `—` if missing |
| n_train/n_test/num_days | integer (existing `fmtMetric`) |
| extra metrics  | existing `fmtMetric` (int or 4 dp)  |
| Notes          | `r.notes` or empty                  |

### 3. Sorting

- `useState<{ colId: string; dir: "asc" | "desc" }>` with default
  `{ colId: "start", dir: "desc" }` (newest first — matches current behavior).
- Each header is a `<button>`: clicking a new column sorts ascending; clicking
  the active column toggles direction. Active column shows a ▲/▼ indicator.
- Comparator: `null`/`undefined` sort last regardless of direction; strings via
  `localeCompare`; numbers numerically.
- The trend chart above the table keeps its own chronological sort
  (`[...runs].sort((a,b) => a.ts - b.ts)`); table sorting is independent.

### 4. Visual

- Zebra striping: `odd:bg-white even:bg-ink-50/60`.
- Row hover: `hover:bg-sky-50/70`.
- Sticky header: `sticky top-0 z-10` on `<thead>` (the container is
  `overflow-auto`), keeping `bg-ink-50`.
- Header buttons: `cursor-pointer`, subtle hover, sort arrow.

### 5. i18n — `web-ui/src/i18n/locales/{en,pt}.ts`, key `notebooks.runs.col`

Rename / add keys:

| Key              | en                  | pt                   |
|------------------|---------------------|----------------------|
| `start` (was `when`) | Start           | Início               |
| `model`          | Model               | Modelo               |
| `trainingDuration` (was `duration`) | Training Duration | Duração do treino |
| `dataSource` (was `loadSource`) | Data Source | Fonte de dados   |
| `loadTime`       | Load time           | Tempo de carga       |
| `rmse`           | RMSE                | RMSE                 |
| `mae`            | MAE                 | MAE                  |
| `r2`             | R2                  | R2                   |
| `testFraction`   | Test Fraction       | Fração de teste      |
| `nTrain`         | n_train             | n_train              |
| `nTest`          | n_test              | n_test               |
| `numDays`        | Num of Days         | Nº de dias           |
| `notes`          | Notes               | Notas                |

Known metric key → i18n label is resolved via a small map in the component;
unknown extra metrics fall back to the raw key (no translation).

### 6. Build & tests

- The SPA in `web-ui/` is gitignored and `era5 ui` serves a prebuilt bundle
  (`src/era5_etl/web/static/assets/index-*.js`), so the TSX change is not
  visible until the SPA is rebuilt (`make ui-build` / `bun run build`). The
  rebuild step is part of delivering this change.
- Add a small pytest guard asserting the template's metrics cell source
  contains the three new keys (`test_fraction`, `n_train`, `num_days`), so the
  template and the table stay in sync.

## Out of scope (YAGNI)

- No backfill of historical runs.
- No CSV/clipboard export.
- No per-column show/hide UI.
- No change to the run-storage backend schema.
- No new realized-fraction metric (configured `TEST_FRACTION` is logged).

## Files touched

- `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`
- `web-ui/src/components/notebooks/ModelRunsPanel.tsx`
- `web-ui/src/i18n/locales/en.ts`
- `web-ui/src/i18n/locales/pt.ts`
- `tests/` — new template-metrics guard test
- Rebuilt SPA bundle under `src/era5_etl/web/static/` (build artifact)
