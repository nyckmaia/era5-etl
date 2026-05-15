import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import {
  QueryBuilder,
  formatQuery,
  type Field,
  type RuleGroupType,
} from "react-querybuilder";
import "react-querybuilder/dist/query-builder.css";

import { api } from "@/lib/api";
import { useLocalStorage } from "@/hooks/useLocalStorage";

interface Props {
  dataset: string;
  onApply: (sql: string) => void;
}

interface BuilderState {
  projections: string[];
  groupBy: string[];
  where: RuleGroupType;
  orderColumn: string;
  orderDir: "ASC" | "DESC";
  limit: number;
}

const EMPTY_WHERE: RuleGroupType = { combinator: "and", rules: [] };

export function QueryBuilderPanel({ dataset, onApply }: Props) {
  const schemaQ = useQuery({
    queryKey: ["query-schema", dataset],
    queryFn: () => api.querySchema(dataset),
  });
  const view = schemaQ.data?.view ?? dataset.replace(/-/g, "_");
  const columns = schemaQ.data?.columns ?? [];

  const [state, setState] = useLocalStorage<BuilderState>(
    `query.builder.${view}`,
    {
      projections: [],
      groupBy: [],
      where: EMPTY_WHERE,
      orderColumn: "",
      orderDir: "ASC",
      limit: 100,
    },
  );

  const fields: Field[] = columns.map((c) => ({
    name: c.name,
    label: `${c.name} (${c.type})`,
  }));

  function compile(): string {
    const select =
      state.projections.length > 0 ? state.projections.join(", ") : "*";
    let sql = `SELECT ${select}\nFROM ${view}`;
    const whereSql = formatQuery(state.where, "sql");
    if (whereSql && whereSql !== "(1 = 1)") sql += `\nWHERE ${whereSql}`;
    if (state.groupBy.length > 0)
      sql += `\nGROUP BY ${state.groupBy.join(", ")}`;
    if (state.orderColumn)
      sql += `\nORDER BY ${state.orderColumn} ${state.orderDir}`;
    sql += `\nLIMIT ${state.limit};`;
    return sql;
  }

  function MultiCols({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string[];
    onChange: (v: string[]) => void;
  }) {
    return (
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-500">
          {label}
        </label>
        <div className="flex flex-wrap gap-1">
          {columns.map((c) => {
            const on = value.includes(c.name);
            return (
              <button
                key={c.name}
                type="button"
                onClick={() =>
                  onChange(
                    on
                      ? value.filter((x) => x !== c.name)
                      : [...value, c.name],
                  )
                }
                className={
                  on
                    ? "rounded-full bg-ocean-600 px-2 py-0.5 text-[11px] text-white"
                    : "rounded-full bg-ink-100 px-2 py-0.5 text-[11px] text-ink-600 hover:bg-ink-200"
                }
              >
                {c.name}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-ink-200 bg-ink-50/50 p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
        Construtor visual — {view}
      </div>

      <MultiCols
        label="Colunas (vazio = *)"
        value={state.projections}
        onChange={(v) => setState((s) => ({ ...s, projections: v }))}
      />

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-500">
          Filtros (WHERE)
        </label>
        <div className="rounded border border-ink-200 bg-white p-2">
          <QueryBuilder
            fields={fields}
            query={state.where}
            onQueryChange={(q) => setState((s) => ({ ...s, where: q }))}
          />
        </div>
      </div>

      <MultiCols
        label="Agrupar por (GROUP BY)"
        value={state.groupBy}
        onChange={(v) => setState((s) => ({ ...s, groupBy: v }))}
      />

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-500">
            Ordenar por
          </label>
          <select
            className="input text-xs"
            value={state.orderColumn}
            onChange={(e) =>
              setState((s) => ({ ...s, orderColumn: e.target.value }))
            }
          >
            <option value="">(nenhum)</option>
            {columns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <select
          className="input text-xs"
          value={state.orderDir}
          onChange={(e) =>
            setState((s) => ({
              ...s,
              orderDir: e.target.value as "ASC" | "DESC",
            }))
          }
        >
          <option value="ASC">ASC</option>
          <option value="DESC">DESC</option>
        </select>
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-ink-500">
            Limite
          </label>
          <input
            type="number"
            min={1}
            max={100000}
            value={state.limit}
            onChange={(e) =>
              setState((s) => ({
                ...s,
                limit: Math.min(
                  100000,
                  Math.max(1, Number(e.target.value) || 1),
                ),
              }))
            }
            className="input w-24 text-xs"
          />
        </div>
      </div>

      <button
        type="button"
        onClick={() => onApply(compile())}
        className="btn-primary"
      >
        <Wand2 className="h-4 w-4" />
        Gerar SQL na aba ativa
      </button>
    </div>
  );
}
