# Model Runs Table Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the **Model runs** table in each `/notebooks` notebook — rename/uppercase headers, add Test Fraction / n_train / Num of Days columns (logged by the XGBoost template), make every column sortable, and add zebra striping.

**Architecture:** Three source changes plus a rebuild. (1) The XGBoost notebook template logs three new metrics. (2) `ModelRunsPanel.tsx` is refactored to a single `columns` descriptor array that drives the header, sorting, and body rows uniformly; known metric keys get a fixed ordered layout, unknown ones still append as generic columns. (3) i18n labels (en + pt). (4) Rebuild the SPA bundle that `era5 ui` serves.

**Tech Stack:** React 18 + TypeScript + Tailwind + react-i18next (Vite SPA in `web-ui/`), Python 3.12 + pytest (template + guard test), bundled JSON notebook templates.

---

## File Structure

- `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` — **modify** the metrics cell to log `test_fraction`, `n_train`, `num_days` (and `n_train` alongside existing `n_test`).
- `tests/test_notebook_templates.py` — **create** a guard test asserting the template logs the new metric keys.
- `web-ui/src/i18n/locales/en.ts` — **modify** `notebooks.runs.col` (rename + add keys).
- `web-ui/src/i18n/locales/pt.ts` — **modify** `notebooks.runs.col` (rename + add keys).
- `web-ui/src/components/notebooks/ModelRunsPanel.tsx` — **rewrite** to the column-descriptor model with sorting + zebra striping.
- `src/era5_etl/web/static/**` — **regenerated** build artifact (committed; this is what `era5 ui` serves).

No backend route or storage-schema change: `NotebookRun.metrics` is already a free-form `Record<string, unknown>`.

---

## Task 1: Template logs the new metrics (+ guard test)

**Files:**
- Test: `tests/test_notebook_templates.py` (create)
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` (metrics cell)

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_notebook_templates.py`:

```python
"""Guard: bundled notebook templates log the metrics the UI table expects."""

from __future__ import annotations

from era5_etl.notebooks.templates import load_template


def _code_sources(template_id: str) -> str:
    tpl = load_template(template_id)
    assert tpl is not None, f"template {template_id!r} not found"
    return "\n".join(
        c.get("source", "")
        for c in tpl.get("cells", [])
        if c.get("type") == "code"
    )


def test_xgboost_template_logs_new_run_metrics():
    src = _code_sources("xgboost_temperature_forecast")
    for key in ("test_fraction", "n_train", "n_test", "num_days"):
        assert f'"{key}"' in src, f"template must log metric {key!r}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -v`
Expected: FAIL — `test_fraction` / `n_train` / `num_days` not yet in the template (only `n_test` is present).

- [ ] **Step 3: Edit the template metrics cell**

In `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`, find the metrics code cell and replace its `source` value.

