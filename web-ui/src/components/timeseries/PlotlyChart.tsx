import { Suspense, lazy, useMemo } from "react";

import type { TSSeriesResult } from "@/lib/api";

import { computeStats } from "./stats";
import type { TraceStyle, CellLayout } from "./types";

// Lazy + factory over plotly.js-dist-min keeps Plotly (~1MB) out of the
// main bundle and avoids pulling the full plotly.js package.
const Plot = lazy(async () => {
  const Plotly = (await import("plotly.js-dist-min")).default;
  const createPlotlyComponent = (await import("react-plotly.js/factory"))
    .default;
  return { default: createPlotlyComponent(Plotly) };
});

interface Props {
  seriesId: string[]; // stable ids, index-aligned to `results`
  results: TSSeriesResult[];
  styles: Record<string, TraceStyle>;
  layout: CellLayout;
  /** Per series (index-aligned to results): draw a dashed mean line. */
  showMean: boolean[];
  /** Per series (index-aligned): visual-only Y unit conversion. */
  transformFns: ((v: number) => number)[];
}

export function PlotlyChart({
  seriesId,
  results,
  styles,
  layout,
  showMean,
  transformFns,
}: Props) {
  const data = useMemo(() => {
    const traces: Record<string, unknown>[] = [];
    // Iterate by ORIGINAL index so style/seriesId/showMean stay aligned
    // even when an earlier series errored or returned no points.
    results.forEach((r, i) => {
      if (r.error || r.x.length === 0) return;
      const st = styles[seriesId[i]] ?? DEFAULT_STYLE;
      const yaxis = r.axis === "y2" ? "y2" : "y";
      const tf = transformFns[i] ?? ((v: number) => v);
      const yv = r.y.map((v) => (v == null ? v : tf(v)));
      traces.push({
        type: "scattergl",
        mode: st.mode,
        name: r.name,
        x: r.x,
        y: yv,
        yaxis,
        line: { color: st.color, dash: st.dash, width: st.width },
        marker: { color: st.color, size: Math.max(4, st.width + 2) },
        connectgaps: false,
      });
      if (showMean[i]) {
        const m = computeStats(yv).mean;
        if (m != null) {
          traces.push({
            type: "scattergl",
            mode: "lines",
            name: `${r.name} (média)`,
            x: [r.x[0], r.x[r.x.length - 1]],
            y: [m, m],
            yaxis,
            line: {
              color: st.color,
              dash: "dash",
              width: Math.max(1, st.width - 0.5),
            },
            hoverinfo: "skip",
            showlegend: false,
          });
        }
      }
    });
    return traces;
  }, [results, styles, seriesId, showMean, transformFns]);

  const hasY2 = results.some((r) => !r.error && r.axis === "y2");

  const plotLayout = useMemo(
    () => ({
      autosize: true,
      uirevision: "keep", // preserve zoom across restyles
      title: layout.title
        ? { text: layout.title, font: { size: 15 } }
        : undefined,
      margin: { l: 56, r: hasY2 ? 56 : 24, t: layout.title ? 40 : 16, b: 40 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "ui-sans-serif, system-ui", size: 12, color: "#334155" },
      xaxis: {
        type: "date",
        gridcolor: "#e8edf3",
        linecolor: "#cbd5e1",
        zeroline: false,
      },
      yaxis: {
        type: layout.logY ? "log" : "linear",
        gridcolor: "#e8edf3",
        linecolor: "#cbd5e1",
        zeroline: false,
      },
      yaxis2: {
        type: layout.logY2 ? "log" : "linear",
        overlaying: "y",
        side: "right",
        showgrid: false,
        zeroline: false,
      },
      showlegend: layout.showLegend,
      legend: { orientation: "h", y: -0.18 },
    }),
    [layout, hasY2],
  );

  return (
    <Suspense
      fallback={
        <div className="flex h-[360px] items-center justify-center text-sm text-ink-400">
          Carregando gráfico…
        </div>
      }
    >
      <Plot
        data={data as never}
        layout={plotLayout as never}
        config={
          {
            displaylogo: false,
            responsive: true,
            modeBarButtonsToRemove: ["lasso2d", "select2d"],
          } as never
        }
        useResizeHandler
        style={{ width: "100%", height: "380px" }}
      />
    </Suspense>
  );
}

export const DEFAULT_STYLE: TraceStyle = {
  color: "#0284c7",
  dash: "solid",
  width: 2,
  mode: "lines",
};

// A small ocean→moss→amber cycle so overlaid traces are distinguishable
// out of the box (matches the app palette).
export const STYLE_CYCLE: string[] = [
  "#0284c7",
  "#16a34a",
  "#f59e0b",
  "#9333ea",
  "#dc2626",
  "#0369a1",
];
