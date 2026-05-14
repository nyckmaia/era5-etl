import { useQuery } from "@tanstack/react-query";
import { Loader2, MapPin } from "lucide-react";

import { api } from "@/lib/api";
import { maskToHours, popcount } from "@/lib/hours";

interface Props {
  dataset: string;
  lat: number;
  lon: number;
}

export function CellDetailPanel({ dataset, lat, lon }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["cell-detail", dataset, lat, lon],
    queryFn: () => api.inventory.cellDetail({ dataset, lat, lon }),
  });

  if (isLoading)
    return (
      <Wrap lat={lat} lon={lon}>
        <div className="flex items-center gap-2 text-sm text-ink-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Carregando...
        </div>
      </Wrap>
    );

  if (error)
    return (
      <Wrap lat={lat} lon={lon}>
        <p className="text-sm text-red-600">{(error as Error).message}</p>
      </Wrap>
    );

  if (!data || data.dates.length === 0)
    return (
      <Wrap lat={lat} lon={lon}>
        <p className="text-sm text-ink-400">Nenhum dado para esta célula.</p>
      </Wrap>
    );

  const totalDates = data.dates.length;
  const allVars = new Set<string>();
  let totalHours = 0;
  for (const d of data.dates) {
    for (const v of d.variables) {
      allVars.add(v.name);
      totalHours += v.hours.length;
    }
  }

  return (
    <Wrap lat={lat} lon={lon}>
      <div className="grid grid-cols-3 gap-2 text-center">
        <Stat label="Datas" value={totalDates.toString()} />
        <Stat label="Variáveis" value={allVars.size.toString()} />
        <Stat label="Horas/cell" value={totalHours.toString()} />
      </div>

      <div className="mt-4">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Por data
        </h4>
        <div className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-ink-100">
          <table className="w-full text-xs">
            <thead className="bg-ink-50">
              <tr>
                <th className="px-2 py-1.5 text-left">Data</th>
                <th className="px-2 py-1.5 text-left">Var</th>
                <th className="px-2 py-1.5 text-left">Horas</th>
              </tr>
            </thead>
            <tbody>
              {data.dates.flatMap((d) =>
                d.variables.map((v) => (
                  <tr key={`${d.date}-${v.name}`} className="border-t border-ink-100">
                    <td className="px-2 py-1.5 font-mono text-[11px]">{d.date}</td>
                    <td className="px-2 py-1.5">
                      <span className="rounded bg-ocean-100/50 px-1.5 py-0.5 text-[10px] text-ocean-700">
                        {v.name}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[10px] text-ink-600">
                      {v.hours.length === 24
                        ? "todas (24)"
                        : v.hours.map((h) => h.toString().padStart(2, "0")).join(",")}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Wrap>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-ink-50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-ink-400">{label}</div>
      <div className="text-base font-semibold text-ink-800">{value}</div>
    </div>
  );
}

function Wrap({
  lat,
  lon,
  children,
}: {
  lat: number;
  lon: number;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2 text-ink-700">
        <MapPin className="h-4 w-4 text-ocean-600" />
        <h3 className="text-sm font-semibold">
          Célula <span className="font-mono">{lat.toFixed(3)}, {lon.toFixed(3)}</span>
        </h3>
      </div>
      {children}
    </div>
  );
}

// Suppress import — used by a subcomponent imported elsewhere; keeps tree-shake
// from yelling about unused export.
void maskToHours;
void popcount;
