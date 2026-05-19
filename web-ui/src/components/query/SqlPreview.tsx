import Editor from "@monaco-editor/react";
import { useMemo } from "react";

import { formatSql } from "@/lib/sql";

interface Props {
  /** Raw SQL; auto-formatted and syntax-highlighted for display. */
  sql: string;
  placeholder?: string;
  height?: string;
}

/**
 * Read-only, syntax-highlighted SQL preview. Same Monaco setup as the
 * editor (light theme, JetBrains Mono) so reserved words are coloured
 * and the generated query is auto-formatted before display.
 */
export default function SqlPreview({
  sql,
  placeholder = "—",
  height = "100%",
}: Props) {
  const pretty = useMemo(() => formatSql(sql), [sql]);

  if (!sql.trim()) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-ink-200 bg-white p-3 font-mono text-[11px] italic text-ink-400">
        {placeholder}
      </div>
    );
  }

  return (
    <div className="h-full overflow-hidden rounded-xl border border-ink-200 bg-white">
      <Editor
        height={height}
        language="sql"
        theme="light"
        value={pretty}
        options={{
          readOnly: true,
          domReadOnly: true,
          minimap: { enabled: false },
          lineNumbers: "off",
          folding: false,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "on",
          renderLineHighlight: "none",
          scrollbar: { vertical: "auto", horizontal: "auto" },
          contextmenu: false,
        }}
      />
    </div>
  );
}
