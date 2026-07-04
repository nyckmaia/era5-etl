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
- ``application/vnd.plotly.v1+json``: ``{figure: <json.loads(fig.to_json())>}``
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
    """Serialize a pandas DataFrame into a compact JSON shape.

    Mirrors how Jupyter renders a frame:

    * When the frame is longer than ``display.max_rows`` (default 60), show
      only ``display.min_rows`` (default 10) split between the head and tail,
      and tell the front-end where to draw the ``...`` ellipsis row.
    * The row index is sent as a dedicated column so it can be rendered as the
      visual first column (like Jupyter / pandas).
    * ``display.precision`` (default 6) is forwarded so the front-end formats
      float columns to that many decimals. A notebook can override it once via
      ``pd.set_option("display.precision", N)`` and every frame follows.
    """
    import pandas as pd  # type: ignore  # helpers already require pandas

    total = len(df)

    def _opt(name: str, default: Any) -> Any:
        try:
            val = pd.get_option(name)
        except Exception:
            return default
        return default if val is None else val

    # ``max_rows`` keeps its None (= unlimited) meaning; the others fall back.
    try:
        max_rows = pd.get_option("display.max_rows")
    except Exception:
        max_rows = 60
    min_rows = int(_opt("display.min_rows", 10))
    precision = int(_opt("display.precision", 6))

    # Decide whether to truncate to a head+tail window. A hard transport cap
    # applies even when display options would show more. ``min_rows < total``
    # guards the degenerate case where head+tail would overlap (duplicate rows).
    if max_rows is not None and total > max_rows and min_rows < total:
        head_n = (min_rows + 1) // 2
        tail_n = max(0, min_rows - head_n)
    elif total > MAX_DATAFRAME_ROWS:
        head_n = MAX_DATAFRAME_ROWS // 2
        tail_n = MAX_DATAFRAME_ROWS - head_n
    else:
        head_n = tail_n = None

    if head_n is None:
        shown = df
        ellipsis_after = None
    else:
        shown = pd.concat([df.head(head_n), df.tail(tail_n)])
        ellipsis_after = head_n

    schema = [{"name": str(c), "dtype": str(shown[c].dtype)} for c in shown.columns]
    rows: list[list[Any]] = []
    for _, row in shown.iterrows():
        rows.append([_jsonify(v) for v in row.tolist()])
    index = [_jsonify(v) for v in shown.index.tolist()]
    return {
        "schema": schema,
        "rows": rows,
        "index": index,
        "index_name": "" if shown.index.name is None else str(shown.index.name),
        "ellipsis_after": ellipsis_after,
        "float_precision": precision,
        "truncated": ellipsis_after is not None,
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


def _display(value: Any, display_id: str | None = None) -> None:
    """Dispatch ``value`` to the most informative MIME type.

    When ``display_id`` is given it is attached to the ``display`` message so
    the front-end can REPLACE the previous output carrying the same id in
    place (a live-updating chart) instead of appending a new one. Without it,
    every emit appends (legacy behaviour).
    """
    if value is None:
        return

    def _emit(mime: str, data: dict[str, Any]) -> None:
        msg: dict[str, Any] = {"type": "display", "mime": mime, "data": data}
        if display_id is not None:
            msg["display_id"] = display_id
        _send(msg)

    # Plotly figure
    try:
        import plotly.graph_objects as go  # type: ignore

        if isinstance(value, go.Figure):
            # Serialize via Plotly's own JSON encoder, NOT ``to_dict()``.
            # ``to_dict()`` keeps numpy/``datetime64`` arrays as-is, and the
            # outer ``json.dumps(..., default=str)`` then stringifies a whole
            # array into a single ``"[...]"`` string — which a Plotly date
            # axis can't parse, collapsing every point onto epoch 0
            # (1969-12-31). ``to_json()`` emits proper JSON (datetimes as
            # ISO-8601 strings, numpy arrays as lists); ``json.loads`` turns
            # it back into plain dict/list/str so the outer dump is a no-op.
            _emit(
                "application/vnd.plotly.v1+json",
                {"figure": json.loads(value.to_json())},
            )
            return
    except ImportError:
        pass
    # Pandas DataFrame
    try:
        import pandas as pd  # type: ignore

        if isinstance(value, pd.DataFrame):
            _emit("application/vnd.dataframe+json", _serialize_dataframe(value))
            return
        if isinstance(value, pd.Series):
            _emit(
                "application/vnd.dataframe+json",
                _serialize_dataframe(value.to_frame()),
            )
            return
    except ImportError:
        pass
    # Anything else → repr
    text = repr(value)
    if len(text) > MAX_TEXT_BYTES:
        text = text[:MAX_TEXT_BYTES] + " ... [truncated]"
    _emit("text/plain", {"text": text})


def _user_display(*objects: Any, display_id: str | None = None) -> None:
    """Jupyter-compatible ``display()`` exposed to user cells.

    Renders each object immediately — not only the cell's last expression —
    so a cell can show a DataFrame/figure *before* it raises or runs more
    code. Matches IPython's ``display`` so cells stay portable to Jupyter.

    Pass ``display_id`` to give the output a stable identity; a later
    ``display(obj, display_id=same)`` / ``update_display`` replaces it in
    place (used for the live Optuna convergence chart).
    """
    for obj in objects:
        _display(obj, display_id=display_id)


def _user_update_display(obj: Any, display_id: str) -> None:
    """Update a previously shown output in place (IPython-compatible name).

    ``update_display(fig, display_id="optuna-monitor")`` re-emits ``fig`` with
    the same ``display_id`` so the front-end redraws that one output instead
    of stacking a new chart on every Optuna trial.
    """
    _display(obj, display_id=display_id)


def _user_warn(*messages: Any) -> None:
    """Emit an amber WARNING output to the cell (rendered yellow in the UI).

    Exposed to user cells as ``warn(...)``. Unlike ``raise`` it does not stop
    the cell — used to flag non-fatal issues (e.g. interpolated values) while
    letting execution continue.
    """
    text = " ".join(str(m) for m in messages)
    _send({"type": "stream", "name": "warning", "text": text})


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
    _USER_NS["display"] = _user_display
    _USER_NS["update_display"] = _user_update_display
    _USER_NS["warn"] = _user_warn
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
