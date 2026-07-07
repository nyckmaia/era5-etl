import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";
import { forwardRef, useImperativeHandle, useRef } from "react";

export interface SchemaColumn {
  name: string;
  type: string;
}

/** Imperative handle so the parent can push SQL into the (uncontrolled)
 *  editor — templates, formatting, builder output — without feeding `value`
 *  back on every keystroke (which repositions the caret while typing). */
export interface SqlEditorHandle {
  setValue: (sql: string) => void;
}

interface SqlEditorProps {
  /** Initial content only — the editor is UNCONTROLLED. Push later changes
   *  through the imperative `setValue` handle, not by re-rendering `value`. */
  value: string;
  onChange: (value: string) => void;
  onRun: () => void;
  schemaColumns: SchemaColumn[];
  viewName: string;
  /** Distinct Monaco model path per tab → independent undo history. */
  path?: string;
  height?: string;
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

const SqlEditor = forwardRef<SqlEditorHandle, SqlEditorProps>(function SqlEditor(
  { value, onChange, onRun, schemaColumns, viewName, path, height = "240px" },
  ref,
) {
  // Keep the module-level schema ref current on every render so the
  // globally-registered provider always sees the latest dataset.
  schemaRef.columns = schemaColumns;
  schemaRef.viewName = viewName;

  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;

  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  // External SQL (templates / format / builder) is applied imperatively so
  // the model — not a lagging React `value` prop — stays the source of truth.
  useImperativeHandle(
    ref,
    () => ({
      setValue: (sql: string) => {
        editorRef.current?.setValue(sql);
      },
    }),
    [],
  );

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    registerSqlCompletion(monaco);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      onRunRef.current();
    });
  };

  return (
    <div className="overflow-hidden rounded-lg border border-ink-200">
      <Editor
        height={height}
        language="sql"
        theme="light"
        path={path}
        defaultValue={value}
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
});

export default SqlEditor;
