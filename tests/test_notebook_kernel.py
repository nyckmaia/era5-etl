"""Smoke tests for the per-notebook subprocess kernel.

These spawn an actual Python subprocess via ``KernelManager``. They are fast
(< 5s each on a warm machine) but require ``sys.executable`` to be able to
import the project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from era5_etl.notebooks.kernel_manager import (
    KernelBusyError,
    KernelManager,
)


@pytest.fixture
def kernel(tmp_path):
    mgr = KernelManager()
    k = mgr.get_or_start(
        "test-kernel",
        Path(tmp_path),
        "http://127.0.0.1:0/api/notebooks/test-kernel/runs",
    )
    yield k
    mgr.stop_all()


def _events(stream):
    return list(stream)


def test_kernel_starts_and_executes_simple_expression(kernel):
    events = _events(kernel.run_cell("c1", "1 + 1", "python"))
    types = [e["type"] for e in events]
    assert "done" in types
    displays = [e for e in events if e["type"] == "display"]
    assert any(d["data"].get("text") == "2" for d in displays)


def test_kernel_captures_stdout_and_stderr(kernel):
    code = (
        "import sys\n"
        "print('hello', flush=True)\n"
        "print('warn', file=sys.stderr, flush=True)\n"
    )
    events = _events(kernel.run_cell("c2", code, "python"))
    streams = [e for e in events if e["type"] == "stream"]
    stdout = "".join(s["text"] for s in streams if s["name"] == "stdout")
    stderr = "".join(s["text"] for s in streams if s["name"] == "stderr")
    assert "hello" in stdout
    assert "warn" in stderr


def test_kernel_preserves_state_across_cells(kernel):
    _events(kernel.run_cell("a", "x = 41", "python"))
    events = _events(kernel.run_cell("b", "x + 1", "python"))
    displays = [e for e in events if e["type"] == "display"]
    assert any(d["data"].get("text") == "42" for d in displays)


def test_kernel_reports_errors(kernel):
    events = _events(kernel.run_cell("err", "1 / 0", "python"))
    errors = [e for e in events if e["type"] == "error"]
    assert errors and errors[0]["ename"] == "ZeroDivisionError"


def test_kernel_plotly_datetime_x_serializes_as_iso_list(kernel):
    """Regression: a Plotly figure with a datetime x-axis must serialize the
    x array as a list of ISO strings.

    ``fig.to_dict()`` + ``json.dumps(default=str)`` used to stringify the
    whole numpy ``datetime64`` array into one ``"[...]"`` string, which a
    Plotly date axis can't parse — every point collapsed onto epoch 0
    (1969-12-31). The kernel now serializes via ``fig.to_json()``.
    """
    pytest.importorskip("plotly")
    pytest.importorskip("pandas")
    code = (
        "import pandas as pd\n"
        "import plotly.graph_objects as go\n"
        "x = pd.to_datetime(pd.Series(pd.date_range('2025-06-13 22:00', periods=4, freq='h')))\n"
        "go.Figure(go.Scatter(x=x, y=[1.0, 2.0, 3.0, 4.0], mode='lines'))\n"
    )
    events = _events(kernel.run_cell("plt", code, "python"))
    figs = [
        e
        for e in events
        if e["type"] == "display"
        and e.get("mime") == "application/vnd.plotly.v1+json"
    ]
    assert figs, "expected a plotly display event"
    xs = figs[0]["data"]["figure"]["data"][0]["x"]
    assert isinstance(xs, list) and len(xs) == 4, f"x must be a 4-item list, got {xs!r}"
    assert all(isinstance(v, str) for v in xs), f"x must be ISO strings, got {xs!r}"
    assert xs[0].startswith("2025-06-13T22:00"), xs[0]


def test_kernel_dataframe_truncates_head_tail_with_index(kernel):
    """A long DataFrame renders Jupyter-style: head + tail with an ellipsis,
    the row index as a dedicated column, and the float precision forwarded."""
    pytest.importorskip("pandas")
    code = (
        "import pandas as pd\n"
        "pd.set_option('display.precision', 2)\n"
        "pd.set_option('display.max_rows', 60)\n"
        "pd.set_option('display.min_rows', 10)\n"
        "pd.DataFrame({'x': [i + 0.123456 for i in range(100)]}, index=range(100))\n"
    )
    events = _events(kernel.run_cell("df", code, "python"))
    dfs = [
        e
        for e in events
        if e["type"] == "display"
        and e.get("mime") == "application/vnd.dataframe+json"
    ]
    assert dfs, "expected a dataframe display event"
    data = dfs[0]["data"]
    assert data["total_rows"] == 100
    assert data["truncated"] is True
    assert data["ellipsis_after"] == 5
    assert len(data["rows"]) == 10  # head 5 + tail 5
    assert len(data["index"]) == 10
    assert data["index"][0] == 0 and data["index"][-1] == 99
    assert data["float_precision"] == 2
    # The kernel forwards raw float values; rounding is a front-end concern.
    assert abs(data["rows"][0][0] - 0.123456) < 1e-9


def test_kernel_small_dataframe_keeps_all_rows_and_index(kernel):
    """A short DataFrame is shown whole, no ellipsis, but still index-first."""
    pytest.importorskip("pandas")
    code = (
        "import pandas as pd\n"
        "pd.DataFrame({'a': [1, 2, 3]}, index=['r0', 'r1', 'r2'])\n"
    )
    events = _events(kernel.run_cell("df2", code, "python"))
    data = next(
        e["data"]
        for e in events
        if e["type"] == "display"
        and e.get("mime") == "application/vnd.dataframe+json"
    )
    assert data["truncated"] is False
    assert data["ellipsis_after"] is None
    assert len(data["rows"]) == 3
    assert data["index"] == ["r0", "r1", "r2"]


def test_kernel_display_renders_before_raise(kernel):
    """`display()` emits a DataFrame output even when the cell later raises,
    so a validation cell can show the offending rows alongside the error."""
    pytest.importorskip("pandas")
    code = (
        "import pandas as pd\n"
        "display(pd.DataFrame({'a': [1, 2]}))\n"
        "raise ValueError('boom')\n"
    )
    events = _events(kernel.run_cell("disp", code, "python"))
    dfs = [
        e
        for e in events
        if e["type"] == "display"
        and e.get("mime") == "application/vnd.dataframe+json"
    ]
    errs = [e for e in events if e["type"] == "error"]
    assert dfs, "display() should emit a dataframe output before the raise"
    assert dfs[0]["data"]["total_rows"] == 2
    assert errs and errs[0]["ename"] == "ValueError"


def test_kernel_warn_emits_warning_stream(kernel):
    """`warn()` emits a `stream` event named 'warning' (rendered amber) and
    does not stop the cell."""
    code = "warn('heads up:', 3, 'rows interpolated')\nprint('after')\n"
    events = _events(kernel.run_cell("w", code, "python"))
    warns = [
        e
        for e in events
        if e["type"] == "stream" and e.get("name") == "warning"
    ]
    assert warns, "warn() should emit a 'warning' stream"
    assert "interpolated" in warns[0]["text"]
    # Execution continues after the warning.
    stdout = "".join(
        e["text"] for e in events if e["type"] == "stream" and e.get("name") == "stdout"
    )
    assert "after" in stdout
    assert not [e for e in events if e["type"] == "error"]


def test_kernel_busy_raises_for_concurrent_calls(kernel):
    # Start a cell but don't drain it — the lock is held inside run_cell.
    gen = kernel.run_cell("slow", "import time; time.sleep(0.3); 1", "python")
    # Pull the first event to ensure the cell is executing.
    next(gen)
    with pytest.raises(KernelBusyError):
        list(kernel.run_cell("conflict", "2", "python"))
    # Drain the original cell so the lock releases for the next test.
    list(gen)


def test_kernel_status_transitions(tmp_path):
    mgr = KernelManager()
    assert mgr.status("nb-x") == "dead"
    mgr.get_or_start(
        "nb-x",
        Path(tmp_path),
        "http://127.0.0.1:0/api/notebooks/nb-x/runs",
    )
    assert mgr.status("nb-x") == "idle"
    mgr.stop("nb-x")
    assert mgr.status("nb-x") == "dead"
