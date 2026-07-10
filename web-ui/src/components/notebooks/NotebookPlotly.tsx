import { Suspense, lazy } from "react";

/**
 * Plotly renderer for notebook cells. Accepts a raw Plotly figure object
 * (as produced by ``Figure.to_dict()`` server-side) and renders it. Lazy
 * loads plotly so the notebook page doesn't pull ~1MB upfront.
 */
const Plot = lazy(async () => {
  const Plotly = (await import("plotly.js-dist-min")).default;
  const createPlotlyComponent = (await import("react-plotly.js/factory")).default;
  return { default: createPlotlyComponent(Plotly) };
});

interface PlotlyFigure {
  data?: unknown[];
  layout?: Record<string, unknown>;
  frames?: unknown[];
}

export function NotebookPlotly({ figure }: { figure: PlotlyFigure }) {
  // Reserve the figure's final height while plotly.js lazy-loads. A tiny
  // fallback made every plot grow ~400px after load, shifting the whole
  // page under the user's cursor (clicks landed on the wrong cell/line).
  const height =
    typeof figure.layout?.height === "number" ? figure.layout.height : 380;
  return (
    <Suspense
      fallback={
        <div style={{ minHeight: height }} className="text-xs text-ink-400">
          Loading plot…
        </div>
      }
    >
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={(figure.data ?? []) as any}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        layout={{ autosize: true, ...(figure.layout ?? {}) } as any}
        useResizeHandler
        style={{ width: "100%", minHeight: height }}
        config={{ displaylogo: false, responsive: true }}
      />
    </Suspense>
  );
}
