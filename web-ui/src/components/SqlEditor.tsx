import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";
import { useRef } from "react";

export interface SchemaColumn {
  name: string;
  type: string;
}

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  schemaColumns: SchemaColumn[];
  viewName: string;
}

const SQL_KEYWORDS = [
  "SELECT",
  "FROM",
  "WHERE",
  "GROUP BY",
  "ORDER BY",
  "HAVING",
  "LIMIT",
  "OFFSET",
  "JOIN",
  "LEFT JOIN",
  "RIGHT JOIN",
  "INNER JOIN",
  "ON",
  "AS",
  "COUNT",
  "AVG",
  "SUM",
  "MIN",
  "MAX",
  "DISTINCT",
  "BETWEEN",
  "IN",
  "LIKE",
  "AND",
  "OR",
  "NOT",
  "IS",
  "NULL",
  "CASE",
  "WHEN",
  "THEN",
  "ELSE",
  "END",
  "CAST",
  "ASC",
  "DESC",
  "UNION",
  "UNION ALL",
  "WITH",
  "date_trunc",
  "date_part",
  "extract",
  "coalesce",
  "round",
  "abs",
  "floor",
  "ceil",
  "strftime",
];

// The completion provider can only be registered once per Monaco instance.
// We keep the live schema in a module-level ref so the single provider always
// reflects the latest props.
let providerRegistered = false;
const schemaRef: { columns: SchemaColumn[]; viewName: string } = {
  columns: [],
  viewName: "",
};

function registerSqlCompletion(monaco: Monaco) {
  if (providerRegistered) return;
  providerRegistered = true;

  monaco.languages.registerCompletionItemProvider("sql", {
    provideCompletionItems(
      model: import("monaco-editor").editor.ITextModel,
      position: import("monaco-editor").Position,
    ) {
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };

      const suggestions: {
        label: string;
        kind: number;
        insertText: string;
        detail?: string;
        range: typeof range;
      }[] = [];

      for (const kw of SQL_KEYWORDS) {
        suggestions.push({
          label: kw,
          kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: kw,
          range,
        });
      }

      if (schemaRef.viewName) {
        suggestions.push({
          label: schemaRef.viewName,
          kind: monaco.languages.CompletionItemKind.Struct,
          insertText: schemaRef.viewName,
          detail: "view",
          range,
        });
      }

      for (const col of schemaRef.columns) {
        suggestions.push({
          label: col.name,
          kind: monaco.languages.CompletionItemKind.Field,
          insertText: col.name,
          detail: col.type,
          range,
        });
      }

      return { suggestions };
    },
  });
}

export default function SqlEditor({
  value,
  onChange,
  onRun,
  schemaColumns,
  viewName,
}: SqlEditorProps) {
  // Keep the module-level schema ref current on every render so the
  // globally-registered provider always sees the latest dataset.
  schemaRef.columns = schemaColumns;
  schemaRef.viewName = viewName;

  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;

  const handleMount: OnMount = (editor, monaco) => {
    registerSqlCompletion(monaco);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      onRunRef.current();
    });
  };

  return (
    <div className="overflow-hidden rounded-lg border border-ink-200">
      <Editor
        height="240px"
        language="sql"
        theme="light"
        value={value}
        onChange={(v) => onChange(v ?? "")}
        onMount={handleMount}
        options={{
          minimap: { enabled: false },
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 13,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "on",
        }}
      />
    </div>
  );
}
