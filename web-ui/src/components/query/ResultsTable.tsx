import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ColumnPrecision, PrecisionConfig } from "@/lib/api";
import { cn } from "@/lib/format";
import { unitForColumn } from "@/lib/units";

type Cell = string | number | null;
type SortState = { index: number; dir: "asc" | "desc" } | null;

interface ResultsTableProps {
  columns: string[];
  columnTypes: string[];
  rows: Cell[][];
  /** Display-precision config for the focused dataset (float formatting). */
  precision?: PrecisionConfig;
  /** Lowercased {column → raw unit} lookup from dataset metadata. */
  unitMap: Record<string, string>;
}

const isNumericType = (t: string | undefined): boolean =>
  t === "float" || t === "int";

/** Round/truncate a float to the configured number of decimals. */
function formatCell(raw: Cell, precision: ColumnPrecision): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return String(raw);
  const { decimals, method } = precision;
  if (method === "truncate") {
    const f = 10 ** decimals;
    return (Math.trunc(n * f) / f).toFixed(decimals);
  }
  return n.toFixed(decimals);
}

/**
 * Results grid for the SQL editor: a sortable, unit-annotated table with a
 * header that stays pinned while the rows scroll.
 *
 * - Click a header to cycle sort: none → ascending → descending → none.
 *   Numeric columns sort by value; everything else sorts as text
 *   (locale-aware). NULLs always sink to the bottom, both directions.
 * - The unit of measure (e.g. `[K]`, `[m s⁻¹]`) renders under the column
 *   name when the column maps to a known dataset variable.
 * - Numeric columns are right-aligned with tabular figures.
 */
export function ResultsTable({
  columns,
  columnTypes,
  rows,
  precision,
  unitMap,
}: ResultsTableProps) {
  const [sort, setSort] = useState<SortState>(null);

  // A new query result (different columns) invalidates any active sort.
  useEffect(() => {
    setSort(null);
  }, [columns]);

  function toggleSort(index: number) {
    setSort((prev) => {
      if (!prev || prev.index !== index) return { index, dir: "asc" };
      if (prev.dir === "asc") return { index, dir: "desc" };
      return null;
    });
  }

  // Sort an index array (stable) rather than the rows, so React keys stay
  // tied to the original row identity.
  const order = useMemo(() => {
    const idx = rows.map((_, i) => i);
    if (!sort) return idx;
    const { index, dir } = sort;
    const numeric = isNumericType(columnTypes[index]);
    const sign = dir === "asc" ? 1 : -1;
    return idx.sort((ia, ib) => {
      const a = rows[ia][index];
      const b = rows[ib][index];
      const aMissing = a === null || a === undefined;
      const bMissing = b === null || b === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1; // NULLs last, regardless of direction
      if (bMissing) return -1;
      const c = numeric
        ? Number(a) - Number(b)
        : String(a).localeCompare(String(b), undefined, {
            numeric: true,
            sensitivity: "base",
          });
      return sign * c;
    });
  }, [rows, columnTypes, sort]);

  function renderValue(cell: Cell, colName: string, colType: string): string {
    if (colType === "float" && precision && Number.isFinite(Number(cell))) {
      const override = precision.columns[colName];
      return formatCell(
        cell,
        override ?? {
          decimals: precision.default_decimals,
          method: precision.default_method,
        },
      );
    }
    return String(cell);
  }

  return (
    <div className="max-h-[40vh] overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-xs">
        <thead>
          <tr>
            {columns.map((col, j) => {
              const numeric = isNumericType(columnTypes[j]);
              const unit = unitForColumn(unitMap, col);
              const active = sort?.index === j;
              const Icon = active
                ? sort?.dir === "asc"
                  ? ArrowUp
                  : ArrowDown
                : ChevronsUpDown;
              return (
                <th
                  key={`${col}-${j}`}
                  aria-sort={
                    active
                      ? sort?.dir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                  className="sticky top-0 z-10 border-b border-ink-200 bg-ink-50 px-3 py-2"
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(j)}
                    title={`Ordenar por ${col}`}
                    className="group flex w-full flex-col gap-0.5"
                  >
                    {/* Name + sort affordance, aligned per column type. */}
                    <span
                      className={cn(
                        "flex items-center gap-1.5",
                        numeric ? "flex-row-reverse" : "",
                      )}
                    >
                      <span className="whitespace-nowrap font-medium text-ink-700">
                        {col}
                      </span>
                      <Icon
                        className={cn(
                          "h-3.5 w-3.5 shrink-0 transition-opacity",
                          active
                            ? "text-ocean-600"
                            : "text-ink-300 opacity-0 group-hover:opacity-100",
                        )}
                      />
                    </span>
                    {/* Unit of measure — centered under the column name, at
                        the same font size as the name. */}
                    {unit ? (
                      <span className="block w-full text-center font-mono font-normal leading-tight text-ink-400">
                        [{unit}]
                      </span>
                    ) : null}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length || 1}
                className="px-3 py-6 text-center text-ink-400"
              >
                Nenhuma linha retornada.
              </td>
            </tr>
          ) : (
            order.map((rowIdx) => {
              const row = rows[rowIdx];
              return (
                <tr key={rowIdx} className="group">
                  {row.map((cell, j) => {
                    const numeric = isNumericType(columnTypes[j]);
                    const tdClass = cn(
                      "border-b border-ink-100 px-3 py-1.5 font-mono group-hover:bg-ocean-50/50",
                      numeric ? "text-right tabular-nums" : "text-left",
                    );
                    if (cell === null) {
                      return (
                        <td key={j} className={tdClass}>
                          <span className="text-ink-300">∅</span>
                        </td>
                      );
                    }
                    return (
                      <td key={j} className={cn(tdClass, "text-ink-700")}>
                        {renderValue(cell, columns[j], columnTypes[j])}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
