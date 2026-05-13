import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/format";

export function QueryPage() {
  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const [dataset, setDataset] = useState<string>("era5-land");
  const [sql, setSql] = useState<string>(
    `SELECT date, hour_utc, COUNT(*) AS n\nFROM era5_land_view\nGROUP BY 1, 2\nORDER BY 1, 2\nLIMIT 100;`,
  );

  const runQuery = useMutation({
    mutationFn: () => api.query({ dataset, sql, limit: 100 }),
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">SQL query</h1>
        <p className="mt-1 text-ink-500">
          Read-only queries against the dataset's DuckDB view. <code>INSERT</code>,{" "}
          <code>DROP</code>, etc. are blocked server-side.
        </p>
      </header>

      <div className="card p-6">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="text-xs uppercase tracking-wide text-ink-500">Dataset</label>
          <div className="flex gap-2">
            {datasets?.map((d) => (
              <button
                key={d.name}
                onClick={() => setDataset(d.name)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium",
                  dataset === d.name
                    ? "bg-ocean-600 text-white"
                    : "bg-ink-100 text-ink-500 hover:bg-ink-200",
                )}
              >
                {d.name}
              </button>
            ))}
          </div>
        </div>
        <textarea
          className="input min-h-[140px] font-mono text-xs"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
        />
        <div className="mt-3 flex justify-end">
          <button
            className="btn-primary"
            onClick={() => runQuery.mutate()}
            disabled={runQuery.isPending}
          >
            <Play className="h-4 w-4" />
            Run query
          </button>
        </div>
      </div>

      {runQuery.isError ? (
        <p className="text-sm text-red-600">{(runQuery.error as Error).message}</p>
      ) : null}

      {runQuery.data ? (
        <div className="card overflow-hidden">
          <div className="border-b border-ink-100 px-5 py-3 text-xs text-ink-500">
            <span className="font-medium text-ink-800">{runQuery.data.row_count}</span> rows
            {runQuery.data.truncated ? " (truncated)" : null}
          </div>
          <div className="max-h-[60vh] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-ink-50">
                <tr>
                  {runQuery.data.columns.map((c) => (
                    <th key={c} className="px-3 py-2 text-left font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runQuery.data.rows.map((row, i) => (
                  <tr key={i} className="border-t border-ink-100">
                    {row.map((cell, j) => (
                      <td key={j} className="px-3 py-1.5 font-mono">
                        {cell === null ? <span className="text-ink-300">·</span> : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
