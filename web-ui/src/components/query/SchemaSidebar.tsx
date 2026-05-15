import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, PanelLeftClose, Table2 } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/format";

interface Props {
  datasets: string[];
  collapsed: boolean;
  onToggle: () => void;
  onInsert: (text: string) => void;
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
        <span className="ml-auto text-[10px] text-ink-400">{cols.length}</span>
      </button>
      {open ? (
        <ul className="ml-4 mt-0.5 border-l border-ink-100 pl-2">
          {cols.length === 0 ? (
            <li className="px-1 py-0.5 text-[11px] italic text-ink-400">
              {q.isLoading ? "…" : "sem dados"}
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
      ) : null}
    </div>
  );
}

export function SchemaSidebar({
  datasets,
  collapsed,
  onToggle,
  onInsert,
}: Props) {
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
      <div className={cn("flex-1 overflow-y-auto p-2")}>
        {datasets.map((d) => (
          <ViewNode key={d} dataset={d} onInsert={onInsert} />
        ))}
      </div>
    </div>
  );
}
