import Editor from "@monaco-editor/react";
import { useRef, useState } from "react";

interface Props {
  value: string;
  onChange: (next: string) => void;
  language: "python" | "sql" | "markdown";
  /** Distinct Monaco model path per cell → independent undo history. */
  path?: string;
  onRunRequested?: () => void;
}

// Floor so an empty/short cell still has a comfortable click target.
const MIN_HEIGHT = 3 * 19 + 12;

export function CellEditor({
  value,
  onChange,
  language,
  path,
  onRunRequested,
}: Props) {
  const valueRef = useRef(value);
  valueRef.current = value;

  // The editor always shows its FULL content with no inner vertical scrollbar:
  // height follows Monaco's real content height (accounts for wrapped lines),
  // reported via onDidContentSizeChange. Long cells grow the page instead of
  // scrolling inside a fixed box.
  const [height, setHeight] = useState(MIN_HEIGHT);

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
        // No inner vertical scroll — the container grows to fit the content.
        scrollbar: { vertical: "hidden", horizontal: "auto", alwaysConsumeMouseWheel: false },
        renderLineHighlight: "none",
        padding: { top: 6, bottom: 6 },
      }}
      onMount={(editor, monaco) => {
        const applyHeight = () => {
          const next = Math.max(MIN_HEIGHT, editor.getContentHeight());
          setHeight((prev) => (prev === next ? prev : next));
        };
        editor.onDidContentSizeChange(applyHeight);
        applyHeight();
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
