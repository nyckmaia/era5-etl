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
