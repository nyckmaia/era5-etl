import { useMutation } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Copy,
  Play,
  Plus,
  Sliders,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  api,
  type TSSeriesResult,
  type TSViewMeta,
  type TimeseriesRequest,
} from "@/lib/api";
import { cn } from "@/lib/format";

import { PlotlyChart, STYLE_CYCLE, DEFAULT_STYLE } from "./PlotlyChart";
import { SeriesEditor } from "./SeriesEditor";
import { computeStats, fmtStat } from "./stats";
import { applyTransform, compileTransform } from "./transform";
import { TraceStylePanel } from "./TraceStylePanel";
import type { Bucket, Cell, SeriesCfg } from "./types";
import { newId } from "./types";

interface Props {
  cell: Cell;
  index: number;
  total: number;
  metaViews: TSViewMeta[];
  onChange: (c: Cell) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onMove: (dir: -1 | 1) => void;
}

export function defaultSeries(metaViews: TSViewMeta[]): SeriesCfg {
  const vm =
    metaViews.find((v) => v.view === "era5") ?? metaViews[0] ?? null;
  const station = vm?.location_kind === "station";
  return {
    id: newId(),
    view: vm?.view ?? "",
    yColumn: vm?.numeric_columns[0]?.name ?? "",
    agg: "avg",
    axis: "y",
    location: station
      ? { kind: "point", station_id: null }
      : { kind: "point", lat: null, lon: null },
  };
}

