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

// Monaco's line height at fontSize 13, + vertical padding (6 top + 6 bottom).
const LINE_HEIGHT = 19;
const V_PADDING = 12;
// Floor so an empty/short cell still has a comfortable click target.
const MIN_HEIGHT = 3 * LINE_HEIGHT + V_PADDING;

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
  // Initial height is ESTIMATED from the line count instead of the 3-line
  // floor: with dozens of cells, mounting all of them tiny and growing them
  // one by one reflowed the page for seconds — clicks aimed at a cell landed
  // on the wrong spot (cursor at the start of the cell). Wrapped lines are
  // corrected by onDidContentSizeChange with only a small shift.
  const [height, setHeight] = useState(() =>
    Math.max(MIN_HEIGHT, value.split("\n").length * LINE_HEIGHT + V_PADDING),
  );

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
        // Re-measure on container resize (side panel toggle, scrollbar
        // appearing): a stale layout maps clicks to the wrong column.
        automaticLayout: true,
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
