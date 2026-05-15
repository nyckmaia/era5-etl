import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  MapPin,
  Play,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import { getRouteApi } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { RunProgress } from "@/components/RunProgress";
import { api, DatasetInfo, DiffPreview } from "@/lib/api";
import { cn, formatBytes } from "@/lib/format";

type Step = 0 | 1 | 2 | 3 | 4 | 5;

const HOURS_ALL = Array.from({ length: 24 }, (_, h) => `${h.toString().padStart(2, "0")}:00`);
const HOURS_SYNOPTIC = ["00:00", "06:00", "12:00", "18:00"];
const HOURS_3H = Array.from({ length: 8 }, (_, i) => `${(i * 3).toString().padStart(2, "0")}:00`);

const AREA_PRESETS: Record<string, [number, number, number, number]> = {
  Brazil: [6, -74, -34, -34],
  Global: [90, -180, -90, 180],
  "South America": [13, -82, -56, -34],
};

const downloadRouteApi = getRouteApi("/download");

export function DownloadWizardPage() {
  const search = downloadRouteApi.useSearch();
  const [step, setStep] = useState<Step>(0);
  const [dataset, setDataset] = useState<string>("");
  const [variables, setVariables] = useState<string[]>([]);
  const [area, setArea] = useState<[number, number, number, number]>([6, -74, -34, -34]);
  const [hours, setHours] = useState<string[]>(HOURS_SYNOPTIC);
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-01-31");
  const [applyDiff, setApplyDiff] = useState(true);

  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const activeDataset = useMemo(
    () => datasets?.find((d) => d.name === dataset),
    [datasets, dataset],
  );

  // Deep-link entry: when the dashboard/inventory hands us a dataset via
  // search params, preselect it (+ its default variables) and jump to the
  // requested step (Variables by default). Runs once, after datasets load.
  const deepLinkApplied = useRef(false);
  useEffect(() => {
    if (deepLinkApplied.current) return;
    if (!search.dataset || !datasets) return;
    const info = datasets.find((d) => d.name === search.dataset);
    if (!info) return;
    deepLinkApplied.current = true;
    setDataset(info.name);
    setVariables(info.default_variables);
    const requested = search.step;
    const target =
      typeof requested === "number" && requested >= 0 && requested <= 5
        ? (requested as Step)
        : 1;
    setStep(target);
  }, [search.dataset, search.step, datasets]);

  const estimateMutation = useMutation({
    mutationFn: () =>
      api.estimate({
        dataset,
        variables,
        start_date: startDate,
        end_date: endDate,
        area,
        hours,
      }),
  });
  const runMutation = useMutation({
    mutationFn: () =>
      api.startRunWithDiff({
        dataset,
        variables,
        start_date: startDate,
        end_date: endDate,
        area,
        hours,
        apply_diff: applyDiff,
      }),
  });

  const diffMutation = useMutation({
    mutationFn: () =>
      api.diffPreview({
        dataset,
        area,
        date_from: startDate,
        date_to: endDate,
        hours: hours.map((h) => parseInt(h.slice(0, 2), 10)),
        variables,
      }),
  });

  const canAdvance = ((): boolean => {
    switch (step) {
      case 0:
        return Boolean(dataset);
      case 1:
        return variables.length > 0;
      case 2:
        return area.length === 4;
      case 3:
        return Boolean(startDate && endDate && hours.length > 0);
      case 4:
        return true;
      default:
        return true;
    }
  })();

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">Download wizard</h1>
          <p className="mt-1 text-ink-500">
            Configure a CDS request. Variables and grid resolution are independent for each dataset.
          </p>
        </div>
        <Stepper step={step} />
      </header>

      <div className="card p-8">
        {step === 0 && (
          <StepDataset
            datasets={datasets ?? []}
            value={dataset}
            onChange={(d) => {
              setDataset(d);
              const info = datasets?.find((x) => x.name === d);
              if (info) setVariables(info.default_variables);
            }}
          />
        )}
        {step === 1 && activeDataset && (
          <StepVariables dataset={activeDataset} value={variables} onChange={setVariables} />
        )}
        {step === 2 && <StepArea value={area} onChange={setArea} />}
        {step === 3 && (
          <StepPeriod
            startDate={startDate}
            endDate={endDate}
            hours={hours}
            onStart={setStartDate}
            onEnd={setEndDate}
            onHours={setHours}
          />
        )}
        {step === 4 && (
          <StepDiff
            diff={diffMutation}
            applyDiff={applyDiff}
            onApplyDiffChange={setApplyDiff}
            onCompute={() => diffMutation.mutate()}
          />
        )}
        {step === 5 && (
          <StepConfirm
            dataset={dataset}
            variables={variables}
            area={area}
            hours={hours}
            startDate={startDate}
            endDate={endDate}
            applyDiff={applyDiff}
            estimate={estimateMutation}
            run={runMutation}
            onEstimate={() => estimateMutation.mutate()}
            onRun={() => runMutation.mutate()}
          />
        )}
      </div>

      <div className="flex justify-between">
        <button
          className="btn-ghost"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1) as Step)}
        >
          <ChevronLeft className="h-4 w-4" /> Back
        </button>
        {step < 5 ? (
          <button
            className="btn-primary"
            disabled={!canAdvance}
            onClick={() => {
              const next = Math.min(5, step + 1) as Step;
              setStep(next);
              // Auto-fetch the diff when entering the diff step.
              if (next === 4 && !diffMutation.data && !diffMutation.isPending) {
                diffMutation.mutate();
              }
            }}
          >
            Next <ChevronRight className="h-4 w-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Stepper({ step }: { step: Step }) {
  const labels = ["Dataset", "Variables", "Area", "Period", "Smart Diff", "Confirm"];
  return (
    <ol className="flex items-center gap-2 text-xs">
      {labels.map((label, i) => (
        <li
          key={label}
          className={cn(
            "rounded-full px-3 py-1",
            i === step
              ? "bg-ocean-600 text-white"
              : i < step
                ? "bg-moss-500/20 text-moss-600"
                : "bg-ink-100 text-ink-400",
          )}
        >
          {label}
        </li>
      ))}
    </ol>
  );
}

function StepDataset({
  datasets,
  value,
  onChange,
}: {
  datasets: DatasetInfo[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">Choose dataset</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {datasets.map((d) => {
          const isActive = value === d.name;
          const label =
            d.name === "era5"
              ? "ERA5"
              : d.name === "era5-land"
                ? "ERA5-LAND"
                : d.name;
          const description =
            d.name === "era5"
              ? "Atmospheric reanalysis on 0.25° grid -- temperature, pressure, wind, radiation, clouds."
              : d.name === "era5-land"
                ? "Land-surface reanalysis on 0.1° grid -- soil temperature, soil moisture, surface fluxes."
                : d.cds_dataset_id;

          return (
            <button
              key={d.name}
              onClick={() => onChange(d.name)}
              className={cn(
                "flex flex-col items-start gap-2 rounded-2xl border p-5 text-left transition",
                isActive
                  ? "border-ocean-500 bg-ocean-50 shadow-elevated"
                  : "border-ink-200 bg-white hover:border-ocean-300",
              )}
            >
              <div className="text-xs font-medium uppercase tracking-wider text-ocean-600">
                {d.name}
              </div>
              <div className="text-xl font-semibold text-ink-800">{label}</div>
              <p className="text-sm text-ink-500">{description}</p>
              <div className="mt-2 text-xs text-ink-400">
                Resolution: {d.grid_resolution_deg}° · {d.variables.length} variables available
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepVariables({
  dataset,
  value,
  onChange,
}: {
  dataset: DatasetInfo;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  function toggle(v: string) {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-medium">Select variables</h2>
        <div className="space-x-2 text-xs">
          <button
            onClick={() => onChange(dataset.default_variables)}
            className="text-ocean-600 hover:underline"
          >
            Default preset
          </button>
          <button
            onClick={() => onChange(dataset.variables.map((v) => v.api_name))}
            className="text-ocean-600 hover:underline"
          >
            All
          </button>
          <button onClick={() => onChange([])} className="text-ink-400 hover:underline">
            Clear
          </button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {dataset.variables.map((v) => {
          const checked = value.includes(v.api_name);
          return (
            <label
              key={v.api_name}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition",
                checked
                  ? "border-ocean-400 bg-ocean-50/60"
                  : "border-ink-200 bg-white hover:border-ocean-300",
              )}
            >
              <input
                type="checkbox"
                className="mt-1"
                checked={checked}
                onChange={() => toggle(v.api_name)}
              />
              <div className="flex-1">
                <div className="flex items-baseline justify-between">
                  <span className="font-medium text-ink-800">{v.full_name}</span>
                  <span className="font-mono text-[11px] text-ink-400">{v.unit}</span>
                </div>
                <div className="text-xs text-ink-400">{v.api_name}</div>
                <div className="mt-1 text-xs text-ink-500">{v.description}</div>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function StepArea({
  value,
  onChange,
}: {
  value: [number, number, number, number];
  onChange: (v: [number, number, number, number]) => void;
}) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">Geographic area</h2>
      <div className="flex flex-wrap gap-2">
        {Object.entries(AREA_PRESETS).map(([name, bbox]) => (
          <button
            key={name}
            className="btn-outline"
            onClick={() => onChange(bbox)}
          >
            <MapPin className="h-3.5 w-3.5" />
            {name}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[
          { label: "North", idx: 0 },
          { label: "West", idx: 1 },
          { label: "South", idx: 2 },
          { label: "East", idx: 3 },
        ].map(({ label, idx }) => (
          <label key={label} className="block">
            <span className="text-xs uppercase tracking-wide text-ink-500">{label}</span>
            <input
              className="input mt-1 font-mono"
              type="number"
              step="0.1"
              value={value[idx]}
              onChange={(e) => {
                const next = [...value] as [number, number, number, number];
                next[idx] = Number.parseFloat(e.target.value);
                onChange(next);
              }}
            />
          </label>
        ))}
      </div>
      <p className="text-xs text-ink-400">
        Bounding box order: [North, West, South, East] in decimal degrees.
      </p>
    </div>
  );
}

function StepPeriod({
  startDate,
  endDate,
  hours,
  onStart,
  onEnd,
  onHours,
}: {
  startDate: string;
  endDate: string;
  hours: string[];
  onStart: (v: string) => void;
  onEnd: (v: string) => void;
  onHours: (v: string[]) => void;
}) {
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">Period & hours</h2>

      <div className="grid grid-cols-2 gap-4">
        <label>
          <span className="text-xs uppercase tracking-wide text-ink-500">Start date</span>
          <input
            type="date"
            className="input mt-1"
            value={startDate}
            onChange={(e) => onStart(e.target.value)}
          />
        </label>
        <label>
          <span className="text-xs uppercase tracking-wide text-ink-500">End date</span>
          <input
            type="date"
            className="input mt-1"
            value={endDate}
            onChange={(e) => onEnd(e.target.value)}
          />
        </label>
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-wide text-ink-500">Hours (UTC)</span>
          <div className="space-x-2 text-xs">
            <button onClick={() => onHours(HOURS_ALL)} className="text-ocean-600 hover:underline">
              All 24
            </button>
            <button onClick={() => onHours(HOURS_3H)} className="text-ocean-600 hover:underline">
              Every 3h
            </button>
            <button onClick={() => onHours(HOURS_SYNOPTIC)} className="text-ocean-600 hover:underline">
              Synoptic (0/6/12/18)
            </button>
          </div>
        </div>
        <div className="grid grid-cols-6 gap-1.5 md:grid-cols-12">
          {HOURS_ALL.map((h) => {
            const active = hours.includes(h);
            return (
              <button
                key={h}
                onClick={() =>
                  onHours(active ? hours.filter((x) => x !== h) : [...hours, h].sort())
                }
                className={cn(
                  "rounded-md px-1 py-1 font-mono text-[11px]",
                  active
                    ? "bg-ocean-600 text-white"
                    : "bg-ink-100 text-ink-500 hover:bg-ink-200",
                )}
              >
                {h.slice(0, 2)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StepDiff({
  diff,
  applyDiff,
  onApplyDiffChange,
  onCompute,
}: {
  diff: ReturnType<typeof useMutation<DiffPreview, Error, void, unknown>>;
  applyDiff: boolean;
  onApplyDiffChange: (v: boolean) => void;
  onCompute: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-ocean-600" />
        <h2 className="text-lg font-medium">Smart Diff</h2>
      </div>
      <p className="text-sm text-ink-500">
        Comparamos sua requisição com o que já está no banco para baixar
        apenas os pontos × datas × horas × variáveis faltantes.
      </p>

      {diff.isPending ? (
        <div className="flex items-center gap-2 rounded-xl border border-ink-200 bg-ink-50/50 p-6 text-sm text-ink-500">
          <Loader2 className="h-5 w-5 animate-spin text-ocean-500" />
          Calculando o que já está no banco...
        </div>
      ) : diff.error ? (
        <div className="space-y-3">
          <p className="text-sm text-red-600">{(diff.error as Error).message}</p>
          <button onClick={onCompute} className="btn-outline">
            Tentar novamente
          </button>
        </div>
      ) : diff.data ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <DiffStat
            label="Já no banco"
            value={(diff.data.requested_cells - diff.data.missing_cells).toLocaleString()}
            sub={`${diff.data.savings_pct.toFixed(1)}%`}
            tone="success"
          />
          <DiffStat
            label="Faltando"
            value={diff.data.missing_cells.toLocaleString()}
            sub={`${(100 - diff.data.savings_pct).toFixed(1)}%`}
            tone={diff.data.missing_cells === 0 ? "success" : "warn"}
          />
          <DiffStat
            label="Total requisitado"
            value={diff.data.requested_cells.toLocaleString()}
            sub="células"
            tone="neutral"
          />
        </div>
      ) : (
        <button onClick={onCompute} className="btn-primary">
          Calcular diff
        </button>
      )}

      {diff.data && diff.data.missing_cells > 0 && (
        <div className="rounded-xl border border-ink-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink-700">
            Modo de download
          </h3>
          <div className="space-y-2">
            <Toggle
              checked={applyDiff}
              onChange={() => onApplyDiffChange(true)}
              icon={<TrendingDown className="h-4 w-4" />}
              title="Baixar apenas o que falta (recomendado)"
              subtitle={`Economiza ~${diff.data.savings_pct.toFixed(0)}% das requisições ao CDS.`}
            />
            <Toggle
              checked={!applyDiff}
              onChange={() => onApplyDiffChange(false)}
              icon={<Play className="h-4 w-4" />}
              title="Baixar tudo (sobrescrever)"
              subtitle="Re-baixa também os dados já presentes."
            />
          </div>
        </div>
      )}

      {diff.data && diff.data.missing_cells === 0 && (
        <div className="rounded-xl border border-moss-400 bg-moss-400/10 p-4 text-sm text-moss-600">
          ✓ Tudo que você pediu já está no banco. Nada a baixar.
        </div>
      )}
    </div>
  );
}

function DiffStat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "success" | "warn" | "neutral";
}) {
  const toneCls = {
    success: "border-moss-400 bg-moss-400/5 text-moss-600",
    warn: "border-amber-400 bg-amber-50 text-amber-600",
    neutral: "border-ink-200 bg-ink-50 text-ink-700",
  }[tone];
  return (
    <div className={cn("rounded-xl border p-4", toneCls)}>
      <div className="text-[10px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      <div className="mt-1 text-xs opacity-70">{sub}</div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  icon,
  title,
  subtitle,
}: {
  checked: boolean;
  onChange: () => void;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition",
        checked ? "border-ocean-400 bg-ocean-50/50" : "border-ink-200 bg-white hover:border-ocean-300",
      )}
    >
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="mt-1"
      />
      <div className="flex-1">
        <div className="flex items-center gap-2 text-sm font-medium text-ink-800">
          {icon}
          {title}
        </div>
        <div className="mt-0.5 text-xs text-ink-500">{subtitle}</div>
      </div>
    </label>
  );
}

function StepConfirm({
  dataset,
  variables,
  area,
  hours,
  startDate,
  endDate,
  applyDiff,
  estimate,
  run,
  onEstimate,
  onRun,
}: {
  dataset: string;
  variables: string[];
  area: [number, number, number, number];
  hours: string[];
  startDate: string;
  endDate: string;
  applyDiff: boolean;
  estimate: ReturnType<typeof useMutation<any, any, any, any>>;
  run: ReturnType<typeof useMutation<any, any, any, any>>;
  onEstimate: () => void;
  onRun: () => void;
}) {
  const result = estimate.data;
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">Confirm & start</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <Row label="Dataset" value={dataset} />
        <Row label="Period" value={`${startDate} → ${endDate}`} />
        <Row label="Variables" value={`${variables.length} selected`} />
        <Row label="Hours" value={`${hours.length} of 24`} />
        <Row label="Area" value={`N ${area[0]} · W ${area[1]} · S ${area[2]} · E ${area[3]}`} />
        <Row
          label="Smart diff"
          value={applyDiff ? "Enabled (skip cached)" : "Disabled (full request)"}
        />
      </dl>

      <div className="flex flex-wrap gap-3">
        <button onClick={onEstimate} className="btn-outline" disabled={estimate.isPending}>
          {estimate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Estimate size
        </button>
        <button onClick={onRun} className="btn-primary" disabled={run.isPending}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Start download
        </button>
      </div>

      {estimate.isError ? (
        <p className="text-sm text-red-600">{(estimate.error as Error).message}</p>
      ) : null}
      {result ? (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-ink-800">Plan summary</h3>
          <p className="mt-1 text-sm text-ink-500">
            <span className="font-medium text-ink-800">{result.total_chunks}</span> chunk(s) ·{" "}
            <span className="font-medium text-ink-800">
              {formatBytes(result.total_estimated_bytes)}
            </span>{" "}
            estimated uncompressed
          </p>
          <div className="mt-3 max-h-64 overflow-y-auto rounded-lg border border-ink-100">
            <table className="w-full text-xs">
              <thead className="bg-ink-50">
                <tr>
                  <th className="px-3 py-2 text-left">#</th>
                  <th className="px-3 py-2 text-left">chunk_id</th>
                  <th className="px-3 py-2 text-left">Variables</th>
                  <th className="px-3 py-2 text-right">MB</th>
                </tr>
              </thead>
              <tbody>
                {result.chunks.map((c: { chunk_id: string; variables: string[]; estimated_mb: number }, i: number) => (
                  <tr key={c.chunk_id} className="border-t border-ink-100">
                    <td className="px-3 py-1.5 text-ink-400">{i + 1}</td>
                    <td className="px-3 py-1.5 font-mono">{c.chunk_id}</td>
                    <td className="px-3 py-1.5">{c.variables.length}</td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {c.estimated_mb.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      {run.data ? (
        <div className="space-y-2">
          <p className="text-sm text-moss-600">
            Run started: <span className="font-mono">{run.data.run_id}</span>
          </p>
          <RunProgress runId={run.data.run_id} dataset={dataset} />
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-400">{label}</dt>
      <dd className="font-medium text-ink-800">{value}</dd>
    </>
  );
}