Find this exact string (the value of the metrics cell's `"source"`):

```
# --- Metrics --------------------------------------------------------\nimport numpy as np\nfrom sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score\n\ny_true = test[target_col].to_numpy()\ny_pred = model.predict(test[feature_cols])\nrmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))\nmae  = float(mean_absolute_error(y_true, y_pred))\nr2   = float(r2_score(y_true, y_pred))\nmetrics = {\"rmse\": rmse, \"mae\": mae, \"r2\": r2, \"n_test\": int(len(test))}\nprint(metrics)
```

Replace it with:

```
# --- Metrics --------------------------------------------------------\nimport numpy as np\nimport pandas as pd\nfrom sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score\n\ny_true = test[target_col].to_numpy()\ny_pred = model.predict(test[feature_cols])\nrmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))\nmae  = float(mean_absolute_error(y_true, y_pred))\nr2   = float(r2_score(y_true, y_pred))\nmetrics = {\n    \"rmse\": rmse,\n    \"mae\": mae,\n    \"r2\": r2,\n    \"test_fraction\": float(TEST_FRACTION),\n    \"n_train\": int(len(train)),\n    \"n_test\": int(len(test)),\n    \"num_days\": int((pd.to_datetime(DATE_END) - pd.to_datetime(DATE_START)).days) + 1,\n}\nprint(metrics)
```

(`TEST_FRACTION`, `train`, `test`, `DATE_START`, `DATE_END` are all already defined by earlier cells in the kernel's shared namespace; `pd` is imported in this cell for clarity.)

- [ ] **Step 4: Verify the JSON is still valid and the test passes**

Run: `py -3.12 -c "import json; json.load(open(r'src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json', encoding='utf-8')); print('json ok')"`
Expected: `json ok`

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -v`
Expected: PASS

- [ ] **Step 5: Run the existing notebook tests to confirm no regression**

Run: `py -3.12 -m pytest tests/test_notebook_routes.py tests/test_notebook_store.py -v`
Expected: PASS (template still loads and creates a notebook).

- [ ] **Step 6: Commit**

```bash
git add tests/test_notebook_templates.py src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): log test_fraction, n_train, num_days in xgboost template"
```

---

## Task 2: i18n labels (en + pt)

**Files:**
- Modify: `web-ui/src/i18n/locales/en.ts` (key `notebooks.runs.col`)
- Modify: `web-ui/src/i18n/locales/pt.ts` (key `notebooks.runs.col`)

No test (no frontend test runner). The only consumer of these keys is `ModelRunsPanel.tsx` (confirmed: no other file references `notebooks.runs.col.*`). Type-checking happens in Task 3.

- [ ] **Step 1: Replace the `col` block in `en.ts`**

Find:

```ts
      col: {
        when: "When",
        model: "Model",
        duration: "Duration",
        loadSource: "Load",
        loadTime: "Load time",
        notes: "Notes",
      },
```

Replace with:

```ts
      col: {
        start: "Start",
        model: "Model",
        trainingDuration: "Training Duration",
        dataSource: "Data Source",
        loadTime: "Load time",
        rmse: "RMSE",
        mae: "MAE",
        r2: "R2",
        testFraction: "Test Fraction",
        nTrain: "n_train",
        nTest: "n_test",
        numDays: "Num of Days",
        notes: "Notes",
      },
```

- [ ] **Step 2: Replace the `col` block in `pt.ts`**

Find:

```ts
      col: {
        when: "Quando",
        model: "Modelo",
        duration: "Duração",
        loadSource: "Carregamento",
        loadTime: "Tempo de carga",
        notes: "Notas",
      },
```

Replace with:

```ts
      col: {
        start: "Início",
        model: "Modelo",
        trainingDuration: "Duração do treino",
        dataSource: "Fonte de dados",
        loadTime: "Tempo de carga",
        rmse: "RMSE",
        mae: "MAE",
        r2: "R2",
        testFraction: "Fração de teste",
        nTrain: "n_train",
        nTest: "n_test",
        numDays: "Nº de dias",
        notes: "Notas",
      },
```

- [ ] **Step 3: Commit** (committed together with Task 3 after type-check passes — see Task 3 Step 4. Skip a separate commit here.)

---

## Task 3: Rewrite `ModelRunsPanel.tsx` (column model + sorting + zebra)

**Files:**
- Rewrite: `web-ui/src/components/notebooks/ModelRunsPanel.tsx`

Verification is `npm run lint` (= `tsc --noEmit`) since there is no unit-test runner.

- [ ] **Step 1: Replace the entire file with the column-descriptor implementation**

```tsx
import { Suspense, lazy, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { NotebookRun } from "@/lib/api";

const Plot = lazy(async () => {
  const Plotly = (await import("plotly.js-dist-min")).default;
  const createPlotlyComponent = (await import("react-plotly.js/factory")).default;
  return { default: createPlotlyComponent(Plotly) };
});

interface Props {
  runs: NotebookRun[];
}

// Metrics surfaced via the Data Source / Load time columns, not metric columns.
const LOAD_KEYS = new Set(["load_source", "load_duration_s"]);

// Known metric columns, in the exact left-to-right order. Any other metric a
// notebook logs is appended after these as a generic column (raw key header).
const FIXED_METRIC_ORDER = [
  "rmse",
  "mae",
  "r2",
  "test_fraction",
  "n_train",
  "n_test",
  "num_days",
];
const FIXED_SET = new Set(FIXED_METRIC_ORDER);

// Known metric key -> i18n label key (under notebooks.runs.col).
const METRIC_I18N: Record<string, string> = {
  rmse: "notebooks.runs.col.rmse",
  mae: "notebooks.runs.col.mae",
  r2: "notebooks.runs.col.r2",
  test_fraction: "notebooks.runs.col.testFraction",
  n_train: "notebooks.runs.col.nTrain",
  n_test: "notebooks.runs.col.nTest",
  num_days: "notebooks.runs.col.numDays",
};

// All non-load metric keys present, for the trend-chart selector.
function metricKeys(runs: NotebookRun[]): string[] {
  const keys = new Set<string>();
  runs.forEach((r) =>
    Object.keys(r.metrics ?? {}).forEach((k) => {
      if (!LOAD_KEYS.has(k)) keys.add(k);
    }),
  );
  return Array.from(keys);
}

// Metric keys present that are neither load keys nor in the fixed set.
function extraMetricKeys(runs: NotebookRun[]): string[] {
  const keys = new Set<string>();
  runs.forEach((r) =>
    Object.keys(r.metrics ?? {}).forEach((k) => {
      if (!LOAD_KEYS.has(k) && !FIXED_SET.has(k)) keys.add(k);
    }),
  );
  return Array.from(keys);
}

// Format a metric: test_fraction to 2 dp, integers bare, other floats to 4 dp.
function formatMetric(key: string, v: unknown): string {
  if (typeof v !== "number") return "—";
  if (key === "test_fraction") return v.toFixed(2);
  return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

// Read a run's load provenance with safe defaults for older runs.
function loadInfo(r: NotebookRun): { source: string; seconds: number | null } {
  const m = r.metrics ?? {};
  const src = typeof m.load_source === "string" ? m.load_source : "—";
  const sec = typeof m.load_duration_s === "number" ? m.load_duration_s : null;
  return { source: src, seconds: sec };
}

type SortValue = number | string | null;

interface Col {
  id: string;
  label: string;
  align: "left" | "right";
  sortValue: (r: NotebookRun) => SortValue;
  render: (r: NotebookRun) => ReactNode;
}

export function ModelRunsPanel({ runs }: Props) {
  const { t } = useTranslation();
  const allKeys = useMemo(() => metricKeys(runs), [runs]);
  const extraKeys = useMemo(() => extraMetricKeys(runs), [runs]);
  const [metric, setMetric] = useState<string>(
    allKeys.includes("rmse") ? "rmse" : (allKeys[0] ?? ""),
  );
  const [sort, setSort] = useState<{ colId: string; dir: "asc" | "desc" }>({
    colId: "start",
    dir: "desc",
  });

  const columns = useMemo<Col[]>(() => {
    const metricCols: Col[] = [...FIXED_METRIC_ORDER, ...extraKeys].map(
      (key): Col => ({
        id: `metric:${key}`,
        label: METRIC_I18N[key] ? t(METRIC_I18N[key]) : key,
        align: "right",
        sortValue: (r) => {
          const v = r.metrics?.[key];
          return typeof v === "number" || typeof v === "string" ? v : null;
        },
        render: (r) => formatMetric(key, r.metrics?.[key]),
      }),
    );
    return [
      {
        id: "start",
        label: t("notebooks.runs.col.start"),
        align: "left",
        sortValue: (r) => r.ts,
        render: (r) => new Date(r.ts).toLocaleString(),
      },
      {
        id: "model",
        label: t("notebooks.runs.col.model"),
        align: "left",
        sortValue: (r) => r.model_name ?? "",
        render: (r) => r.model_name,
      },
      {
        id: "trainingDuration",
        label: t("notebooks.runs.col.trainingDuration"),
        align: "right",
        sortValue: (r) => r.duration_s,
        render: (r) => `${r.duration_s.toFixed(2)}s`,
      },
      {
        id: "dataSource",
        label: t("notebooks.runs.col.dataSource"),
        align: "left",
        sortValue: (r) => loadInfo(r).source,
        render: (r) => loadInfo(r).source,
      },
      {
        id: "loadTime",
        label: t("notebooks.runs.col.loadTime"),
        align: "right",
        sortValue: (r) => loadInfo(r).seconds,
        render: (r) => {
          const s = loadInfo(r).seconds;
          return s === null ? "—" : `${s.toFixed(2)}s`;
        },
      },
      ...metricCols,
      {
        id: "notes",
        label: t("notebooks.runs.col.notes"),
        align: "left",
        sortValue: (r) => r.notes ?? "",
        render: (r) => r.notes || "",
      },
    ];
  }, [t, extraKeys]);

  const sortedRuns = useMemo(() => {
    const col = columns.find((c) => c.id === sort.colId) ?? columns[0];
    const arr = [...runs];
    arr.sort((a, b) => {
      const av = col.sortValue(a);
      const bv = col.sortValue(b);
      const an = av === null || av === undefined;
      const bn = bv === null || bv === undefined;
      if (an && bn) return 0;
      if (an) return 1; // nulls/missing always sort last
      if (bn) return -1;
      const base =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? base : -base;
    });
    return arr;
  }, [runs, columns, sort]);

  if (runs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-ink-200 p-4 text-center text-xs text-ink-500">
        {t("notebooks.runs.empty")}
      </div>
    );
  }

  const chartRuns = [...runs].sort((a, b) => a.ts - b.ts);
  const xs = chartRuns.map((_, i) => i + 1);
  const ys = chartRuns.map((r) => {
    const v = r.metrics?.[metric];
    return typeof v === "number" ? v : null;
  });

  function toggleSort(colId: string) {
    setSort((prev) =>
      prev.colId === colId
        ? { colId, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { colId, dir: "asc" },
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-ink-800">
          {t("notebooks.runs.title", { count: runs.length })}
        </h3>
        {allKeys.length > 0 && (
          <label className="flex items-center gap-1 text-xs text-ink-500">
            {t("notebooks.runs.metricLabel")}
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="rounded border border-ink-200 bg-white px-1.5 py-0.5 text-xs"
            >
              {allKeys.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {metric && ys.some((v) => v !== null) && (
        <Suspense fallback={<div className="h-32 animate-pulse rounded bg-ink-50" />}>
          <Plot
            data={[
              {
                x: xs,
                y: ys,
                type: "scatter",
                mode: "lines+markers",
                line: { color: "#0369a1" },
                marker: { size: 6 },
              },
            ]}
            layout={{
              autosize: true,
              height: 180,
              margin: { l: 40, r: 10, t: 10, b: 30 },
              xaxis: { title: { text: t("notebooks.runs.xAxis") }, dtick: 1 },
              yaxis: { title: { text: metric } },
              showlegend: false,
            }}
            useResizeHandler
            style={{ width: "100%" }}
            config={{ displaylogo: false, responsive: true, staticPlot: true }}
          />
        </Suspense>
      )}
      <div className="max-h-96 overflow-auto rounded-md border border-ink-200">
        <table className="min-w-full text-xs tabular-nums">
          <thead className="sticky top-0 z-10 bg-ink-50">
            <tr>
              {columns.map((c) => {
                const active = c.id === sort.colId;
                return (
                  <th key={c.id} className="font-medium text-ink-700">
                    <button
                      type="button"
                      onClick={() => toggleSort(c.id)}
                      className={`flex w-full items-center gap-1 px-2 py-1 hover:bg-ink-100 ${
                        c.align === "right" ? "justify-end" : "justify-start"
                      }`}
                    >
                      <span>{c.label}</span>
                      {active && (
                        <span className="text-[9px] text-ink-500">
                          {sort.dir === "asc" ? "▲" : "▼"}
                        </span>
                      )}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sortedRuns.map((r) => (
              <tr
                key={r.id}
                className="odd:bg-white even:bg-ink-50/60 hover:bg-sky-50/70"
              >
                {columns.map((c) => (
                  <td
                    key={c.id}
                    className={`px-2 py-1 ${
                      c.align === "right" ? "text-right" : "text-left"
                    } ${c.id === "notes" ? "text-ink-500" : "text-ink-600"}`}
                  >
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check the SPA**

Run: `cd web-ui && npm run lint`
Expected: no errors (exit 0). `npm run lint` is `tsc --noEmit`.

If `node_modules` is missing, install first (per project env note — bun cannot reach the registry):
`cd web-ui && NODE_OPTIONS="--use-system-ca" npm install` then re-run `npm run lint`.

- [ ] **Step 3: Verify there are no remaining references to the old i18n keys**

Run (from repo root): `git grep -n "runs.col.when\|runs.col.duration\|runs.col.loadSource" -- web-ui/src` 
Expected: no output (all renamed; only `ModelRunsPanel.tsx` used them).

- [ ] **Step 4: Commit the frontend source (component + i18n together)**

```bash
git add web-ui/src/components/notebooks/ModelRunsPanel.tsx web-ui/src/i18n/locales/en.ts web-ui/src/i18n/locales/pt.ts
git commit -m "feat(ui): sortable Model runs table with new columns + zebra striping"
```

---

## Task 4: Rebuild the SPA bundle and verify

**Files:**
- Regenerated: `src/era5_etl/web/static/**` (build artifact served by `era5 ui`)

- [ ] **Step 1: Build the SPA**

Run: `make ui-build`
Expected: a fresh bundle written under `src/era5_etl/web/static/` (the `ui-build` target runs `bun install && bun run build`).

If `bun install` fails to reach the registry (known in this environment), build with npm instead:
`cd web-ui && NODE_OPTIONS="--use-system-ca" npm install && npm run build`
The Vite config emits into `src/era5_etl/web/static/`.

- [ ] **Step 2: Smoke-test the served UI**

Run the app (suggest the user run interactively): `! py -3.12 -m era5_etl ui` (or `make api-dev` + the built static), open `/notebooks`, open a notebook with logged runs, expand **Model runs**, and confirm:
- Headers read: Start · Model · Training Duration · Data Source · Load time · RMSE · MAE · R2 · Test Fraction · n_train · n_test · Num of Days · Notes.
- Clicking any header sorts the table and shows a ▲/▼ indicator; default is Start ▼ (newest first).
- Rows alternate background colour and highlight on hover.
- Old runs show `—` under Test Fraction / n_train / Num of Days; a freshly re-run notebook populates them.

- [ ] **Step 3: Commit the rebuilt bundle**

```bash
git add src/era5_etl/web/static
git commit -m "build(ui): rebuild SPA with updated Model runs table"
```

---

## Task 5: Final verification

- [ ] **Step 1: Full Python test suite**

Run: `py -3.12 -m pytest`
Expected: all pass (previously 178 + the new template guard test).

- [ ] **Step 2: SPA type-check clean**

Run: `cd web-ui && npm run lint`
Expected: exit 0.

---

## Self-Review (author check)

**Spec coverage** (each requirement → task):
- a) When→Start — Task 2 (`start`) + Task 3 (`start` column). ✓
- b) Duration→Training Duration — Task 2 (`trainingDuration`) + Task 3. ✓
- c) Load→Data Source — Task 2 (`dataSource`) + Task 3. ✓
- d) rmse/mae/r2 uppercase — Task 2 (`rmse/mae/r2` labels) + Task 3 METRIC_I18N. ✓
- e) Test Fraction after R2 (0–1, 2 dp) — Task 1 (log `test_fraction`) + Task 3 (`FIXED_METRIC_ORDER` position + `formatMetric` 2 dp). ✓
- f) n_train between R2 and n_test; Num of Days after n_test — Task 1 (log both) + Task 3 (`FIXED_METRIC_ORDER`). ✓
- g) Sortable by any column + zebra — Task 3 (sort state/comparator + `odd:/even:` striping). ✓

**Placeholder scan:** none — every code/edit step shows exact content.

**Type consistency:** `Col`, `SortValue`, `FIXED_METRIC_ORDER`, `METRIC_I18N`, `formatMetric`, `loadInfo`, `metricKeys`, `extraMetricKeys` are all defined in Task 3 and used consistently. i18n keys added in Task 2 exactly match the `notebooks.runs.col.*` keys referenced in Task 3.

**Notes:**
- Default sort `start`/`desc` preserves today's newest-first ordering.
- Generic fallback (decision #2) preserved via `extraMetricKeys` + raw-key header.
- No backend/storage change (`metrics` is a free-form map); old runs render `—` for new columns (decision #1).
