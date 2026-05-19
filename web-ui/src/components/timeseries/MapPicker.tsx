import { DeckGL } from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import { Map as MapLibreMap } from "react-map-gl/maplibre";
import { useMemo } from "react";

import { api, type TSLocation, type TSViewMeta } from "@/lib/api";

import "maplibre-gl/dist/maplibre-gl.css";

const BASEMAP: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap",
      maxzoom: 19,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#e6eef3" } },
    { id: "osm", type: "raster", source: "osm" },
  ],
};

const INITIAL = { longitude: -54, latitude: -14, zoom: 3.4, pitch: 0, bearing: 0 };

interface Pt {
  lat: number;
  lon: number;
  label: string;
  station_id?: string;
}

interface Props {
  meta: TSViewMeta;
  onPick: (loc: Partial<TSLocation>) => void;
  onClose: () => void;
}

function viewDataset(view: string): string {
  if (view === "era5") return "era5";
  if (view === "era5_land") return "era5-land";
  return "inmet"; // inmet / era5_inmet -> station catalogue
}

/**
 * Snap a coordinate onto the dataset grid and trim Float32 noise.
 *
 * Grid-point coords come from the coverage index stored as Float32, so
 * e.g. -15.7 arrives as -15.699999809265137. Rounding to the nearest grid
 * step and then to the grid's decimal places yields the canonical value
 * that actually exists in the DB (ERA5 0.25° -> 2dp, ERA5-LAND 0.1° -> 1dp).
 */
function snapToGrid(v: number, res: number | null): number {
  if (!res) return v;
  const snapped = Math.round(v / res) * res;
  const dec = res < 1 ? (String(res).split(".")[1]?.length ?? 6) : 0;
  return Number(snapped.toFixed(dec));
}

export function MapPicker({ meta, onPick, onClose }: Props) {
  const isStation = meta.location_kind === "station";
  const ds = viewDataset(meta.view);

  const gridQ = useQuery({
    queryKey: ["ts-grid", ds],
    queryFn: () => api.inventory.gridPoints({ dataset: ds, format: "auto" }),
    enabled: !isStation,
  });
  const staQ = useQuery({
    queryKey: ["ts-sta", "inmet"],
    queryFn: () => api.inventory.stations("inmet"),
    enabled: isStation,
  });

  const points: Pt[] = useMemo(() => {
    if (isStation) {
      return (staQ.data?.stations ?? [])
        .filter((s) => s.latitude != null && s.longitude != null)
        .map((s) => ({
          lat: s.latitude as number,
          lon: s.longitude as number,
          station_id: s.station_id,
          label: `${s.station_id}${s.nome ? ` · ${s.nome}` : ""}`,
        }));
    }
    return (gridQ.data ?? []).map((g) => ({
      lat: g.lat,
      lon: g.lon,
      label: `${g.lat.toFixed(3)}, ${g.lon.toFixed(3)}`,
    }));
  }, [isStation, staQ.data, gridQ.data]);

  const loading = isStation ? staQ.isLoading : gridQ.isLoading;

  const layer = new ScatterplotLayer<Pt>({
    id: "pick-points",
    data: points,
    pickable: true,
    radiusUnits: "meters",
    radiusMinPixels: 3,
    radiusMaxPixels: 9,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 2000,
    getFillColor: isStation ? [232, 115, 12, 200] : [2, 132, 199, 180],
    getLineColor: [255, 255, 255, 220],
    lineWidthMinPixels: 1,
    stroked: true,
  });

  function handleClick(info: PickingInfo) {
    const o = info.object as Pt | undefined;
    if (!o) return;
    if (isStation) {
      onPick({ kind: "point", station_id: o.station_id });
    } else {
      // Use the grid point's canonical (snapped) coords, never the raw
      // Float32 value — keeps LAT/LON at the dataset's resolution.
      onPick({
        kind: "point",
        lat: snapToGrid(o.lat, meta.grid_resolution),
        lon: snapToGrid(o.lon, meta.grid_resolution),
      });
    }
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="card relative flex h-[80vh] w-full max-w-4xl flex-col overflow-hidden p-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-100 px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-ink-800">
              {isStation
                ? "Selecione uma estação"
                : `Selecione um ponto de grade (${meta.view.toUpperCase()})`}
            </h3>
            <p className="text-xs text-ink-400">
              {loading
                ? "Carregando…"
                : `${points.length.toLocaleString()} ${
                    isStation ? "estação(ões)" : "ponto(s)"
                  } · clique para escolher`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            aria-label="Fechar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="relative flex-1">
          <DeckGL
            initialViewState={INITIAL}
            controller
            layers={[layer]}
            onClick={handleClick}
            getTooltip={(info: PickingInfo) => {
              const o = info.object as Pt | undefined;
              return o
                ? {
                    html: `<div style="font:12px Inter,sans-serif">${o.label}</div>`,
                    style: {
                      background: "white",
                      color: "#0f172a",
                      padding: "4px 8px",
                      borderRadius: "6px",
                    },
                  }
                : null;
            }}
          >
            <MapLibreMap
              mapLib={maplibregl as unknown as never}
              mapStyle={BASEMAP}
              attributionControl={false}
            />
          </DeckGL>
          {!loading && points.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-xl bg-white/95 px-4 py-3 text-center text-sm text-ink-500 shadow ring-1 ring-ink-200">
                Nenhum {isStation ? "estação" : "ponto"} disponível —
                baixe dados primeiro.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
