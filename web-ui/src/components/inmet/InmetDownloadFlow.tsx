import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useState } from "react";

import { RunProgress } from "@/components/RunProgress";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";

/**
 * Dedicated INMET download flow.
 *
 * INMET is a station source: one ZIP per year (all stations), no
 * variables/area/hours/smart-diff/size-estimate. So the ERA5 wizard does
 * not apply -- this is the branch rendered by the /download page when the
 * selected dataset is non-grid. Steps: ERA5/ERA5-LAND prerequisite ->
 * pick years -> run + progress.
 */
export function InmetDownloadFlow() {
  const prereqQ = useQuery({
    queryKey: ["inmet-prerequisite"],
    queryFn: api.inmet.prerequisite,
  });
  const yearsQ = useQuery({
    queryKey: ["inmet-years"],
    queryFn: api.inmet.years,
    retry: false,
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const runMutation = useMutation({
    mutationFn: () => api.inmet.run([...selected].sort((a, b) => a - b)),
  });

  const years = yearsQ.data?.years ?? [];
  const prereqOk = prereqQ.data?.ok ?? false;
  const allSelected = years.length > 0 && selected.size === years.length;

  function toggle(y: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(y) ? next.delete(y) : next.add(y);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
          Download INMET
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Estações meteorológicas do INMET. Um ZIP por ano (todas as
          estações) — sem variáveis, área ou Smart Diff.
        </p>
      </header>

      {/* 1. Prerequisite */}
      <section className="card p-5">
        <h2 className="text-lg font-medium text-ink-800">
          1. Pré-requisito: ERA5 e ERA5-LAND
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          O INMET é comparado contra as grades de reanálise (view{" "}
          <code>era5_inmet</code> e distâncias por estação). É preciso ter ao
          menos o mínimo de cada uma baixado primeiro.
        </p>
        {prereqQ.isLoading ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-ink-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Verificando...
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <PrereqPill label="ERA5" ok={prereqQ.data?.era5 ?? false} />
            <PrereqPill
              label="ERA5-LAND"
              ok={prereqQ.data?.era5_land ?? false}
            />
            {!prereqOk && (
              <div className="flex flex-wrap gap-2">
                {(prereqQ.data?.missing ?? []).map((ds) => (
                  <Link
                    key={ds}
                    to="/download"
                    search={{ dataset: ds, step: 1 }}
                    className="btn-outline text-sm"
                  >
                    Baixar {ds.toUpperCase()} →
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* 2. Year selection */}
      <section
        className={cn("card p-5", !prereqOk && "pointer-events-none opacity-50")}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium text-ink-800">
            2. Anos disponíveis no portal
          </h2>
          {years.length > 0 && (
            <button
              type="button"
              className="text-xs text-ocean-600 hover:underline"
              onClick={() =>
                setSelected(allSelected ? new Set() : new Set(years))
              }
            >
              {allSelected ? "Desmarcar todos" : "Marcar todos"}
            </button>
          )}
        </div>

        {yearsQ.isLoading ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-ink-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Consultando o
            portal INMET...
          </div>
        ) : yearsQ.isError ? (
          <p className="mt-3 text-sm text-amber-700">
            Não foi possível listar os anos do portal INMET (fora do ar ou
            layout mudou). Tente novamente mais tarde.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
            {years.map((y) => {
              const on = selected.has(y);
              return (
                <button
                  key={y}
                  type="button"
                  onClick={() => toggle(y)}
                  className={cn(
                    "rounded-lg border px-2 py-1.5 text-sm tabular-nums",
                    on
                      ? "border-ocean-500 bg-ocean-50 text-ocean-700"
                      : "border-ink-200 text-ink-600 hover:bg-ink-50",
                  )}
                >
                  {y}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* 3. Run */}
      <section className="card p-5">
        <h2 className="text-lg font-medium text-ink-800">3. Executar</h2>
        <p className="mt-1 text-sm text-ink-500">
          {selected.size === 0
            ? "Selecione ao menos um ano."
            : `${selected.size} ano(s) selecionado(s).`}
        </p>
        <button
          className="btn-primary mt-4"
          disabled={
            !prereqOk || selected.size === 0 || runMutation.isPending
          }
          onClick={() => runMutation.mutate()}
        >
          {runMutation.isPending && (
            <Loader2 className="h-4 w-4 animate-spin" />
          )}
          Baixar + processar INMET
        </button>

        {runMutation.isError && (
          <p className="mt-3 text-sm text-amber-700">
            Falha ao iniciar: {(runMutation.error as Error).message}
          </p>
        )}

        {runMutation.data && (
          <div className="mt-5 space-y-4">
            <p className="text-sm text-ink-500">
              Run iniciado:{" "}
              <span className="font-mono">{runMutation.data.run_id}</span>
            </p>
            <RunProgress
              runId={runMutation.data.run_id}
              dataset="inmet"
              kind="station"
            />
            <div className="rounded-xl border border-ink-200 bg-ink-50/60 p-4 text-sm">
              <p className="font-medium text-ink-800">Próximos passos</p>
              <ul className="mt-2 list-inside list-disc space-y-1 text-ink-600">
                <li>
                  <Link
                    to="/inventory"
                    className="text-ocean-600 hover:underline"
                  >
                    Ver as estações no Inventário
                  </Link>{" "}
                  (mapa de pontos por estação).
                </li>
                <li>
                  Comparar com a reanálise via a view{" "}
                  <code>era5_inmet</code> (CLI:{" "}
                  <code>era5 era5-inmet</code>) — INMET alinhado ao ERA5/
                  ERA5-LAND nos 4 vizinhos de grade, mesma data e hora.
                </li>
              </ul>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function PrereqPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm",
        ok
          ? "bg-emerald-50 text-emerald-700"
          : "bg-amber-50 text-amber-700",
      )}
    >
      {ok ? (
        <CheckCircle2 className="h-4 w-4" />
      ) : (
        <AlertTriangle className="h-4 w-4" />
      )}
      {label} {ok ? "pronto" : "faltando"}
    </span>
  );
}
