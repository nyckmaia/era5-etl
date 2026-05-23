import { AlertTriangle } from "lucide-react";

import type { CellOutput as CellOutputT } from "@/lib/api";

import { NotebookPlotly } from "./NotebookPlotly";

interface DataFrameJSON {
  schema: Array<{ name: string; dtype: string }>;
  rows: unknown[][];
  truncated: boolean;
  total_rows: number;
}

function DataFrameTable({ df }: { df: DataFrameJSON }) {
  return (
    <div className="overflow-auto rounded-md border border-ink-200">
      <table className="min-w-full text-xs tabular-nums">
        <thead className="sticky top-0 bg-ink-50">
          <tr>
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
            <tr key={i} className="even:bg-ink-50/50">
              {row.map((v, j) => (
                <td
                  key={j}
                  className="border-b border-ink-100 px-2 py-1 text-ink-600"
                >
                  {v === null || v === undefined ? (
                    <span className="text-ink-300">null</span>
                  ) : (
                    String(v)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {df.truncated && (
        <div className="bg-ink-50 px-2 py-1 text-[11px] text-ink-500">
          Showing first {df.rows.length} of {df.total_rows.toLocaleString()} rows.
        </div>
      )}
    </div>
  );
}

export function CellOutput({ output }: { output: CellOutputT }) {
  if (output.type === "stream") {
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
