import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  Check,
  Clock,
  Info,
  Loader2,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { RunProgress } from "@/components/RunProgress";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";

type YearStatus = "complete" | "partial" | "stale" | "current";

type YearStatusItem = {
  year: number;
  status: YearStatus;
  n_stations: number;
  n_stations_complete: number;
  min_date_max: string | null;
  max_date_max: string | null;
  downloaded_at: string | null;
};

const DISMISSED_PARTIAL_KEY = "inmet:dismissed-partial";

function readDismissed(): Set<number> {
  try {
    const raw = localStorage.getItem(DISMISSED_PARTIAL_KEY);
    return new Set(raw ? (JSON.parse(raw) as number[]) : []);
  } catch {
    return new Set();
  }
}

function writeDismissed(years: Set<number>): void {
  try {
    localStorage.setItem(DISMISSED_PARTIAL_KEY, JSON.stringify([...years]));
  } catch {
    // localStorage can be unavailable (Safari private mode); ignore.
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: YearStatus }) {
  const icons = {
    complete: <Check className="h-3 w-3" />,
    partial: <AlertTriangle className="h-3 w-3" />,
    stale: <RotateCcw className="h-3 w-3" />,
    current: <Clock className="h-3 w-3" />,
  };
  return icons[status];
}

function statusButtonClasses(
  status: YearStatus | undefined,
  selected: boolean,
  dismissed: boolean,
): string {
  if (selected) {
    return "border-ocean-500 bg-ocean-50 text-ocean-700";
  }
  if (!status) {
    return "border-ink-200 text-ink-600 hover:bg-ink-50";
  }
  if (status === "complete") {
    return "border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100";
  }
  if (status === "partial") {
    return dismissed
      ? "border-ink-200 text-ink-600 hover:bg-ink-50"
      : "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100";
  }
  if (status === "stale") {
    return "border-rose-300 bg-rose-50 text-rose-800 hover:bg-rose-100";
  }
  return "border-sky-300 bg-sky-50 text-sky-800 hover:bg-sky-100";
}

