import { useMutation } from "@tanstack/react-query";
import { Loader2, Map as MapIcon, Download } from "lucide-react";
import { useEffect } from "react";

import { api } from "@/lib/api";

interface Props {
  dataset: string;
  polygon: [number, number][]; // [lat, lon][]
  onFillGapsClick?: (bbox: [number, number, number, number]) => void;
}

function bboxOfPolygon(poly: [number, number][]): [number, number, number, number] {
  let minLat = poly[0][0],
    maxLat = poly[0][0],
    minLon = poly[0][1],
    maxLon = poly[0][1];
  for (const [lat, lon] of poly) {
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }
  return [maxLat, minLon, minLat, maxLon];
}

export function RegionSummaryPanel({ dataset, polygon, onFillGapsClick }: Props) {
  const m = useMutation({
    mutationFn: () => api.inventory.regionSummary({ dataset, polygon }),
  });

  useEffect(() => {
    if (polygon.length >= 3) m.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polygon, dataset]);

  const bbox = polygon.length >= 3 ? bboxOfPolygon(polygon) : null;

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2 text-ink-700">
        <MapIcon className="h-4 w-4 text-ocean-600" />
        <h3 className="text-sm font-semibold">Região selecionada</h3>
      </div>

      {polygon.length < 3 ? (
        <p className="text-sm text-ink-400">
          Polígono incompleto (mínimo 3 vértices).
        </p>
      ) : m.isPending ? (
        <div className="flex items-center gap-2 text-sm text-ink-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Calculando...
        </div>
      ) : m.error ? (
        <p className="text-sm text-red-600">{(m.error as Error).message}</p>
      ) : m.data ? (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="Pontos" value={m.data.n_points.toLocaleString()} />
            <Stat
              label="Vars/cell"
              value={m.data.vars_per_cell_avg.toFixed(1)}
            />
            <Stat
              label="Gaps"
              value={m.data.gaps.length.toString()}
              warn={m.data.gaps.length > 0}
            />
          </div>

          {m.data.date_range ? (
            <div className="mt-3 text-xs text-ink-500">
              Período coberto:{" "}
              <span className="font-mono text-ink-700">
                {m.data.date_range[0]} → {m.data.date_range[1]}
              </span>
            </div>
          ) : null}

          {m.data.gaps.length > 0 ? (
            <div className="mt-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Datas com cobertura parcial
              </h4>
              <div className="mt-2 max-h-44 overflow-y-auto rounded-lg border border-ink-100">
                <table className="w-full text-xs">
                  <thead className="bg-ink-50">
                    <tr>
                      <th className="px-2 py-1.5 text-left">Data</th>
                      <th className="px-2 py-1.5 text-right">Faltando</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.data.gaps.slice(0, 30).map((g) => (
                      <tr key={g.date} className="border-t border-ink-100">
                        <td className="px-2 py-1.5 font-mono text-[11px]">{g.date}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[11px] text-amber-600">
                          {g.missing_pct.toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {bbox && onFillGapsClick ? (
            <button
              className="btn-outline mt-4 w-full justify-center"
              onClick={() => onFillGapsClick(bbox)}
            >
              <Download className="h-4 w-4" />
              Baixar dados faltantes para esta região
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className={"rounded-lg p-2 " + (warn ? "bg-amber-50" : "bg-ink-50")}>
      <div className="text-[10px] uppercase tracking-wide text-ink-400">{label}</div>
      <div
        className={
          "text-base font-semibold " + (warn ? "text-amber-600" : "text-ink-800")
        }
      >
        {value}
      </div>
    </div>
  );
}
