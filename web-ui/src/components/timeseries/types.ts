import type { TSLocation } from "@/lib/api";

export type Bucket = "raw" | "hour" | "day" | "month";
export type Agg = "avg" | "min" | "max" | "sum";

export interface SeriesCfg {
  id: string;
  view: string;
  yColumn: string;
  agg: Agg;
  axis: "y" | "y2";
  location: TSLocation;
  name?: string;
  /** Draw the series mean as a constant dashed horizontal line. */
  showMean?: boolean;
  /**
   * Visual-only unit conversion applied to Y before plotting/stats.
   * The stored data is never changed. ``preset`` is a key from
   * transform.PRESETS; for "custom" the lambda body is in ``expr``
   * (variable ``x`` = the original value, e.g. "x - 273.15").
   */
  transform?: { preset: string; expr?: string };
}

export interface TraceStyle {
  color: string;
  dash: "solid" | "dash" | "dot";
  width: number;
  mode: "lines" | "lines+markers" | "markers";
}

export interface CellLayout {
  title: string;
  logY: boolean;
  logY2: boolean;
  showLegend: boolean;
}

export interface Cell {
  id: string;
  title: string;
  dateFrom: string;
  dateTo: string;
  bucket: Bucket;
  maxPoints: number;
  series: SeriesCfg[];
  traceStyles: Record<string, TraceStyle>; // keyed by SeriesCfg.id
  layout: CellLayout;
}

export interface Notebook {
  version: 1;
  cells: Cell[];
}

export function newId(): string {
  return Math.random().toString(36).slice(2, 10);
}