export function ChartCell({
  cell,
  index,
  total,
  metaViews,
  onChange,
  onRemove,
  onDuplicate,
  onMove,
}: Props) {
  const [results, setResults] = useState<TSSeriesResult[] | null>(null);
  const [showStyle, setShowStyle] = useState(false);
  const seededRef = useRef(false);

  // Prefill the date range from the first series' view (full available
  // range, capped to its max) once, when empty.
  useEffect(() => {
    if (seededRef.current || cell.dateFrom || cell.dateTo) return;
    const first = cell.series[0];
    const vm = metaViews.find((v) => v.view === first?.view);
    if (vm?.date_min && vm?.date_max) {
      seededRef.current = true;
      onChange({ ...cell, dateFrom: vm.date_min, dateTo: vm.date_max });
    }
  }, [cell, metaViews, onChange]);

  const runMutation = useMutation({
    mutationFn: () => {
      const body: TimeseriesRequest = {
        date_from: cell.dateFrom,
        date_to: cell.dateTo,
        bucket: cell.bucket,
        max_points: cell.maxPoints,
        series: cell.series.map((s) => ({
          view: s.view,
          y_column: s.yColumn,
          agg: s.agg,
          location: s.location,
          axis: s.axis,
          name: s.name ?? null,
        })),
      };
      return api.timeseries.run(body);
    },
    onSuccess: (resp) => {
      setResults(resp.series);
      // Ensure a style exists for every series id.
      const styles = { ...cell.traceStyles };
      let changed = false;
      cell.series.forEach((s, i) => {
        if (!styles[s.id]) {
          styles[s.id] = {
            ...DEFAULT_STYLE,
            color: STYLE_CYCLE[i % STYLE_CYCLE.length],
          };
          changed = true;
        }
      });
      if (changed) onChange({ ...cell, traceStyles: styles });
      const errs = resp.series.filter((s) => s.error);
      if (errs.length) toast.warning(`${errs.length} série(s) com erro`);
      if (resp.truncated)
        toast.message("Resolução reduzida para caber no limite de pontos");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  function patch(p: Partial<Cell>) {
    onChange({ ...cell, ...p });
  }
  function setSeries(i: number, s: SeriesCfg) {
    const series = [...cell.series];
    series[i] = s;
    patch({ series });
  }

  const canRun =
    cell.series.length > 0 &&
    cell.dateFrom !== "" &&
    cell.dateTo !== "" &&
    cell.series.every((s) => s.view && s.yColumn);

  const seriesIds = cell.series.map((s) => s.id);
  // Visual-only unit conversions, index-aligned to series/results.
  const transformFns = cell.series.map(
    (s) => compileTransform(s.transform).fn,
  );

  // Available coverage of the first series' view — shown next to the date
  // inputs and used to bound them. Explains why a wide range can return a
  // short chart: ERA5/ERA5-LAND/INMET only hold what was downloaded.
  const firstVm = metaViews.find((v) => v.view === cell.series[0]?.view);
  const availMin = firstVm?.date_min ?? undefined;
  const availMax = firstVm?.date_max ?? undefined;

  // Last timestamp actually returned (max across series).
  const lastData = results
    ?.flatMap((r) => (r.x.length ? [r.x[r.x.length - 1]] : []))
    .sort()
    .at(-1);
  const endsEarly =
    lastData && cell.dateTo && lastData.slice(0, 10) < cell.dateTo;

  return (
    <section className="card overflow-hidden">
      {/* Notebook-style header rail */}
      <div className="flex items-center gap-3 border-b border-ink-100 bg-ink-50/60 px-4 py-2">
        <span className="font-mono text-xs text-ocean-700">
          [{String(index + 1).padStart(2, "0")}]
        </span>
        <input
          className="flex-1 bg-transparent text-sm font-medium text-ink-800 outline-none placeholder:text-ink-400"
          value={cell.title}
          placeholder="Gráfico sem título"
          onChange={(e) => patch({ title: e.target.value })}
        />
        <div className="flex items-center gap-1 text-ink-400">
          <IconBtn
            title="Mover para cima"
            disabled={index === 0}
            onClick={() => onMove(-1)}
          >
            <ChevronUp className="h-4 w-4" />
          </IconBtn>
          <IconBtn
            title="Mover para baixo"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
          >
            <ChevronDown className="h-4 w-4" />
          </IconBtn>
          <IconBtn title="Duplicar" onClick={onDuplicate}>
            <Copy className="h-4 w-4" />
          </IconBtn>
          <IconBtn title="Remover" onClick={onRemove}>
            <Trash2 className="h-4 w-4 text-rose-600" />
          </IconBtn>
        </div>
      </div>

      <div className="space-y-4 p-4">
        {/* Range / bucket controls */}
        <div className="flex flex-wrap items-end gap-3">
          <Field label="De">
            <input
              type="date"
              className="input w-40"
              min={availMin}
              max={availMax}
              value={cell.dateFrom}
              onChange={(e) => patch({ dateFrom: e.target.value })}
            />
          </Field>
          <Field label="Até">
            <input
              type="date"
              className="input w-40"
              min={availMin}
              max={availMax}
              value={cell.dateTo}
              onChange={(e) => patch({ dateTo: e.target.value })}
            />
          </Field>
          <Field label="Resolução temporal">
            <select
              className="input w-56"
              value={cell.bucket}
              title={
                "Como agregar os valores no tempo antes de plotar. " +
                "Reduz o nº de pontos e suaviza a curva."
              }
              onChange={(e) =>
                patch({ bucket: e.target.value as Bucket })
              }
            >
              <option value="raw">raw — todos os pontos (sem agregar)</option>
              <option value="hour">hour — média por hora</option>
              <option value="day">day — média por dia</option>
              <option value="month">month — média por mês</option>
            </select>
          </Field>
          <Field label="Máx. pontos">
            <input
              type="number"
              min={100}
              max={200000}
              step={100}
              className="input w-28"
              title={
                "Limite de pontos por série. Se exceder, a resolução é " +
                "reduzida automaticamente (raw→hour→day→month)."
              }
              value={cell.maxPoints}
              onChange={(e) =>
                patch({ maxPoints: Number(e.target.value) || 20000 })
              }
            />
          </Field>
          <button
            type="button"
            className="btn-primary"
            disabled={!canRun || runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            <Play className="h-4 w-4" />
            {runMutation.isPending ? "Gerando…" : "Gerar"}
          </button>
          <button
            type="button"
            className="btn-outline"
            onClick={() => setShowStyle((v) => !v)}
          >
            <Sliders className="h-4 w-4" />
            Estilo
          </button>
        </div>

        {(availMin || availMax) && (
          <p className="-mt-2 text-xs text-ink-400">
            Dados disponíveis para{" "}
            <span className="font-medium text-ink-600">
              {cell.series[0]?.view?.toUpperCase()}
            </span>
            : {availMin ?? "?"} – {availMax ?? "?"}. Datas fora dessa faixa
            não têm dados.
          </p>
        )}

        {/* Series */}
        <div className="space-y-2">
          {cell.series.map((s, i) => (
            <SeriesEditor
              key={s.id}
              index={i}
              metaViews={metaViews}
              series={s}
              swatch={
                (cell.traceStyles[s.id] ?? {
                  color: STYLE_CYCLE[i % STYLE_CYCLE.length],
                }).color
              }
              onChange={(ns) => setSeries(i, ns)}
              onRemove={() =>
                patch({
                  series: cell.series.filter((_, j) => j !== i),
                })
              }
            />
          ))}
          <button
            type="button"
            className="btn-ghost text-sm text-ocean-700"
            onClick={() =>
              patch({ series: [...cell.series, defaultSeries(metaViews)] })
            }
          >
            <Plus className="h-4 w-4" />
            Adicionar série
          </button>
        </div>

        {showStyle && (
          <div className="rounded-xl border border-ink-100 bg-ink-50/40 p-3">
            <TraceStylePanel
              series={cell.series}
              styles={cell.traceStyles}
              onStyle={(id, st) =>
                patch({
                  traceStyles: { ...cell.traceStyles, [id]: st },
                })
              }
              layout={cell.layout}
              onLayout={(l) => patch({ layout: l })}
            />
          </div>
        )}

        {/* Chart */}
        {results ? (
          <>
            <PlotlyChart
              seriesId={seriesIds}
              results={results}
              styles={cell.traceStyles}
              layout={cell.layout}
              showMean={cell.series.map((s) => !!s.showMean)}
              transformFns={transformFns}
            />

            {/* Per-series descriptive statistics */}
            <div className="space-y-1.5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Estatísticas
              </h4>
              {results.map((r, i) =>
                r.error || r.x.length === 0 ? null : (
                  <StatsRow
                    key={seriesIds[i] ?? i}
                    name={r.name}
                    color={
                      (cell.traceStyles[seriesIds[i]] ?? {
                        color: STYLE_CYCLE[i % STYLE_CYCLE.length],
                      }).color
                    }
                    y={applyTransform(
                      r.y,
                      transformFns[i] ?? ((v: number) => v),
                    )}
                    showMean={!!cell.series[i]?.showMean}
                    onToggleMean={(v) =>
                      cell.series[i] &&
                      setSeries(i, { ...cell.series[i], showMean: v })
                    }
                  />
                ),
              )}
            </div>
            {results.some((r) => r.error || r.downsampled) && (
              <div className="space-y-1 text-xs">
                {results
                  .filter((r) => r.downsampled)
                  .map((r, i) => (
                    <p key={`d${i}`} className="text-amber-700">
                      {r.name}: resolução reduzida para “{r.bucket_used}”
                      ({r.n_points} pts).
                    </p>
                  ))}
                {results
                  .filter((r) => r.error)
                  .map((r, i) => (
                    <p key={`e${i}`} className="text-rose-700">
                      {r.name}: {r.error}
                    </p>
                  ))}
              </div>
            )}
            {endsEarly && (
              <p className="text-xs text-amber-700">
                Os dados terminam em {lastData?.slice(0, 16).replace("T", " ")}{" "}
                (você pediu até {cell.dateTo}). O gráfico mostra tudo que
                está baixado — baixe mais período na página Download para
                estender.
              </p>
            )}
          </>
        ) : (
          <div className="flex h-[200px] items-center justify-center rounded-xl border border-dashed border-ink-200 text-sm text-ink-400">
            Configure as séries e clique em “Gerar”.
          </div>
        )}
      </div>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wide text-ink-500">
        {label}
      </span>
      <div className="mt-0.5">{children}</div>
    </label>
  );
}

function IconBtn({
  children,
  title,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  title: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md p-1.5 transition-colors hover:bg-ink-100 hover:text-ink-700",
        disabled && "cursor-not-allowed opacity-30 hover:bg-transparent",
      )}
    >
      {children}
    </button>
  );
}

function StatsRow({
  name,
  color,
  y,
  showMean,
  onToggleMean,
}: {
  name: string;
  color: string;
  y: (number | null)[];
  showMean: boolean;
  onToggleMean: (v: boolean) => void;
}) {
  const s = computeStats(y);
  const items: [string, number | null][] = [
    ["mín", s.min],
    ["máx", s.max],
    ["média", s.mean],
    ["desv.pad", s.std],
    ["variância", s.variance],
    ["IQR", s.iqr],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-ink-100 bg-white px-3 py-2 text-xs">
      <span className="flex items-center gap-1.5 font-medium text-ink-700">
        <span
          className="h-2.5 w-2.5 rounded-full ring-1 ring-ink-300"
          style={{ background: color }}
        />
        {name}
      </span>
      <span className="text-ink-400">n={s.count}</span>
      {items.map(([k, v]) => (
        <span key={k} className="tabular-nums text-ink-600">
          <span className="text-ink-400">{k}</span>{" "}
          <span className="font-medium text-ink-800">{fmtStat(v)}</span>
        </span>
      ))}
      <label
        className="ml-auto flex cursor-pointer items-center gap-1.5 text-ink-600"
        title="Mostrar a média como uma linha horizontal tracejada da cor da série"
      >
        <input
          type="checkbox"
          checked={showMean}
          onChange={(e) => onToggleMean(e.target.checked)}
        />
        linha da média
      </label>
    </div>
  );
}
