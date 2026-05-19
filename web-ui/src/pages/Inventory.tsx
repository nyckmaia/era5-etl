import { useQueries, useQuery } from "@tanstack/react-query";
import { Loader2, MapPin } from "lucide-react";
import { useMemo, useState } from "react";

import { CellDetailPanel } from "@/components/inventory/CellDetailPanel";
import {
  InventoryMap,
  MARKER_SHAPES,
  type MapLayerData,
  type MarkerShape,
} from "@/components/inventory/InventoryMap";
import {
  api,
  type GridPoint,
  type StationInventory,
  type StationPoint,
} from "@/lib/api";
import { cn } from "@/lib/format";
import { useLocalStorage } from "@/hooks/useLocalStorage";

interface LayerCfg {
  enabled: boolean;
  color: string;
  sizeMul: number; // 0.25 .. 4
  opacity: number; // 0 .. 100
  shape: MarkerShape;
}

const DEFAULT_COLORS: Record<string, string> = {
  era5: "#2864c8",
  "era5-land": "#1f9d55",
  inmet: "#e8730c",
};
const DEFAULT_SHAPES: Record<string, MarkerShape> = {
  era5: "circle",
  "era5-land": "square",
  inmet: "star",
};
const FALLBACK_PALETTE = [
  "#2864c8",
  "#1f9d55",
  "#e8730c",
  "#9333ea",
  "#dc2626",
];
const SHAPE_LABELS: Record<MarkerShape, string> = {
  circle: "Círculo",
  square: "Quadrado",
  triangle: "Triângulo",
  diamond: "Losango",
  star: "Estrela",
  cross: "Cruz",
};

function defaultCfg(name: string, index: number): LayerCfg {
  return {
    enabled: true,
    color:
      DEFAULT_COLORS[name] ??
      FALLBACK_PALETTE[index % FALLBACK_PALETTE.length],
    sizeMul: 1,
    opacity: 80,
    shape:
      DEFAULT_SHAPES[name] ??
      MARKER_SHAPES[index % MARKER_SHAPES.length],
  };
}

type ActivePoint = {
  datasetId: string;
  kind: "grid" | "station";
  lat: number;
  lon: number;
} | null;

