import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Loader2,
  Play,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { CellEditor } from "@/components/notebooks/CellEditor";
import { CellOutput } from "@/components/notebooks/CellOutput";
import { KernelStatusBadge } from "@/components/notebooks/KernelStatusBadge";
import { ModelRunsPanel } from "@/components/notebooks/ModelRunsPanel";
import {
  api,
  streamRunCell,
  type CellOutput as CellOutputT,
  type KernelStatus,
  type NotebookCell,
} from "@/lib/api";

function newCellId(): string {
  return Math.random().toString(36).slice(2, 14);
}

export function NotebookEditorPage() {
  const { t } = useTranslation();
  const { notebookId } = useParams({ strict: false }) as { notebookId: string };
  const queryClient = useQueryClient();

  const nbQ = useQuery({
    queryKey: ["notebook", notebookId],
    queryFn: () => api.notebooks.get(notebookId),
  });

  const [cells, setCells] = useState<NotebookCell[]>([]);
  const [name, setName] = useState("");
  const [kernelStatus, setKernelStatus] = useState<KernelStatus>("dead");
  const [runningCell, setRunningCell] = useState<string | null>(null);
  const [showRuns, setShowRuns] = useState(true);
  const cancelRef = useRef<(() => void) | null>(null);

  // Hydrate state from server payload.
  useEffect(() => {
    if (nbQ.data) {
      setCells(nbQ.data.cells);
      setName(nbQ.data.name);
    }
  }, [nbQ.data?.id]);

  // Poll kernel status while the page is mounted.
  const statusQ = useQuery({
    queryKey: ["notebook-kernel", notebookId],
    queryFn: () => api.notebooks.kernel.status(notebookId),
    refetchInterval: 4000,
  });
  useEffect(() => {
    if (statusQ.data) setKernelStatus(statusQ.data.status);
  }, [statusQ.data]);

  const saveMut = useMutation({
    mutationFn: () => api.notebooks.save(notebookId, { name, cells }),
    onSuccess: (data) => {
      queryClient.setQueryData(["notebook", notebookId], data);
    },
  });
  const restartMut = useMutation({
    mutationFn: () => api.notebooks.kernel.restart(notebookId),
    onSuccess: (r) => setKernelStatus(r.status),
  });
  const stopMut = useMutation({
    mutationFn: () => api.notebooks.kernel.stop(notebookId),
    onSuccess: (r) => setKernelStatus(r.status),
  });

  const updateCell = useCallback((id: string, patch: Partial<NotebookCell>) => {
    setCells((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }, []);

  const addCell = useCallback(
    (after: number, type: "code" | "sql" | "markdown" = "code") => {
      setCells((prev) => {
        const cell: NotebookCell = {
          id: newCellId(),
          type,
          source: "",
          outputs: [],
        };
        return [...prev.slice(0, after + 1), cell, ...prev.slice(after + 1)];
      });
    },
    [],
  );

  const removeCell = useCallback(
    (id: string) => setCells((prev) => prev.filter((c) => c.id !== id)),
    [],
  );

  const runCell = useCallback(
    (cell: NotebookCell) => {
      if (cell.type === "markdown") return;
      if (cancelRef.current) cancelRef.current();
      setRunningCell(cell.id);
      // Clear outputs.
      updateCell(cell.id, { outputs: [] });
      const collected: CellOutputT[] = [];
      cancelRef.current = streamRunCell(
        notebookId,
        cell.id,
        cell.source,
        cell.type === "sql" ? "sql" : "python",
        ({ type, data }) => {
          if (type === "stream") {
            collected.push(data as CellOutputT);
          } else if (type === "display") {
            collected.push(data as CellOutputT);
          } else if (type === "error") {
            collected.push({ type: "error", ...(data as object) } as CellOutputT);
          }
          updateCell(cell.id, { outputs: [...collected] });
        },
        () => {
          cancelRef.current = null;
          setRunningCell(null);
          // After a successful run, refresh runs in case the kernel called log_model_run.
          queryClient.invalidateQueries({ queryKey: ["notebook", notebookId] });
        },
      );
    },
    [notebookId, updateCell, queryClient],
  );

  const onRunCellRef = useRef<(c: NotebookCell) => void>(runCell);
  onRunCellRef.current = runCell;

  // Persist outputs (and source edits) on save.
  useEffect(() => {
    return () => {
      if (cancelRef.current) cancelRef.current();
    };
  }, []);

  if (nbQ.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("notebooks.editor.loading")}
      </div>
    );
  }
  if (!nbQ.data) {
    return (
      <div className="card p-6 text-sm text-rose-700">
        {t("notebooks.editor.notFound")}
      </div>
    );
  }

  const runs = nbQ.data.runs ?? [];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link to="/notebooks" className="text-ink-500 hover:text-ink-700">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-transparent bg-transparent px-1 py-0.5 text-2xl font-semibold text-ink-800 outline-none hover:border-ink-200 focus:border-ocean-400"
          />
        </div>
        <div className="flex items-center gap-3">
          <KernelStatusBadge
            status={kernelStatus}
            onRestart={() => restartMut.mutate()}
            onStop={() => stopMut.mutate()}
            disabled={restartMut.isPending || stopMut.isPending}
          />
          <button
            type="button"
            className="btn-primary"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
          >
            {saveMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {t("notebooks.editor.save")}
          </button>
        </div>
      </header>

      <div className="space-y-3">
        {cells.map((cell, idx) => (
          <div
            key={cell.id}
            className="card overflow-hidden p-0"
          >
            <div className="flex items-center justify-between gap-2 border-b border-ink-100 bg-ink-50/50 px-2 py-1.5">
              <div className="flex items-center gap-2">
                <select
                  value={cell.type}
                  onChange={(e) =>
                    updateCell(cell.id, {
                      type: e.target.value as NotebookCell["type"],
                    })
                  }
                  className="rounded border border-ink-200 bg-white px-1.5 py-0.5 text-xs"
                >
                  <option value="code">Python</option>
                  <option value="sql">SQL</option>
                  <option value="markdown">Markdown</option>
                </select>
                <span className="text-xs text-ink-400">#{idx + 1}</span>
              </div>
              <div className="flex items-center gap-1">
                {cell.type !== "markdown" && (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-0.5 text-xs text-ink-600 hover:bg-white disabled:opacity-50"
                    onClick={() => runCell(cell)}
                    disabled={runningCell !== null}
                    title={t("notebooks.editor.runCellTitle")}
                  >
                    {runningCell === cell.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Play className="h-3 w-3" />
                    )}
                    {t("notebooks.editor.runCell")}
                  </button>
                )}
                <button
                  type="button"
                  className="rounded-md border border-ink-200 px-2 py-0.5 text-xs text-ink-600 hover:bg-white"
                  onClick={() => addCell(idx)}
                  title={t("notebooks.editor.addBelow")}
                >
                  <Plus className="h-3 w-3" />
                </button>
                <button
                  type="button"
                  className="rounded-md border border-ink-200 px-2 py-0.5 text-xs text-ink-500 hover:bg-white hover:text-rose-600"
                  onClick={() => removeCell(cell.id)}
                  title={t("notebooks.editor.removeCell")}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
            <CellEditor
              value={cell.source}
              onChange={(s) => updateCell(cell.id, { source: s })}
              language={
                cell.type === "code"
                  ? "python"
                  : cell.type === "sql"
                    ? "sql"
                    : "markdown"
              }
              path={`${notebookId}/${cell.id}`}
              onRunRequested={() => onRunCellRef.current(cell)}
            />
            {cell.outputs && cell.outputs.length > 0 && (
              <div className="border-t border-ink-100 p-3 space-y-2">
                {cell.outputs.map((out, i) => (
                  <CellOutput key={i} output={out} />
                ))}
              </div>
            )}
          </div>
        ))}
        <button
          type="button"
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-ink-200 py-3 text-xs text-ink-500 hover:border-ocean-400 hover:bg-ocean-50/50"
          onClick={() => addCell(cells.length - 1)}
        >
          <Plus className="h-3 w-3" />
          {t("notebooks.editor.addCell")}
        </button>
      </div>

      <section className="card p-4">
        <button
          type="button"
          className="flex w-full items-center justify-between text-left"
          onClick={() => setShowRuns((x) => !x)}
        >
          <h2 className="text-base font-semibold text-ink-800">
            {t("notebooks.runs.section")}
          </h2>
          {showRuns ? (
            <ChevronDown className="h-4 w-4 text-ink-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-ink-500" />
          )}
        </button>
        {showRuns && (
          <div className="mt-3">
            <ModelRunsPanel runs={runs} />
          </div>
        )}
      </section>
    </div>
  );
}
