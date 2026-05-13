import { CheckCircle2, Clock, Cloud, Download, Loader2, Send, XCircle } from "lucide-react";
import { useEffect, useReducer, useRef } from "react";

import { cn } from "@/lib/format";

export type ChunkPhase =
  | "submitting"
  | "queued"
  | "running"
  | "downloading"
  | "processing"
  | "completed"
  | "failed";

export interface ProgressPayload {
  stage?: string;
  stage_progress?: number;
  message?: string;
  global_progress?: number;
  timestamp?: number;
  chunk_id?: string;
  chunk_index?: number;
  chunks_total?: number;
  phase?: ChunkPhase;
  bytes_downloaded?: number;
  bytes_total?: number;
}

interface ChunkState {
  chunk_id: string;
  chunk_index: number | null;
  chunks_total: number | null;
  phase: ChunkPhase;
  message: string;
  bytes_downloaded: number | null;
  bytes_total: number | null;
  last_update: number;
  started_at: number;
}

interface RunState {
  chunks: Record<string, ChunkState>;
  events: { ts: number; chunk_id: string | null; phase: string | null; message: string }[];
  status: "running" | "completed" | "failed";
  error: string | null;
  chunks_total: number | null;
}

const INITIAL_STATE: RunState = {
  chunks: {},
  events: [],
  status: "running",
  error: null,
  chunks_total: null,
};

type Action =
  | { type: "progress"; payload: ProgressPayload }
  | { type: "end"; status: "completed" | "failed"; error: string | null };

function reducer(state: RunState, action: Action): RunState {
  if (action.type === "end") {
    return { ...state, status: action.status, error: action.error };
  }
  const p = action.payload;
  if (!p.chunk_id || !p.phase) {
    return state;
  }
  const prev = state.chunks[p.chunk_id];
  const now = p.timestamp ?? Date.now() / 1000;
  const next: ChunkState = {
    chunk_id: p.chunk_id,
    chunk_index: p.chunk_index ?? prev?.chunk_index ?? null,
    chunks_total: p.chunks_total ?? prev?.chunks_total ?? null,
    phase: p.phase,
    message: p.message ?? "",
    bytes_downloaded: p.bytes_downloaded ?? prev?.bytes_downloaded ?? null,
    bytes_total: p.bytes_total ?? prev?.bytes_total ?? null,
    last_update: now,
    started_at: prev?.started_at ?? now,
  };
  const events = [
    { ts: now, chunk_id: p.chunk_id, phase: p.phase, message: p.message ?? "" },
    ...state.events,
  ].slice(0, 50);
  return {
    ...state,
    chunks: { ...state.chunks, [p.chunk_id]: next },
    events,
    chunks_total: p.chunks_total ?? state.chunks_total,
  };
}

