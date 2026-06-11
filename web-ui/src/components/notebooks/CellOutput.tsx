import { AlertTriangle } from "lucide-react";
import { Fragment } from "react";

import type { CellOutput as CellOutputT } from "@/lib/api";

import { NotebookPlotly } from "./NotebookPlotly";

interface DataFrameJSON {
  schema: Array<{ name: string; dtype: string }>;
  rows: unknown[][];
  truncated: boolean;
  total_rows: number;
  /** Row-index values, aligned with `rows`. Rendered as the first column. */
  index?: unknown[];
  index_name?: string;
  /** Draw a `…` ellipsis row before the row at this position (head/tail). */
  ellipsis_after?: number | null;
  /** Decimals for float columns (pandas `display.precision`). */
  float_precision?: number;
}

/** Format one cell: float columns honour `precision`; null renders muted. */
function formatCell(
  v: unknown,
  dtype: string,
  precision: number | undefined,
) {
  if (v === null || v === undefined) {
    return <span className="text-ink-300">null</span>;
  }
  if (
    typeof v === "number" &&
    dtype.startsWith("float") &&
    precision != null &&
    Number.isFinite(v)
  ) {
    return v.toFixed(precision);
  }
  return String(v);
}

function DataFrameTable({ df }: { df: DataFrameJSON }) {
  const hasIndex = Array.isArray(df.index);
  const ellipsisAfter = df.ellipsis_after ?? null;
  const idxCell =
    "border-b border-r border-ink-200 px-2 py-1 text-left font-medium text-ink-500";

  return (
    <div className="overflow-auto rounded-md border border-ink-200">
      <table className="min-w-full text-xs tabular-nums">
        <thead className="sticky top-0 bg-ink-50">
          <tr>
            {hasIndex && (
              <th className={idxCell}>
                <div>{df.index_name || " "}</div>
                <div className="text-[10px] font-normal text-ink-400">
                  &nbsp;
                </div>
              </th>
            )}
            {df.schema.map((c) => (
              <th
                key={c.name}
                className="border-b border-ink-200 px-2 py-1 text-left font-medium text-ink-700"
              >
                <div>{c.name}</div>
                <div className="text-[10px] font-normal text-ink-400">
                  {c.dtype}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {df.rows.map((row, i) => (
            <Fragment key={i}>
              {ellipsisAfter !== null && i === ellipsisAfter && (
                <tr className="text-ink-400">
                  {hasIndex && (
                    <td className="border-b border-r border-ink-100 px-2 py-1 text-center">
                      …
                    </td>
                  )}
                  {df.schema.map((c) => (
                    <td
                      key={c.name}
                      className="border-b border-ink-100 px-2 py-1 text-center"
                    >
                      …
                    </td>
                  ))}
                </tr>
              )}
              <tr className="even:bg-ink-50/50">
                {hasIndex && (
                  <td className="border-b border-r border-ink-100 px-2 py-1 font-medium text-ink-500">
                    {String(df.index?.[i] ?? "")}
                  </td>
                )}
                {row.map((v, j) => (
                  <td
                    key={j}
                    className="border-b border-ink-100 px-2 py-1 text-ink-600"
                  >
                    {formatCell(v, df.schema[j]?.dtype ?? "", df.float_precision)}
                  </td>
                ))}
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
      {df.truncated && (
        <div className="bg-ink-50 px-2 py-1 text-[11px] text-ink-500">
          Showing {df.rows.length} of {df.total_rows.toLocaleString()} rows
          (head + tail).
        </div>
      )}
    </div>
  );
}

export function CellOutput({ output }: { output: CellOutputT }) {
  if (output.type === "stream") {
    if (output.name === "warning") {
      return (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <pre className="whitespace-pre-wrap font-mono">{output.text}</pre>
        </div>
      );
    }
    const isErr = output.name === "stderr";
    return (
      <pre
        className={`whitespace-pre-wrap rounded-md px-3 py-2 font-mono text-xs ${
          isErr ? "bg-rose-50 text-rose-800" : "bg-ink-50 text-ink-700"
        }`}
      >
        {output.text}
      </pre>
    );
  }
  if (output.type === "error") {
    return (
      <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-xs">
        <div className="flex items-center gap-2 font-medium text-rose-800">
          <AlertTriangle className="h-4 w-4" />
          {output.ename}: {output.evalue}
        </div>
        {output.traceback.length > 0 && (
          <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] text-rose-700">
            {output.traceback.join("")}
          </pre>
        )}
      </div>
    );
  }
  if (output.type === "display") {
    if (output.mime === "application/vnd.plotly.v1+json") {
      const data = output.data as { figure: unknown };
      return <NotebookPlotly figure={data.figure as never} />;
    }
    if (output.mime === "application/vnd.dataframe+json") {
      return <DataFrameTable df={output.data as DataFrameJSON} />;
    }
    if (output.mime === "text/plain") {
      const data = output.data as { text: string };
      return (
        <pre className="whitespace-pre-wrap rounded-md bg-ink-50 px-3 py-2 font-mono text-xs text-ink-700">
          {data.text}
        </pre>
      );
    }
  }
  return null;
}
