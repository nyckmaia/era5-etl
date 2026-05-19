import { Trash2 } from "lucide-react";

import type { TSViewMeta } from "@/lib/api";

import { LocationPicker } from "./LocationPicker";
import type { Agg, SeriesCfg } from "./types";

interface Props {
  index: number;
  metaViews: TSViewMeta[];
  series: SeriesCfg;
  onChange: (s: SeriesCfg) => void;
  onRemove: () => void;
  swatch: string;
}

const AGGS: Agg[] = ["avg", "min", "max", "sum"];

export function SeriesEditor({
  index,
  metaViews,
  series,
  onChange,
  onRemove,
  swatch,
}: Props) {
  const viewMeta = metaViews.find((v) => v.view === series.view);

  function patch(p: Partial<SeriesCfg>) {
    onChange({ ...series, ...p });
  }

  function changeView(view: string) {
    const vm = metaViews.find((v) => v.view === view);
    const firstCol = vm?.numeric_columns[0]?.name ?? "";
    // Reset location to a sane default for the new view's kind.
    const loc =
      vm?.location_kind === "station"
        ? { kind: "point" as const, station_id: null }
        : { kind: "point" as const, lat: null, lon: null };
    patch({ view, yColumn: firstCol, location: loc });
  }

  return (
    <div className="rounded-xl border border-ink-200 bg-ink-50/40 p-3">
      <div className="flex flex-wrap items-end gap-3">
        <span
          className="mb-1 h-3 w-3 shrink-0 rounded-full ring-1 ring-ink-300"
          style={{ background: swatch }}
          title={`Série ${index + 1}`}
        />
        <Field label="View">
          <select
            className="input w-36"
            value={series.view}
            onChange={(e) => changeView(e.target.value)}
          >
            {metaViews.length === 0 && <option value="">—</option>}
            {metaViews.map((v) => (
              <option key={v.view} value={v.view}>
                {v.view.toUpperCase()}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Variável (Y)">
          <select
            className="input w-52"
            value={series.yColumn}
            onChange={(e) => patch({ yColumn: e.target.value })}
          >
            {(viewMeta?.numeric_columns ?? []).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Agregação">
          <select
            className="input w-24"
            value={series.agg}
            onChange={(e) => patch({ agg: e.target.value as Agg })}
          >
            {AGGS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Eixo">
          <select
            className="input w-20"
            value={series.axis}
            onChange={(e) =>
              patch({ axis: e.target.value as "y" | "y2" })
            }
          >
            <option value="y">Y</option>
            <option value="y2">Y2</option>
          </select>
        </Field>

        <Field label="Nome (opcional)">
          <input
            className="input w-44"
            defaultValue={series.name ?? ""}
            placeholder="rótulo da série"
            onBlur={(e) => patch({ name: e.target.value || undefined })}
          />
        </Field>

        <button
          type="button"
          onClick={onRemove}
          className="btn-ghost ml-auto h-9 px-2 text-rose-600"
          title="Remover série"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-3 border-t border-ink-200 pt-3">
        <LocationPicker
          meta={viewMeta}
          value={series.location}
          onChange={(location) => patch({ location })}
        />
      </div>
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
