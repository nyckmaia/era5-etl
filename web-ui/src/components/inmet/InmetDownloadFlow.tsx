import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { RunProgress } from "@/components/RunProgress";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";

/**
 * Dedicated INMET download flow. See the original Portuguese-only
 * version's docstring for the design notes; the only change here is
 * that every user-visible string is sourced from i18n.
 */
export function InmetDownloadFlow() {
  const { t } = useTranslation();
  const yearsQ = useQuery({
    queryKey: ["inmet-years"],
    queryFn: api.inmet.years,
    retry: false,
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const runMutation = useMutation({
    mutationFn: () => api.inmet.run([...selected].sort((a, b) => a - b)),
  });

  const years = yearsQ.data?.years ?? [];
  const allSelected = years.length > 0 && selected.size === years.length;

  function toggle(y: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(y) ? next.delete(y) : next.add(y);
      return next;
    });
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

      <section className="card p-5">
        <div className="flex items-center justify-between">
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
              return (
                <button
                  key={y}
                  type="button"
                  onClick={() => toggle(y)}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-sm tabular-nums",
                    on
                      ? "border-ocean-500 bg-ocean-50 text-ocean-700"
                      : "border-ink-200 text-ink-600 hover:bg-ink-50",
                  )}
                >
                  {y}
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
          onClick={() => runMutation.mutate()}
        >
          {runMutation.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          {t("inmet.run.button")}
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
    </div>
  );
}
