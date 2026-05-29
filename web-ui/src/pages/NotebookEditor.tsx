import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleX,
  Clock,
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

/** Format a number of seconds as MM:SS. */
function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
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
  // Latest cells, readable inside the async "Run all" loop without re-binding.
  const cellsRef = useRef<NotebookCell[]>(cells);
  cellsRef.current = cells;
  const [name, setName] = useState("");
  const [kernelStatus, setKernelStatus] = useState<KernelStatus>("dead");
  const [runningCell, setRunningCell] = useState<string | null>(null);
  const [runningAll, setRunningAll] = useState(false);
  const [showRuns, setShowRuns] = useState(true);
  const cancelRef = useRef<(() => void) | null>(null);
  // Stop flag for the "Run all" loop (set when the user runs all again or leaves).
  const runAllCancelRef = useRef(false);
  // Per-cell run outcome (Jupyter-style executed indicator): "ok" once a cell
  // finished cleanly, "error" if it raised. Absent = never executed this session.
  const [runStatus, setRunStatus] = useState<Record<string, "ok" | "error">>({});
  // Per-cell execution time (seconds). Set when a run finishes; shown as MM:SS.
  const [elapsed, setElapsed] = useState<Record<string, number>>({});
  // Wall-clock start of the in-flight run, used to drive the live chronometer.
  const runStartRef = useRef<number | null>(null);
  // Forces a re-render ~2×/s so the running cell's chronometer ticks.
  const [, setTick] = useState(0);

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

  // Kernel display name (e.g. "Python 3.12"). Fetched directly: the value
  // depends on the server's interpreter, which is also what runs the kernel.
  const kernelInfoQ = useQuery({
    queryKey: ["notebook-kernel-info", notebookId],
    queryFn: () => api.notebooks.kernel.info(notebookId),
  });

  // Tick while a cell is running so the live MM:SS chronometer updates.
  useEffect(() => {
    if (!runningCell) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 500);
    return () => window.clearInterval(id);
  }, [runningCell]);

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

  // Execute one cell and resolve when the kernel signals "done". Used both by
  // the per-cell Run button and the sequential "Run all" loop. Resolves with
  // true if the cell finished without an error output, false otherwise.
  const executeCell = useCallback(
    (cell: NotebookCell): Promise<boolean> => {
      return new Promise<boolean>((resolve) => {
        if (cell.type === "markdown") {
          resolve(true);
          return;
        }
        if (cancelRef.current) cancelRef.current();
        setRunningCell(cell.id);
        // Start the chronometer and drop any previous timing for this cell.
        runStartRef.current = Date.now();
        setElapsed((prev) => {
          const next = { ...prev };
          delete next[cell.id];
          return next;
        });
        // Clear outputs and the previous run status.
        updateCell(cell.id, { outputs: [] });
        setRunStatus((prev) => {
          const next = { ...prev };
          delete next[cell.id];
          return next;
        });
        const collected: CellOutputT[] = [];
        let hadError = false;
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
              hadError = true;
              collected.push({ type: "error", ...(data as object) } as CellOutputT);
            }
            updateCell(cell.id, { outputs: [...collected] });
          },
          () => {
            // Freeze the chronometer at its final value (MM:SS).
            const started = runStartRef.current;
            runStartRef.current = null;
            if (started != null) {
              setElapsed((prev) => ({
                ...prev,
                [cell.id]: (Date.now() - started) / 1000,
              }));
            }
            cancelRef.current = null;
            setRunningCell(null);
            // Mark the cell executed (ok/error) for the Jupyter-style indicator.
            setRunStatus((prev) => ({
              ...prev,
              [cell.id]: hadError ? "error" : "ok",
            }));
            // After a run, refresh runs in case the kernel called log_model_run.
            queryClient.invalidateQueries({ queryKey: ["notebook", notebookId] });
            resolve(!hadError);
          },
        );
      });
    },
    [notebookId, updateCell, queryClient],
  );

  const runCell = useCallback(
    (cell: NotebookCell) => {
      void executeCell(cell);
    },
    [executeCell],
  );

  // Run every code/SQL cell top-to-bottom, awaiting each so the kernel (one
  // cell at a time) stays in order. Stops early if a cell errors.
  const runAll = useCallback(async () => {
    if (runningAll) return;
    runAllCancelRef.current = false;
    setRunningAll(true);
    try {
      for (const cell of cellsRef.current) {
        if (runAllCancelRef.current) break;
        if (cell.type === "markdown") continue;
        const ok = await executeCell(cell);
        if (!ok) break; // surface the failing cell, don't barrel on
      }
    } finally {
      setRunningAll(false);
    }
  }, [executeCell, runningAll]);

  const onRunCellRef = useRef<(c: NotebookCell) => void>(runCell);
  onRunCellRef.current = runCell;

  // Persist outputs (and source edits) on save.
  useEffect(() => {
    return () => {
      runAllCancelRef.current = true;
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
            kernelName={kernelInfoQ.data?.kernel_name}
            onRestart={() => restartMut.mutate()}
            onStop={() => stopMut.mutate()}
            disabled={restartMut.isPending || stopMut.isPending}
          />
          <button
            type="button"
            className="btn-outline inline-flex items-center gap-1.5"
            onClick={() => runAll()}
            disabled={runningAll || runningCell !== null}
            title={t("notebooks.editor.runAllTitle")}
          >
            {runningAll ? (
              <Loader2 className="h-4 w-4 animate-spin text-emerald-600" />
            ) : (
              <Play className="h-4 w-4 fill-emerald-600 text-emerald-600" />
            )}
            {runningAll
              ? t("notebooks.editor.runAllRunning")
              : t("notebooks.editor.runAll")}
          </button>
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
                {cell.type !== "markdown" &&
                  (runningCell === cell.id ? (
                    <Loader2
                      className="h-3.5 w-3.5 shrink-0 animate-spin text-emerald-600"
                      aria-label={t("notebooks.editor.runStatusRunning")}
                    />
                  ) : runStatus[cell.id] === "ok" ? (
                    <CircleCheck
                      className="h-3.5 w-3.5 shrink-0 text-emerald-600"
                      aria-label={t("notebooks.editor.runStatusDone")}
                    />
                  ) : runStatus[cell.id] === "error" ? (
                    <CircleX
                      className="h-3.5 w-3.5 shrink-0 text-rose-600"
                      aria-label={t("notebooks.editor.runStatusRunning")}
                    />
                  ) : (
                    <Circle
                      className="h-3.5 w-3.5 shrink-0 text-ink-300"
                      aria-label={t("notebooks.editor.runStatusPending")}
                    />
                  ))}
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
                {cell.type !== "markdown" &&
                  (runningCell === cell.id || elapsed[cell.id] != null) && (
                    <span
                      className="inline-flex items-center gap-1 px-1 font-mono text-xs tabular-nums text-ink-500"
                      title={t("notebooks.editor.runCellTitle")}
                    >
                      <Clock className="h-3 w-3" />
                      {runningCell === cell.id
                        ? formatDuration(
                            (Date.now() - (runStartRef.current ?? Date.now())) /
                              1000,
                          )
                        : formatDuration(elapsed[cell.id])}
                    </span>
                  )}
                {cell.type !== "markdown" && (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-0.5 text-xs text-ink-600 hover:bg-white disabled:opacity-50"
                    onClick={() => runCell(cell)}
                    disabled={runningCell !== null || runningAll}
                    title={t("notebooks.editor.runCellTitle")}
                  >
                    {runningCell === cell.id ? (
                      <Loader2 className="h-3 w-3 animate-spin text-emerald-600" />
                    ) : (
                      <Play className="h-3 w-3 fill-emerald-600 text-emerald-600" />
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
                  className="rounded-md border border-ink-200 px-2 py-0.5 text-xs text-rose-600 hover:bg-white hover:text-rose-700"
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
