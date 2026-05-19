import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  FunctionSquare,
  Loader2,
  Pencil,
  Plus,
  PanelLeftClose,
  Sparkles,
  Table2,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, type UserObject } from "@/lib/api";

interface Props {
  datasets: string[];
  userObjects: UserObject[];
  collapsed: boolean;
  onToggle: () => void;
  onInsert: (text: string) => void;
  onNewView: () => void;
  onEditView: (o: UserObject) => void;
}

function ColumnList({
  cols,
  loading,
  onInsert,
}: {
  cols: { name: string; type: string }[];
  loading: boolean;
  onInsert: (text: string) => void;
}) {
  return (
    <ul className="ml-4 mt-0.5 border-l border-ink-100 pl-2">
      {loading ? (
        Array.from({ length: 4 }).map((_, i) => (
          <li key={i} className="px-1 py-0.5">
            <div
              className="h-2.5 animate-pulse rounded bg-ink-100"
              style={{ width: `${70 - i * 12}%` }}
            />
          </li>
        ))
      ) : cols.length === 0 ? (
        <li className="px-1 py-0.5 text-[11px] italic text-ink-400">
          sem dados
        </li>
      ) : (
        cols.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              onClick={() => onInsert(c.name)}
              title={`Inserir "${c.name}"`}
              className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-[11px] hover:bg-ocean-50"
            >
              <span className="truncate text-ink-700">{c.name}</span>
              <span className="ml-auto shrink-0 text-[10px] text-ink-400">
                {c.type}
              </span>
            </button>
          </li>
        ))
      )}
    </ul>
  );
}

