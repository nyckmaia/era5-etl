"""Notebook kernel — runs inside the per-notebook subprocess.

Reads newline-delimited JSON requests from stdin and writes newline-delimited
JSON responses to stdout. The parent (``KernelManager``) is responsible for
spawning, terminating and routing.

Protocol
--------

Request (one per line)::

    {"type": "exec", "cell_id": "...", "code": "...", "lang": "python"|"sql"}

Responses (multiple per request, terminated by a ``done`` message)::

    {"type": "stream", "name": "stdout"|"stderr", "text": "..."}
    {"type": "display", "mime": "...", "data": {...}}
    {"type": "error",  "ename": "...", "evalue": "...", "traceback": [...]}
    {"type": "done",   "cell_id": "...", "duration_s": 1.23}

Display MIME types
------------------

- ``application/vnd.dataframe+json``: ``{schema: [{name, dtype}, ...], rows: [...], truncated: bool, total_rows: int}``
- ``application/vnd.plotly.v1+json``: ``{figure: <fig.to_dict()>}``
- ``text/plain``: ``{text: "..."}``

A cell whose final statement is an expression has its value auto-displayed
(DataFrame / Plotly Figure / others via ``repr``).
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_DATAFRAME_ROWS = 1000

_USER_NS: dict[str, Any] = {}


def _send(obj: dict[str, Any]) -> None:
    """Write one JSON line to stdout and flush."""
    sys.__stdout__.write(json.dumps(obj, default=str) + "\n")
    sys.__stdout__.flush()


def _stream(name: str, text: str) -> None:
    if not text:
        return
    if len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        text = text[: MAX_TEXT_BYTES // 2] + "\n... [output truncated] ...\n"
    _send({"type": "stream", "name": name, "text": text})


def _serialize_dataframe(df: Any) -> dict[str, Any]:
    """Serialize a pandas DataFrame into a compact JSON shape."""
    total = int(len(df))
    truncated = total > MAX_DATAFRAME_ROWS
    head = df.head(MAX_DATAFRAME_ROWS) if truncated else df
    schema = [{"name": str(c), "dtype": str(head[c].dtype)} for c in head.columns]
    rows: list[list[Any]] = []
    for _, row in head.iterrows():
        rows.append([_jsonify(v) for v in row.tolist()])
    return {
        "schema": schema,
        "rows": rows,
        "truncated": truncated,
        "total_rows": total,
    }


def _jsonify(v: Any) -> Any:
    """Convert numpy / pandas / datetime scalars into JSON-friendly forms."""
    try:
        import numpy as np  # type: ignore

        if isinstance(v, np.generic):
            return v.item()
    except ImportError:
        pass
    try:
        import pandas as pd  # type: ignore

        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if pd.isna(v):
            return None
    except ImportError:
        pass
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    try:
        return str(v)
    except Exception:
        return repr(v)


def _display(value: Any) -> None:
    """Dispatch ``value`` to the most informative MIME type."""
    if value is None:
        return
    # Plotly figure
    try:
        import plotly.graph_objects as go  # type: ignore

        if isinstance(value, go.Figure):
            _send(
                {
                    "type": "display",
                    "mime": "application/vnd.plotly.v1+json",
                    "data": {"figure": value.to_dict()},
                }
            )
            return
    except ImportError:
        pass
    # Pandas DataFrame
    try:
        import pandas as pd  # type: ignore

        if isinstance(value, pd.DataFrame):
            _send(
                {
                    "type": "display",
                    "mime": "application/vnd.dataframe+json",
                    "data": _serialize_dataframe(value),
                }
            )
            return
        if isinstance(value, pd.Series):
            _send(
                {
                    "type": "display",
                    "mime": "application/vnd.dataframe+json",
                    "data": _serialize_dataframe(value.to_frame()),
                }
            )
            return
    except ImportError:
        pass
    # Anything else → repr
    text = repr(value)
    if len(text) > MAX_TEXT_BYTES:
        text = text[:MAX_TEXT_BYTES] + " ... [truncated]"
    _send({"type": "display", "mime": "text/plain", "data": {"text": text}})


def _split_last_expression(code: str) -> tuple[str, str | None]:
    """If the cell's last statement is an expression, return ``(body, expr)``.

    Otherwise return ``(code, None)``. The expression is returned as a
    source string so we can compile it in ``eval`` mode and auto-display
    its value.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return code, None
    if not tree.body:
        return code, None
    last = tree.body[-1]
    if not isinstance(last, ast.Expr):
        return code, None
    body = ast.Module(body=tree.body[:-1], type_ignores=[])
    expr = ast.Expression(body=last.value)
    return ast.unparse(body), ast.unparse(expr)


