import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, Plus, Trash2, X } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api, type BuildSpec, type UserObject } from "@/lib/api";
import { cn } from "@/lib/format";
import { formatSql } from "@/lib/sql";

const SqlPreview = lazy(() => import("@/components/query/SqlPreview"));

const IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const APPROX_COLS = new Set(["latitude", "longitude"]);

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Base view names (era5, era5_land, inmet). */
  datasets: string[];
  editing?: UserObject | null;
}

interface JoinRow {
  left: string; // "alias.col"
  right: string; // "col" (of this source)
  approx: boolean;
  epsilon: number;
}

function aliasFor(view: string, taken: Set<string>): string {
  const base = view
    .split("_")
    .map((p) => p[0])
    .join("");
  let a = base || "v";
  let n = 1;
  while (taken.has(a)) a = `${base}${++n}`;
  taken.add(a);
  return a;
}

/**
 * Visual builder: pick columns across the base views, configure JOINs
 * (equi or epsilon), and watch the generated SQL rewrite live on the
 * right before saving it as a VIEW.
 */
export function ViewBuilderModal({
  open,
  onOpenChange,
  datasets,
  editing,
}: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]); // ordered view names
  const [cols, setCols] = useState<Record<string, string[]>>({});
  const [joinType, setJoinType] = useState<"INNER" | "LEFT">("LEFT");
  const [joins, setJoins] = useState<Record<string, JoinRow[]>>({});
  const [sql, setSql] = useState("");
  const [preview, setPreview] = useState<{
    ok: boolean;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setPicked([]);
      setCols({});
      setJoins({});
      setJoinType("LEFT");
      setSql("");
      setPreview(null);
    }
  }, [open, editing]);

  // Stable alias per picked view (recomputed from order).
  const aliases = useMemo(() => {
    const taken = new Set<string>();
    const m: Record<string, string> = {};
    for (const v of picked) m[v] = aliasFor(v, taken);
    return m;
  }, [picked]);

  const schemaQueries = useQueries({
    queries: picked.map((v) => ({
      queryKey: ["query-schema", v],
      queryFn: () => api.querySchema(v),
    })),
  });
  const schemaByView: Record<string, string[]> = {};
  picked.forEach((v, i) => {
    schemaByView[v] = (schemaQueries[i].data?.columns ?? []).map(
      (c) => c.name,
    );
  });

  function togglePick(v: string) {
    setPicked((p) =>
      p.includes(v) ? p.filter((x) => x !== v) : [...p, v],
    );
  }
  function toggleCol(v: string, c: string) {
    setCols((m) => {
      const cur = m[v] ?? [];
      return {
        ...m,
        [v]: cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c],
      };
    });
  }

  const spec: BuildSpec = useMemo(() => {
    const sources = picked
      .filter((v) => (cols[v] ?? []).length > 0)
      .map((v) => ({
        view: v.replace(/-/g, "_"),
        alias: aliases[v],
        columns: cols[v] ?? [],
      }));
    const joinPairs = picked.flatMap((v) => {
      const a = aliases[v];
      return (joins[a] ?? [])
        .filter((j) => j.left && j.right)
        .map((j) => ({
          left: j.left,
          right: `${a}.${j.right}`,
          approx: j.approx,
          epsilon: j.epsilon,
        }));
    });
    return {
      name: name || "untitled",
      join_type: joinType,
      sources,
      joins: joinPairs,
    };
  }, [picked, cols, aliases, joins, joinType, name]);

  // Live SQL (debounced) + server validation.
  useEffect(() => {
    if (!open || spec.sources.length === 0) {
      setSql("");
      setPreview(null);
      return;
    }
    const t = setTimeout(() => {
      api.userViews
        .buildSql(spec)
        .then((r) => {
          setSql(r.sql);
          return api.userViews.preview({
            name: spec.name,
            kind: "view",
            sql: r.sql,
          });
        })
        .then((p) => p && setPreview({ ok: p.ok, error: p.error }))
        .catch((e) => {
          setSql("");
          setPreview({ ok: false, error: (e as Error).message });
        });
    }, 400);
    return () => clearTimeout(t);
  }, [open, spec]);

  const nameValid = IDENT_RE.test(name);

  const save = useMutation({
    mutationFn: () => {
      const body = { name, kind: "view", sql: formatSql(sql) };
      return editing
        ? api.userViews.update(editing.id, body)
        : api.userViews.create(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-views"] });
      qc.invalidateQueries({ queryKey: ["query-schema"] });
      toast.success(`"${name}" salvo no SCHEMA`);
      onOpenChange(false);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const nonHead = picked.slice(1);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-900/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[85vh] w-[min(64rem,94vw)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-ink-100 bg-white shadow-card">
          <div className="flex items-center justify-between border-b border-ink-100 px-5 py-3">
            <Dialog.Title className="text-sm font-semibold text-ink-800">
              {editing ? `Editar "${editing.name}"` : "Nova VIEW personalizada"}
            </Dialog.Title>
            <Dialog.Close className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-2">
            {/* Left: configuration */}
            <div className="min-h-0 space-y-5 overflow-y-auto border-r border-ink-100 p-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  1 · Fontes
                </p>
                <p className="mb-2 text-[11px] text-ink-400">
                  Clique para incluir/remover uma view. Selecionadas ficam
                  em azul com ✓.
                </p>
                <div className="flex flex-wrap gap-2">
                  {datasets.map((v) => {
                    const on = picked.includes(v);
                    return (
                      <button
                        key={v}
                        type="button"
                        aria-pressed={on}
                        onClick={() => togglePick(v)}
                        className={cn(
                          "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
                          on
                            ? "border-ocean-600 bg-ocean-600 text-white shadow-sm"
                            : "border-ink-200 bg-white text-ink-600 hover:border-ocean-300 hover:bg-ocean-50",
                        )}
                      >
                        {on ? (
                          <Check className="h-3 w-3 shrink-0" />
                        ) : (
                          <Plus className="h-3 w-3 shrink-0 text-ink-400" />
                        )}
                        {v.replace(/-/g, "_")}
                        {on ? ` · ${aliases[v]}` : ""}
                      </button>
                    );
                  })}
                </div>
              </div>

              {picked.length > 0 ? (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                    2 · Colunas
                  </p>
                  <p className="mb-2 text-[11px] text-ink-400">
                    Clique nas colunas que entram na VIEW. As marcadas
                    (✓, azul) serão projetadas.
                  </p>
                  <div className="space-y-3">
                    {picked.map((v) => {
                      const sel = cols[v] ?? [];
                      return (
                        <div key={v}>
                          <p className="mb-1 flex items-center gap-1 text-xs font-medium text-ink-700">
                            {v.replace(/-/g, "_")}{" "}
                            <span className="text-ink-400">
                              ({aliases[v]})
                            </span>
                            <span
                              className={cn(
                                "ml-auto rounded-full px-1.5 py-0.5 text-[10px]",
                                sel.length
                                  ? "bg-ocean-100 text-ocean-700"
                                  : "bg-ink-100 text-ink-400",
                              )}
                            >
                              {sel.length} selecionada
                              {sel.length === 1 ? "" : "s"}
                            </span>
                          </p>
                          <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto rounded-lg border border-ink-100 p-2">
                            {(schemaByView[v] ?? []).length === 0 ? (
                              <span className="text-[11px] italic text-ink-400">
                                sem dados
                              </span>
                            ) : (
                              schemaByView[v].map((c) => {
                                const on = sel.includes(c);
                                return (
                                  <button
                                    key={c}
                                    type="button"
                                    aria-pressed={on}
                                    onClick={() => toggleCol(v, c)}
                                    className={cn(
                                      "flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] transition-colors",
                                      on
                                        ? "border-ocean-600 bg-ocean-600 text-white"
                                        : "border-ink-200 bg-white text-ink-600 hover:border-ocean-300 hover:bg-ocean-50",
                                    )}
                                  >
                                    {on ? (
                                      <Check className="h-2.5 w-2.5 shrink-0" />
                                    ) : null}
                                    {c}
                                  </button>
                                );
                              })
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {nonHead.length > 0 ? (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                      3 · JOINs
                    </p>
                    <div className="flex overflow-hidden rounded-lg border border-ink-200">
                      {(["INNER", "LEFT"] as const).map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setJoinType(t)}
                          className={cn(
                            "px-2 py-1 text-[11px]",
                            joinType === t
                              ? "bg-ocean-600 text-white"
                              : "bg-white text-ink-600 hover:bg-ink-50",
                          )}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </div>

                  {nonHead.map((v) => {
                    const a = aliases[v];
                    const leftOpts = picked
                      .slice(0, picked.indexOf(v))
                      .flatMap((pv) =>
                        (schemaByView[pv] ?? []).map(
                          (c) => `${aliases[pv]}.${c}`,
                        ),
                      );
                    const rows = joins[a] ?? [];
                    return (
                      <div
                        key={v}
                        className="mb-2 rounded-lg border border-ink-100 p-2"
                      >
                        <p className="mb-1 text-[11px] font-medium text-ink-600">
                          {joinType} JOIN {v.replace(/-/g, "_")} ({a})
                        </p>
                        {rows.map((r, i) => (
                          <div
                            key={i}
                            className="mb-1 flex items-center gap-1"
                          >
                            <select
                              className="input !py-1 text-[11px]"
                              value={r.left}
                              onChange={(e) =>
                                setJoins((m) => {
                                  const next = [...(m[a] ?? [])];
                                  next[i] = { ...next[i], left: e.target.value };
                                  return { ...m, [a]: next };
                                })
                              }
                            >
                              <option value="">left…</option>
                              {leftOpts.map((o) => (
                                <option key={o} value={o}>
                                  {o}
                                </option>
                              ))}
                            </select>
                            <span className="text-ink-400">=</span>
                            <select
                              className="input !py-1 text-[11px]"
                              value={r.right}
                              onChange={(e) =>
                                setJoins((m) => {
                                  const next = [...(m[a] ?? [])];
                                  next[i] = {
                                    ...next[i],
                                    right: e.target.value,
                                    approx: APPROX_COLS.has(e.target.value),
                                  };
                                  return { ...m, [a]: next };
                                })
                              }
                            >
                              <option value="">{a}.…</option>
                              {(schemaByView[v] ?? []).map((c) => (
                                <option key={c} value={c}>
                                  {c}
                                </option>
                              ))}
                            </select>
                            <label
                              className="flex items-center gap-1 text-[10px] text-ink-500"
                              title="Join aproximado: usa abs(a − b) < epsilon (necessário para coordenadas Float32 de grade)"
                            >
                              <input
                                type="checkbox"
                                checked={r.approx}
                                onChange={(e) =>
                                  setJoins((m) => {
                                    const next = [...(m[a] ?? [])];
                                    next[i] = {
                                      ...next[i],
                                      approx: e.target.checked,
                                    };
                                    return { ...m, [a]: next };
                                  })
                                }
                              />
                              aprox.
                            </label>
                            <button
                              type="button"
                              className="text-ink-300 hover:text-rose-500"
                              onClick={() =>
                                setJoins((m) => ({
                                  ...m,
                                  [a]: (m[a] ?? []).filter(
                                    (_, j) => j !== i,
                                  ),
                                }))
                              }
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          className="flex items-center gap-1 text-[11px] text-ocean-600 hover:text-ocean-700"
                          onClick={() =>
                            setJoins((m) => ({
                              ...m,
                              [a]: [
                                ...(m[a] ?? []),
                                {
                                  left: "",
                                  right: "",
                                  approx: false,
                                  epsilon: 1e-4,
                                },
                              ],
                            }))
                          }
                        >
                          <Plus className="h-3 w-3" /> condição
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>

            {/* Right: live SQL (the hero) */}
            <div className="flex min-h-0 flex-col bg-ink-900/[0.02] p-5">
              <div className="mb-2 flex items-center justify-between">
                <label className="flex-1 text-xs font-medium text-ink-600">
                  Nome da VIEW
                  <input
                    className={cn(
                      "input mt-1",
                      name &&
                        !nameValid &&
                        "border-rose-400 focus:ring-rose-300",
                    )}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="ex.: era5_inmet"
                  />
                </label>
              </div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  SQL gerado
                </span>
                <button
                  type="button"
                  className="flex items-center gap-1 text-[11px] text-ink-400 hover:text-ink-700"
                  disabled={!sql}
                  onClick={() => {
                    navigator.clipboard.writeText(formatSql(sql));
                    toast.success("SQL copiado");
                  }}
                >
                  <Copy className="h-3 w-3" /> copiar
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <Suspense
                  fallback={
                    <div className="flex h-full items-center justify-center rounded-xl border border-ink-200 bg-white text-[11px] text-ink-400">
                      carregando editor…
                    </div>
                  }
                >
                  <SqlPreview
                    sql={sql}
                    placeholder="Selecione fontes e colunas para gerar o SQL…"
                  />
                </Suspense>
              </div>
              {preview ? (
                <p
                  className={cn(
                    "mt-2 flex items-center gap-1 text-[11px]",
                    preview.ok ? "text-emerald-600" : "text-rose-500",
                  )}
                >
                  {preview.ok ? (
                    <>
                      <Check className="h-3 w-3" /> SQL válido
                    </>
                  ) : (
                    <>{preview.error}</>
                  )}
                </p>
              ) : null}
              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  className="btn-outline"
                  onClick={() => onOpenChange(false)}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className="btn-primary"
                  disabled={
                    save.isPending ||
                    !nameValid ||
                    !sql ||
                    (preview != null && !preview.ok)
                  }
                  onClick={() => save.mutate()}
                >
                  {save.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : null}
                  Salvar VIEW
                </button>
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
