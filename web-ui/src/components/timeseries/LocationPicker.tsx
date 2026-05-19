import { useQuery } from "@tanstack/react-query";
import { Map as MapIcon } from "lucide-react";
import { useState } from "react";

import { api, type TSLocation, type TSViewMeta } from "@/lib/api";
import { cn } from "@/lib/format";

import { MapPicker } from "./MapPicker";

interface Props {
  meta: TSViewMeta | undefined;
  value: TSLocation;
  onChange: (loc: TSLocation) => void;
}

function num(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function LocationPicker({ meta, value, onChange }: Props) {
  const isStation = meta?.location_kind === "station";
  const res = meta?.grid_resolution ?? null;
  const [mapOpen, setMapOpen] = useState(false);

  // Station list (only fetched for station views) to power a datalist.
  const stationsQ = useQuery({
    queryKey: ["inv-stations", "inmet"],
    queryFn: () => api.inventory.stations("inmet"),
    enabled: isStation,
  });

  function snap(v: number | null): number | null {
    if (v == null || !res) return v;
    const snapped = Math.round(v / res) * res;
    const dec = res < 1 ? (String(res).split(".")[1]?.length ?? 6) : 0;
    return Number(snapped.toFixed(dec));
  }

  function patch(p: Partial<TSLocation>) {
    onChange({ ...value, ...p });
  }

  const KindToggle = (
    <div className="inline-flex overflow-hidden rounded-lg border border-ink-200 text-xs">
      {(["point", "region"] as const).map((k) => (
        <button
          key={k}
          type="button"
          onClick={() => patch({ kind: k })}
          className={cn(
            "px-2.5 py-1 transition-colors",
            value.kind === k
              ? "bg-ocean-600 text-white"
              : "bg-white text-ink-600 hover:bg-ink-50",
          )}
        >
          {k === "point" ? (isStation ? "Estação" : "Ponto") : "Região"}
        </button>
      ))}
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {KindToggle}
        {value.kind === "point" && meta && (
          <button
            type="button"
            onClick={() => setMapOpen(true)}
            className="btn-outline h-8 px-2.5 text-xs"
            title="Escolher no mapa"
          >
            <MapIcon className="h-3.5 w-3.5" />
            Escolher no mapa
          </button>
        )}
        {value.kind === "point" && (
          <span className="text-[11px] text-ink-400">
            {isStation
              ? value.station_id
                ? `estação ${value.station_id}`
                : "nenhuma estação"
              : value.lat != null && value.lon != null
                ? `lat ${value.lat}, lon ${value.lon}`
                : "nenhum ponto"}
          </span>
        )}
      </div>

      {mapOpen && meta && (
        <MapPicker
          meta={meta}
          onPick={(loc) => patch(loc)}
          onClose={() => setMapOpen(false)}
        />
      )}

      {!isStation && value.kind === "point" && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={`Lat${res ? ` (grade ${res}°)` : ""}`}>
            <input
              key={`lat-${value.lat ?? ""}`}
              type="number"
              step="any"
              className="input w-28"
              defaultValue={value.lat ?? ""}
              onBlur={(e) =>
                patch({ lat: snap(num(e.target.value)) })
              }
            />
          </Field>
          <Field label="Lon">
            <input
              key={`lon-${value.lon ?? ""}`}
              type="number"
              step="any"
              className="input w-28"
              defaultValue={value.lon ?? ""}
              onBlur={(e) =>
                patch({ lon: snap(num(e.target.value)) })
              }
            />
          </Field>
        </div>
      )}

      {!isStation && value.kind === "region" && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(
            [
              ["north", "Norte"],
              ["south", "Sul"],
              ["west", "Oeste"],
              ["east", "Leste"],
            ] as const
          ).map(([k, lbl]) => (
            <Field key={k} label={lbl}>
              <input
                type="number"
                step="any"
                className="input w-full"
                defaultValue={(value[k] as number | null) ?? ""}
                onBlur={(e) => patch({ [k]: num(e.target.value) })}
              />
            </Field>
          ))}
        </div>
      )}

      {isStation && value.kind === "point" && (
        <Field label="Estação (código WMO)">
          <input
            key={`sid-${value.station_id ?? ""}`}
            list="ts-stations"
            className="input w-56"
            placeholder="A001"
            defaultValue={value.station_id ?? ""}
            onBlur={(e) => patch({ station_id: e.target.value || null })}
          />
          <datalist id="ts-stations">
            {(stationsQ.data?.stations ?? []).map((s) => (
              <option key={s.station_id} value={s.station_id}>
                {s.nome ?? ""} {s.uf ? `(${s.uf})` : ""}
              </option>
            ))}
          </datalist>
        </Field>
      )}

      {isStation && value.kind === "region" && (
        <Field label="UF (todas as estações da UF)">
          <input
            className="input w-28"
            placeholder="DF"
            defaultValue={value.uf ?? ""}
            onBlur={(e) =>
              patch({ uf: e.target.value.toUpperCase() || null })
            }
          />
        </Field>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wide text-ink-500">
        {label}
      </span>
      <div className="mt-0.5">{children}</div>
    </label>
  );
}
