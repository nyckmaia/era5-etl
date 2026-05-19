/**
 * Visual-only Y-axis unit conversion.
 *
 * The conversion is applied to the *plotted* values and the per-series
 * statistics — never to the stored data. ERA5/ERA5-LAND temperatures are
 * in Kelvin, INMET in °C; converting one of them on the chart makes the
 * overlay directly comparable without touching the parquet.
 */
import type { SeriesCfg } from "./types";

export interface TransformPreset {
  id: string;
  label: string;
  /** Lambda body in `x` (original value); null = identity. */
  expr: string | null;
}

export const PRESETS: TransformPreset[] = [
  { id: "none", label: "Sem conversão", expr: null },
  { id: "k_to_c", label: "Kelvin → Celsius", expr: "x - 273.15" },
  { id: "c_to_k", label: "Celsius → Kelvin", expr: "x + 273.15" },
  { id: "k_to_f", label: "Kelvin → Fahrenheit", expr: "x * 9 / 5 - 459.67" },
  { id: "c_to_f", label: "Celsius → Fahrenheit", expr: "x * 9 / 5 + 32" },
  { id: "custom", label: "Custom (fórmula)…", expr: null },
];

// Arithmetic only: digits, the variable `x`, exponent e/E, operators and
// parens. No identifiers/letters (besides x/e) -> no access to globals.
const _SAFE = /^[0-9xX.eE+\-*/()\s]+$/;

export interface CompiledTransform {
  fn: (v: number) => number;
  identity: boolean;
  error: string | null;
}

function exprFor(t: SeriesCfg["transform"]): string | null {
  if (!t || t.preset === "none") return null;
  if (t.preset === "custom") return (t.expr ?? "").trim() || null;
  return PRESETS.find((p) => p.id === t.preset)?.expr ?? null;
}

export function compileTransform(
  t: SeriesCfg["transform"],
): CompiledTransform {
  const expr = exprFor(t);
  if (!expr) {
    return { fn: (v) => v, identity: true, error: null };
  }
  if (!_SAFE.test(expr)) {
    return {
      fn: (v) => v,
      identity: true,
      error: "Fórmula inválida: use apenas números, x, e + - * / ( ).",
    };
  }
  try {
    // eslint-disable-next-line no-new-func
    const raw = new Function("x", `"use strict"; return (${expr});`) as (
      x: number,
    ) => number;
    const probe = raw(300);
    if (typeof probe !== "number" || !Number.isFinite(probe)) {
      throw new Error("não retorna um número");
    }
    return {
      fn: (v) => {
        if (v == null || !Number.isFinite(v)) return v;
        const r = raw(v);
        return typeof r === "number" && Number.isFinite(r) ? r : v;
      },
      identity: false,
      error: null,
    };
  } catch (e) {
    return {
      fn: (v) => v,
      identity: true,
      error: `Fórmula inválida: ${(e as Error).message}`,
    };
  }
}

/** Apply a compiled transform to a y array (nulls preserved). */
export function applyTransform(
  y: (number | null)[],
  fn: (v: number) => number,
): (number | null)[] {
  return y.map((v) => (v == null ? v : fn(v)));
}
