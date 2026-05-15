import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PanelRightClose,
  Pencil,
  Play,
  Star,
  Trash2,
} from "lucide-react";

import { api, type QueryHistoryEntry } from "@/lib/api";
import { cn } from "@/lib/format";
import { useLocalStorage } from "@/hooks/useLocalStorage";

interface Props {
  view: string;
  collapsed: boolean;
  onToggle: () => void;
  onLoad: (sql: string) => void;
}

const HKEY = (view: string) => ["query", "history", view];

function HistoryPanel({
  view,
  onLoad,
}: {
  view: string;
  onLoad: (sql: string) => void;
}) {
  const qc = useQueryClient();
  const [favOnly, setFavOnly] = useLocalStorage(
    "query.historyFavoritesOnly",
    false,
  );

  const q = useQuery({
    queryKey: HKEY(view),
    queryFn: () => api.queryHistory.list(view),
    enabled: Boolean(view),
  });

  const sync = (entries: QueryHistoryEntry[]) =>
    qc.setQueryData(HKEY(view), entries);

  const patch = useMutation({
    mutationFn: (v: {
      id: string;
      patch: { name?: string | null; favorite?: boolean };
    }) => api.queryHistory.patch(view, v.id, v.patch),
    onSuccess: sync,
  });
  const del = useMutation({
    mutationFn: (id: string) => api.queryHistory.del(view, id),
    onSuccess: sync,
  });
  const clear = useMutation({
    mutationFn: () => api.queryHistory.clear(view),
    onSuccess: sync,
  });

  const entries = (q.data ?? []).filter((e) => !favOnly || e.favorite);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setFavOnly((f) => !f)}
          className={cn(
            "flex items-center gap-1 rounded px-2 py-1 text-[11px]",
            favOnly
              ? "bg-amber-100 text-amber-700"
              : "text-ink-500 hover:bg-ink-100",
          )}
        >
          <Star
            className={cn("h-3 w-3", favOnly && "fill-amber-500 text-amber-500")}
          />
          Favoritas
        </button>
        <button
          type="button"
          onClick={() => clear.mutate()}
          className="text-[11px] text-ink-400 hover:text-red-600"
        >
          Limpar
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {entries.length === 0 ? (
          <p className="px-2 py-4 text-center text-[11px] italic text-ink-400">
            Sem histórico
          </p>
        ) : (
          entries.map((e) => (
            <div
              key={e.id}
              className="group mb-1 rounded-lg border border-ink-100 p-2 text-[11px] hover:border-ink-200"
            >
              <pre className="mb-1 max-h-16 overflow-hidden whitespace-pre-wrap font-mono text-[10px] text-ink-600">
                {e.name ? `★ ${e.name}` : e.sql}
              </pre>
              <div className="flex items-center justify-between text-[10px] text-ink-400">
                <span>
                  {e.rows} rows · {e.elapsed_ms}ms
                </span>
                <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                  <button
                    type="button"
                    title="Carregar"
                    onClick={() => onLoad(e.sql)}
                    className="rounded p-0.5 hover:bg-ocean-100 hover:text-ocean-700"
                  >
                    <Play className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    title="Favoritar"
                    onClick={() =>
                      patch.mutate({
                        id: e.id,
                        patch: { favorite: !e.favorite },
                      })
                    }
                    className="rounded p-0.5 hover:bg-amber-100"
                  >
                    <Star
                      className={cn(
                        "h-3 w-3",
                        e.favorite && "fill-amber-500 text-amber-500",
                      )}
                    />
                  </button>
                  <button
                    type="button"
                    title="Renomear"
                    onClick={() => {
                      const name = window.prompt(
                        "Nome (vazio = remover):",
                        e.name ?? "",
                      );
                      if (name === null) return;
                      patch.mutate({
                        id: e.id,
                        patch: { name: name.trim() || null },
                      });
                    }}
                    className="rounded p-0.5 hover:bg-ink-100"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    title="Excluir"
                    onClick={() => del.mutate(e.id)}
                    className="rounded p-0.5 hover:bg-red-100 hover:text-red-600"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function TemplatesPanel({ onLoad }: { onLoad: (sql: string) => void }) {
  const q = useQuery({
    queryKey: ["query", "templates"],
    queryFn: api.queryTemplates,
  });
  return (
    <div className="flex-1 overflow-y-auto p-2">
      {(q.data ?? []).map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onLoad(t.sql)}
          className="mb-1 w-full rounded-lg border border-ink-100 p-2 text-left hover:border-ocean-200 hover:bg-ocean-50"
        >
          <div className="text-xs font-medium text-ink-700">{t.name}</div>
          {t.category ? (
            <div className="text-[10px] uppercase tracking-wide text-ink-400">
              {t.category}
            </div>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function RightSidebar({ view, collapsed, onToggle, onLoad }: Props) {
  const [tab, setTab] = useLocalStorage<"templates" | "history">(
    "query.rightTab",
    "history",
  );

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title="Mostrar painel"
        className="flex h-full w-11 shrink-0 flex-col items-center gap-2 border-l border-ink-200 py-3 text-ink-400 hover:text-ink-700"
      >
        <Star className="h-4 w-4" />
        <span className="[writing-mode:vertical-rl] text-[10px] uppercase tracking-wide">
          Histórico
        </span>
      </button>
    );
  }

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-ink-200">
      <div className="flex items-center justify-between border-b border-ink-100 px-2 py-1.5">
        <div className="flex gap-1">
          {(["history", "templates"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={cn(
                "rounded px-2 py-1 text-[11px] font-medium capitalize",
                tab === t
                  ? "bg-ocean-600 text-white"
                  : "text-ink-500 hover:bg-ink-100",
              )}
            >
              {t === "history" ? "Histórico" : "Templates"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-0.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
          aria-label="Recolher"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>
      {tab === "history" ? (
        <HistoryPanel view={view} onLoad={onLoad} />
      ) : (
        <TemplatesPanel onLoad={onLoad} />
      )}
    </div>
  );
}
