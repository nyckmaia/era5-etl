import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Play, WandSparkles } from "lucide-react";
import { Suspense, lazy, useState } from "react";
import { format as formatSql } from "sql-formatter";

import { api, type ColumnPrecision } from "@/lib/api";
import { cn } from "@/lib/format";

const SqlEditor = lazy(() => import("@/components/SqlEditor"));

function formatCell(
  raw: string | number | null,
  precision: ColumnPrecision,
): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return String(raw);
  const { decimals, method } = precision;
  if (method === "truncate") {
    const f = 10 ** decimals;
    return (Math.trunc(n * f) / f).toFixed(decimals);
  }
  return n.toFixed(decimals);
}

export function QueryPage() {
  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const [dataset, setDataset] = useState<string>("era5-land");
  const [sql, setSql] = useState<string>(
    `SELECT date, hour_utc, COUNT(*) AS n\nFROM era5_land\nGROUP BY 1, 2\nORDER BY 1, 2\nLIMIT 100;`,
  );
  const [limit, setLimit] = useState<number>(1000);

  const schemaQuery = useQuery({
    queryKey: ["query-schema", dataset],
    queryFn: () => api.querySchema(dataset),
  });

  const precisionQuery = useQuery({
    queryKey: ["precision", dataset],
    queryFn: () => api.precision.get(dataset),
  });

  const runQuery = useMutation({
    mutationFn: () => api.query({ dataset, sql, limit }),
  });

  const schemaColumns = schemaQuery.data?.columns ?? [];
  const viewName = schemaQuery.data?.view ?? dataset.replace(/-/g, "_");

  const handleFormat = () => {
    try {
      setSql(
        formatSql(sql, {
          language: "duckdb",
          keywordCase: "upper",
          indentStyle: "standard",
        }),
      );
    } catch {
      // Leave SQL untouched if it cannot be parsed.
    }
  };

  const runWithFormat = () => {
    handleFormat();
    runQuery.mutate();
  };

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

        <Suspense
          fallback={
            <textarea
              className="input min-h-[240px] font-mono text-xs"
              value={sql}
              onChange={(e) => setSql(e.target.value)}
            />
          }
        >
          <SqlEditor
            value={sql}
            onChange={setSql}
            onRun={runWithFormat}
            schemaColumns={schemaColumns}
            viewName={viewName}
          />
        </Suspense>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <button className="btn-outline" onClick={handleFormat} type="button">
            <WandSparkles className="h-4 w-4" />
            Formatar
          </button>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs uppercase tracking-wide text-ink-500">
              Linhas
              <input
                type="number"
                min={1}
                max={100000}
                value={limit}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v)) setLimit(Math.min(100000, Math.max(1, v)));
                }}
                className="input w-24 text-xs"
              />
            </label>
            <button
              className="btn-primary"
              onClick={() => runQuery.mutate()}
              disabled={runQuery.isPending}
            >
              {runQuery.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              Run query
            </button>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-ink-400">
          Ctrl/Cmd+Enter executa a query.
        </p>
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
                  {runQuery.data.columns.map((c, i) => (
                    <th key={c} className="px-3 py-2 text-left font-medium">
                      <div>{c}</div>
                      <div className="text-[10px] font-normal text-ink-400">
                        {runQuery.data.column_types[i]}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runQuery.data.rows.map((row, i) => (
                  <tr key={i} className="border-t border-ink-100">
                    {row.map((cell, j) => {
                      if (cell === null) {
                        return (
                          <td key={j} className="px-3 py-1.5 font-mono">
                            <span className="text-ink-300">·</span>
                          </td>
                        );
                      }
                      const colName = runQuery.data.columns[j];
                      const colType = runQuery.data.column_types[j];
                      let display = String(cell);
                      if (colType === "float" && Number.isFinite(Number(cell))) {
                        const cfg = precisionQuery.data;
                        if (cfg) {
                          const override = cfg.columns[colName];
                          display = formatCell(
                            cell,
                            override ?? {
                              decimals: cfg.default_decimals,
                              method: cfg.default_method,
                            },
                          );
                        }
                      }
                      return (
                        <td key={j} className="px-3 py-1.5 font-mono">
                          {display}
                        </td>
                      );
                    })}
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
