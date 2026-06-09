import { Link } from "@tanstack/react-router";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Cloud,
  Database,
  Download,
  FileStack,
  Hourglass,
  Loader2,
  Send,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useEffect, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

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
  files_done?: number;
  files_total?: number;
  // Multi-phase orchestration (INMET auto-bootstrap flow). When
  // ``phase_total > 1`` we surface a small chip ("Etapa N/M · Label")
  // above the bars; single-phase runs (all non-INMET datasets, and INMET
  // when prerequisites are already present) leave these at null/1/1 and
  // the chip is hidden.
  pipeline_phase?: string;
  phase_index?: number;
  phase_total?: number;
}

interface ChunkState {
  chunk_id: string;
  chunk_index: number | null;
  chunks_total: number | null;
  phase: ChunkPhase;
  message: string;
  bytes_total: number | null;
  bytes_downloaded: number | null; // live download progress (poller)
  started_at: number; // epoch s of the first event seen for this chunk
  elapsed_ms: number | null; // total wall-clock, set when terminal
  last_update: number;
}

interface ConvertState {
  done: number;
  total: number;
  message: string;
}

interface FinalizingState {
  message: string;
  last_update: number;
}

interface PhaseState {
  name: string;
  index: number;
  total: number;
}

interface RunState {
  chunks: Record<string, ChunkState>;
  events: { ts: number; chunk_id: string | null; phase: string | null; message: string }[];
  status: "running" | "completed" | "failed";
  error: string | null;
  chunks_total: number | null;
  convert: ConvertState | null;
  pipeline_phase: PhaseState | null;
  finalizing: FinalizingState | null;
}

const INITIAL_STATE: RunState = {
  chunks: {},
  events: [],
  status: "running",
  error: null,
  chunks_total: null,
  convert: null,
  pipeline_phase: null,
  finalizing: null,
};

type Action =
  | { type: "progress"; payload: ProgressPayload }
  | { type: "end"; status: "completed" | "failed"; error: string | null };

function reducer(state: RunState, action: Action): RunState {
  if (action.type === "end") {
    return { ...state, status: action.status, error: action.error };
  }
  const p = action.payload;

  // Refresh the phase chip on every event: backend stamps every progress
  // event with the active phase, so we keep this in sync via reducer.
  const pipeline_phase: PhaseState | null =
    p.pipeline_phase && (p.phase_total ?? 1) > 1
      ? {
          name: p.pipeline_phase,
          index: p.phase_index ?? 1,
          total: p.phase_total ?? 1,
        }
      : state.pipeline_phase;

  // Finalizing events are emitted by the post-convert stages (refresh
  // indexes, create views). They carry a rotating message and let the UI
  // render a "wait…" banner while convert is already at 100%.
  if (p.stage === "finalizing") {
    const now = p.timestamp ?? Date.now() / 1000;
    return {
      ...state,
      pipeline_phase,
      finalizing: { message: p.message ?? "", last_update: now },
      events: [
        { ts: now, chunk_id: null, phase: "finalizing", message: p.message ?? "" },
        ...state.events,
      ].slice(0, 50),
    };
  }

  // Conversion-stage events carry no chunk_id; they drive a separate bar.
  if (p.stage === "convert") {
    const now = p.timestamp ?? Date.now() / 1000;
    return {
      ...state,
      pipeline_phase,
      convert: {
        done: p.files_done ?? state.convert?.done ?? 0,
        total: p.files_total ?? state.convert?.total ?? 0,
        message: p.message ?? state.convert?.message ?? "",
      },
      events: [
        { ts: now, chunk_id: null, phase: "convert", message: p.message ?? "" },
        ...state.events,
      ].slice(0, 50),
    };
  }

  if (!p.chunk_id || !p.phase) {
    // Even non-chunk events update the phase chip (e.g. "starting"
    // submitted before the first chunk event).
    return pipeline_phase === state.pipeline_phase
      ? state
      : { ...state, pipeline_phase };
  }
  const prev = state.chunks[p.chunk_id];
  const now = p.timestamp ?? Date.now() / 1000;
  const startedAt = prev?.started_at ?? now;
  const isTerminal = p.phase === "completed" || p.phase === "failed";
  const next: ChunkState = {
    chunk_id: p.chunk_id,
    chunk_index: p.chunk_index ?? prev?.chunk_index ?? null,
    chunks_total: p.chunks_total ?? prev?.chunks_total ?? null,
    phase: p.phase,
    message: p.message ?? "",
    bytes_total: p.bytes_total ?? prev?.bytes_total ?? null,
    bytes_downloaded: p.bytes_downloaded ?? prev?.bytes_downloaded ?? null,
    started_at: startedAt,
    elapsed_ms: isTerminal
      ? Math.max(0, Math.round((now - startedAt) * 1000))
      : (prev?.elapsed_ms ?? null),
    last_update: now,
  };
  const events = [
    { ts: now, chunk_id: p.chunk_id, phase: p.phase, message: p.message ?? "" },
    ...state.events,
  ].slice(0, 50);
  return {
    ...state,
    pipeline_phase,
    chunks: { ...state.chunks, [p.chunk_id]: next },
    events,
    chunks_total: p.chunks_total ?? state.chunks_total,
  };
}

