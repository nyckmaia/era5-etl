import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Loader2, X } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api, type UserObject } from "@/lib/api";
import { cn } from "@/lib/format";
import { formatSql } from "@/lib/sql";

const SqlPreview = lazy(() => import("@/components/query/SqlPreview"));

const IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const DDL_RE =
  /^\s*create\s+(or\s+replace\s+)?(temp(orary)?\s+)?(view|macro)\b/i;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** SQL seeded from the active editor tab. */
  initialSql: string;
  /** When set, the dialog edits an existing object instead of creating. */
  editing?: UserObject | null;
}

/**
 * Persist the active editor SQL as a named VIEW/MACRO. The exact DDL that
 * will be stored is always shown read-only before saving.
 */
export function SaveObjectDialog({
  open,
  onOpenChange,
  initialSql,
  editing,
}: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"view" | "macro">("view");
  const [preview, setPreview] = useState<{
    ok: boolean;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setKind(editing?.kind ?? "view");
      setPreview(null);
    }
  }, [open, editing]);

  const generatedSql = useMemo(() => {
    const body = (editing?.sql ?? initialSql ?? "").trim();
    if (DDL_RE.test(body)) return body;
    if (kind === "macro") return body; // a macro needs an explicit CREATE
    if (!name) return body;
    return `CREATE OR REPLACE VIEW ${name} AS\n${body}`;
  }, [editing, initialSql, kind, name]);

  const prettySql = useMemo(
    () => formatSql(generatedSql),
    [generatedSql],
  );
  const nameValid = IDENT_RE.test(name);
  const macroNeedsDdl = kind === "macro" && !DDL_RE.test(generatedSql);

  // Debounced server-side validation (real DuckDB compile + columns).
  useEffect(() => {
    if (!open || !nameValid || macroNeedsDdl) {
      setPreview(null);
      return;
    }
    const t = setTimeout(() => {
      api.userViews
        .preview({ name, kind, sql: generatedSql })
        .then((p) => setPreview({ ok: p.ok, error: p.error }))
        .catch((e) => setPreview({ ok: false, error: (e as Error).message }));
    }, 400);
    return () => clearTimeout(t);
  }, [open, name, kind, generatedSql, nameValid, macroNeedsDdl]);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? api.userViews.update(editing.id, { name, kind, sql: prettySql })
        : api.userViews.create({ name, kind, sql: prettySql }),
    onSuccess: async () => {
      // Refresh the SCHEMA sidebar before closing so the new/renamed
      // object is visible the moment the dialog disappears.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["user-views"] }),
        qc.invalidateQueries({ queryKey: ["query-schema"] }),
      ]);
      toast.success(
        editing ? `"${name}" atualizado` : `"${name}" salvo no SCHEMA`,
      );
      onOpenChange(false);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-900/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(40rem,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-2xl border border-ink-100 bg-white p-5 shadow-card">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-sm font-semibold text-ink-800">
              {editing ? "Editar objeto" : "Salvar como VIEW / MACRO"}
            </Dialog.Title>
            <Dialog.Close className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <div className="flex gap-3">
            <label className="flex-1 text-xs font-medium text-ink-600">
              Nome
              <input
                className={cn(
                  "input mt-1",
                  name && !nameValid && "border-rose-400 focus:ring-rose-300",
                )}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ex.: era5_inmet"
                autoFocus
              />
            </label>
            <div className="text-xs font-medium text-ink-600">
              Tipo
              <div className="mt-1 flex overflow-hidden rounded-xl border border-ink-200">
                {(["view", "macro"] as const).map((k) => {
                  const on = kind === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setKind(k)}
                      className={cn(
                        "flex items-center gap-1 px-3 py-2 text-sm capitalize transition-colors",
                        on
                          ? "bg-ocean-600 font-semibold text-white"
                          : "bg-white text-ink-500 hover:bg-ocean-50",
                      )}
                    >
                      {on ? <Check className="h-3 w-3" /> : null}
                      {k}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {name && !nameValid ? (
            <p className="-mt-1 text-[11px] text-rose-500">
              Use apenas letras, dígitos e _ (identificador SQL válido).
            </p>
          ) : null}

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-ink-600">
                SQL gerado
              </span>
              <button
                type="button"
                className="flex items-center gap-1 text-[11px] text-ink-400 hover:text-ink-700"
                onClick={() => {
                  navigator.clipboard.writeText(prettySql);
                  toast.success("SQL copiado");
                }}
              >
                <Copy className="h-3 w-3" /> copiar
              </button>
            </div>
            <div className="h-48">
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center rounded-xl border border-ink-200 bg-white text-[11px] text-ink-400">
                    carregando editor…
                  </div>
                }
              >
                <SqlPreview sql={prettySql} />
              </Suspense>
            </div>
          </div>

          {macroNeedsDdl ? (
            <p className="text-[11px] text-amber-600">
              Macros exigem um comando completo:{" "}
              <code>CREATE OR REPLACE MACRO nome(args) AS …</code>
            </p>
          ) : preview ? (
            <p
              className={cn(
                "flex items-center gap-1 text-[11px]",
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

          <div className="flex justify-end gap-2">
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
                macroNeedsDdl ||
                (preview != null && !preview.ok)
              }
              onClick={() => save.mutate()}
            >
              {save.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              {editing ? "Salvar alterações" : "Salvar"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
