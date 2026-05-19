import type { SeriesCfg, TraceStyle, CellLayout } from "./types";
import { DEFAULT_STYLE } from "./PlotlyChart";

interface Props {
  series: SeriesCfg[];
  styles: Record<string, TraceStyle>;
  onStyle: (id: string, st: TraceStyle) => void;
  layout: CellLayout;
  onLayout: (l: CellLayout) => void;
}

export function TraceStylePanel({
  series,
  styles,
  onStyle,
  layout,
  onLayout,
}: Props) {
  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Estilo por série
        </h4>
        <div className="mt-2 space-y-2">
          {series.map((s, i) => {
            const st = styles[s.id] ?? DEFAULT_STYLE;
            const set = (p: Partial<TraceStyle>) =>
              onStyle(s.id, { ...st, ...p });
            return (
              <div
                key={s.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-100 bg-white px-3 py-2 text-xs"
              >
                <span className="font-medium text-ink-700">
                  #{i + 1} {s.name || `${s.view}.${s.yColumn}`}
                </span>
                <label className="flex items-center gap-1.5">
                  Cor
                  <input
                    type="color"
                    value={st.color}
                    onChange={(e) => set({ color: e.target.value })}
                    className="h-7 w-9 cursor-pointer rounded border border-ink-200 bg-white p-0.5"
                  />
                </label>
                <label className="flex items-center gap-1.5">
                  Linha
                  <select
                    className="input h-8 py-0"
                    value={st.dash}
                    onChange={(e) =>
                      set({ dash: e.target.value as TraceStyle["dash"] })
                    }
                  >
                    <option value="solid">sólida</option>
                    <option value="dash">tracejada</option>
                    <option value="dot">pontilhada</option>
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  Espessura
                  <input
                    type="number"
                    min={1}
                    max={8}
                    value={st.width}
                    onChange={(e) =>
                      set({ width: Number(e.target.value) || 1 })
                    }
                    className="input h-8 w-16 py-0"
                  />
                </label>
                <label className="flex items-center gap-1.5">
                  Modo
                  <select
                    className="input h-8 py-0"
                    value={st.mode}
                    onChange={(e) =>
                      set({ mode: e.target.value as TraceStyle["mode"] })
                    }
                  >
                    <option value="lines">linhas</option>
                    <option value="lines+markers">linhas+pontos</option>
                    <option value="markers">pontos</option>
                  </select>
                </label>
              </div>
            );
          })}
          {series.length === 0 && (
            <p className="text-xs text-ink-400">Sem séries.</p>
          )}
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Gráfico
        </h4>
        <div className="mt-2 flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5">
            Título
            <input
              className="input h-8 w-56 py-0"
              defaultValue={layout.title}
              onBlur={(e) => onLayout({ ...layout, title: e.target.value })}
            />
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={layout.logY}
              onChange={(e) =>
                onLayout({ ...layout, logY: e.target.checked })
              }
            />
            log Y
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={layout.logY2}
              onChange={(e) =>
                onLayout({ ...layout, logY2: e.target.checked })
              }
            />
            log Y2
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={layout.showLegend}
              onChange={(e) =>
                onLayout({ ...layout, showLegend: e.target.checked })
              }
            />
            legenda
          </label>
        </div>
      </div>
    </div>
  );
}
