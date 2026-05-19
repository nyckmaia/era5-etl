import { DeckGL } from "@deck.gl/react";
import { IconLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import { Map as MapLibreMap } from "react-map-gl/maplibre";
import { useMemo } from "react";

import type { GridPoint } from "@/lib/api";

import "maplibre-gl/dist/maplibre-gl.css";

// Brazil bounds. The map starts here so users see something familiar even
// before they have downloaded any data.
const INITIAL_VIEW = {
  longitude: -54,
  latitude: -14,
  zoom: 3.2,
  pitch: 0,
  bearing: 0,
};

// Self-contained raster basemap (single OSM raster source) so the basemap
// always renders even if a remote vector style/CDN is blocked.
const BASEMAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "osm-raster": {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#e6eef3" } },
    { id: "osm", type: "raster", source: "osm-raster" },
  ],
};

export const MARKER_SHAPES = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "star",
  "cross",
] as const;
export type MarkerShape = (typeof MARKER_SHAPES)[number];

/** One overlaid system (ERA5 / ERA5-LAND / INMET) as its own point layer. */
export interface MapLayerData {
  id: string; // dataset name, e.g. "era5-land"
  label: string; // display label, e.g. "ERA5-LAND"
  kind: "grid" | "station";
  points: GridPoint[];
  color: string; // hex, e.g. "#2864c8"
  opacity: number; // 0-100
  sizeMul: number; // size multiplier (0.25 .. 4)
  shape: MarkerShape;
  visible: boolean;
}

export interface InventoryMapProps {
  layers: MapLayerData[];
  onPointClick: (
    datasetId: string,
    kind: "grid" | "station",
    lat: number,
    lon: number,
  ) => void;
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = Number.parseInt(full || "2864c8", 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// --- marker icon atlas -------------------------------------------------
// One white silhouette per shape on a transparent 64×64 canvas. Drawn as
// a `mask` icon so deck.gl tints it per-layer via getColor (one canvas
// per shape, reused across colors). Memoised data URLs.
const ICON_PX = 64;
const _iconCache = new Map<MarkerShape, string>();

function drawShape(ctx: CanvasRenderingContext2D, shape: MarkerShape) {
  const c = ICON_PX / 2;
  const r = ICON_PX / 2 - 4;
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#ffffff";
  ctx.lineJoin = "round";
  ctx.beginPath();
  if (shape === "circle") {
    ctx.arc(c, c, r, 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  if (shape === "square") {
    ctx.fillRect(c - r, c - r, r * 2, r * 2);
    return;
  }
  if (shape === "cross") {
    const t = r * 0.42;
    ctx.fillRect(c - t, c - r, t * 2, r * 2);
    ctx.fillRect(c - r, c - t, r * 2, t * 2);
    return;
  }
  let pts: [number, number][];
  if (shape === "triangle") {
    pts = [
      [c, c - r],
      [c + r, c + r],
      [c - r, c + r],
    ];
  } else if (shape === "diamond") {
    pts = [
      [c, c - r],
      [c + r, c],
      [c, c + r],
      [c - r, c],
    ];
  } else {
    // star (5-point)
    pts = [];
    for (let i = 0; i < 10; i++) {
      const ang = (Math.PI / 5) * i - Math.PI / 2;
      const rad = i % 2 === 0 ? r : r * 0.42;
      pts.push([c + rad * Math.cos(ang), c + rad * Math.sin(ang)]);
    }
  }
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
  ctx.closePath();
  ctx.fill();
}

function markerIconUrl(shape: MarkerShape): string {
  const cached = _iconCache.get(shape);
  if (cached) return cached;
  const canvas = document.createElement("canvas");
  canvas.width = ICON_PX;
  canvas.height = ICON_PX;
  const ctx = canvas.getContext("2d");
  if (ctx) drawShape(ctx, shape);
  const url = canvas.toDataURL();
  _iconCache.set(shape, url);
  return url;
}

const LAYER_PREFIX = "pts-";

export function InventoryMap({ layers, onPointClick }: InventoryMapProps) {
  const deckLayers = useMemo(() => {
    return layers
      .filter((l) => l.visible && l.points.length > 0)
      .map((l) => {
        const [r, g, b] = hexToRgb(l.color);
        const alpha = Math.round(
          (Math.max(0, Math.min(100, l.opacity)) / 100) * 255,
        );
        const url = markerIconUrl(l.shape);
        return new IconLayer<GridPoint>({
          id: `${LAYER_PREFIX}${l.id}`,
          data: l.points,
          pickable: true,
          billboard: true,
          getIcon: () => ({
            id: `${l.shape}`,
            url,
            width: ICON_PX,
            height: ICON_PX,
            anchorX: ICON_PX / 2,
            anchorY: ICON_PX / 2,
            mask: true,
          }),
          sizeUnits: "pixels",
          sizeMinPixels: 3,
          sizeMaxPixels: 44,
          getPosition: (d) => [d.lon, d.lat],
          getSize: (d) =>
            (10 + Math.log10(Math.max(1, Number(d.days))) * 5) * l.sizeMul,
          getColor: [r, g, b, alpha],
          updateTriggers: {
            getColor: [l.color, l.opacity],
            getSize: [l.sizeMul],
            getIcon: [l.shape],
          },
        });
      });
  }, [layers]);

  const layerById = useMemo(() => {
    const m = new Map<string, MapLayerData>();
    for (const l of layers) m.set(l.id, l);
    return m;
  }, [layers]);

  function handleClick(info: PickingInfo) {
    if (!info.object || !info.layer) return;
    const id = String(info.layer.id).slice(LAYER_PREFIX.length);
    const l = layerById.get(id);
    if (!l) return;
    const o = info.object as GridPoint;
    onPointClick(id, l.kind, o.lat, o.lon);
  }

  const tooltip = (info: PickingInfo) => {
    if (!info.object || !info.layer) return null;
    const id = String(info.layer.id).slice(LAYER_PREFIX.length);
    const l = layerById.get(id);
    if (!l) return null;
    const o = info.object as GridPoint;
    const detail =
      l.kind === "station"
        ? `${o.days} ano(s) · ${o.vars} variável(eis)`
        : `${o.days} dia(s) · ${o.vars} variável(eis)`;
    return {
      html: `
        <div style="font-family: Inter, sans-serif; font-size: 12px;">
          <div style="font-weight:600;">${l.label}</div>
          <div>${o.lat.toFixed(3)}, ${o.lon.toFixed(3)}</div>
          <div style="opacity:0.7; margin-top:2px;">${detail}</div>
        </div>`,
      style: {
        background: "white",
        color: "#0f172a",
        padding: "6px 8px",
        borderRadius: "6px",
        boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
      },
    };
  };

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl border border-ink-200">
      <DeckGL
        initialViewState={INITIAL_VIEW}
        controller
        layers={deckLayers}
        onClick={handleClick}
        getTooltip={tooltip}
      >
        <MapLibreMap
          mapLib={maplibregl as unknown as never}
          mapStyle={BASEMAP_STYLE}
          attributionControl={false}
        />
      </DeckGL>
    </div>
  );
}
