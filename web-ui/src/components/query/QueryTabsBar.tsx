import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Plus, X } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/format";

export interface PersistedTab {
  id: string;
  name: string;
  sql: string;
  userEdited: boolean;
}

interface Props {
  tabs: PersistedTab[];
  activeId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onClose: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onReorder: (ids: string[]) => void;
}

function SortableTab({
  tab,
  active,
  onSelect,
  onClose,
  onRename,
}: {
  tab: PersistedTab;
  active: boolean;
  onSelect: () => void;
  onClose: () => void;
  onRename: (name: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: tab.id });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(tab.name);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group flex shrink-0 items-center gap-1.5 rounded-t-lg border border-b-0 px-3 py-1.5 text-xs",
        active
          ? "border-ink-200 bg-white font-medium text-ink-800"
          : "border-transparent bg-ink-100 text-ink-500 hover:bg-ink-200",
      )}
    >
      <span {...attributes} {...listeners} className="cursor-grab select-none">
        ⠿
      </span>
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            setEditing(false);
            if (draft.trim()) onRename(draft.trim());
            else setDraft(tab.name);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") {
              setDraft(tab.name);
              setEditing(false);
            }
          }}
          className="w-24 rounded border border-ink-200 px-1 text-xs"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          onDoubleClick={() => {
            setDraft(tab.name);
            setEditing(true);
          }}
          className="max-w-[12rem] truncate"
        >
          {tab.name}
        </button>
      )}
      <button
        type="button"
        onClick={onClose}
        className="rounded p-0.5 text-ink-300 opacity-0 transition hover:bg-ink-200 hover:text-ink-700 group-hover:opacity-100"
        aria-label="Close tab"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

export function QueryTabsBar({
  tabs,
  activeId,
  onSelect,
  onAdd,
  onClose,
  onRename,
  onReorder,
}: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  function handleDragEnd(e: DragEndEvent) {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const ids = tabs.map((t) => t.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    onReorder(ids);
  }

  return (
    <div className="flex items-end gap-1 border-b border-ink-200">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={tabs.map((t) => t.id)}
          strategy={horizontalListSortingStrategy}
        >
          <div className="flex items-end gap-1 overflow-x-auto">
            {tabs.map((t) => (
              <SortableTab
                key={t.id}
                tab={t}
                active={t.id === activeId}
                onSelect={() => onSelect(t.id)}
                onClose={() => onClose(t.id)}
                onRename={(name) => onRename(t.id, name)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
      <button
        type="button"
        onClick={onAdd}
        className="mb-1 ml-1 rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
        aria-label="New tab"
      >
        <Plus className="h-4 w-4" />
      </button>
    </div>
  );
}
