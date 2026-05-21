import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
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
import { useTranslation } from "react-i18next";

import { InmetDownloadFlow } from "@/components/inmet/InmetDownloadFlow";
import { RunProgress } from "@/components/RunProgress";
import { api, DatasetInfo, DiffPreview } from "@/lib/api";
import { cn, formatBytes } from "@/lib/format";

type Step = 0 | 1 | 2 | 3 | 4 | 5;

const HOURS_ALL = Array.from({ length: 24 }, (_, h) => `${h.toString().padStart(2, "0")}:00`);
const HOURS_SYNOPTIC = ["00:00", "06:00", "12:00", "18:00"];
const HOURS_3H = Array.from({ length: 8 }, (_, i) => `${(i * 3).toString().padStart(2, "0")}:00`);

// Stable preset ids so the i18n key drives the visible label per language.
const AREA_PRESETS: { id: "brazil" | "global" | "southAmerica"; bbox: [number, number, number, number] }[] = [
  { id: "brazil", bbox: [6, -74, -34, -34] },
  { id: "global", bbox: [90, -180, -90, 180] },
  { id: "southAmerica", bbox: [13, -82, -56, -34] },
];

const downloadRouteApi = getRouteApi("/download");

export function DownloadWizardPage() {
  const { t } = useTranslation();
  const search = downloadRouteApi.useSearch();
  const [step, setStep] = useState<Step>(0);
  const [dataset, setDataset] = useState<string>("");
  const [variables, setVariables] = useState<string[]>([]);
  const [area, setArea] = useState<[number, number, number, number]>([6, -74, -34, -34]);
  // Brazilian region(s) for polygon clipping. Empty list = no clip (download
  // the raw bbox). UF siglas (e.g. ["SP", "RJ"]) clip to the union; ["BR"]
  // clips to the whole-country polygon. Sent verbatim as ``clip_regions`` in
  // the pipeline payload.
  const [clipRegions, setClipRegions] = useState<string[]>([]);
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
        clip_regions: clipRegions.length > 0 ? clipRegions : null,
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
        clip_regions: clipRegions.length > 0 ? clipRegions : null,
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

  // Any change to an input that feeds the diff/estimate invalidates their
  // cached results. Without this, going Back from Smart Diff to adjust the
  // period/area and returning shows STALE estimates: the step-4 auto-fetch
  // only fires when `diffMutation.data` is empty, and the Confirm step's
  // estimate has the same staleness. Resetting forces a recompute on the
  // next visit. `reset` is stable; deps are the serialized inputs only.
  const diffReset = diffMutation.reset;
  const estimateReset = estimateMutation.reset;
  useEffect(() => {
    diffReset();
    estimateReset();
  }, [
    dataset,
    startDate,
    endDate,
    area.join(","),
    hours.join(","),
    variables.join(","),
    clipRegions.join(","),
    diffReset,
    estimateReset,
  ]);

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

  // Station sources (INMET) don't fit the CDS wizard (no variables/area/
  // hours/smart-diff/estimate). Branch to the dedicated minimal flow once
  // a non-grid dataset is selected. Placed after all hooks (rules of
  // hooks) and before the wizard render.
  if (activeDataset && activeDataset.is_gridded === false) {
    return <InmetDownloadFlow />;
  }

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
            {t("wizard.title")}
          </h1>
          <p className="mt-1 text-ink-500">{t("wizard.subtitle")}</p>
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
        {step === 2 && (
          <StepArea
            value={area}
            onChange={setArea}
            clipRegions={clipRegions}
            onClipRegionsChange={setClipRegions}
          />
        )}
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
            onNarrow={(s) => setStep(s)}
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
            clipRegions={clipRegions}
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
          <ChevronLeft className="h-4 w-4" /> {t("common.back")}
        </button>
        {step < 5 ? (
          <button
            className="btn-primary"
            disabled={!canAdvance}
            onClick={() => {
              const next = Math.min(5, step + 1) as Step;
              setStep(next);
              if (next === 4 && !diffMutation.data && !diffMutation.isPending) {
                diffMutation.mutate();
              }
            }}
          >
            {t("common.next")} <ChevronRight className="h-4 w-4" />
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Stepper({ step }: { step: Step }) {
  const { t } = useTranslation();
  const keys = [
    "wizard.steps.dataset",
    "wizard.steps.variables",
    "wizard.steps.area",
    "wizard.steps.period",
    "wizard.steps.smartDiff",
    "wizard.steps.confirm",
  ];
  return (
    <ol className="flex items-center gap-2 text-xs">
      {keys.map((key, i) => (
        <li
          key={key}
          className={cn(
            "rounded-full px-3 py-1",
            i === step
              ? "bg-ocean-600 text-white"
              : i < step
                ? "bg-moss-500/20 text-moss-600"
                : "bg-ink-100 text-ink-400",
          )}
        >
          {t(key)}
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
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">{t("wizard.chooseDataset")}</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {datasets.map((d) => {
          const isActive = value === d.name;
          const label =
            d.name === "era5"
              ? "ERA5"
              : d.name === "era5-land"
                ? "ERA5-LAND"
                : d.name.toUpperCase();
          const descKey = `dashboard.descriptions.${d.name}`;
          const description =
            t(descKey, { defaultValue: "" }) ||
            d.cds_dataset_id ||
            t("dashboard.fallbackDescription");
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
                {t("wizard.resolution")}: {d.grid_resolution_deg}° ·{" "}
                {t("wizard.variablesAvailable", { count: d.variables.length })}
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
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const groups = dataset.variable_groups ?? [];
  const sections = useMemo(() => {
    if (groups.length === 0) {
      return [
        {
          id: "__all__",
          label: t("wizard.variables.allVariables"),
          variables: dataset.variables,
        },
      ];
    }
    return groups.map((g) => ({
      id: g.id,
      label: g.label,
      variables: dataset.variables.filter((v) =>
        (v.groups ?? []).includes(g.id),
      ),
    }));
  }, [groups, dataset.variables, t]);

  const q = query.trim().toLowerCase();
  const filteredSections = useMemo(() => {
    if (!q) return sections;
    return sections
      .map((s) => ({
        ...s,
        variables: s.variables.filter((v) =>
          [v.api_name, v.full_name, v.description, v.short_name]
            .filter(Boolean)
            .some((t) => t.toLowerCase().includes(q)),
        ),
      }))
      .filter((s) => s.variables.length > 0);
  }, [sections, q]);

  function toggle(v: string) {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  }

  function toggleGroup(api_names: string[]) {
    const all = api_names.every((n) => value.includes(n));
    if (all) {
      // Deselect every variable that belongs to this group.
      onChange(value.filter((n) => !api_names.includes(n)));
    } else {
      // Add anything missing (preserve selections from other groups).
      const merged = new Set(value);
      for (const n of api_names) merged.add(n);
      onChange([...merged]);
    }
  }

  const totalSelected = value.length;
  const totalAvailable = dataset.variables.length;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-medium">
          {t("wizard.variables.title")}{" "}
          <span className="text-sm font-normal text-ink-400">
            {t("wizard.variables.counter", {
              selected: totalSelected,
              total: totalAvailable,
            })}
          </span>
        </h2>
        <div className="space-x-2 text-xs">
          <button
            onClick={() => onChange(dataset.default_variables)}
            className="text-ocean-600 hover:underline"
          >
            {t("wizard.variables.defaultPreset")}
          </button>
          <button
            onClick={() => onChange(dataset.variables.map((v) => v.api_name))}
            className="text-ocean-600 hover:underline"
          >
            {t("wizard.variables.all")}
          </button>
          <button onClick={() => onChange([])} className="text-ink-400 hover:underline">
            {t("wizard.variables.clear")}
          </button>
        </div>
      </div>

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("wizard.variables.filter")}
        className="input w-full"
      />

      <div className="space-y-5">
        {filteredSections.map((section) => {
          const apiNames = section.variables.map((v) => v.api_name);
          const selectedInGroup = apiNames.filter((n) =>
            value.includes(n),
          ).length;
          const allSelected =
            selectedInGroup === apiNames.length && apiNames.length > 0;
          return (
            <section key={section.id} className="space-y-2">
              <div className="flex items-baseline justify-between border-b border-ink-100 pb-1">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-600">
                  {section.label}{" "}
                  <span className="ml-1 text-xs font-normal text-ink-400">
                    {t("wizard.variables.sectionCounter", {
                      selected: selectedInGroup,
                      total: apiNames.length,
                    })}
                  </span>
                </h3>
                <button
                  type="button"
                  className="text-xs text-ocean-600 hover:underline"
                  onClick={() => toggleGroup(apiNames)}
                  disabled={apiNames.length === 0}
                >
                  {allSelected
                    ? t("wizard.variables.deselectAll")
                    : t("wizard.variables.selectAll")}
                </button>
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {section.variables.map((v) => {
                  const checked = value.includes(v.api_name);
                  return (
                    <label
                      key={`${section.id}-${v.api_name}`}
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
                          <span className="font-medium text-ink-800">
                            {v.full_name}
                          </span>
                          <span className="font-mono text-[11px] text-ink-400">
                            {v.unit}
                          </span>
                        </div>
                        <div className="text-xs text-ink-400">{v.api_name}</div>
                        <div className="mt-1 text-xs text-ink-500">
                          {v.description}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </section>
          );
        })}
        {filteredSections.length === 0 ? (
          <p className="rounded-lg border border-dashed border-ink-200 p-6 text-center text-sm text-ink-400">
            {t("wizard.variables.nothingMatches", { query })}
          </p>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Coordinate input that tolerates intermediate text ("", "-", "-12.")
 * while typing. A plain number input bound to NaN (what
 * `parseFloat("-")` yields) made it impossible to type negatives.
 */
function CoordInput({
  value,
  onCommit,
}: {
  value: number;
  onCommit: (n: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const focused = useRef(false);

  // Sync from props (preset / UF selection) only while not actively typing.
  useEffect(() => {
    if (!focused.current) setText(String(value));
  }, [value]);

  return (
    <input
      className="input mt-1 font-mono"
      type="text"
      inputMode="decimal"
      value={text}
      onFocus={() => {
        focused.current = true;
      }}
      onBlur={() => {
        focused.current = false;
        setText(String(value));
      }}
      onChange={(e) => {
        const t = e.target.value;
        if (!/^-?\d*\.?\d*$/.test(t)) return; // reject non-numeric chars
        setText(t);
        const n = Number(t);
        if (t !== "" && t !== "-" && t !== "." && Number.isFinite(n)) {
          onCommit(n);
        }
      }}
    />
  );
}

const UF_LIST = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
  "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
  "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
];

function StepArea({
  value,
  onChange,
  clipRegions,
  onClipRegionsChange,
}: {
  value: [number, number, number, number];
  onChange: (v: [number, number, number, number]) => void;
  clipRegions: string[];
  onClipRegionsChange: (regions: string[]) => void;
}) {
  const { t } = useTranslation();
  // Mirror `clipRegions` for UF buttons. ["BR"] selects the country
  // chip; UF siglas select individual states; [] = no clip.
  const selectedUfs = clipRegions.filter((r) => r !== "BR");
  const brSelected = clipRegions.includes("BR");
  const { data: ufBboxes } = useQuery({
    queryKey: ["regions-uf"],
    queryFn: api.regions.uf,
  });

  function applyUfs(ufs: string[]) {
    onClipRegionsChange(ufs);
    if (ufs.length === 0 || !ufBboxes) return;
    const sel = ufBboxes.filter((b) => ufs.includes(b.uf));
    if (sel.length === 0) return;
    const north = Math.max(...sel.map((b) => b.north));
    const west = Math.min(...sel.map((b) => b.west));
    const south = Math.min(...sel.map((b) => b.south));
    const east = Math.max(...sel.map((b) => b.east));
    onChange([north, west, south, east]);
  }

  function applyBrazil() {
    onClipRegionsChange(["BR"]);
    const brazil = AREA_PRESETS.find((p) => p.id === "brazil");
    if (brazil) onChange(brazil.bbox);
  }

  function toggleUf(uf: string) {
    const base = brSelected ? [] : selectedUfs;
    applyUfs(
      base.includes(uf) ? base.filter((x) => x !== uf) : [...base, uf],
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium">{t("wizard.area.title")}</h2>
      <div className="flex flex-wrap gap-2">
        {AREA_PRESETS.map((preset) => (
          <button
            key={preset.id}
            className="btn-outline"
            onClick={() => {
              if (preset.id === "brazil") {
                applyBrazil();
              } else {
                onClipRegionsChange([]);
                onChange(preset.bbox);
              }
            }}
          >
            <MapPin className="h-3.5 w-3.5" />
            {t(`wizard.area.presets.${preset.id}`)}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-ink-200 p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            {t("wizard.area.brazilRegions")}
          </span>
          <div className="flex gap-3 text-xs">
            <button
              type="button"
              className="text-ocean-600 hover:underline"
              onClick={applyBrazil}
            >
              {t("wizard.area.brazilWhole")}
            </button>
            <button
              type="button"
              className="text-ocean-600 hover:underline"
              onClick={() => applyUfs([...UF_LIST])}
            >
              {t("wizard.area.allUfs")}
            </button>
            <button
              type="button"
              className="text-ink-500 hover:underline"
              onClick={() => onClipRegionsChange([])}
            >
              {t("wizard.area.noClip")}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {UF_LIST.map((uf) => {
            const on = !brSelected && selectedUfs.includes(uf);
            return (
              <button
                key={uf}
                type="button"
                onClick={() => toggleUf(uf)}
                className={
                  on
                    ? "rounded-md bg-ocean-600 px-2.5 py-1 text-xs font-medium text-white"
                    : "rounded-md bg-ink-100 px-2.5 py-1 text-xs font-medium text-ink-600 hover:bg-ink-200"
                }
              >
                {uf}
              </button>
            );
          })}
        </div>
        {brSelected ? (
          <p className="mt-2 text-[11px] text-ocean-600">
            {t("wizard.area.brazilClipNote")}
          </p>
        ) : selectedUfs.length > 0 ? (
          <p className="mt-2 text-[11px] text-ocean-600">
            {t("wizard.area.ufsClipNote", { count: selectedUfs.length })}
          </p>
        ) : (
          <p className="mt-2 text-[11px] text-ink-400">
            {t("wizard.area.noClipNote")}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[
          { key: "wizard.area.north", idx: 0 },
          { key: "wizard.area.west", idx: 1 },
          { key: "wizard.area.south", idx: 2 },
          { key: "wizard.area.east", idx: 3 },
        ].map(({ key, idx }) => (
          <label key={key} className="block">
            <span className="text-xs uppercase tracking-wide text-ink-500">
              {t(key)}
            </span>
            <CoordInput
              value={value[idx]}
              onCommit={(n) => {
                const next = [...value] as [
                  number,
                  number,
                  number,
                  number,
                ];
                next[idx] = n;
                // Manual bbox edit invalidates the polygon clip: the
                // resulting rectangle no longer corresponds to the union
                // of the selected regions.
                if (clipRegions.length > 0) onClipRegionsChange([]);
                onChange(next);
              }}
            />
          </label>
        ))}
      </div>
      <p className="text-xs text-ink-400">{t("wizard.area.bboxOrder")}</p>
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
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">{t("wizard.period.title")}</h2>

      <div className="grid grid-cols-2 gap-4">
        <label>
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {t("wizard.period.startDate")}
          </span>
          <input
            type="date"
            className="input mt-1"
            value={startDate}
            onChange={(e) => onStart(e.target.value)}
          />
        </label>
        <label>
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {t("wizard.period.endDate")}
          </span>
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
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {t("wizard.period.hours")}
          </span>
          <div className="space-x-2 text-xs">
            <button onClick={() => onHours(HOURS_ALL)} className="text-ocean-600 hover:underline">
              {t("wizard.period.hoursAll")}
            </button>
            <button onClick={() => onHours(HOURS_3H)} className="text-ocean-600 hover:underline">
              {t("wizard.period.hours3h")}
            </button>
            <button onClick={() => onHours(HOURS_SYNOPTIC)} className="text-ocean-600 hover:underline">
              {t("wizard.period.hoursSynoptic")}
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
  onNarrow,
}: {
  diff: ReturnType<typeof useMutation<DiffPreview, Error, void, unknown>>;
  applyDiff: boolean;
  onApplyDiffChange: (v: boolean) => void;
  onCompute: () => void;
  onNarrow: (step: Step) => void;
}) {
  const skipped = diff.data?.diff_skipped === true;
  // When the request is too big to diff, the download proceeds via the
  // size-bounded chunk plan regardless; reflect that in the mode flag.
  useEffect(() => {
    if (skipped) onApplyDiffChange(false);
  }, [skipped, onApplyDiffChange]);
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
      ) : diff.data && skipped ? (
        <div className="space-y-4 rounded-xl border border-amber-300 bg-amber-50 p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <h3 className="text-sm font-semibold text-amber-900">
                Requisição grande demais para o diff célula-a-célula
              </h3>
              <p className="mt-1 text-sm text-amber-800">
                Sua seleção expande para{" "}
                <span className="font-semibold tabular-nums">
                  {diff.data.requested_cells.toLocaleString()}
                </span>{" "}
                células (ponto × data × hora × variável). Fazer o diff fino
                disso esgotaria a memória, então ele foi pulado. O download
                será planejado em{" "}
                <span className="font-semibold tabular-nums">
                  {diff.data.estimated_chunks?.toLocaleString() ?? "?"}
                </span>{" "}
                chunks sequenciais independentes — processados um a um, sem
                estourar memória.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <DiffStat
              label="Download TOTAL"
              value={
                diff.data.estimated_download_bytes != null
                  ? formatBytes(diff.data.estimated_download_bytes)
                  : "—"
              }
              sub={
                diff.data.estimated_chunks
                  ? `soma dos ${diff.data.estimated_chunks.toLocaleString()} chunks`
                  : "todos os chunks somados"
              }
              tone="neutral"
            />
            <DiffStat
              label="Em disco TOTAL (≈)"
              value={
                diff.data.estimated_disk_bytes != null
                  ? formatBytes(diff.data.estimated_disk_bytes)
                  : "—"
              }
              sub="após conversão (todos os chunks)"
              tone="neutral"
            />
            <DiffStat
              label="Chunks sequenciais"
              value={diff.data.estimated_chunks?.toLocaleString() ?? "—"}
              sub="baixados em série"
              tone="warn"
            />
          </div>

          <p className="text-xs text-amber-700">
            Os tamanhos acima são o <strong>total somado de todos os
            chunks</strong> (não por chunk).
            {diff.data.estimated_download_bytes != null &&
            diff.data.estimated_chunks
              ? ` Em média ≈ ${formatBytes(
                  diff.data.estimated_download_bytes /
                    diff.data.estimated_chunks,
                )} de download por chunk.`
              : ""}
          </p>

          <p className="text-xs text-amber-700">
            Você pode <strong>prosseguir</strong> (clique em “Next”) e o
            download rodará como esses chunks sequenciais, ou{" "}
            <strong>voltar</strong> e escolher um período/área menor para um
            download mais rápido.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onNarrow(2)}
              className="btn-outline"
            >
              <MapPin className="h-4 w-4" /> Ajustar área
            </button>
            <button
              type="button"
              onClick={() => onNarrow(3)}
              className="btn-outline"
            >
              <ChevronLeft className="h-4 w-4" /> Ajustar período
            </button>
          </div>
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

      {diff.data && !skipped && (
        <div className="space-y-2">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <DiffStat
              label="Será baixado (≈)"
              value={
                diff.data.missing_download_bytes != null
                  ? formatBytes(diff.data.missing_download_bytes)
                  : "—"
              }
              sub="apenas o que falta · transferência CDS"
              tone={diff.data.missing_cells === 0 ? "success" : "warn"}
            />
            <DiffStat
              label="Em disco (≈)"
              value={
                diff.data.missing_disk_bytes != null
                  ? formatBytes(diff.data.missing_disk_bytes)
                  : "—"
              }
              sub="parquet após conversão"
              tone="neutral"
            />
          </div>
          {diff.data.estimated_download_bytes != null && (
            <p className="text-xs text-ink-400">
              Requisição completa:{" "}
              <span className="font-medium text-ink-600">
                {formatBytes(diff.data.estimated_download_bytes)}
              </span>{" "}
              de download ·{" "}
              <span className="font-medium text-ink-600">
                {diff.data.estimated_disk_bytes != null
                  ? formatBytes(diff.data.estimated_disk_bytes)
                  : "—"}
              </span>{" "}
              em disco (caso opte por “baixar tudo”).
            </p>
          )}
        </div>
      )}

      {diff.data && !skipped && diff.data.missing_cells > 0 && (
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

      {diff.data && !skipped && diff.data.missing_cells === 0 && (
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
  clipRegions,
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
  clipRegions: string[];
  estimate: ReturnType<typeof useMutation<any, any, any, any>>;
  run: ReturnType<typeof useMutation<any, any, any, any>>;
  onEstimate: () => void;
  onRun: () => void;
}) {
  const result = estimate.data;
  const clipLabel =
    clipRegions.length === 0
      ? "No clip (raw bbox)"
      : clipRegions.includes("BR")
        ? "Brasil (polygon, half-cell buffer)"
        : `UF(s): ${clipRegions.join(", ")} (half-cell buffer)`;
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">Confirm & start</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <Row label="Dataset" value={dataset} />
        <Row label="Period" value={`${startDate} → ${endDate}`} />
        <Row label="Variables" value={`${variables.length} selected`} />
        <Row label="Hours" value={`${hours.length} of 24`} />
        <Row label="Area" value={`N ${area[0]} · W ${area[1]} · S ${area[2]} · E ${area[3]}`} />
        <Row label="Polygon clip" value={clipLabel} />
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