export function RunProgress({ runId }: { runId: string }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const src = new EventSource(`/api/pipeline/runs/${runId}/progress`);
    sourceRef.current = src;

    src.addEventListener("progress", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data) as ProgressPayload;
        dispatch({ type: "progress", payload });
      } catch {
        // ignore malformed event
      }
    });
    src.addEventListener("end", (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data) as { status: "completed" | "failed"; error: string | null };
        dispatch({ type: "end", status: payload.status, error: payload.error });
      } catch {
        dispatch({ type: "end", status: "failed", error: "Unknown error" });
      }
      src.close();
    });
    src.onerror = () => {
      // Browser auto-retries; nothing to do here.
    };
    return () => src.close();
  }, [runId]);

  const chunkList = Object.values(state.chunks).sort((a, b) => {
    const ia = a.chunk_index ?? Number.MAX_SAFE_INTEGER;
    const ib = b.chunk_index ?? Number.MAX_SAFE_INTEGER;
    return ia - ib;
  });
  const total = state.chunks_total ?? chunkList.length;
  const completed = chunkList.filter((c) => c.phase === "completed").length;
  const active = chunkList.find(
    (c) => c.phase !== "completed" && c.phase !== "failed",
  );
  const overall = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-ink-400">
              {state.status === "completed"
                ? "Download finished"
                : state.status === "failed"
                  ? "Download failed"
                  : "Download in progress"}
            </div>
            <div className="mt-1 text-lg font-semibold text-ink-900">
              {active
                ? `Chunk ${active.chunk_index ?? "?"} of ${total}`
                : state.status === "completed"
                  ? `${completed} of ${total} chunks complete`
                  : `${completed} of ${total} chunks done`}
            </div>
          </div>
          <StatusIndicator status={state.status} />
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-ink-100">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              state.status === "failed"
                ? "bg-rose-500"
                : state.status === "completed"
                  ? "bg-emerald-500"
                  : "bg-ocean-500",
            )}
            style={{ width: `${overall}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-ink-400">
          <span>{overall}% overall</span>
          {active && (
            <span>
              {active.message ? active.message.slice(0, 80) : `${active.phase}…`}
            </span>
          )}
        </div>
        {state.error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {state.error}
          </div>
        )}
      </header>

      <section className="rounded-2xl border border-ink-100 bg-white shadow-sm">
        <div className="border-b border-ink-100 px-5 py-3 text-xs font-medium uppercase tracking-wide text-ink-500">
          Chunks
        </div>
        <ul className="divide-y divide-ink-100">
          {chunkList.length === 0 && (
            <li className="px-5 py-4 text-sm text-ink-400">
              Waiting for the first chunk…
            </li>
          )}
          {chunkList.map((c) => (
            <ChunkRow key={c.chunk_id} chunk={c} />
          ))}
        </ul>
      </section>

      <section className="rounded-2xl border border-ink-100 bg-white shadow-sm">
        <div className="border-b border-ink-100 px-5 py-3 text-xs font-medium uppercase tracking-wide text-ink-500">
          Recent events
        </div>
        <ul className="max-h-60 divide-y divide-ink-50 overflow-y-auto font-mono text-[11px]">
          {state.events.slice(0, 30).map((e, i) => (
            <li key={i} className="flex gap-3 px-5 py-1.5">
              <span className="text-ink-400">
                {new Date(e.ts * 1000).toLocaleTimeString()}
              </span>
              {e.chunk_id && <span className="text-ocean-700">{e.chunk_id}</span>}
              {e.phase && (
                <span className="text-ink-600">→ {e.phase}</span>
              )}
              <span className="truncate text-ink-500">{e.message}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ChunkRow({ chunk }: { chunk: ChunkState }) {
  return (
    <li className="flex items-center gap-3 px-5 py-3 text-sm">
      <PhaseIcon phase={chunk.phase} />
      <div className="flex-1 truncate">
        <div className="font-medium text-ink-800">{chunk.chunk_id}</div>
        <div className="truncate text-[11px] text-ink-400">{chunk.message}</div>
      </div>
      <PhaseBadge phase={chunk.phase} />
      {chunk.phase === "downloading" && chunk.bytes_total != null && (
        <span className="text-[11px] text-ink-500">
          {(chunk.bytes_total / 1024 / 1024).toFixed(1)} MB
        </span>
      )}
    </li>
  );
}

function PhaseIcon({ phase }: { phase: ChunkPhase }) {
  switch (phase) {
    case "submitting":
      return <Send className="h-4 w-4 text-ocean-500" />;
    case "queued":
      return <Clock className="h-4 w-4 text-amber-500" />;
    case "running":
      return <Cloud className="h-4 w-4 animate-pulse text-amber-600" />;
    case "downloading":
      return <Download className="h-4 w-4 text-ocean-600" />;
    case "processing":
      return <Loader2 className="h-4 w-4 animate-spin text-ink-500" />;
    case "completed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-rose-600" />;
  }
}

function PhaseBadge({ phase }: { phase: ChunkPhase }) {
  const styles: Record<ChunkPhase, string> = {
    submitting: "bg-ocean-100 text-ocean-700",
    queued: "bg-amber-100 text-amber-700",
    running: "bg-amber-100 text-amber-800",
    downloading: "bg-ocean-100 text-ocean-700",
    processing: "bg-ink-100 text-ink-700",
    completed: "bg-emerald-100 text-emerald-700",
    failed: "bg-rose-100 text-rose-700",
  };
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        styles[phase],
      )}
    >
      {phase}
    </span>
  );
}

function StatusIndicator({ status }: { status: RunState["status"] }) {
  if (status === "completed") {
    return (
      <span className="flex items-center gap-1 text-sm text-emerald-700">
        <CheckCircle2 className="h-4 w-4" /> Completed
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex items-center gap-1 text-sm text-rose-700">
        <XCircle className="h-4 w-4" /> Failed
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-sm text-ocean-700">
      <Loader2 className="h-4 w-4 animate-spin" /> Running
    </span>
  );
}
