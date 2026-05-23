import Editor from "@monaco-editor/react";
import { useRef } from "react";

interface Props {
  value: string;
  onChange: (next: string) => void;
  language: "python" | "sql" | "markdown";
  /** Distinct Monaco model path per cell → independent undo history. */
  path?: string;
  onRunRequested?: () => void;
}

export function CellEditor({
  value,
  onChange,
  language,
  path,
  onRunRequested,
}: Props) {
  const valueRef = useRef(value);
  valueRef.current = value;

  // Auto-grow: ~20 lines max, min 3.
  const lineCount = Math.max(3, Math.min(20, value.split("\n").length));
  const height = `${lineCount * 19 + 12}px`;

  return (
    <Editor
      height={height}
      defaultLanguage={language}
      language={language}
      value={value}
      onChange={(v) => onChange(v ?? "")}
      path={path}
      theme="vs"
      options={{
        minimap: { enabled: false },
        fontSize: 13,
        scrollBeyondLastLine: false,
        wordWrap: "on",
        lineNumbers: language === "markdown" ? "off" : "on",
        scrollbar: { vertical: "hidden", horizontal: "auto", alwaysConsumeMouseWheel: false },
        renderLineHighlight: "none",
        padding: { top: 6, bottom: 6 },
      }}
      onMount={(editor, monaco) => {
        editor.addCommand(
          monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
          () => {
            if (onRunRequested) onRunRequested();
          },
        );
        editor.addCommand(
          monaco.KeyMod.Shift | monaco.KeyCode.Enter,
          () => {
            if (onRunRequested) onRunRequested();
          },
        );
      }}
    />
  );
}
