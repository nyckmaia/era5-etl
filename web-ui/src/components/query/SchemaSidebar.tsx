import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
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
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { api, type UserObject } from "@/lib/api";
import { cn } from "@/lib/format";

/**
 * Extract referenced names DuckDB reported as missing from a user-view
 * error message. DuckDB phrasing varies by version and by what kind of
 * binder lookup failed; this captures the common cases. Anything not
 * matched falls back to the full error string in the UI tooltip.
 */
function extractMissingRefs(error: string): string[] {
  const patterns: RegExp[] = [
    /Table with name ["']?([\w.-]+)["']? does not exist/gi,
    /View with name ["']?([\w.-]+)["']? does not exist/gi,
    /Table or view ["']?([\w.-]+)["']? does not exist/gi,
    /Referenced (?:table|view|column) ["']?([\w.-]+)["']?/gi,
    /relation ["']?([\w.-]+)["']? does not exist/gi,
  ];
  const names = new Set<string>();
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(error)) !== null) {
      // Ignore obviously-unhelpful captures (e.g., partial matches that
      // are actually keywords).
      if (m[1] && m[1].length > 0 && !/^(?:select|from|where)$/i.test(m[1])) {
        names.add(m[1]);
      }
    }
  }
  return [...names];
}

interface Props {
  datasets: string[];
  userObjects: UserObject[];
  collapsed: boolean;
  onToggle: () => void;
  onInsert: (text: string) => void;
  onNewView: () => void;
  onEditView: (o: UserObject) => void;
  /** Load an object's defining SQL into the editor (system builtins). */
  onOpenSql: (o: UserObject) => void;
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
  const { t } = useTranslation();
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
          {t("query.schema.noData")}
        </li>
      ) : (
        cols.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              onClick={() => onInsert(c.name)}
              title={t("query.insert", { name: c.name })}
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
  const { t } = useTranslation();
  // Collapsed by default — the user expands what they need.
  const [open, setOpen] = useState(false);
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
            title={t("query.schema.schemaError")}
          >
            {t("query.schema.schemaError")}
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

function WarnBadge({ obj }: { obj: UserObject }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const missing = extractMissingRefs(obj.error ?? "");
  const hoverTitle =
    missing.length > 0
      ? t("query.schema.warnBadge.hoverMissing", {
          names: missing.join(", "),
        })
      : (obj.error ?? t("query.schema.warnBadge.hoverGeneric"));
  return (
    <>
      <button
        type="button"
        title={hoverTitle}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className="shrink-0 rounded bg-amber-100 px-1.5 py-px text-[9px] font-bold uppercase tracking-wider text-amber-800 ring-1 ring-amber-300 transition hover:bg-amber-200"
        aria-expanded={open}
        aria-label={t("query.schema.warnBadge.ariaLabel")}
      >
        {t("query.schema.warnBadge.label")}
      </button>
      {open ? (
        <div
          className={cn(
            "absolute left-0 right-2 z-10 mt-1 origin-top-left rounded-lg border border-amber-300 bg-amber-50/95 p-3 text-[11px] leading-relaxed text-amber-900 shadow-md backdrop-blur",
          )}
          style={{ top: "100%" }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" />
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-amber-900">
                {t("query.schema.warnPopover.title")}
              </div>
              <p className="mt-1">
                {missing.length > 0
                  ? t("query.schema.warnPopover.bodyWithList", { name: obj.name })
                  : t("query.schema.warnPopover.bodyWithoutList", { name: obj.name })}
              </p>
              {missing.length > 0 ? (
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4 font-mono text-[11px]">
                  {missing.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              ) : null}
              <p className="mt-2 text-amber-800/90">
                {t("query.schema.warnPopover.action")}
              </p>
              {obj.error && missing.length === 0 ? (
                <pre className="mt-2 max-h-32 overflow-auto rounded bg-amber-100/70 p-2 font-mono text-[10px] leading-snug text-amber-900">
                  {obj.error}
                </pre>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}


function UserObjectNode({
  obj,
  onInsert,
  onEditView,
  onOpenSql,
}: {
  obj: UserObject;
  onInsert: (text: string) => void;
  onEditView: (o: UserObject) => void;
  onOpenSql: (o: UserObject) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.userViews.del(obj.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-views"] });
      qc.invalidateQueries({ queryKey: ["query-schema"] });
      toast.success(t("query.schema.removed", { name: obj.name }));
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const isMacro = obj.kind === "macro";

  return (
    <div className="group relative mb-2">
      <div className="flex w-full items-center gap-1 rounded px-1 py-1 text-xs font-medium text-ink-700 hover:bg-ink-100">
        <button
          type="button"
          // Builtins: clicking loads their defining SQL into the editor
          // (read-only objects — there is nothing to expand/edit).
          onClick={() => {
            if (obj.builtin) onOpenSql(obj);
            else if (!isMacro) setOpen((o) => !o);
          }}
          title={obj.builtin ? t("query.schema.builtinOpenSql") : undefined}
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
        </button>
        {!obj.ok ? <WarnBadge obj={obj} /> : null}
        {obj.builtin ? (
          <span
            className="shrink-0 rounded bg-ink-100 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider text-ink-500"
            title={t("query.schema.builtinHint")}
          >
            {t("query.schema.builtinBadge")}
          </span>
        ) : (
          <>
            <button
              type="button"
              title={t("common.edit")}
              onClick={() => onEditView(obj)}
              className="hidden text-ink-400 hover:text-ink-700 group-hover:block"
            >
              <Pencil className="h-3 w-3" />
            </button>
            <button
              type="button"
              title={t("common.delete")}
              onClick={() => del.mutate()}
              className="hidden text-ink-400 hover:text-rose-500 group-hover:block"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </>
        )}
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
  onOpenSql,
}: Props) {
  const { t } = useTranslation();
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
        okCount === total
          ? t("query.schema.allViewsLoaded", { total })
          : t("query.schema.partialLoaded", { ok: okCount, total }),
      );
      setShowDone(true);
      const id = setTimeout(() => setShowDone(false), 4000);
      return () => clearTimeout(id);
    }
    if (!allDone) notified.current = false;
  }, [allDone, okCount, total, t]);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title={t("query.schema.showSchema")}
        className="flex h-full w-11 shrink-0 flex-col items-center gap-2 border-r border-ink-200 py-3 text-ink-400 hover:text-ink-700"
      >
        <Table2 className="h-4 w-4" />
        <span className="[writing-mode:vertical-rl] text-[10px] uppercase tracking-wide">
          {t("query.schema.title")}
        </span>
      </button>
    );
  }

  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r border-ink-200">
      <div className="flex items-center justify-between border-b border-ink-100 px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          {t("query.schema.title")}
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-0.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
          aria-label={t("query.schema.collapseSchema")}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <p className="mb-1 flex items-center gap-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
          <Database className="h-3 w-3" /> {t("query.schema.sistema")}
        </p>

        {loading ? (
          <div className="mb-2 px-1">
            <div className="flex items-center gap-1 text-[10px] text-ink-500">
              <Loader2 className="h-3 w-3 animate-spin text-ocean-500" />
              {t("query.schema.loadingViews", { settled, total })}
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
              ? t("query.schema.allViewsLoaded", { total })
              : t("query.schema.partialLoaded", { ok: okCount, total })}
          </div>
        ) : null}

        {datasets.map((d) => (
          <ViewNode key={d} dataset={d} onInsert={onInsert} />
        ))}

        <div className="mb-1 mt-3 flex items-center justify-between px-1">
          <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
            <Sparkles className="h-3 w-3" /> {t("query.schema.myViews")}
          </p>
          <button
            type="button"
            title={t("query.schema.newView")}
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
            {t("query.schema.createFromSystem")}
          </button>
        ) : (
          userObjects.map((o) => (
            <UserObjectNode
              key={o.id}
              obj={o}
              onInsert={onInsert}
              onEditView={onEditView}
              onOpenSql={onOpenSql}
            />
          ))
        )}
      </div>
    </div>
  );
}
