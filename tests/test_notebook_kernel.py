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