// CDS request lifecycle in order, for the stepper above the download bar.
// Each entry maps a pre-download phase to a short i18n label; "completed"
// is not a step (it means every step is done) and "downloading" is the
// point at which Bar #1 starts tracking real bytes. Order is shared across
// languages; the visible label is resolved via i18n at render time.
const LIFECYCLE_STEPS: { phase: ChunkPhase; key: string }[] = [
  { phase: "submitting", key: "runProgress.lifecycle.sending" },
  { phase: "queued", key: "runProgress.lifecycle.accepted" },
  { phase: "running", key: "runProgress.lifecycle.processing" },
  { phase: "downloading", key: "runProgress.lifecycle.downloading" },
];

export function RunProgress({
  runId,
  dataset,
  kind = "grid",
}: {
  runId: string;
  dataset?: string;
  // "grid" = ERA5/ERA5-LAND (CDS/NetCDF). "station" = INMET (yearly
  // portal ZIPs) -> the 3 bars are relabelled for that context.
  kind?: "grid" | "station";
}) {
  const { t } = useTranslation();
  const isStation = kind === "station";
  const unitLabel = t(
    isStation ? "runProgress.units.year" : "runProgress.units.chunk",
  );
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const sourceRef = useRef<EventSource | null>(null);

  // Whole-pipeline wall clock: starts when this run mounts, ticks every
  // second while running, and freezes at the exact end time so the user
  // sees the total download + processing duration.
  const startedAtRef = useRef<number>(Date.now());
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (state.status !== "running") {
      // Freeze the clock the moment the run ends (first non-running tick).
      setEndedAt((prev) => prev ?? Date.now());
      return;
    }
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [state.status]);

  const elapsedMs = (endedAt ?? now) - startedAtRef.current;

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
        const payload = JSON.parse(e.data) as {
          status: "completed" | "failed";
          error: string | null;
        };
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

  // Bar: overall download group (chunks completed / total)
  const groupPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  // Bar: current file download. Bar #1 now tracks REAL bytes for the active
  // chunk (the file-size monitor streams bytes_downloaded; bytes_total comes
  // from the cdsapi "Downloading … (NN MB)" log line). Before the download
  // phase the bar is empty — the lifecycle stepper explains the wait.
  const dl = active?.bytes_downloaded ?? null;
  const dlTotal = active?.bytes_total ?? null;
  const isDownloading = active?.phase === "downloading";
  // Real percent when both known; clamp to 99 until the chunk completes so
  // it never claims 100% before the file is actually finished.
  const bytePct =
    isDownloading && dl != null && dlTotal && dlTotal > 0
      ? Math.min(99, Math.round((dl / dlTotal) * 100))
      : 0;
  // Downloading with an unknown total → animated shimmer instead of a number.
  const fileIndeterminate = isDownloading && (dl == null || !dlTotal);
  const fileBarPct =
    completed > 0 && completed === total ? 100 : isDownloading ? bytePct : 0;

  // Bar: NetCDF -> Parquet conversion
  const conv = state.convert;
  const convPct =
    conv && conv.total > 0 ? Math.round((conv.done / conv.total) * 100) : 0;

  // "Starting up": run accepted by the backend but no SSE chunk event has
  // arrived yet. Make it explicit that the FIRST step is submitting the CDS
  // request (not a frozen "Running" spinner).
  const startingUp =
    state.status === "running" &&
    !active &&
    completed === 0 &&
    !(conv && conv.total > 0);

  // ETA for the whole run = mean completed-chunk wall-clock × remaining
  // chunks. Robust from minutes to days; null (→ "calculating") until the
  // first chunk finishes, since chunk durations are wildly uneven (CDS queue
  // time dominates and is unpredictable).
  const etaMs: number | null = (() => {
    if (state.status !== "running" || total <= 0) return null;
    const done = chunkList.filter(
      (c) => c.phase === "completed" && c.elapsed_ms != null,
    );
    if (done.length === 0) return null;
    const avg =
      done.reduce((acc, c) => acc + (c.elapsed_ms as number), 0) / done.length;
    const remaining = Math.max(0, total - completed);
    return remaining > 0 ? Math.round(avg * remaining) : 0;
  })();

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm">
        {state.pipeline_phase && (
          <PhaseChip phase={state.pipeline_phase} status={state.status} />
        )}
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-ink-400">
              {state.status === "completed"
                ? t("runProgress.finished")
                : state.status === "failed"
                  ? t("runProgress.failed")
                  : t("runProgress.running")}
            </div>
            <div className="mt-1 text-lg font-semibold text-ink-900">
              {state.status === "completed"
                ? t("runProgress.completedTitle")
                : startingUp
                  ? isStation
                    ? t("runProgress.startingINMET")
                    : t("runProgress.startingCDS")
                  : active
                    ? t(
                        isStation
                          ? "runProgress.yearOf"
                          : "runProgress.chunkOf",
                        { i: active.chunk_index ?? "?", n: total },
                      )
                    : conv && conv.total > 0
                      ? t("runProgress.converting", {
                          done: conv.done,
                          total: conv.total,
                        })
                      : t("runProgress.progressOf", {
                          done: completed,
                          total,
                          unit: unitLabel,
                        })}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusIndicator status={state.status} />
            <ElapsedTimer
              elapsedMs={elapsedMs}
              running={state.status === "running"}
            />
            {state.status === "running" && <EtaChip etaMs={etaMs} />}
          </div>
        </div>

        <div className="mt-5 space-y-4">
          {!isStation && (
            <div className="space-y-2">
              <RequestLifecycle
                phase={
                  active?.phase ??
                  (completed === total && total > 0 ? "completed" : null)
                }
                failed={state.status === "failed"}
              />
              <Bar
                icon={<Cloud className="h-4 w-4 text-amber-600" />}
                label={t("runProgress.bars.currentRequest")}
                pct={fileBarPct}
                indeterminate={fileIndeterminate}
                sub={
                  isDownloading
                    ? dl != null
                      ? dlTotal
                        ? `${(dl / 1024 / 1024).toFixed(1)} / ${(dlTotal / 1024 / 1024).toFixed(1)} MB`
                        : `${(dl / 1024 / 1024).toFixed(1)} MB`
                      : t("runProgress.barSub.downloadingNetcdf")
                    : state.status === "completed"
                      ? t("runProgress.barSub.completed")
                      : startingUp
                        ? t("runProgress.barSub.submitting")
                        : t("runProgress.barSub.waitingServer")
                }
                tone={state.status === "failed" ? "fail" : "phase"}
                pulse={startingUp}
              />
            </div>
          )}
          <Bar
            icon={<FileStack className="h-4 w-4 text-ocean-600" />}
            label={t(
              isStation
                ? "runProgress.bars.yearsDownload"
                : "runProgress.bars.groupDownload",
            )}
            pct={groupPct}
            sub={t("runProgress.progressOf", {
              done: completed,
              total,
              unit: unitLabel,
            })}
            tone={state.status === "failed" ? "fail" : "group"}
          />
          <Bar
            icon={<Download className="h-4 w-4 text-moss-600" />}
            label={t(
              isStation
                ? "runProgress.bars.conversionCsv"
                : "runProgress.bars.conversionNetcdf",
            )}
            pct={convPct}
            sub={
              conv
                ? `${conv.done}/${conv.total} · ${conv.message.slice(0, 60)}`
                : isStation
                  ? t("runProgress.barSub.waitingYearDownloads")
                  : t("runProgress.barSub.waitingDownloads")
            }
            tone={state.status === "failed" ? "fail" : "convert"}
          />
        </div>

        {state.error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
            {state.error}
          </div>
        )}

        {state.status === "running" && state.finalizing && (
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-ocean-200 bg-ocean-50/70 px-4 py-3">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-ocean-600" />
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-medium text-ocean-900">
                {t("runProgress.finalizing.title")}
              </div>
              <div className="mt-0.5 truncate text-ocean-700">
                {state.finalizing.message}
              </div>
              <div className="mt-1 text-[11px] text-ocean-600/80">
                {t("runProgress.finalizing.explanation")}
              </div>
            </div>
          </div>
        )}

        {state.status === "completed" && (
          <div className="mt-5 flex flex-col items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <Sparkles className="h-5 w-5 shrink-0 text-emerald-600" />
              <div>
                <div className="text-sm font-semibold text-emerald-800">
                  {t("runProgress.completedTitle")}
                </div>
                <div className="text-xs text-emerald-700">
                  {t("runProgress.completedSubtitle", {
                    done: completed,
                    unit: unitLabel,
                  })}
                </div>
              </div>
            </div>
            <Link
              to="/query"
              search={
                dataset ? { view: dataset.replace(/-/g, "_") } : { view: undefined }
              }
              className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700"
            >
              <Database className="h-4 w-4" />
              {t("runProgress.goToQuery")}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        )}
      </header>

      <section className="rounded-2xl border border-ink-100 bg-white shadow-sm">
        <div className="border-b border-ink-100 px-5 py-3 text-xs font-medium uppercase tracking-wide text-ink-500">
          {t(
            isStation
              ? "runProgress.listHeader.years"
              : "runProgress.listHeader.chunks",
          )}
        </div>
        <ul className="divide-y divide-ink-100">
          {chunkList.length === 0 && (
            <li className="px-5 py-4 text-sm text-ink-400">
              {t(
                isStation
                  ? "runProgress.waitingFirstYear"
                  : "runProgress.waitingFirstChunk",
              )}
            </li>
          )}
          {chunkList.map((c) => (
            <ChunkRow key={c.chunk_id} chunk={c} />
          ))}
        </ul>
      </section>

      <section className="rounded-2xl border border-ink-100 bg-white shadow-sm">
        <div className="border-b border-ink-100 px-5 py-3 text-xs font-medium uppercase tracking-wide text-ink-500">
          {t("runProgress.recentEvents")}
        </div>
        <ul className="max-h-60 divide-y divide-ink-50 overflow-y-auto font-mono text-[11px]">
          {state.events.slice(0, 30).map((e, i) => (
            <li key={i} className="flex gap-3 px-5 py-1.5">
              <span className="text-ink-400">
                {new Date(e.ts * 1000).toLocaleTimeString()}
              </span>
              {e.chunk_id && <span className="text-ocean-700">{e.chunk_id}</span>}
              {e.phase && <span className="text-ink-600">→ {e.phase}</span>}
              <span className="truncate text-ink-500">{e.message}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function formatHMS(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

// Flexible, human-readable duration that scales from seconds to days, used
// for per-chunk timings and the run ETA: 45s · 5m 20s · 3h 12m · 2d 4h.
function formatDurationCompact(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function ElapsedTimer({
  elapsedMs,
  running,
}: {
  elapsedMs: number;
  running: boolean;
}) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-full border px-2.5 py-1",
        running
          ? "border-ink-100 bg-ink-50"
          : "border-emerald-200 bg-emerald-50",
      )}
    >
      <Clock
        className={cn(
          "h-3.5 w-3.5",
          running ? "text-ink-400" : "text-emerald-600",
        )}
      />
      <span
        className={cn(
          "text-[10px] font-medium uppercase tracking-wide",
          running ? "text-ink-400" : "text-emerald-700",
        )}
      >
        {running
          ? t("runProgress.timer.elapsed")
          : t("runProgress.timer.total")}
      </span>
      <span
        className={cn(
          "font-mono text-xs tabular-nums",
          running ? "text-ink-700" : "text-emerald-800",
        )}
      >
        {formatHMS(elapsedMs)}
      </span>
    </span>
  );
}

// Estimated time remaining for the whole run. Mirrors ElapsedTimer's pill but
// with an ocean accent so it reads as a forecast, not the live clock. Shows
// "calculating…" until the first chunk completes and a value can be derived;
// formatDurationCompact keeps it legible from "~45s" to "~2d 4h".
function EtaChip({ etaMs }: { etaMs: number | null }) {
  const { t } = useTranslation();
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-ink-100 bg-ink-50 px-2.5 py-1">
      <Hourglass className="h-3.5 w-3.5 text-ocean-600" />
      <span className="text-[10px] font-medium uppercase tracking-wide text-ocean-700">
        {t("runProgress.eta.label")}
      </span>
      <span className="font-mono text-xs tabular-nums text-ocean-700">
        {etaMs == null
          ? t("runProgress.eta.calculating")
          : `~${formatDurationCompact(etaMs)}`}
      </span>
    </span>
  );
}