def _exec_python(code: str) -> None:
    body, last_expr = _split_last_expression(code)
    if body.strip():
        compiled = compile(body, "<cell>", "exec")
        exec(compiled, _USER_NS)
    if last_expr is not None:
        compiled = compile(last_expr, "<cell>", "eval")
        value = eval(compiled, _USER_NS)
        _display(value)


def _exec_sql(code: str) -> None:
    con = _USER_NS.get("con")
    if con is None:
        raise RuntimeError(
            "DuckDB connection 'con' is not available in this kernel."
        )
    try:
        import pandas as pd  # type: ignore  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "SQL cells require pandas; install with: pip install -e ."
        ) from None
    df = con.execute(code).df()
    _display(df)


def _boot(data_dir: str, notebook_id: str, runs_url: str, runs_token: str) -> None:
    """Populate the user namespace with the standard helpers."""
    from era5_etl.notebooks import connect
    from era5_etl.notebooks.helpers_module import install_helpers

    _USER_NS["__name__"] = "__notebook__"
    _USER_NS["__data_dir__"] = data_dir
    _USER_NS["__notebook_id__"] = notebook_id
    _USER_NS["con"] = connect(Path(data_dir))
    install_helpers(
        _USER_NS,
        data_dir=Path(data_dir),
        notebook_id=notebook_id,
        runs_url=runs_url,
        runs_token=runs_token,
    )


def _handle(req: dict[str, Any]) -> None:
    if req.get("type") != "exec":
        return
    cell_id = req.get("cell_id", "")
    code = req.get("code", "")
    lang = req.get("lang", "python")
    t0 = time.perf_counter()
    stdout = io.StringIO()
    stderr = io.StringIO()
    error_payload: dict[str, Any] | None = None
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if lang == "sql":
                _exec_sql(code)
            else:
                _exec_python(code)
    except BaseException as exc:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        # Strip the kernel runner's own frames from the user-visible trace.
        cleaned: list[str] = []
        skip = True
        for line in tb:
            if skip and "<cell>" not in line and "File \"<string>\"" not in line:
                if line.startswith("Traceback"):
                    cleaned.append(line)
                continue
            skip = False
            cleaned.append(line)
        if not cleaned:
            cleaned = tb
        error_payload = {
            "type": "error",
            "ename": type(exc).__name__,
            "evalue": str(exc),
            "traceback": cleaned,
        }
    _stream("stdout", stdout.getvalue())
    _stream("stderr", stderr.getvalue())
    if error_payload is not None:
        _send(error_payload)
    _send(
        {
            "type": "done",
            "cell_id": cell_id,
            "duration_s": round(time.perf_counter() - t0, 4),
        }
    )


def main() -> int:
    data_dir = os.environ.get("ERA5_NB_DATA_DIR", "")
    notebook_id = os.environ.get("ERA5_NB_ID", "")
    runs_url = os.environ.get("ERA5_NB_RUNS_URL", "")
    runs_token = os.environ.get("ERA5_NB_RUNS_TOKEN", "")
    try:
        _boot(data_dir, notebook_id, runs_url, runs_token)
    except BaseException as exc:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        _send(
            {
                "type": "error",
                "ename": type(exc).__name__,
                "evalue": f"Kernel boot failed: {exc}",
                "traceback": tb,
            }
        )
        _send({"type": "done", "cell_id": "__boot__", "duration_s": 0.0})
    _send({"type": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("type") == "shutdown":
            break
        _handle(req)
    return 0


if __name__ == "__main__":
    sys.exit(main())
