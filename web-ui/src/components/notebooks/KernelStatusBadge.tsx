import { CircleDot, Loader2, Power, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { KernelStatus } from "@/lib/api";

interface Props {
  status: KernelStatus;
  onRestart: () => void;
  onStop: () => void;
  disabled?: boolean;
}

export function KernelStatusBadge({ status, onRestart, onStop, disabled }: Props) {
  const { t } = useTranslation();
  const Icon = status === "busy" ? Loader2 : CircleDot;
  const tone =
    status === "idle"
      ? "border-emerald-300 bg-emerald-50 text-emerald-800"
      : status === "busy"
        ? "border-sky-300 bg-sky-50 text-sky-800"
        : "border-ink-200 bg-ink-50 text-ink-600";
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${tone}`}
      >
        <Icon className={`h-3 w-3 ${status === "busy" ? "animate-spin" : ""}`} />
        {t(`notebooks.kernel.${status}`)}
      </span>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-600 hover:bg-ink-50 disabled:opacity-50"
        onClick={onRestart}
        disabled={disabled}
        title={t("notebooks.kernel.restartTitle")}
      >
        <RotateCcw className="h-3 w-3" />
        {t("notebooks.kernel.restart")}
      </button>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-600 hover:bg-ink-50 disabled:opacity-50"
        onClick={onStop}
        disabled={disabled || status === "dead"}
        title={t("notebooks.kernel.stopTitle")}
      >
        <Power className="h-3 w-3" />
        {t("notebooks.kernel.stop")}
      </button>
    </div>
  );
}