// Horizontal stepper that surfaces the otherwise-invisible CDS request
// lifecycle above the download bar: sending the request → it's accepted →
// the server prepares the file (the long, previously-mysterious wait) →
// the file becomes available and downloads. Grid datasets only (INMET has
// no CDS round-trip). Done steps fill emerald; the active step pulses amber;
// pending steps are muted; a failed run flips the "accepted" slot to a red
// "rejected" state.
function RequestLifecycle({
  phase,
  failed,
}: {
  phase: ChunkPhase | null;
  failed: boolean;
}) {
  const { t } = useTranslation();
  const activeIdx =
    phase === "completed"
      ? LIFECYCLE_STEPS.length
      : phase
        ? Math.max(0, LIFECYCLE_STEPS.findIndex((s) => s.phase === phase))
        : 0;
  return (
    <ol className="flex items-center gap-1.5">
      {LIFECYCLE_STEPS.map((step, i) => {
        const done = i < activeIdx;
        const current = i === activeIdx && !failed;
        const rejected = failed && i === 1; // "accepted" slot → "rejected"
        return (
          <li key={step.phase} className="flex flex-1 items-center gap-1.5">
            <span
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition-colors",
                rejected
                  ? "bg-rose-100 text-rose-700"
                  : done
                    ? "bg-emerald-100 text-emerald-700"
                    : current
                      ? "bg-amber-100 text-amber-800 animate-pulse"
                      : "bg-ink-100 text-ink-400",
              )}
            >
              {rejected ? (
                <XCircle className="h-3 w-3 shrink-0" />
              ) : done ? (
                <CheckCircle2 className="h-3 w-3 shrink-0" />
              ) : current ? (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
              ) : (
                <span className="h-3 w-3 shrink-0 rounded-full border border-current" />
              )}
              <span className="hidden md:inline">
                {rejected ? t("runProgress.lifecycle.rejected") : t(step.key)}
              </span>
            </span>
            {i < LIFECYCLE_STEPS.length - 1 && (
              <span
                className={cn(
                  "h-px flex-1 transition-colors",
                  done ? "bg-emerald-300" : "bg-ink-200",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Bar({
  icon,
  label,
  pct,
  sub,
  tone,
  pulse = false,
  indeterminate = false,
}: {
  icon: React.ReactNode;
  label: string;
  pct: number;
  sub: string;
  tone: "group" | "phase" | "convert" | "fail";
  pulse?: boolean;
  // When true the total size is unknown but bytes are flowing: render a
  // sliding shimmer instead of a fixed-width fill, and hide the percentage.
  indeterminate?: boolean;
}) {
  const fill = {
    group: "bg-ocean-500",
    phase: "bg-amber-500",
    convert: "bg-moss-500",
    fail: "bg-rose-500",
  }[tone];
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="flex items-center gap-2 font-medium text-ink-700">
          {icon}
          {label}
        </span>
        <span className="tabular-nums text-ink-500">
          {indeterminate ? "…" : `${pct}%`}
        </span>
      </div>
      <div className="relative h-2 overflow-hidden rounded-full bg-ink-100">
        {indeterminate ? (
          <div
            className={cn(
              "absolute inset-y-0 w-1/3 rounded-full animate-indeterminate",
              fill,
            )}
          />
        ) : (
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              fill,
              pulse && "animate-pulse",
            )}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <div className="mt-1 truncate text-[11px] text-ink-400">{sub}</div>
    </div>
  );
}

function ChunkRow({ chunk }: { chunk: ChunkState }) {
  const { t } = useTranslation();
  const showTime =
    (chunk.phase === "completed" || chunk.phase === "failed") &&
    chunk.elapsed_ms != null;
  return (
    <li className="flex items-center gap-3 px-5 py-3 text-sm">
      <PhaseIcon phase={chunk.phase} />
      <div className="flex-1 truncate">
        <div className="font-medium text-ink-800">{chunk.chunk_id}</div>
        <div className="truncate text-[11px] text-ink-400">{chunk.message}</div>
      </div>
      {showTime && (
        <span
          className="flex items-center gap-1 text-[11px] tabular-nums text-ink-500"
          title={t("runProgress.chunkTime")}
        >
          <Clock className="h-3 w-3 text-ink-400" />
          {formatDurationCompact(chunk.elapsed_ms as number)}
        </span>
      )}
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

function PhaseChip({
  phase,
  status,
}: {
  phase: PhaseState;
  status: RunState["status"];
}) {
  const { t } = useTranslation();
  const isBootstrap = phase.name.startsWith("bootstrap-");
  const tone =
    status === "failed"
      ? "border-rose-300 bg-rose-50 text-rose-700"
      : isBootstrap
        ? "border-amber-300 bg-amber-50 text-amber-800"
        : "border-ocean-300 bg-ocean-50 text-ocean-700";
  const labelKey = `runProgress.phaseLabels.${phase.name}`;
  const labelTranslated = t(labelKey, { defaultValue: phase.name });
  return (
    <div
      className={cn(
        "mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]",
        tone,
      )}
    >
      <span className="tabular-nums">
        {t("runProgress.phaseStep", { i: phase.index, n: phase.total })}
      </span>
      <span className="text-ink-300" aria-hidden>
        ·
      </span>
      <span className="normal-case tracking-normal">{labelTranslated}</span>
    </div>
  );
}

function StatusIndicator({ status }: { status: RunState["status"] }) {
  const { t } = useTranslation();
  if (status === "completed") {
    return (
      <span className="flex items-center gap-1 text-sm text-emerald-700">
        <CheckCircle2 className="h-4 w-4" /> {t("common.completed")}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex items-center gap-1 text-sm text-rose-700">
        <XCircle className="h-4 w-4" /> {t("common.failed")}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-sm text-ocean-700">
      <Loader2 className="h-4 w-4 animate-spin" /> {t("common.running")}
    </span>
  );
}
