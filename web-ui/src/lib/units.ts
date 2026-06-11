// Pretty-printing of physical units for the /query results table.
//
// The dataset YAMLs store units in a terse ASCII form ("m/s", "m3/m3",
// "J/m2", "kg/m2/s", ...). We render them with proper Unicode superscripts
// and a middle space so columns read like "m s⁻¹", "m³ m⁻³", "J m⁻²".
//
// A curated map is the source of truth: the unit set is small, finite and
// known (it comes from era5 / era5-land / inmet variables.yaml), and a few
// strings ("N/m2 s", "K kg/m2") are ambiguous to parse left-to-right. The
// generic parser only runs as a fallback for units we haven't seen yet.

import type { DatasetInfo } from "@/lib/api";

const SUPERSCRIPT: Record<string, string> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

/** Marker rendered for dimensionless quantities (e.g. albedo, ratios), so
 *  the header shows `[-]` rather than no bracket at all. */
const DIMENSIONLESS = "-";

/** Curated raw-unit → display-unit map. {@link DIMENSIONLESS} marks units
 *  with no physical dimension. */
const UNIT_PRETTY: Record<string, string> = {
  K: "K",
  C: "°C",
  Pa: "Pa",
  mB: "mB",
  mm: "mm",
  m: "m",
  s: "s",
  rad: "rad",
  "%": "%",
  deg: "°",
  degree: "°",
  dimensionless: DIMENSIONLESS,
  "(0-1)": DIMENSIONLESS,
  "m/s": "m s⁻¹",
  "m3/m3": "m³ m⁻³",
  "m2/m2": "m² m⁻²",
  "m2/s2": "m² s⁻²",
  "1/m": "m⁻¹",
  "J/m2": "J m⁻²",
  "J/kg": "J kg⁻¹",
  "KJ/m2": "kJ m⁻²",
  "W/m2": "W m⁻²",
  "W/m": "W m⁻¹",
  "N/m2": "N m⁻²",
  "N/m2 s": "N m⁻² s",
  "kg/m2": "kg m⁻²",
  "kg/m3": "kg m⁻³",
  "kg/m2/s": "kg m⁻² s⁻¹",
  "kg/m/s": "kg m⁻¹ s⁻¹",
  "K kg/m2": "K kg m⁻²",
};

const toSuperscript = (n: number): string =>
  String(n)
    .split("")
    .map((c) => SUPERSCRIPT[c] ?? c)
    .join("");

/** Format a single "base+digits" token (e.g. "m2") with a signed exponent.
 *  A positive sign keeps it in the numerator, negative pushes it to a
 *  reciprocal (denominator) with a superscript minus. */
function formatToken(token: string, sign: 1 | -1): string {
  const m = token.match(/^([A-Za-zµ°]+)(\d+)?$/);
  if (!m) return token;
  const base = m[1];
  const exp = (m[2] ? Number.parseInt(m[2], 10) : 1) * sign;
  if (exp === 1) return base;
  return base + (exp < 0 ? "⁻" : "") + toSuperscript(Math.abs(exp));
}

/** Generic fallback parser for units not in {@link UNIT_PRETTY}. Treats the
 *  first "/"-segment as the numerator and every later segment as a
 *  denominator (negative exponents). */
function genericPretty(raw: string): string {
  const segments = raw.split("/").map((s) => s.trim()).filter(Boolean);
  if (segments.length === 0) return raw;
  const numerator = segments[0].split(/\s+/).filter(Boolean);
  const denominator = segments
    .slice(1)
    .flatMap((seg) => seg.split(/\s+/))
    .filter(Boolean);
  return [
    ...numerator.map((t) => formatToken(t, 1)),
    ...denominator.map((t) => formatToken(t, -1)),
  ].join(" ");
}

/** Turn a raw unit string into its display form (without brackets).
 *  Returns "" for dimensionless / unknown-empty units. */
export function formatUnit(raw: string | null | undefined): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (trimmed === "" || trimmed === "-") return "";
  if (Object.prototype.hasOwnProperty.call(UNIT_PRETTY, trimmed)) {
    return UNIT_PRETTY[trimmed];
  }
  return genericPretty(trimmed);
}

/** Build a lowercased {column name → raw unit} lookup from all dataset
 *  metadata. A result column can carry a variable's `friendly_name`,
 *  `api_name` or `short_name` depending on how the SQL aliased it, so we
 *  index all three. Coordinate columns get the degree unit. */
export function buildColumnUnitMap(
  datasets: DatasetInfo[] | undefined,
): Record<string, string> {
  // Universal coordinate columns — pre-seeded so a same-named variable
  // (none today) can't override them.
  const map: Record<string, string> = {
    latitude: "degree",
    longitude: "degree",
  };
  for (const d of datasets ?? []) {
    for (const v of d.variables ?? []) {
      if (!v.unit) continue;
      for (const key of [v.friendly_name, v.api_name, v.short_name]) {
        if (!key) continue;
        const k = key.toLowerCase();
        if (!(k in map)) map[k] = v.unit;
      }
    }
  }
  return map;
}

/** Resolve a result-column name to its display unit (or "" if none). */
export function unitForColumn(
  unitMap: Record<string, string>,
  column: string,
): string {
  return formatUnit(unitMap[column.toLowerCase()]);
}
