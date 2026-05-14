import { Square, Hexagon, MousePointer2, X } from "lucide-react";

import { cn } from "@/lib/format";

import type { SelectionMode } from "./InventoryMap";

interface Props {
  mode: SelectionMode;
  onChange: (m: SelectionMode) => void;
  onReset: () => void;
}

const TOOLS: { id: SelectionMode; label: string; icon: typeof Square; help: string }[] = [
  { id: "click", label: "Clique", icon: MousePointer2, help: "Clique em vértices; finalize com Reset" },
  { id: "rectangle", label: "Retângulo", icon: Square, help: "Arraste para desenhar um bbox" },
  { id: "lasso", label: "Lasso", icon: Hexagon, help: "Clique vértices, duplo-clique para fechar" },
];

export function SelectionToolbar({ mode, onChange, onReset }: Props) {
  return (
    <div className="absolute right-3 top-3 z-10 flex flex-col gap-1 rounded-xl bg-white/95 p-1.5 shadow-elevated ring-1 ring-ink-200">
      {TOOLS.map(({ id, label, icon: Icon, help }) => {
        const active = mode === id;
        return (
          <button
            key={id}
            title={help}
            onClick={() => onChange(active ? "none" : id)}
            className={cn(
              "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
              active ? "bg-ocean-600 text-white" : "text-ink-600 hover:bg-ink-100",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        );
      })}
      <div className="my-0.5 h-px bg-ink-200" />
      <button
        onClick={() => {
          onChange("none");
          onReset();
        }}
        className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium text-ink-500 hover:bg-ink-100"
        title="Limpar seleção"
      >
        <X className="h-3.5 w-3.5" />
        Limpar
      </button>
    </div>
  );
}
