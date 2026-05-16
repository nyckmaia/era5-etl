import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getRouteApi } from "@tanstack/react-router";
import {
  Download,
  Loader2,
  Play,
  SlidersHorizontal,
  WandSparkles,
} from "lucide-react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { format as formatSql } from "sql-formatter";
import { toast } from "sonner";

import { QueryBuilderPanel } from "@/components/query/QueryBuilderPanel";
import { QueryTabsBar, type PersistedTab } from "@/components/query/QueryTabsBar";
import { RightSidebar } from "@/components/query/RightSidebar";
import { SchemaSidebar } from "@/components/query/SchemaSidebar";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import { api, type ColumnPrecision } from "@/lib/api";
import { cn } from "@/lib/format";

const SqlEditor = lazy(() => import("@/components/SqlEditor"));

const routeApi = getRouteApi("/query");

const uid = () =>
  globalThis.crypto?.randomUUID?.() ??
  `t-${Date.now()}-${Math.random().toString(36).slice(2)}`;

const datasetToView = (d: string) => d.replace(/-/g, "_");
const viewToDataset = (v: string) => v.replace(/_/g, "-");

const defaultSql = (view: string) => `SELECT *\nFROM ${view}\nLIMIT 100;`;

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
  const search = routeApi.useSearch();
  const qc = useQueryClient();
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  // Focused dataset: drives autocomplete/builder/history bucket/precision.
  // It does NOT scope query execution (M02a: every view is registered).
  const [focusedDataset, setFocusedDataset] = useLocalStorage<string>(
    "query.focusedDataset",
    "era5-land",
  );
  const focusedView = datasetToView(focusedDataset);

  const [tabs, setTabs] = useLocalStorage<PersistedTab[]>("query.tabs", []);
  const [activeId, setActiveId] = useLocalStorage<string>(
    "query.activeTabId",
    "",
  );
  const [leftCollapsed, setLeftCollapsed] = useLocalStorage(
    "query.leftCollapsed",
    false,
  );
  const [rightCollapsed, setRightCollapsed] = useLocalStorage(
    "query.rightCollapsed",
    false,
  );
  const [showBuilder, setShowBuilder] = useState(false);
  const [limit, setLimit] = useState(1000);

  // One-time bootstrap: seed tab 1 from ?view= (M01) or the focused view.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    const seedView = search.view || focusedView;
    if (search.view) setFocusedDataset(viewToDataset(search.view));
    setTabs((prev) => {
      if (prev.length > 0) {
        // Deep-linked with ?view= → retarget the active (unedited) tab.
        if (search.view) {
          return prev.map((t) =>
            t.id === activeId && !t.userEdited
              ? { ...t, sql: defaultSql(seedView) }
              : t,
          );
        }
        return prev;
      }
      const id = uid();
      setActiveId(id);
      return [
        { id, name: "Query 1", sql: defaultSql(seedView), userEdited: false },
      ];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0] ?? null;

  const schemaQuery = useQuery({
    queryKey: ["query-schema", focusedDataset],
    queryFn: () => api.querySchema(focusedDataset),
  });
  const precisionQuery = useQuery({
    queryKey: ["precision", focusedDataset],
    queryFn: () => api.precision.get(focusedDataset),
  });

  const runQuery = useMutation({
    mutationFn: async (sqlArg?: string) => {
      const sql = sqlArg ?? activeTab?.sql;
      if (!sql) throw new Error("No active tab");
      const t0 = performance.now();
      const res = await api.query({ sql, limit });
      const elapsed = Math.round(performance.now() - t0);
      await api.queryHistory.append(focusedView, {
        sql,
        rows: res.row_count,
        elapsed_ms: elapsed,
      });
      qc.invalidateQueries({
        queryKey: ["query", "history", focusedView],
      });
      return res;
    },
    onError: (e) => toast.error((e as Error).message),
    onSuccess: (r) =>
      toast.success(`${r.row_count} linhas${r.truncated ? " (truncado)" : ""}`),
  });

  function updateActiveSql(sql: string, userEdited = true) {
    setTabs((prev) =>
      prev.map((t) =>
        t.id === activeTab?.id
          ? { ...t, sql, userEdited: t.userEdited || userEdited }
          : t,
      ),
    );
  }

  function addTab() {
    const id = uid();
    setTabs((prev) => [
      ...prev,
      {
        id,
        name: `Query ${prev.length + 1}`,
        sql: defaultSql(focusedView),
        userEdited: false,
      },
    ]);
    setActiveId(id);
  }

  function closeTab(id: string) {
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (next.length === 0) {
        const nid = uid();
        setActiveId(nid);
        return [
          {
            id: nid,
            name: "Query 1",
            sql: defaultSql(focusedView),
            userEdited: false,
          },
        ];
      }
      if (id === activeId) setActiveId(next[next.length - 1].id);
      return next;
    });
  }

  function renameTab(id: string, name: string) {
    setTabs((prev) => prev.map((t) => (t.id === id ? { ...t, name } : t)));
  }

  function reorderTabs(ids: string[]) {
    setTabs((prev) =>
      ids
        .map((i) => prev.find((t) => t.id === i))
        .filter((t): t is PersistedTab => Boolean(t)),
    );
  }

  function tryFormat(sql: string): string {
    try {
      return formatSql(sql, {
        language: "duckdb",
        keywordCase: "upper",
        indentStyle: "standard",
      });
    } catch {
      return sql; // Leave SQL untouched if it cannot be parsed.
    }
  }

  function handleFormat() {
    if (!activeTab) return;
    updateActiveSql(tryFormat(activeTab.sql));
  }

  // "Run query" (button + Ctrl+Enter): auto-format the active tab, then
  // execute the formatted text (state updates are async, so the formatted
  // SQL is passed explicitly rather than read back from the tab).
  function formatAndRun() {
    if (!activeTab) return;
    const fmt = tryFormat(activeTab.sql);
    updateActiveSql(fmt);
    runQuery.mutate(fmt);
  }

  const schemaColumns = schemaQuery.data?.columns ?? [];

  return (
    <div className="flex flex-1 flex-col gap-4">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
            SQL query
          </h1>
          <p className="mt-1 text-ink-500">
            Consultas read-only. Todos os datasets já estão registrados — use{" "}
            <code>FROM era5</code>, <code>FROM era5_land</code> ou um JOIN.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-500">
          Contexto
          <select
            className="input text-xs"
            value={focusedDataset}
            onChange={(e) => setFocusedDataset(e.target.value)}
          >
            {datasets?.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="card flex min-h-0 flex-1 overflow-hidden p-0">
        <SchemaSidebar
          datasets={datasets?.map((d) => d.name) ?? []}
          collapsed={leftCollapsed}
          onToggle={() => setLeftCollapsed((c) => !c)}
          onInsert={(text) =>
            updateActiveSql(activeTab ? `${activeTab.sql} ${text}` : text)
          }
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="px-3 pt-3">
            <QueryTabsBar
              tabs={tabs}
              activeId={activeTab?.id ?? ""}
              onSelect={setActiveId}
              onAdd={addTab}
              onClose={closeTab}
              onRename={renameTab}
              onReorder={reorderTabs}
            />
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            <Suspense
              fallback={
                <textarea
                  className="input min-h-[240px] w-full font-mono text-xs"
                  value={activeTab?.sql ?? ""}
                  onChange={(e) => updateActiveSql(e.target.value)}
                />
              }
            >
              {activeTab ? (
                <SqlEditor
                  key={activeTab.id}
                  path={`tab-${activeTab.id}.sql`}
                  value={activeTab.sql}
                  onChange={(v) => updateActiveSql(v)}
                  onRun={formatAndRun}
                  schemaColumns={schemaColumns}
                  viewName={focusedView}
                />
              ) : null}
            </Suspense>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-2">
                <button
                  className="btn-outline"
                  onClick={handleFormat}
                  type="button"
                >
                  <WandSparkles className="h-4 w-4" />
                  Formatar
                </button>
                <button
                  className={cn(
                    "btn-outline",
                    showBuilder && "bg-ocean-50 text-ocean-700",
                  )}
                  onClick={() => setShowBuilder((s) => !s)}
                  type="button"
                >
                  <SlidersHorizontal className="h-4 w-4" />
                  Construtor
                </button>
              </div>

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
                      if (Number.isFinite(v))
                        setLimit(Math.min(100000, Math.max(1, v)));
                    }}
                    className="input w-24 text-xs"
                  />
                </label>
                <button
                  className="btn-outline"
                  type="button"
                  disabled={!activeTab}
                  onClick={() =>
                    activeTab &&
                    api
                      .exportQuery("csv", activeTab.sql)
                      .catch((e) => toast.error((e as Error).message))
                  }
                >
                  <Download className="h-4 w-4" />
                  CSV
                </button>
                <button
                  className="btn-outline"
                  type="button"
                  disabled={!activeTab}
                  onClick={() =>
                    activeTab &&
                    api
                      .exportQuery("parquet", activeTab.sql)
                      .catch((e) => toast.error((e as Error).message))
                  }
                >
                  <Download className="h-4 w-4" />
                  Parquet
                </button>
                <button
                  className="btn-primary"
                  onClick={formatAndRun}
                  disabled={runQuery.isPending || !activeTab}
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

            {showBuilder ? (
              <div className="mt-4">
                <QueryBuilderPanel
                  dataset={focusedDataset}
                  onApply={(sql) => {
                    updateActiveSql(sql);
                    setShowBuilder(false);
                    toast.success("SQL gerado na aba ativa");
                  }}
                />
              </div>
            ) : null}

            {runQuery.data ? (
              <div className="mt-4 overflow-hidden rounded-lg border border-ink-100">
                <div className="border-b border-ink-100 px-5 py-3 text-xs text-ink-500">
                  <span className="font-medium text-ink-800">
                    {runQuery.data.row_count}
                  </span>{" "}
                  rows
                  {runQuery.data.truncated ? " (truncated)" : null}
                </div>
                <div className="max-h-[40vh] overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-ink-50">
                      <tr>
                        {runQuery.data.columns.map((c, i) => (
                          <th
                            key={c}
                            className="px-3 py-2 text-left font-medium"
                          >
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
                                  <span className="text-ink-300">∅</span>
                                </td>
                              );
                            }
                            const colName = runQuery.data.columns[j];
                            const colType = runQuery.data.column_types[j];
                            let display = String(cell);
                            if (
                              colType === "float" &&
                              Number.isFinite(Number(cell))
                            ) {
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
        </div>

        <RightSidebar
          view={focusedView}
          collapsed={rightCollapsed}
          onToggle={() => setRightCollapsed((c) => !c)}
          onLoad={(sql) => updateActiveSql(sql)}
        />
      </div>
    </div>
  );
}
