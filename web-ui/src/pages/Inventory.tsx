import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronDown, Loader2, MapPin } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { CellDetailPanel } from "@/components/inventory/CellDetailPanel";
import {
  InventoryMap,
  type SelectionMode,
} from "@/components/inventory/InventoryMap";
import { RegionSummaryPanel } from "@/components/inventory/RegionSummaryPanel";
import { SelectionToolbar } from "@/components/inventory/SelectionToolbar";
import {
  api,
  type DatasetInfo,
  type GridPoint,
  type StationPoint,
} from "@/lib/api";
import { cn, formatBytes } from "@/lib/format";
import { useLocalStorage } from "@/hooks/useLocalStorage";

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const fmtHour = (h: number) => `${String(h).padStart(2, "0")}:00`;

export function InventoryPage() {
  const navigate = useNavigate();
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  const [dataset, setDataset] = useState<string>("");
  const [variableFilter, setVariableFilter] = useState<string[]>([]);
  const [hourFilter, setHourFilter] = useState<number[]>(HOURS);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const userEditedDates = useRef(false);
  const seededVarsFor = useRef<string>("");
  const [varMenuOpen, setVarMenuOpen] = useState(false);
  const [hourMenuOpen, setHourMenuOpen] = useState(false);
  const varMenuRef = useRef<HTMLDivElement | null>(null);
  const hourMenuRef = useRef<HTMLDivElement | null>(null);
  const [pointColor, setPointColor] = useLocalStorage<string>(
    "inventory.pointColor",
    "#2864c8",
  );
  const [pointOpacity, setPointOpacity] = useLocalStorage<number>(
    "inventory.pointOpacity",
    85,
  );
  const [showPoints, setShowPoints] = useLocalStorage<boolean>(
    "inventory.showPoints",
    true,
  );
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("none");
  const [selection, setSelection] = useState<[number, number][] | null>(null);
  const [activeCell, setActiveCell] = useState<{ lat: number; lon: number } | null>(
    null,
  );
  const [activeStation, setActiveStation] = useState<StationPoint | null>(null);

  // Default to user's preferred dataset on first load.
  useMemo(() => {
    if (!dataset && datasets && datasets.length > 0) {
      setDataset(datasets[0].name);
    }
  }, [dataset, datasets]);

  const activeDataset: DatasetInfo | undefined = useMemo(
    () => datasets?.find((d) => d.name === dataset),
    [datasets, dataset],
  );

  // Station sources (e.g. INMET) have no regular grid: no variable/hour/
  // date coverage filters, no polygon region summary. They render as
  // station points from /api/inventory/stations instead of /grid-points.
  const stationMode = activeDataset ? activeDataset.is_gridded === false : false;

  // M1: variables start ALL-checked ("checked = visible"). Seed once per
  // dataset, when its variable list is known.
  useEffect(() => {
    if (!activeDataset) return;
    if (seededVarsFor.current === activeDataset.name) return;
    seededVarsFor.current = activeDataset.name;
    setVariableFilter(activeDataset.variables.map((v) => v.api_name));
  }, [activeDataset]);

  const dateRangeQ = useQuery({
    queryKey: ["inventory-date-range", dataset],
    queryFn: () => api.inventory.dateRange(dataset),
    enabled: Boolean(dataset),
  });

  // Prefill the date inputs with the dataset's min/max once the range
  // resolves, unless the user has manually edited the inputs.
  useEffect(() => {
    if (userEditedDates.current) return;
    const r = dateRangeQ.data;
    if (!r) return;
    setDateFrom(r.min ?? "");
    setDateTo(r.max ?? "");
  }, [dateRangeQ.data]);

  // Close the variable popover when clicking outside of it.
  useEffect(() => {
    if (!varMenuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (varMenuRef.current && !varMenuRef.current.contains(e.target as Node)) {
        setVarMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [varMenuOpen]);

  useEffect(() => {
    if (!hourMenuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (hourMenuRef.current && !hourMenuRef.current.contains(e.target as Node)) {
        setHourMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [hourMenuOpen]);

  function changeDataset(next: string) {
    setDataset(next);
    // New dataset → reset date/hour filters; variables re-seed via the
    // effect once the new dataset's variable list resolves.
    userEditedDates.current = false;
    seededVarsFor.current = "";
    setDateFrom("");
    setDateTo("");
    setVariableFilter([]);
    setHourFilter(HOURS);
    setActiveStation(null);
    setActiveCell(null);
    setSelection(null);
  }

  const allVarNames = useMemo(
    () => activeDataset?.variables.map((v) => v.api_name) ?? [],
    [activeDataset],
  );
  const varsAllSelected =
    allVarNames.length > 0 && variableFilter.length === allVarNames.length;
  const varsNoneSelected = variableFilter.length === 0;
  const hoursAllSelected = hourFilter.length === HOURS.length;
  const hoursNoneSelected = hourFilter.length === 0;
  const emptySelection = varsNoneSelected || hoursNoneSelected;

  const pointsQ = useQuery({
    queryKey: [
      "inventory-grid-points",
      dataset,
      dateFrom,
      dateTo,
      variableFilter,
      hourFilter,
    ],
    queryFn: () =>
      api.inventory.gridPoints({
        dataset,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        variable: varsAllSelected ? undefined : variableFilter,
        hour: hoursAllSelected ? undefined : hourFilter,
        format: "auto",
      }),
    enabled: Boolean(dataset) && !stationMode && !emptySelection,
  });

  const stationsQ = useQuery({
    queryKey: ["inventory-stations", dataset],
    queryFn: () => api.inventory.stations(dataset),
    enabled: Boolean(dataset) && stationMode,
  });

  const { data: stats } = useQuery({
    queryKey: ["stats", dataset],
    queryFn: () => api.stats(dataset),
    enabled: Boolean(dataset),
  });

  // In station mode the StationPoints (lat/lon may be null) are projected
  // onto the shared GridPoint shape: `days` carries n_years, `vars`
  // carries n_vars (the map/tooltip switch wording via kind="station").
  const stationByKey = useMemo(() => {
    const m = new Map<string, StationPoint>();
    if (stationMode) {
      for (const s of stationsQ.data?.stations ?? []) {
        if (s.latitude == null || s.longitude == null) continue;
        m.set(`${s.latitude},${s.longitude}`, s);
      }
    }
    return m;
  }, [stationMode, stationsQ.data]);

  const points: GridPoint[] = useMemo(() => {
    if (stationMode) {
      return (stationsQ.data?.stations ?? [])
        .filter((s) => s.latitude != null && s.longitude != null)
        .map((s) => ({
          lat: s.latitude as number,
          lon: s.longitude as number,
          days: s.n_years,
          vars: s.n_vars,
        }));
    }
    return emptySelection ? [] : pointsQ.data ?? [];
  }, [stationMode, stationsQ.data, emptySelection, pointsQ.data]);

  const dataLoading = stationMode ? stationsQ.isLoading : pointsQ.isLoading;

  function fillGaps(_bbox: [number, number, number, number]) {
    // Hand off to the download wizard with the dataset preselected. The
    // wizard jumps to the Variables step when a dataset is passed.
    navigate({ to: "/download", search: { dataset, step: 1 } });
  }

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
            Inventário
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {stationMode
              ? "Visualize as estações meteorológicas disponíveis; clique em uma para ver seus detalhes."
              : "Visualize quais pontos da grade já foram baixados, com quais variáveis e em quais datas e horas."}
          </p>
        </div>
        <select
          value={dataset}
          onChange={(e) => changeDataset(e.target.value)}
          className="input"
        >
          {datasets?.map((d) => (
            <option key={d.name} value={d.name}>
              {d.name.toUpperCase()}
            </option>
          ))}
        </select>
      </header>

      <div className="card flex flex-wrap items-end gap-4 p-4">
        {!stationMode && (
          <>
        <Field label="De">
          <input
            type="date"
            className="input"
            value={dateFrom}
            onChange={(e) => {
              userEditedDates.current = true;
              setDateFrom(e.target.value);
            }}
          />
        </Field>
        <Field label="Até">
          <input
            type="date"
            className="input"
            value={dateTo}
            onChange={(e) => {
              userEditedDates.current = true;
              setDateTo(e.target.value);
            }}
          />
        </Field>
        <Field label="Variáveis">
          <div className="relative" ref={varMenuRef}>
            <button
              type="button"
              onClick={() => setVarMenuOpen((o) => !o)}
              className="input flex min-w-[12rem] items-center justify-between gap-2 text-left"
            >
              <span className="truncate">
                {varsAllSelected
                  ? "Todas"
                  : varsNoneSelected
                    ? "Nenhuma"
                    : `${variableFilter.length} selecionada(s)`}
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" />
            </button>
            {varMenuOpen ? (
              <div className="absolute left-0 z-20 mt-1 max-h-72 w-72 overflow-y-auto rounded-xl border border-ink-200 bg-white p-2 shadow-elevated">
                <button
                  type="button"
                  onClick={() =>
                    setVariableFilter(varsAllSelected ? [] : allVarNames)
                  }
                  className="mb-1 w-full rounded-md px-2 py-1 text-left text-xs text-ocean-600 hover:bg-ink-50"
                >
                  {varsAllSelected ? "Desmarcar todas" : "Marcar todas"}
                </button>
                {activeDataset?.variables.map((v) => {
                  const checked = variableFilter.includes(v.api_name);
                  return (
                    <label
                      key={v.api_name}
                      className={cn(
                        "flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-ink-50",
                        checked && "bg-ocean-50/60",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={checked}
                        onChange={() =>
                          setVariableFilter((prev) =>
                            prev.includes(v.api_name)
                              ? prev.filter((x) => x !== v.api_name)
                              : [...prev, v.api_name],
                          )
                        }
                      />
                      <span className="flex-1">
                        <span className="block text-ink-800">{v.full_name}</span>
                        <span className="block text-[11px] text-ink-400">
                          {v.api_name}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : null}
          </div>
        </Field>
        <Field label="Horas">
          <div className="relative" ref={hourMenuRef}>
            <button
              type="button"
              onClick={() => setHourMenuOpen((o) => !o)}
              className="input flex min-w-[10rem] items-center justify-between gap-2 text-left"
            >
              <span className="truncate">
                {hoursAllSelected
                  ? "Todas"
                  : hoursNoneSelected
                    ? "Nenhuma"
                    : `${hourFilter.length} selecionada(s)`}
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" />
            </button>
            {hourMenuOpen ? (
              <div className="absolute left-0 z-20 mt-1 max-h-72 w-56 overflow-y-auto rounded-xl border border-ink-200 bg-white p-2 shadow-elevated">
                <button
                  type="button"
                  onClick={() => setHourFilter(hoursAllSelected ? [] : HOURS)}
                  className="mb-1 w-full rounded-md px-2 py-1 text-left text-xs text-ocean-600 hover:bg-ink-50"
                >
                  {hoursAllSelected ? "Desmarcar todas" : "Marcar todas"}
                </button>
                {HOURS.map((h) => {
                  const checked = hourFilter.includes(h);
                  return (
                    <label
                      key={h}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-ink-50",
                        checked && "bg-ocean-50/60",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setHourFilter((prev) =>
                            prev.includes(h)
                              ? prev.filter((x) => x !== h)
                              : [...prev, h],
                          )
                        }
                      />
                      <span className="text-ink-800">{fmtHour(h)} UTC</span>
                    </label>
                  );
                })}
              </div>
            ) : null}
          </div>
        </Field>
          </>
        )}
        <Field label="Pontos">
          <label className="input flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={showPoints}
              onChange={(e) => setShowPoints(e.target.checked)}
            />
            <span className="text-sm text-ink-700">Mostrar</span>
          </label>
        </Field>
        <Field label="Opacidade">
          <div className="input flex items-center gap-2">
            <input
              type="range"
              min={0}
              max={100}
              value={pointOpacity}
              onChange={(e) => setPointOpacity(Number(e.target.value))}
              className="w-28 accent-ocean-600"
            />
            <span className="w-9 text-right text-xs tabular-nums text-ink-600">
              {pointOpacity}%
            </span>
          </div>
        </Field>
        <Field label="Cor">
          <input
            type="color"
            value={pointColor}
            onChange={(e) => setPointColor(e.target.value)}
            className="h-9 w-12 cursor-pointer rounded-lg border border-ink-200 bg-white p-1"
            aria-label="Cor dos pontos"
          />
        </Field>
        {!stationMode &&
          (dateFrom || dateTo || !varsAllSelected || !hoursAllSelected) && (
          <button
            onClick={() => {
              userEditedDates.current = false;
              setDateFrom(dateRangeQ.data?.min ?? "");
              setDateTo(dateRangeQ.data?.max ?? "");
              setVariableFilter(allVarNames);
              setHourFilter(HOURS);
            }}
            className="text-xs text-ocean-600 hover:underline"
          >
            Limpar filtros
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="relative h-[560px]">
          <InventoryMap
            points={points}
            kind={stationMode ? "station" : "grid"}
            selectionMode={stationMode ? "none" : selectionMode}
            selection={selection}
            onSelectionChange={setSelection}
            onCellClick={(lat, lon) => {
              if (stationMode) {
                const s = stationByKey.get(`${lat},${lon}`) ?? null;
                setActiveStation(s);
                return;
              }
              setActiveCell({ lat, lon });
              setSelection(null);
            }}
            pointColor={pointColor}
            pointOpacity={pointOpacity}
            showPoints={showPoints}
          />
          {!stationMode && (
            <SelectionToolbar
              mode={selectionMode}
              onChange={(m) => {
                setSelectionMode(m);
                if (m !== "none") setActiveCell(null);
              }}
              onReset={() => {
                setSelection(null);
                setActiveCell(null);
              }}
            />
          )}
          {dataLoading ? (
            <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-full bg-white/95 px-3 py-1 text-xs shadow ring-1 ring-ink-200">
              <Loader2 className="h-3 w-3 animate-spin" />
              {stationMode ? "Carregando estações..." : "Carregando pontos..."}
            </div>
          ) : null}
          {!stationMode && emptySelection ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  Nenhuma variável ou hora selecionada.
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Marque ao menos uma variável e uma hora.
                </p>
              </div>
            </div>
          ) : !dataLoading && points.length === 0 ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  {stationMode
                    ? `Nenhuma estação para ${dataset || "este dataset"}.`
                    : `Nenhum dado baixado para ${dataset || "este dataset"}.`}
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Use a página Download para começar.
                </p>
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          {stationMode ? (
            activeStation ? (
              <StationDetailPanel station={activeStation} />
            ) : (
              <div className="card flex h-full flex-col items-center justify-center p-6 text-center text-sm text-ink-400">
                <MapPin className="mb-2 h-5 w-5" />
                <p>Clique em uma estação para ver seus detalhes.</p>
              </div>
            )
          ) : selection && selection.length >= 3 ? (
            <RegionSummaryPanel
              dataset={dataset}
              polygon={selection}
              onFillGapsClick={fillGaps}
            />
          ) : activeCell ? (
            <CellDetailPanel
              dataset={dataset}
              lat={activeCell.lat}
              lon={activeCell.lon}
            />
          ) : (
            <div className="card flex h-full flex-col items-center justify-center p-6 text-center text-sm text-ink-400">
              <MapPin className="mb-2 h-5 w-5" />
              <p>
                Clique em um ponto para ver detalhes ou use o toolbar para
                selecionar uma região.
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="card flex flex-wrap items-center justify-between gap-4 p-4 text-xs text-ink-500">
        <div className="flex flex-wrap items-center gap-4">
          <Pill
            label={stationMode ? "Estações" : "Pontos"}
            value={points.length.toLocaleString()}
          />
          <Pill label="Dataset" value={dataset || "—"} />
          {stats ? (
            <>
              <Pill label="Arquivos" value={stats.parquet_files.toString()} />
              <Pill label="Tamanho" value={formatBytes(stats.total_size_bytes)} />
              {!stationMode && (
                <Pill label="Chunks" value={stats.manifest_chunks.toString()} />
              )}
            </>
          ) : null}
        </div>
        {!stationMode && pointsQ.data && pointsQ.data.length >= 5000 ? (
          <span className="text-[11px] text-ink-400">
            Carregado via Apache Arrow (payload binário)
          </span>
        ) : null}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wide text-ink-500">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function StationDetailPanel({ station }: { station: StationPoint }) {
  const rows: [string, string][] = [
    ["Código (WMO)", station.station_id],
    ["Nome", station.nome ?? "—"],
    ["UF", station.uf ?? "—"],
    ["Região", station.regiao ?? "—"],
    [
      "Coordenadas",
      station.latitude != null && station.longitude != null
        ? `${station.latitude.toFixed(5)}, ${station.longitude.toFixed(5)}`
        : "—",
    ],
    [
      "Altitude",
      station.altitude != null ? `${station.altitude.toFixed(2)} m` : "—",
    ],
    [
      "Anos",
      station.year_min != null && station.year_max != null
        ? `${station.year_min}–${station.year_max} (${station.n_years})`
        : String(station.n_years),
    ],
    ["Variáveis", String(station.n_vars)],
  ];
  return (
    <div className="card p-4">
      <h3 className="text-sm font-semibold text-ink-800">
        Estação {station.station_id}
      </h3>
      <dl className="mt-3 space-y-1.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 text-sm">
            <dt className="text-ink-500">{k}</dt>
            <dd className="text-right font-medium text-ink-800">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Pill({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-full bg-ink-50 px-3 py-1">
      <span className="text-[10px] uppercase tracking-wide text-ink-400">
        {label}{" "}
      </span>
      <span className="font-medium text-ink-800">{value}</span>
    </span>
  );
}
