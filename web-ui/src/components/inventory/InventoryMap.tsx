import { DeckGL } from "@deck.gl/react";
import { ScatterplotLayer, PolygonLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import maplibregl from "maplibre-gl";
import { Map as MapLibreMap } from "react-map-gl/maplibre";
import { useMemo, useState } from "react";

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

// Free OSM-style basemap; no token needed.
const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

export type SelectionMode = "none" | "click" | "rectangle" | "lasso";

export interface InventoryMapProps {
  points: GridPoint[];
  selectionMode: SelectionMode;
  selection: [number, number][] | null; // polygon ring [lat, lon][]
  onSelectionChange: (poly: [number, number][] | null) => void;
  onCellClick: (lat: number, lon: number) => void;
  colormap: "binary" | "intensity";
  totalVars: number;
}

function intensityColor(t: number): [number, number, number, number] {
  // Smooth interpolation grey -> green-teal. t in [0, 1].
  const c = Math.max(0, Math.min(1, t));
  const r = Math.round(170 + (20 - 170) * c);
  const g = Math.round(170 + (130 - 170) * c);
  const b = Math.round(170 + (100 - 170) * c);
  return [r, g, b, 200];
}

export function InventoryMap(props: InventoryMapProps) {
  const {
    points,
    selectionMode,
    selection,
    onSelectionChange,
    onCellClick,
    colormap,
    totalVars,
  } = props;

  const [dragStart, setDragStart] = useState<[number, number] | null>(null);
  const [dragNow, setDragNow] = useState<[number, number] | null>(null);
  const [lassoPath, setLassoPath] = useState<[number, number][]>([]);

  const pointsLayer = useMemo(
    () =>
      new ScatterplotLayer<GridPoint>({
        id: "grid-points",
        data: points,
        pickable: true,
        radiusUnits: "pixels",
        radiusMinPixels: 2,
        radiusMaxPixels: 8,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: (d) => 2.5 + Math.log10(Math.max(1, d.days)) * 1.4,
        getFillColor: (d) =>
          colormap === "binary"
            ? [40, 100, 200, 200]
            : intensityColor((d.vars ?? 0) / Math.max(1, totalVars)),
        getLineColor: [255, 255, 255, 100],
        lineWidthMinPixels: 0.5,
        stroked: true,
        updateTriggers: {
          getFillColor: [colormap, totalVars],
        },
      }),
    [points, colormap, totalVars],
  );

  const selectionLayer = useMemo(() => {
    const polys: { polygon: [number, number][] }[] = [];
    if (selection && selection.length >= 3) {
      polys.push({
        polygon: selection.map(([lat, lon]) => [lon, lat]),
      });
    }
    if (selectionMode === "rectangle" && dragStart && dragNow) {
      const [a, b] = [dragStart, dragNow];
      polys.push({
        polygon: [
          [a[0], a[1]],
          [b[0], a[1]],
          [b[0], b[1]],
          [a[0], b[1]],
        ],
      });
    }
    if (selectionMode === "lasso" && lassoPath.length >= 2) {
      polys.push({ polygon: lassoPath });
    }
    return new PolygonLayer({
      id: "selection",
      data: polys,
      getPolygon: (d: { polygon: [number, number][] }) => d.polygon,
      getFillColor: [14, 165, 233, 50],
      getLineColor: [14, 165, 233, 220],
      getLineWidth: 2,
      lineWidthUnits: "pixels",
      pickable: false,
    });
  }, [selection, selectionMode, dragStart, dragNow, lassoPath]);

  function handleClick(info: PickingInfo, ev: { srcEvent: MouseEvent }) {
    if (selectionMode === "click") {
      if (info.coordinate) {
        const [lon, lat] = info.coordinate;
        const next: [number, number][] = selection ? [...selection] : [];
        // Append vertex; double-click finishes (not implemented — Reset to clear).
        next.push([lat, lon]);
        onSelectionChange(next);
      }
      return;
    }
    if (selectionMode === "lasso") {
      // Single click also adds a vertex (lasso is poly-by-vertices).
      if (info.coordinate) {
        const [lon, lat] = info.coordinate;
        setLassoPath((p) => [...p, [lon, lat]]);
      }
      return;
    }
    if (info.object) {
      const o = info.object as GridPoint;
      onCellClick(o.lat, o.lon);
    }
    // suppress lint
    void ev;
  }

  function handleDragStart(info: PickingInfo) {
    if (selectionMode !== "rectangle" || !info.coordinate) return;
    const [lon, lat] = info.coordinate;
    setDragStart([lon, lat]);
    setDragNow([lon, lat]);
  }
  function handleDrag(info: PickingInfo) {
    if (selectionMode !== "rectangle" || !dragStart || !info.coordinate) return;
    const [lon, lat] = info.coordinate;
    setDragNow([lon, lat]);
  }
  function handleDragEnd(info: PickingInfo) {
    if (selectionMode !== "rectangle" || !dragStart || !info.coordinate) return;
    const [lon, lat] = info.coordinate;
    const a = dragStart;
    const b: [number, number] = [lon, lat];
    const ring: [number, number][] = [
      [a[1], a[0]],
      [a[1], b[0]],
      [b[1], b[0]],
      [b[1], a[0]],
    ];
    onSelectionChange(ring);
    setDragStart(null);
    setDragNow(null);
  }

  function handleDoubleClick() {
    if (selectionMode === "lasso" && lassoPath.length >= 3) {
      onSelectionChange(lassoPath.map(([lon, lat]) => [lat, lon]));
      setLassoPath([]);
    }
  }

  const tooltip = (info: PickingInfo) => {
    if (!info.object) return null;
    const o = info.object as GridPoint;
    return {
      html: `
        <div style="font-family: Inter, sans-serif; font-size: 12px;">
          <div style="font-weight: 600;">${o.lat.toFixed(3)}, ${o.lon.toFixed(3)}</div>
          <div style="opacity:0.7; margin-top:2px;">${o.days} dia(s) · ${o.vars} variável(eis)</div>
        </div>`,
      style: { background: "white", color: "#0f172a", padding: "6px 8px", borderRadius: "6px", boxShadow: "0 2px 6px rgba(0,0,0,0.15)" },
    };
  };

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl border border-ink-200">
      <DeckGL
        initialViewState={INITIAL_VIEW}
        controller={selectionMode !== "rectangle"}
        layers={[pointsLayer, selectionLayer]}
        onClick={handleClick}
        onDragStart={handleDragStart}
        onDrag={handleDrag}
        onDragEnd={handleDragEnd}
        getTooltip={tooltip}
        onAfterRender={undefined}
      >
        <MapLibreMap
          mapLib={maplibregl as unknown as never}
          mapStyle={BASEMAP_STYLE}
          attributionControl={false}
        />
      </DeckGL>
      {selectionMode === "lasso" && lassoPath.length > 0 ? (
        <div
          className="pointer-events-none absolute inset-x-0 top-3 mx-auto w-max rounded-full bg-ink-800/80 px-3 py-1 text-xs text-white"
          onDoubleClick={handleDoubleClick}
        >
          {lassoPath.length} vértice(s) — duplo-clique para fechar
        </div>
      ) : null}
    </div>
  );
}
