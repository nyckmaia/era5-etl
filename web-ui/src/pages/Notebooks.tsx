import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  FileText,
  Loader2,
  NotebookPen,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/lib/api";

export function NotebooksPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);

  const listQ = useQuery({
    queryKey: ["notebooks"],
    queryFn: api.notebooks.list,
  });
  const tplQ = useQuery({
    queryKey: ["notebook-templates"],
    queryFn: api.notebooks.templates,
    enabled: pickerOpen,
  });

  const createMut = useMutation({
    mutationFn: (template_id: string | null) =>
      api.notebooks.create({ template_id: template_id ?? undefined }),
    onSuccess: (nb) => {
      queryClient.invalidateQueries({ queryKey: ["notebooks"] });
      setPickerOpen(false);
      navigate({ to: "/notebooks/$notebookId", params: { notebookId: nb.id } });
    },
  });
  const deleteMut = useMutation({
    mutationFn: api.notebooks.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notebooks"] }),
  });

  const items = listQ.data ?? [];

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
            {t("notebooks.title")}
          </h1>
          <p className="mt-1 text-sm text-ink-500">{t("notebooks.subtitle")}</p>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setPickerOpen(true)}
        >
          <Plus className="h-4 w-4" />
          {t("notebooks.new")}
        </button>
      </header>

      {listQ.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-ink-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("notebooks.loading")}
        </div>
      ) : items.length === 0 ? (
        <div className="card flex flex-col items-center gap-3 p-10 text-center">
          <NotebookPen className="h-8 w-8 text-ink-400" />
          <p className="text-sm text-ink-500">{t("notebooks.emptyHint")}</p>
          <button
            type="button"
            className="btn-primary mt-2"
            onClick={() => setPickerOpen(true)}
          >
            <Plus className="h-4 w-4" />
            {t("notebooks.new")}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {items.map((nb) => (
            <Link
              key={nb.id}
              to="/notebooks/$notebookId"
              params={{ notebookId: nb.id }}
              className="group card relative p-5 hover:border-ocean-300 hover:shadow-md"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate font-medium text-ink-800">{nb.name}</h2>
                  <p className="mt-1 text-xs text-ink-500">
                    {t("notebooks.card.cells", { count: nb.n_cells })} ·{" "}
                    {new Date(nb.updated_ts).toLocaleString()}
                  </p>
                </div>
                <button
                  type="button"
                  className="opacity-0 transition group-hover:opacity-100"
                  title={t("notebooks.card.delete")}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (confirm(t("notebooks.card.deleteConfirm", { name: nb.name }))) {
                      deleteMut.mutate(nb.id);
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4 text-ink-400 hover:text-rose-600" />
                </button>
              </div>
            </Link>
          ))}
        </div>
      )}

      {pickerOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setPickerOpen(false)}
        >
          <div
            className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-ink-800">
              {t("notebooks.picker.title")}
            </h3>
            <p className="mt-1 text-sm text-ink-500">
              {t("notebooks.picker.body")}
            </p>
            <div className="mt-4 space-y-2">
              <button
                type="button"
                className="flex w-full items-start gap-3 rounded-xl border border-ink-200 p-4 text-left hover:border-ocean-400 hover:bg-ocean-50/50"
                onClick={() => createMut.mutate(null)}
                disabled={createMut.isPending}
              >
                <FileText className="mt-0.5 h-5 w-5 text-ink-500" />
                <div>
                  <div className="font-medium text-ink-800">
                    {t("notebooks.picker.blankName")}
                  </div>
                  <div className="text-xs text-ink-500">
                    {t("notebooks.picker.blankDescription")}
                  </div>
                </div>
              </button>
              {(tplQ.data ?? []).map((tpl) => (
                <button
                  key={tpl.id}
                  type="button"
                  className="flex w-full items-start gap-3 rounded-xl border border-ink-200 p-4 text-left hover:border-ocean-400 hover:bg-ocean-50/50"
                  onClick={() => createMut.mutate(tpl.id)}
                  disabled={createMut.isPending}
                >
                  <Sparkles className="mt-0.5 h-5 w-5 text-amber-500" />
                  <div>
                    <div className="font-medium text-ink-800">{tpl.name}</div>
                    <div className="text-xs text-ink-500">{tpl.description}</div>
                  </div>
                </button>
              ))}
            </div>
            <div className="mt-5 flex justify-end">
              <button
                type="button"
                className="text-sm text-ink-500 hover:underline"
                onClick={() => setPickerOpen(false)}
              >
                {t("notebooks.picker.cancel")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