export function InmetDownloadFlow() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const yearsQ = useQuery({
    queryKey: ["inmet-years"],
    queryFn: api.inmet.years,
    retry: false,
  });
  const statusQ = useQuery({
    queryKey: ["inmet-year-status"],
    queryFn: api.inmet.yearStatus,
    retry: false,
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dismissed, setDismissed] = useState<Set<number>>(() => readDismissed());
  const [partialModal, setPartialModal] = useState<YearStatusItem | null>(null);

  const statusByYear = useMemo(() => {
    const map = new Map<number, YearStatusItem>();
    statusQ.data?.items.forEach((i) => map.set(i.year, i));
    return map;
  }, [statusQ.data]);

  const years = yearsQ.data?.years ?? [];
  const staleYears = useMemo(
    () =>
      (statusQ.data?.items ?? [])
        .filter((i) => i.status === "stale")
        .map((i) => i.year),
    [statusQ.data],
  );
  const currentYearItem = useMemo(
    () => statusQ.data?.items.find((i) => i.status === "current") ?? null,
    [statusQ.data],
  );
  const allSelected = years.length > 0 && selected.size === years.length;
  const selectedTouchesDb = useMemo(
    () => [...selected].some((y) => statusByYear.has(y)),
    [selected, statusByYear],
  );

  function toggle(y: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(y) ? next.delete(y) : next.add(y);
      return next;
    });
  }

  function dismissPartial(year: number) {
    const next = new Set(dismissed);
    next.add(year);
    setDismissed(next);
    writeDismissed(next);
  }

  const runMutation = useMutation({
    mutationFn: ({ years, update }: { years: number[]; update: boolean }) =>
      update ? api.inmet.updateYears(years) : api.inmet.run(years),
    onSuccess: () => {
      // Refresh the year-status so badges reflect the new state once the
      // pipeline finishes (RunProgress doesn't refetch this query).
      queryClient.invalidateQueries({ queryKey: ["inmet-year-status"] });
    },
  });

  function startRun(targets: number[], forceUpdate?: boolean) {
    if (targets.length === 0) return;
    const update =
      forceUpdate ?? targets.some((y) => statusByYear.has(y));
    runMutation.mutate({ years: targets, update });
  }

  function buildTooltip(year: number): string {
    const item = statusByYear.get(year);
    if (!item) return t("inmet.status.tooltip.neverDownloaded");
    const parts = [
      t("inmet.status.tooltip.lastRecord", {
        date: formatDate(item.max_date_max),
      }),
      t("inmet.status.tooltip.stationsComplete", {
        n: item.n_stations_complete,
        total: item.n_stations,
      }),
      t("inmet.status.tooltip.downloadedAt", {
        when: formatDateTime(item.downloaded_at),
      }),
    ];
    return parts.join(" · ");
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
          {t("inmet.title")}
        </h1>
        <p className="mt-1 text-sm text-ink-500">{t("inmet.subtitle")}</p>
      </header>

      <aside className="relative overflow-hidden rounded-2xl border border-amber-200/70 bg-gradient-to-br from-amber-50 to-white p-5">
        <div className="absolute inset-y-0 left-0 w-1 bg-amber-400" aria-hidden />
        <div className="flex items-start gap-3 pl-2">
          <div className="mt-0.5 rounded-full bg-amber-100 p-1.5">
            <Sparkles className="h-4 w-4 text-amber-700" aria-hidden />
          </div>
          <div className="text-sm leading-relaxed text-ink-700">
            <div className="font-semibold tracking-tight text-amber-900">
              {t("inmet.autoBootstrap.title")}
            </div>
            <p className="mt-0.5 text-ink-600">
              <Trans
                i18nKey="inmet.autoBootstrap.body"
                values={{ view: "era5_inmet" }}
                components={{
                  c: (
                    <code className="rounded bg-amber-100 px-1 py-0.5 font-mono text-[12px] text-amber-900" />
                  ),
                }}
              >
                {t("inmet.autoBootstrap.body", { view: "era5_inmet" })}
              </Trans>{" "}
              <span className="text-ink-500">
                {t("inmet.autoBootstrap.noAction")}
              </span>
            </p>
          </div>
        </div>
      </aside>

      <aside className="relative overflow-hidden rounded-2xl border border-sky-200/70 bg-gradient-to-br from-sky-50 to-white p-5">
        <div className="absolute inset-y-0 left-0 w-1 bg-sky-400" aria-hidden />
        <div className="flex items-start gap-3 pl-2">
          <div className="mt-0.5 rounded-full bg-sky-100 p-1.5">
            <Info className="h-4 w-4 text-sky-700" aria-hidden />
          </div>
          <div className="text-sm leading-relaxed text-ink-700">
            <div className="font-semibold tracking-tight text-sky-900">
              {t("inmet.status.lagNoticeTitle")}
            </div>
            <p className="mt-0.5 text-ink-600">
              {t("inmet.status.lagNoticeBody")}
            </p>
          </div>
        </div>
      </aside>

      <section className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-medium text-ink-800">
            {t("inmet.years.title")}
          </h2>
          {years.length > 0 && (
            <button
              type="button"
              className="text-xs text-ocean-600 hover:underline"
              onClick={() =>
                setSelected(allSelected ? new Set() : new Set(years))
              }
            >
              {allSelected
                ? t("inmet.years.deselectAll")
                : t("inmet.years.selectAll")}
            </button>
          )}
        </div>

        {/* Quick actions for the user's local database */}
        {(staleYears.length > 0 || currentYearItem) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {staleYears.length > 0 && (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-md border border-rose-300 bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-800 hover:bg-rose-100"
                onClick={() => startRun(staleYears, true)}
                disabled={runMutation.isPending}
              >
                <RotateCcw className="h-3 w-3" />
                {t("inmet.status.updateAllStale", { count: staleYears.length })}
              </button>
            )}
            {currentYearItem && (
              <button
                type="button"
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-300 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-800 hover:bg-sky-100"
                onClick={() => startRun([currentYearItem.year], true)}
                disabled={runMutation.isPending}
              >
                <Clock className="h-3 w-3" />
                {t("inmet.status.updateCurrent")}
              </button>
            )}
          </div>
        )}

        {/* Legend */}
        {statusQ.data && statusQ.data.items.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-ink-500">
            <span className="font-medium text-ink-600">
              {t("inmet.status.legendLabel")}
            </span>
            <span className="inline-flex items-center gap-1">
              <Check className="h-3 w-3 text-emerald-600" />
              {t("inmet.status.complete")}
            </span>
            <span className="inline-flex items-center gap-1">
              <AlertTriangle className="h-3 w-3 text-amber-600" />
              {t("inmet.status.partial")}
            </span>
            <span className="inline-flex items-center gap-1">
              <RotateCcw className="h-3 w-3 text-rose-600" />
              {t("inmet.status.stale")}
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3 text-sky-600" />
              {t("inmet.status.current")}
            </span>
          </div>
        )}

        {yearsQ.isLoading ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-ink-500">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("inmet.years.loading")}
          </div>
        ) : yearsQ.isError ? (
          <p className="mt-3 text-sm text-amber-700">{t("inmet.years.error")}</p>
        ) : (
          <div className="mt-4 grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
            {years.map((y) => {
              const on = selected.has(y);
              const item = statusByYear.get(y);
              const isDismissedPartial =
                item?.status === "partial" && dismissed.has(y);
              return (
                <button
                  key={y}
                  type="button"
                  onClick={() => {
                    if (item?.status === "partial" && !isDismissedPartial) {
                      setPartialModal(item);
                      return;
                    }
                    toggle(y);
                  }}
                  title={buildTooltip(y)}
                  className={cn(
                    "inline-flex items-center justify-center gap-1 rounded-lg border px-2 py-1.5 text-sm tabular-nums",
                    statusButtonClasses(item?.status, on, isDismissedPartial),
                  )}
                >
                  <span>{y}</span>
                  {item && !isDismissedPartial && (
                    <StatusBadge status={item.status} />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="card p-5">
        <h2 className="text-lg font-medium text-ink-800">{t("inmet.run.title")}</h2>
        <p className="mt-1 text-sm text-ink-500">
          {selected.size === 0
            ? t("inmet.run.selectAtLeastOne")
            : t("inmet.run.yearsSelected", { count: selected.size })}
        </p>
        <button
          className="btn-primary mt-4"
          disabled={selected.size === 0 || runMutation.isPending}
          onClick={() => startRun([...selected].sort((a, b) => a - b))}
        >
          {runMutation.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {selectedTouchesDb
            ? t("inmet.run.buttonUpdate")
            : t("inmet.run.button")}
        </button>

        {runMutation.isError && (
          <p className="mt-3 text-sm text-amber-700">
            {t("inmet.run.failure", {
              message: (runMutation.error as Error).message,
            })}
          </p>
        )}

        {runMutation.data && (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-ink-500">
              {t("inmet.run.runStarted")}{" "}
              <span className="font-mono">{runMutation.data.run_id}</span>
            </p>
            <RunProgress
              key={runMutation.data.run_id}
              runId={runMutation.data.run_id}
              dataset="inmet"
              kind="station"
            />
            <div className="rounded-xl border border-ink-200 bg-ink-50/60 p-4 text-sm">
              <p className="font-medium text-ink-800">{t("inmet.run.nextSteps")}</p>
              <ul className="mt-2 list-inside list-disc space-y-1 text-ink-600">
                <li>
                  <Link
                    to="/inventory"
                    className="text-ocean-600 hover:underline"
                  >
                    {t("inmet.run.seeInventory")}
                  </Link>{" "}
                  {t("inmet.run.seeInventoryHint")}
                </li>
                <li>
                  <Trans
                    i18nKey="inmet.run.compareNote"
                    values={{ view: "era5_inmet" }}
                    components={{ c: <code /> }}
                  >
                    {t("inmet.run.compareNote", { view: "era5_inmet" })}
                  </Trans>
                </li>
              </ul>
            </div>
          </div>
        )}
      </section>

      {/* Partial-year decision modal */}
      {partialModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setPartialModal(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-ink-800">
              {t("inmet.status.partialDialog.title", { year: partialModal.year })}
            </h3>
            <p className="mt-2 text-sm text-ink-600">
              {t("inmet.status.partialDialog.body", {
                missing:
                  partialModal.n_stations - partialModal.n_stations_complete,
                total: partialModal.n_stations,
              })}
            </p>
            <div className="mt-5 flex flex-col gap-2">
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  startRun([partialModal.year], true);
                  setPartialModal(null);
                }}
              >
                {t("inmet.status.partialDialog.update")}
              </button>
              <button
                type="button"
                className="btn-outline"
                onClick={() => {
                  dismissPartial(partialModal.year);
                  setPartialModal(null);
                }}
              >
                {t("inmet.status.partialDialog.dismiss")}
              </button>
              <button
                type="button"
                className="text-xs text-ink-500 hover:underline"
                onClick={() => setPartialModal(null)}
              >
                {t("inmet.status.partialDialog.cancel")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
