import * as Dialog from "@radix-ui/react-dialog";
import { Copy, X } from "lucide-react";
import { Fragment, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import type { NotebookRun } from "@/lib/api";

// Param keys that are experiment inputs rather than XGBoost hyperparameters.
// The notebook's log_model_run() folds these into `params` (see template);
// everything else in `params` is treated as a model hyperparameter.
const INPUT_KEYS = new Set([
  "station_id",
  "date_start",
  "date_end",
  "target_var",
  "test_fraction",
  "era5_land_vars",
]);

interface Props {
  /** The run whose inputs to show, or null to keep the dialog closed. */
  run: NotebookRun | null;
  onClose: () => void;
}

function asText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

/**
 * Read-only view of every input that produced a logged run — station, dates,
 * target, test fraction, the active ERA5-LAND variables and the XGBoost
 * hyperparameters — plus a one-click copy of a ready-to-paste config block so
 * the user can reproduce the exact experiment in the notebook.
 */
export function RunInputsDialog({ run, onClose }: Props) {
  const { t } = useTranslation();

  const data = useMemo(() => {
    const params = (run?.params ?? {}) as Record<string, unknown>;
    const vars = Array.isArray(params.era5_land_vars)
      ? (params.era5_land_vars as unknown[]).map(String)
      : [];
    const xgb = Object.entries(params).filter(([k]) => !INPUT_KEYS.has(k));
    return {
      station: params.station_id,
      dateStart: params.date_start,
      dateEnd: params.date_end,
      target: params.target_var,
      testFraction: params.test_fraction,
      vars,
      xgb,
      // Older runs logged only XGBoost params + notes; flag so we can hint.
      hasInputs:
        params.station_id !== undefined ||
        params.target_var !== undefined ||
        vars.length > 0,
    };
  }, [run]);

  if (!run) return null;
  const r = run;

  function buildConfigSnippet(): string {
    const q = (v: unknown) => (v === undefined ? '""' : `"${String(v)}"`);
    const active = data.vars.map((v) => `"${v}"`).join(", ");
    return [
      `# Reproduce run from ${new Date(r.ts).toISOString()}`,
      `STATION_ID    = ${q(data.station)}`,
      `DATE_START    = ${q(data.dateStart)}`,
      `DATE_END      = ${q(data.dateEnd)}`,
      `TARGET_VAR    = ${q(data.target)}`,
      `TEST_FRACTION = ${data.testFraction ?? 0.2}`,
      `# Re-enable exactly the era5_land variables this run used:`,
      `_active = {${active}}`,
      `era5_land_vars = {k: (k in _active) for k in era5_land_vars}`,
    ].join("\n");
  }

  function copyConfig() {
    navigator.clipboard.writeText(buildConfigSnippet());
    toast.success(t("notebooks.runs.inputs.copied"));
  }

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-900/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(34rem,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-auto rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-sm font-semibold text-ink-800">
              {t("notebooks.runs.inputs.title")}
            </Dialog.Title>
            <Dialog.Close className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          {!data.hasInputs && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-600">
              {t("notebooks.runs.inputs.legacy")}
            </p>
          )}

          {/* Experiment inputs */}
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-ink-500">{t("notebooks.runs.inputs.station")}</dt>
            <dd className="font-medium text-ink-800">{asText(data.station)}</dd>
            <dt className="text-ink-500">{t("notebooks.runs.inputs.period")}</dt>
            <dd className="font-medium text-ink-800">
              {asText(data.dateStart)} → {asText(data.dateEnd)}
            </dd>
            <dt className="text-ink-500">{t("notebooks.runs.inputs.target")}</dt>
            <dd className="font-medium text-ink-800">{asText(data.target)}</dd>
            <dt className="text-ink-500">{t("notebooks.runs.col.testFraction")}</dt>
            <dd className="font-medium text-ink-800">{asText(data.testFraction)}</dd>
          </dl>

          {/* Active ERA5-LAND variables */}
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-ink-600">
              {t("notebooks.runs.inputs.era5Vars", { count: data.vars.length })}
            </h4>
            {data.vars.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {data.vars.map((v) => (
                  <span
                    key={v}
                    className="rounded-full bg-sky-50 px-2 py-0.5 font-mono text-[11px] text-ocean-700"
                  >
                    {v}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-ink-400">—</p>
            )}
          </div>

          {/* XGBoost hyperparameters */}
          {data.xgb.length > 0 && (
            <div>
              <h4 className="mb-1.5 text-xs font-medium text-ink-600">
                {t("notebooks.runs.inputs.xgbParams")}
              </h4>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                {data.xgb.map(([k, v]) => (
                  <Fragment key={k}>
                    <dt className="font-mono text-ink-500">{k}</dt>
                    <dd className="font-mono text-ink-800">{asText(v)}</dd>
                  </Fragment>
                ))}
              </dl>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 border-t border-ink-100 pt-3">
            <button type="button" className="btn-outline" onClick={onClose}>
              {t("notebooks.runs.inputs.close")}
            </button>
            <button
              type="button"
              className="btn-primary flex items-center gap-1.5"
              onClick={copyConfig}
            >
              <Copy className="h-3.5 w-3.5" />
              {t("notebooks.runs.inputs.copy")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
