import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Loader2, MapPin } from "lucide-react";
import { useMemo, useState } from "react";

import { CellDetailPanel } from "@/components/inventory/CellDetailPanel";
import {
  InventoryMap,
  type SelectionMode,
} from "@/components/inventory/InventoryMap";
import { RegionSummaryPanel } from "@/components/inventory/RegionSummaryPanel";
import { SelectionToolbar } from "@/components/inventory/SelectionToolbar";
import { api, type DatasetInfo, type GridPoint } from "@/lib/api";
import { cn, formatBytes } from "@/lib/format";

export function InventoryPage() {
  const navigate = useNavigate();
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  const [dataset, setDataset] = useState<string>("");
  const [variableFilter, setVariableFilter] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [colormap, setColormap] = useState<"binary" | "intensity">("intensity");
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("none");
  const [selection, setSelection] = useState<[number, number][] | null>(null);
  const [activeCell, setActiveCell] = useState<{ lat: number; lon: number } | null>(
    null,
  );

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

  const pointsQ = useQuery({
    queryKey: ["inventory-grid-points", dataset, dateFrom, dateTo, variableFilter],
    queryFn: () =>
      api.inventory.gridPoints({
        dataset,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        variable: variableFilter || undefined,
        format: "auto",
      }),
    enabled: Boolean(dataset),
  });

  const { data: stats } = useQuery({
    queryKey: ["stats", dataset],
    queryFn: () => api.stats(dataset),
    enabled: Boolean(dataset),
  });

  const points: GridPoint[] = pointsQ.data ?? [];
  const totalVars = activeDataset?.variables.length ?? 1;

  function fillGaps(bbox: [number, number, number, number]) {
    // Hand off to the download wizard with the bbox pre-filled via URL state.
    // The wizard reads `area` from query params; if absent it uses defaults.
    const params = new URLSearchParams({
      dataset,
      area: bbox.join(","),
    });
    navigate({ to: "/download", search: { prefill: params.toString() } as never });
  }

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
            Inventário
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            Visualize quais pontos da grade já foram baixados, com quais
            variáveis e em quais datas e horas.
          </p>
        </div>
        <select
          value={dataset}
          onChange={(e) => setDataset(e.target.value)}
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
        <Field label="De">
          <input
            type="date"
            className="input"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </Field>
        <Field label="Até">
          <input
            type="date"
            className="input"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </Field>
        <Field label="Variável">
          <select
            className="input"
            value={variableFilter}
            onChange={(e) => setVariableFilter(e.target.value)}
          >
            <option value="">Todas</option>
            {activeDataset?.variables.map((v) => (
              <option key={v.api_name} value={v.api_name}>
                {v.full_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Cor">
          <div className="flex gap-1 rounded-lg bg-ink-100 p-0.5">
            {(["intensity", "binary"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setColormap(m)}
                className={cn(
                  "rounded-md px-2 py-1 text-xs font-medium",
                  colormap === m ? "bg-white text-ink-800 shadow-sm" : "text-ink-500",
                )}
              >
                {m === "intensity" ? "Intensidade" : "Binário"}
              </button>
            ))}
          </div>
        </Field>
        {(dateFrom || dateTo || variableFilter) && (
          <button
            onClick={() => {
              setDateFrom("");
              setDateTo("");
              setVariableFilter("");
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
            selectionMode={selectionMode}
            selection={selection}
            onSelectionChange={setSelection}
            onCellClick={(lat, lon) => {
              setActiveCell({ lat, lon });
              setSelection(null);
            }}
            colormap={colormap}
            totalVars={totalVars}
          />
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
          {pointsQ.isLoading ? (
            <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-full bg-white/95 px-3 py-1 text-xs shadow ring-1 ring-ink-200">
              <Loader2 className="h-3 w-3 animate-spin" />
              Carregando pontos...
            </div>
          ) : null}
          {!pointsQ.isLoading && points.length === 0 ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  Nenhum dado baixado para {dataset || "este dataset"}.
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Use a página Download para começar.
                </p>
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          {selection && selection.length >= 3 ? (
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
          <Pill label="Pontos" value={points.length.toLocaleString()} />
          <Pill label="Dataset" value={dataset || "—"} />
          {stats ? (
            <>
              <Pill label="Arquivos" value={stats.parquet_files.toString()} />
              <Pill label="Tamanho" value={formatBytes(stats.total_size_bytes)} />
              <Pill label="Chunks" value={stats.manifest_chunks.toString()} />
            </>
          ) : null}
        </div>
        {pointsQ.data && pointsQ.data.length >= 5000 ? (
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
