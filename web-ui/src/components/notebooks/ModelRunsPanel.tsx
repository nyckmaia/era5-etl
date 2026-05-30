import { Suspense, lazy, useMemo, useState } from "react";
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

// Metrics rendered in their own dedicated columns, not the generic metric grid.
const LOAD_KEYS = new Set(["load_source", "load_duration_s"]);

function metricKeys(runs: NotebookRun[]): string[] {
  const keys = new Set<string>();
  runs.forEach((r) =>
    Object.keys(r.metrics ?? {}).forEach((k) => {
      if (!LOAD_KEYS.has(k)) keys.add(k);
    }),
  );
  return Array.from(keys);
}

// Format a metric value: integers without decimals, floats to 4 places.
function fmtMetric(v: unknown): string {
  if (typeof v !== "number") return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

// Read a run's load provenance with safe defaults for older runs.
function loadInfo(r: NotebookRun): { source: string; seconds: number | null } {
  const m = r.metrics ?? {};
  const src = typeof m.load_source === "string" ? m.load_source : "—";
  const sec =
    typeof m.load_duration_s === "number" ? m.load_duration_s : null;
  return { source: src, seconds: sec };
}

export function ModelRunsPanel({ runs }: Props) {
  const { t } = useTranslation();
  const allKeys = useMemo(() => metricKeys(runs), [runs]);
  const [metric, setMetric] = useState<string>(
    allKeys.includes("rmse") ? "rmse" : (allKeys[0] ?? ""),
  );

  if (runs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-ink-200 p-4 text-center text-xs text-ink-500">
        {t("notebooks.runs.empty")}
      </div>
    );
  }

  const sorted = [...runs].sort((a, b) => a.ts - b.ts);
  const xs = sorted.map((_, i) => i + 1);
  const ys = sorted.map((r) => {
    const v = r.metrics?.[metric];
    return typeof v === "number" ? v : null;
  });

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
      <div className="overflow-auto rounded-md border border-ink-200">
        <table className="min-w-full text-xs tabular-nums">
          <thead className="bg-ink-50">
            <tr>
              <th className="px-2 py-1 text-left font-medium text-ink-700">
                {t("notebooks.runs.col.when")}
              </th>
              <th className="px-2 py-1 text-left font-medium text-ink-700">
                {t("notebooks.runs.col.model")}
              </th>
              <th className="px-2 py-1 text-right font-medium text-ink-700">
                {t("notebooks.runs.col.duration")}
              </th>
              <th className="px-2 py-1 text-left font-medium text-ink-700">
                {t("notebooks.runs.col.loadSource")}
              </th>
              <th className="px-2 py-1 text-right font-medium text-ink-700">
                {t("notebooks.runs.col.loadTime")}
              </th>
              {allKeys.map((k) => (
                <th key={k} className="px-2 py-1 text-right font-medium text-ink-700">
                  {k}
                </th>
              ))}
              <th className="px-2 py-1 text-left font-medium text-ink-700">
                {t("notebooks.runs.col.notes")}
              </th>
            </tr>
          </thead>
          <tbody>
            {[...runs]
              .sort((a, b) => b.ts - a.ts)
              .map((r) => (
                <tr key={r.id} className="even:bg-ink-50/50">
                  <td className="px-2 py-1 text-ink-600">
                    {new Date(r.ts).toLocaleString()}
                  </td>
                  <td className="px-2 py-1 text-ink-600">{r.model_name}</td>
                  <td className="px-2 py-1 text-right text-ink-600">
                    {r.duration_s.toFixed(2)}s
                  </td>
                  <td className="px-2 py-1 text-ink-600">
                    {loadInfo(r).source}
                  </td>
                  <td className="px-2 py-1 text-right text-ink-600">
                    {loadInfo(r).seconds === null
                      ? "—"
                      : `${loadInfo(r).seconds!.toFixed(2)}s`}
                  </td>
                  {allKeys.map((k) => (
                    <td key={k} className="px-2 py-1 text-right text-ink-600">
                      {fmtMetric(r.metrics?.[k])}
                    </td>
                  ))}
                  <td className="px-2 py-1 text-ink-500">{r.notes || ""}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
