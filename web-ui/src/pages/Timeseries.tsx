import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, LineChart, Plus } from "lucide-react";
import { useMemo } from "react";

import { ChartCell, defaultSeries } from "@/components/timeseries/ChartCell";
import type { Cell, Notebook } from "@/components/timeseries/types";
import { newId } from "@/components/timeseries/types";
import { api, type TSViewMeta } from "@/lib/api";
import { useLocalStorage } from "@/hooks/useLocalStorage";

const EMPTY: Notebook = { version: 1, cells: [] };

function makeCell(metaViews: TSViewMeta[], title: string): Cell {
  return {
    id: newId(),
    title,
    dateFrom: "",
    dateTo: "",
    bucket: "raw",
    maxPoints: 20000,
    series: [defaultSeries(metaViews)],
    traceStyles: {},
    layout: { title: "", logY: false, logY2: false, showLegend: true },
  };
}

export function TimeseriesPage() {
  const [nb, setNb] = useLocalStorage<Notebook>(
    "timeseries.notebook.v1",
    EMPTY,
  );
  const notebook = nb && nb.version === 1 ? nb : EMPTY;

  const metaQ = useQuery({
    queryKey: ["timeseries-meta"],
    queryFn: api.timeseries.meta,
  });
  const metaViews = useMemo(
    () => metaQ.data?.views ?? [],
    [metaQ.data],
  );

  function setCells(cells: Cell[]) {
    setNb({ version: 1, cells });
  }
  function addCell() {
    setCells([
      ...notebook.cells,
      makeCell(metaViews, `Gráfico ${notebook.cells.length + 1}`),
    ]);
  }
  function updateCell(i: number, c: Cell) {
    const cells = [...notebook.cells];
    cells[i] = c;
    setCells(cells);
  }
  function removeCell(i: number) {
    setCells(notebook.cells.filter((_, j) => j !== i));
  }
  function duplicateCell(i: number) {
    const src = notebook.cells[i];
    const copy: Cell = {
      ...src,
      id: newId(),
      title: `${src.title} (cópia)`,
      series: src.series.map((s) => ({ ...s, id: newId() })),
      traceStyles: {},
    };
    const cells = [...notebook.cells];
    cells.splice(i + 1, 0, copy);
    setCells(cells);
  }
  function moveCell(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= notebook.cells.length) return;
    const cells = [...notebook.cells];
    [cells[i], cells[j]] = [cells[j], cells[i]];
    setCells(cells);
  }

  // The /meta call registers every view, builds era5_inmet, introspects
  // schemas and queries the coverage/station indexes — it can take a
  // moment. Block the whole UI until it settles so the user never picks
  // from half-populated selectors.
  const loading = metaQ.isPending;
  const failed = metaQ.isError;
  const noData = !loading && !failed && metaViews.length === 0;
  const blocked = loading || failed;

  return (
    <div className="space-y-5">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-3xl font-semibold tracking-tight text-ink-800">
            <LineChart className="h-7 w-7 text-ocean-600" />
            Time Series
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-500">
            Notebook de gráficos para analisar e correlacionar séries
            temporais. Cada célula é um gráfico Plotly; cada série escolhe
            view, variável e um ponto/região. O eixo X combina data e hora
            (UTC).
          </p>
        </div>
        <button
          type="button"
          className="btn-primary shrink-0"
          onClick={addCell}
          disabled={noData || blocked}
        >
          <Plus className="h-4 w-4" />
          Novo gráfico
        </button>
      </header>

      {loading ? (
        <div
          className="card relative flex flex-col items-center justify-center gap-3 p-14 text-center"
          aria-busy="true"
          aria-live="polite"
        >
          {/* Soft scrim to make the blocked state unmistakable */}
          <Loader2 className="h-9 w-9 animate-spin text-ocean-600" />
          <p className="text-base font-semibold text-ink-800">
            Preparando a análise de séries temporais…
          </p>
          <p className="max-w-md text-sm text-ink-500">
            O sistema está computando os dados em segundo plano: registrando
            as views (ERA5, ERA5-LAND, INMET, era5_inmet), inspecionando as
            colunas e calculando o intervalo de datas disponível de cada
            dataset.
          </p>
          <p className="text-xs font-medium text-amber-700">
            A interface está bloqueada — aguarde a finalização antes de
            interagir.
          </p>
        </div>
      ) : failed ? (
        <div className="card flex flex-col items-center justify-center gap-3 p-12 text-center">
          <AlertTriangle className="h-8 w-8 text-rose-500" />
          <p className="text-sm font-medium text-ink-700">
            Falha ao carregar os metadados das séries temporais.
          </p>
          <p className="max-w-md text-xs text-ink-400">
            {(metaQ.error as Error)?.message ?? "Erro desconhecido."}
          </p>
          <button
            type="button"
            className="btn-outline"
            onClick={() => metaQ.refetch()}
          >
            <Loader2 className="h-4 w-4" />
            Tentar novamente
          </button>
        </div>
      ) : noData ? (
        <div className="card flex flex-col items-center justify-center gap-2 p-12 text-center">
          <LineChart className="h-8 w-8 text-ink-300" />
          <p className="text-sm font-medium text-ink-700">
            Nenhum dado disponível ainda.
          </p>
          <p className="text-xs text-ink-400">
            Baixe ERA5, ERA5-LAND ou INMET na página Download para começar.
          </p>
        </div>
      ) : notebook.cells.length === 0 ? (
        <div className="card flex flex-col items-center justify-center gap-3 p-12 text-center">
          <p className="text-sm text-ink-500">
            Nenhum gráfico ainda. Crie o primeiro.
          </p>
          <button
            type="button"
            className="btn-primary"
            onClick={addCell}
          >
            <Plus className="h-4 w-4" />
            Novo gráfico
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {notebook.cells.map((cell, i) => (
            <ChartCell
              key={cell.id}
              cell={cell}
              index={i}
              total={notebook.cells.length}
              metaViews={metaViews}
              onChange={(c) => updateCell(i, c)}
              onRemove={() => removeCell(i)}
              onDuplicate={() => duplicateCell(i)}
              onMove={(dir) => moveCell(i, dir)}
            />
          ))}
          <button
            type="button"
            className="btn-outline w-full justify-center"
            onClick={addCell}
          >
            <Plus className="h-4 w-4" />
            Adicionar gráfico
          </button>
        </div>
      )}
    </div>
  );
}