function ViewNode({
  dataset,
  onInsert,
}: {
  dataset: string;
  onInsert: (text: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const q = useQuery({
    queryKey: ["query-schema", dataset],
    queryFn: () => api.querySchema(dataset),
  });
  const view = q.data?.view ?? dataset.replace(/-/g, "_");
  const cols = q.data?.columns ?? [];

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 rounded px-1 py-1 text-left text-xs font-medium text-ink-700 hover:bg-ink-100"
      >
        {open ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        <Table2 className="h-3.5 w-3.5 shrink-0 text-ocean-500" />
        <span className="truncate">{view}</span>
        {q.isLoading ? (
          <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-ocean-400" />
        ) : q.isError ? (
          <span
            className="ml-auto shrink-0 text-[10px] font-medium text-rose-500"
            title="Falha ao carregar o schema"
          >
            erro
          </span>
        ) : (
          <span className="ml-auto text-[10px] text-ink-400">
            {cols.length}
          </span>
        )}
      </button>
      {open ? (
        <ColumnList cols={cols} loading={q.isLoading} onInsert={onInsert} />
      ) : null}
    </div>
  );
}

function UserObjectNode({
  obj,
  onInsert,
  onEditView,
}: {
  obj: UserObject;
  onInsert: (text: string) => void;
  onEditView: (o: UserObject) => void;
}) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.userViews.del(obj.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-views"] });
      qc.invalidateQueries({ queryKey: ["query-schema"] });
      toast.success(`"${obj.name}" removido`);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const isMacro = obj.kind === "macro";

  return (
    <div className="group mb-2">
      <div className="flex w-full items-center gap-1 rounded px-1 py-1 text-xs font-medium text-ink-700 hover:bg-ink-100">
        <button
          type="button"
          onClick={() => !isMacro && setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-1 text-left"
        >
          {isMacro ? (
            <span className="w-3" />
          ) : open ? (
            <ChevronDown className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" />
          )}
          {isMacro ? (
            <FunctionSquare className="h-3.5 w-3.5 shrink-0 text-violet-500" />
          ) : (
            <Table2 className="h-3.5 w-3.5 shrink-0 text-violet-500" />
          )}
          <span className="truncate">{obj.name}</span>
          {!obj.ok ? (
            <span
              title={obj.error ?? "erro"}
              className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500"
            />
          ) : null}
        </button>
        <button
          type="button"
          title="Editar"
          onClick={() => onEditView(obj)}
          className="hidden text-ink-400 hover:text-ink-700 group-hover:block"
        >
          <Pencil className="h-3 w-3" />
        </button>
        <button
          type="button"
          title="Excluir"
          onClick={() => del.mutate()}
          className="hidden text-ink-400 hover:text-rose-500 group-hover:block"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      {open && !isMacro ? (
        <ColumnList cols={obj.columns} loading={false} onInsert={onInsert} />
      ) : null}
    </div>
  );
}

export function SchemaSidebar({
  datasets,
  userObjects,
  collapsed,
  onToggle,
  onInsert,
  onNewView,
  onEditView,
}: Props) {
  // Aggregate the per-view schema loads (same query key/fn as ViewNode,
  // so React Query dedupes — no double fetch). Drives the progress
  // indicator and the one-time "all loaded" notice.
  const schemaQs = useQueries({
    queries: datasets.map((d) => ({
      queryKey: ["query-schema", d],
      queryFn: () => api.querySchema(d),
    })),
  });
  const total = datasets.length;
  const settled = schemaQs.filter((q) => q.isSuccess || q.isError).length;
  const okCount = schemaQs.filter((q) => q.isSuccess).length;
  const loading = total > 0 && settled < total;
  const allDone = total > 0 && settled === total;

  const [showDone, setShowDone] = useState(false);
  const notified = useRef(false);
  useEffect(() => {
    if (allDone && !notified.current) {
      notified.current = true;
      toast.success(
        `${okCount} de ${total} view${total === 1 ? "" : "s"} carregada${
          total === 1 ? "" : "s"
        }`,
      );
      setShowDone(true);
      const t = setTimeout(() => setShowDone(false), 4000);
      return () => clearTimeout(t);
    }
    if (!allDone) notified.current = false;
  }, [allDone, okCount, total]);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title="Mostrar schema"
        className="flex h-full w-11 shrink-0 flex-col items-center gap-2 border-r border-ink-200 py-3 text-ink-400 hover:text-ink-700"
      >
        <Table2 className="h-4 w-4" />
        <span className="[writing-mode:vertical-rl] text-[10px] uppercase tracking-wide">
          Schema
        </span>
      </button>
    );
  }

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r border-ink-200">
      <div className="flex items-center justify-between border-b border-ink-100 px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Schema
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-0.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
          aria-label="Recolher"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <p className="mb-1 flex items-center gap-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          <Database className="h-3 w-3" /> Sistema
        </p>

        {loading ? (
          <div className="mb-2 px-1">
            <div className="flex items-center gap-1 text-[10px] text-ink-500">
              <Loader2 className="h-3 w-3 animate-spin text-ocean-500" />
              Carregando views… {settled}/{total}
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-ink-100">
              <div
                className="h-full rounded-full bg-ocean-500 transition-all duration-300"
                style={{
                  width: `${total ? (settled / total) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        ) : showDone ? (
          <div className="mb-2 flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-[10px] font-medium text-emerald-700 transition-opacity">
            <CheckCircle2 className="h-3 w-3" />
            {okCount === total
              ? `Todas as ${total} views carregadas`
              : `${okCount}/${total} views carregadas`}
          </div>
        ) : null}

        {datasets.map((d) => (
          <ViewNode key={d} dataset={d} onInsert={onInsert} />
        ))}

        <div className="mb-1 mt-3 flex items-center justify-between px-1">
          <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
            <Sparkles className="h-3 w-3" /> Minhas views & macros
          </p>
          <button
            type="button"
            title="Nova VIEW personalizada"
            onClick={onNewView}
            className="rounded p-0.5 text-ocean-600 hover:bg-ocean-50"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
        {userObjects.length === 0 ? (
          <button
            type="button"
            onClick={onNewView}
            className="w-full rounded border border-dashed border-ink-200 px-2 py-2 text-[11px] text-ink-400 hover:border-ocean-300 hover:text-ocean-600"
          >
            ＋ criar a partir das views do sistema
          </button>
        ) : (
          userObjects.map((o) => (
            <UserObjectNode
              key={o.id}
              obj={o}
              onInsert={onInsert}
              onEditView={onEditView}
            />
          ))
        )}
      </div>
    </div>
  );
}
