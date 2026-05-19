import { format } from "sql-formatter";

/**
 * Pretty-print SQL with the DuckDB dialect, uppercased keywords and
 * standard indentation. Returns the input untouched if it cannot be
 * parsed (partial SQL while the builder is still being filled in).
 */
export function formatSql(sql: string): string {
  if (!sql.trim()) return sql;
  try {
    return format(sql, {
      language: "duckdb",
      keywordCase: "upper",
      indentStyle: "standard",
    });
  } catch {
    return sql;
  }
}