export function InventoryPage() {
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  // v2: added per-system marker `shape`. New key so older stored configs
  // (without shape) don't yield an undefined marker.
  const [cfgMap, setCfgMap] = useLocalStorage<Record<string, LayerCfg>>(
    "inventory.layers.v2",
    {},
  );
  const [active, setActive] = useState<ActivePoint>(null);

  const list = useMemo(() => datasets ?? [], [datasets]);

  const cfgFor = (name: string, idx: number): LayerCfg =>
    cfgMap[name] ?? defaultCfg(name, idx);

  function patchCfg(name: string, idx: number, patch: Partial<LayerCfg>) {
    setCfgMap({
      ...cfgMap,
      [name]: { ...cfgFor(name, idx), ...patch },
    });
  }

  // One query per system. Disabled systems don't fetch. Grid datasets use
  // /grid-points (all cells, no filters); station datasets use /stations.
  const results = useQueries({
    queries: list.map((d, idx) => ({
      queryKey: ["inv-layer", d.name, d.is_gridded],
      enabled: cfgFor(d.name, idx).enabled,
      queryFn: () =>
        d.is_gridded
          ? api.inventory.gridPoints({ dataset: d.name, format: "auto" })
          : api.inventory.stations(d.name),
    })),
  });

  const layerInfos = useMemo(() => {
    return list.map((d, idx) => {
      const cfg = cfgFor(d.name, idx);
      const kind: "grid" | "station" = d.is_gridded ? "grid" : "station";
      const res = results[idx];
      let points: GridPoint[] = [];
      let stations: StationPoint[] = [];
      if (kind === "grid") {
        points = (res?.data as GridPoint[] | undefined) ?? [];
      } else {
        stations = (res?.data as StationInventory | undefined)?.stations ?? [];
        points = stations
          .filter((s) => s.latitude != null && s.longitude != null)
          .map((s) => ({
            lat: s.latitude as number,
            lon: s.longitude as number,
            days: s.n_years,
            vars: s.n_vars,
          }));
      }
      return {
        name: d.name,
        label: d.name.toUpperCase(),
        kind,
        cfg,
        idx,
        points,
        stations,
        loading: cfg.enabled && (res?.isLoading ?? false),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, results, cfgMap]);

  const mapLayers: MapLayerData[] = layerInfos.map((li) => ({
    id: li.name,
    label: li.label,
    kind: li.kind,
    points: li.points,
    color: li.cfg.color,
    opacity: li.cfg.opacity,
    sizeMul: li.cfg.sizeMul,
    shape: li.cfg.shape,
    visible: li.cfg.enabled,
  }));

  const anyLoading = layerInfos.some((li) => li.loading);
  const totalVisible = layerInfos
    .filter((li) => li.cfg.enabled)
    .reduce((n, li) => n + li.points.length, 0);

  const activeStation: StationPoint | null = useMemo(() => {
    if (!active || active.kind !== "station") return null;
    const li = layerInfos.find((x) => x.name === active.datasetId);
    return (
      li?.stations.find(
        (s) =>
          s.latitude === active.lat && s.longitude === active.lon,
      ) ?? null
    );
  }, [active, layerInfos]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
          Inventário
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Sobreponha os pontos de cobertura de cada sistema (ERA5,
          ERA5-LAND, INMET). Ajuste cor, tamanho e opacidade por sistema;
          clique em um ponto para ver detalhes.
        </p>
      </header>

      {/* Per-system layer controls */}
      <div className="card space-y-3 p-4">
        {layerInfos.length === 0 ? (
          <p className="text-sm text-ink-400">Carregando sistemas…</p>
        ) : (
          layerInfos.map((li) => (
            <div
              key={li.name}
              className="flex flex-wrap items-center gap-x-5 gap-y-2"
            >
              <label className="flex w-40 cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={li.cfg.enabled}
                  onChange={(e) =>
                    patchCfg(li.name, li.idx, { enabled: e.target.checked })
                  }
                />
                <span className="font-medium text-ink-800">{li.label}</span>
                <span className="text-[10px] uppercase tracking-wide text-ink-400">
                  {li.kind === "station" ? "estações" : "grade"}
                </span>
              </label>

              <label className="flex items-center gap-2 text-xs text-ink-500">
                Cor
                <input
                  type="color"
                  value={li.cfg.color}
                  onChange={(e) =>
                    patchCfg(li.name, li.idx, { color: e.target.value })
                  }
                  className="h-8 w-10 cursor-pointer rounded-lg border border-ink-200 bg-white p-1"
                  aria-label={`Cor de ${li.label}`}
                />
              </label>

              <label className="flex items-center gap-2 text-xs text-ink-500">
                Marcador
                <select
                  value={li.cfg.shape}
                  onChange={(e) =>
                    patchCfg(li.name, li.idx, {
                      shape: e.target.value as MarkerShape,
                    })
                  }
                  className="input h-8 py-0 text-sm"
                  aria-label={`Marcador de ${li.label}`}
                >
                  {MARKER_SHAPES.map((s) => (
                    <option key={s} value={s}>
                      {SHAPE_LABELS[s]}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-2 text-xs text-ink-500">
                Tamanho
                <input
                  type="range"
                  min={0.25}
                  max={4}
                  step={0.25}
                  value={li.cfg.sizeMul}
                  onChange={(e) =>
                    patchCfg(li.name, li.idx, {
                      sizeMul: Number(e.target.value),
                    })
                  }
                  className="w-28 accent-ocean-600"
                  disabled={!li.cfg.enabled}
                />
                <span className="w-9 text-right tabular-nums text-ink-600">
                  {li.cfg.sizeMul}×
                </span>
              </label>

              <label className="flex items-center gap-2 text-xs text-ink-500">
                Opacidade
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={li.cfg.opacity}
                  onChange={(e) =>
                    patchCfg(li.name, li.idx, {
                      opacity: Number(e.target.value),
                    })
                  }
                  className="w-24 accent-ocean-600"
                  disabled={!li.cfg.enabled}
                />
                <span className="w-9 text-right tabular-nums text-ink-600">
                  {li.cfg.opacity}%
                </span>
              </label>

              <span className="ml-auto text-xs tabular-nums text-ink-400">
                {li.cfg.enabled
                  ? `${li.points.length.toLocaleString()} ponto(s)`
                  : "oculto"}
              </span>
            </div>
          ))
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="relative h-[560px]">
          <InventoryMap layers={mapLayers} onPointClick={(datasetId, kind, lat, lon) =>
            setActive({ datasetId, kind, lat, lon })
          } />
          {anyLoading ? (
            <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-full bg-white/95 px-3 py-1 text-xs shadow ring-1 ring-ink-200">
              <Loader2 className="h-3 w-3 animate-spin" />
              Carregando pontos…
            </div>
          ) : null}
          {!anyLoading && totalVisible === 0 ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  Nenhum ponto para os sistemas ativos.
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Habilite um sistema acima ou baixe dados na página
                  Download.
                </p>
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3">
          {active && active.kind === "grid" ? (
            <CellDetailPanel
              dataset={active.datasetId}
              lat={active.lat}
              lon={active.lon}
            />
          ) : active && active.kind === "station" && activeStation ? (
            <StationDetailPanel
              datasetLabel={active.datasetId.toUpperCase()}
              station={activeStation}
            />
          ) : (
            <div className="card flex h-full flex-col items-center justify-center p-6 text-center text-sm text-ink-400">
              <MapPin className="mb-2 h-5 w-5" />
              <p>Clique em um ponto para ver os detalhes do sistema.</p>
            </div>
          )}
        </div>
      </div>

      <div className="card flex flex-wrap items-center gap-4 p-4 text-xs text-ink-500">
        <Pill label="Pontos visíveis" value={totalVisible.toLocaleString()} />
        {layerInfos
          .filter((li) => li.cfg.enabled)
          .map((li) => (
            <Pill
              key={li.name}
              label={li.label}
              value={li.points.length.toLocaleString()}
            />
          ))}
      </div>
    </div>
  );
}

function StationDetailPanel({
  station,
  datasetLabel,
}: {
  station: StationPoint;
  datasetLabel: string;
}) {
  const rows: [string, string][] = [
    ["Sistema", datasetLabel],
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
    <span className={cn("rounded-full bg-ink-50 px-3 py-1")}>
      <span className="text-[10px] uppercase tracking-wide text-ink-400">
        {label}{" "}
      </span>
      <span className="font-medium text-ink-800">{value}</span>
    </span>
  );
}
