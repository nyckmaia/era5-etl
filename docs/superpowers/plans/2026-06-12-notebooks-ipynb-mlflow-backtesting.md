# Notebooks: .ipynb export, cell collapse, MLflow + backtesting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add .ipynb export and per-cell collapse to /notebooks, and ship a new
"XGBoost With Optuna and Windows" template with MLflow tracking, experiment
repeat, and Optuna-managed Expanding/Sliding-window backtesting.

**Architecture:** Backend-first. Pure modules (`notebooks/backtest.py`,
`notebooks/ipynb_export.py`, `web/mlflow_runs.py`) are TDD'd, then wired into
`web/routes/notebooks.py`. MLflow uses a local file store at
`<config_dir>/mlruns` (no server); an on-demand `mlflow ui` subprocess is
managed by `web/routes/mlflow_ui.py`. The Model-runs panel merges legacy JSON
runs with top-level MLflow runs. The new template is a generated copy of
`xgboost_optuna_forecast.json` (original untouched).

**Tech Stack:** FastAPI, Pydantic v2, MLflow ≥2.10, nbformat ≥5.9, Optuna,
XGBoost, React + TanStack Router/Query, plotly.

**Spec:** `docs/superpowers/specs/2026-06-12-notebooks-ipynb-mlflow-backtesting-design.md`

**Conventions for this repo:**
- Run tests with `py -3.12 -m pytest <file> -v` (Windows; no venv).
- The SPA in `web-ui/` is gitignored after build: editing TSX changes nothing
  in `era5 ui` until `bun run build` (or `npm run build`) inside `web-ui/`.
- **Frontend tasks (11 and 12): invoke the `frontend-design:frontend-design`
  skill before writing the TSX** (explicit user request).
- Commit after every task.

---

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml` (modify) | add `mlflow>=2.10`, `nbformat>=5.9` core deps |
| `src/era5_etl/notebooks/backtest.py` (create) | pure Expanding/Sliding window generators |
| `src/era5_etl/notebooks/ipynb_export.py` (create) | notebook dict → nbformat v4 conversion |
| `src/era5_etl/web/mlflow_runs.py` (create) | tracking URI + read parent MLflow runs, panel-shaped |
| `src/era5_etl/web/routes/mlflow_ui.py` (create) | on-demand `mlflow ui` subprocess (start/status/shutdown) |
| `src/era5_etl/web/routes/notebooks.py` (modify) | export endpoint; GET runs merge; kernel extra_env |
| `src/era5_etl/web/notebook_store.py` (modify) | `make_cell(collapsed=...)` |
| `src/era5_etl/web/models/__init__.py` (modify) | `NotebookCellOut.collapsed` |
| `src/era5_etl/notebooks/kernel_manager.py` (modify) | `extra_env` pass-through; `_build_env()` |
| `src/era5_etl/web/server.py` (modify) | register mlflow_ui router + shutdown handler |
| `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` (create) | new template |
| `web-ui/src/lib/api.ts` (modify) | exportIpynb, mlflow start/status, `collapsed` field |
| `web-ui/src/pages/Notebooks.tsx` (modify) | download button per card |
| `web-ui/src/pages/NotebookEditor.tsx` (modify) | collapse toggle, download + MLflow UI buttons |
| `web-ui/src/i18n/locales/en.ts`, `pt.ts` (modify) | new keys |
| `tests/test_notebook_backtest.py` (create) | window generators |
| `tests/test_notebook_ipynb_export.py` (create) | converter |
| `tests/test_notebook_mlflow_runs.py` (create) | MLflow read + GET merge |
| `tests/test_notebook_mlflow_ui.py` (create) | UI launcher (mocked Popen) |
| `tests/test_notebook_store.py` (modify) | collapsed round-trip |
| `tests/test_notebook_routes.py` (modify) | export endpoint, collapsed via API |
| `tests/test_notebook_templates.py` (modify) | new template listed/loads |
| `tests/test_notebook_kernel.py` (modify) | `_build_env` with extra_env |

---

### Task 1: Dependencies (mlflow, nbformat)

**Files:**
- Modify: `pyproject.toml` (dependencies list, the notebook-runtime block around line 65)

- [ ] **Step 1: Edit pyproject.toml**

In the `dependencies` list, extend the notebook-runtime block:

```toml
    # Notebook runtime stack (kernel helpers + bundled XGBoost examples).
    # Core, not optional: the /notebooks feature ships examples that use
    # these out of the box, so a plain ``pip install -e .`` must run them.
    # ``optuna`` powers the "XGBoost with Optuna" template's search.
    # ``mlflow`` is the experiment tracker used by the "XGBoost With Optuna
    # and Windows" template (file store under <config_dir>/mlruns).
    # ``nbformat`` backs the notebook -> .ipynb exporter.
    "pandas>=2.0",
    "plotly>=5.0",
    "scikit-learn>=1.3",
    "xgboost>=2.0",
    "optuna>=3.0",
    "mlflow>=2.10",
    "nbformat>=5.9",
]
```

- [ ] **Step 2: Install the new deps into the test interpreter**

Run: `py -3.12 -m pip install "mlflow>=2.10" "nbformat>=5.9"`

(If pip fails with an SSL error on this machine, export the Windows trust
store to a PEM and set `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` — see the project
memory note — or use `--trusted-host pypi.org --trusted-host files.pythonhosted.org`.)

- [ ] **Step 3: Verify imports**

Run: `py -3.12 -c "import mlflow, nbformat; print(mlflow.__version__, nbformat.__version__)"`
Expected: two version strings, no traceback.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add mlflow and nbformat for notebook tracking and ipynb export"
```

---

### Task 2: Backtesting window generators

**Files:**
- Create: `src/era5_etl/notebooks/backtest.py`
- Test: `tests/test_notebook_backtest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notebook_backtest.py`:

```python
"""Expanding/Sliding window generators for the backtesting template."""

from __future__ import annotations

import pandas as pd
import pytest

from era5_etl.notebooks.backtest import expanding_windows, sliding_windows


def _hourly_index(days: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=days * 24, freq="h")


def test_expanding_grows_anchored_at_start():
    idx = _hourly_index(120)
    wins = expanding_windows(
        idx, initial_train_days=60, test_days=15, step_days=15, max_windows=10
    )
    # train ends at 60, 75, 90, 105 days -> tests end at 75, 90, 105, 120.
    assert len(wins) == 4
    assert [w.index for w in wins] == [0, 1, 2, 3]
    for w in wins:
        assert w.train_start == idx.min()          # anchored
        assert w.train_end == w.test_start          # contiguous, no gap
        assert w.test_end - w.test_start == pd.Timedelta(days=15)
    grow = wins[1].train_end - wins[0].train_end
    assert grow == pd.Timedelta(days=15)


def test_sliding_train_size_is_fixed_and_slides():
    idx = _hourly_index(120)
    wins = sliding_windows(
        idx, train_days=60, test_days=15, step_days=15, max_windows=10
    )
    assert len(wins) == 4
    for w in wins:
        assert w.train_end - w.train_start == pd.Timedelta(days=60)
        assert w.train_end == w.test_start
    slide = wins[1].train_start - wins[0].train_start
    assert slide == pd.Timedelta(days=15)


def test_max_windows_caps_both_methods():
    idx = _hourly_index(365)
    e = expanding_windows(idx, initial_train_days=30, test_days=10, step_days=10, max_windows=3)
    s = sliding_windows(idx, train_days=30, test_days=10, step_days=10, max_windows=3)
    assert len(e) == 3
    assert len(s) == 3


def test_half_open_masks_partition_without_leakage():
    idx = _hourly_index(90)
    (w,) = expanding_windows(
        idx, initial_train_days=60, test_days=30, step_days=30, max_windows=1
    )
    train = idx[(idx >= w.train_start) & (idx < w.train_end)]
    test = idx[(idx >= w.test_start) & (idx < w.test_end)]
    assert len(train) == 60 * 24
    assert len(test) == 30 * 24
    assert train.max() < test.min()                 # no leakage
    assert len(train) + len(test) == len(idx)       # full partition


def test_short_period_raises_with_explanation():
    idx = _hourly_index(30)
    with pytest.raises(ValueError, match="No expanding window fits"):
        expanding_windows(
            idx, initial_train_days=60, test_days=15, step_days=15, max_windows=5
        )
    with pytest.raises(ValueError, match="No sliding window fits"):
        sliding_windows(
            idx, train_days=60, test_days=15, step_days=15, max_windows=5
        )


def test_invalid_params_raise():
    idx = _hourly_index(90)
    with pytest.raises(ValueError, match="initial_train_days"):
        expanding_windows(
            idx, initial_train_days=0, test_days=15, step_days=15, max_windows=5
        )
    with pytest.raises(ValueError, match="index is empty"):
        sliding_windows(
            pd.DatetimeIndex([]), train_days=30, test_days=15, step_days=15, max_windows=5
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_backtest.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'era5_etl.notebooks.backtest'`

- [ ] **Step 3: Implement the module**

Create `src/era5_etl/notebooks/backtest.py`:

```python
"""Temporal backtesting window generators (Expanding / Sliding).

Used by the "XGBoost With Optuna and Windows" notebook template; the kernel
subprocess runs in the same environment as the server, so template cells can
``from era5_etl.notebooks.backtest import expanding_windows, sliding_windows``.
The logic lives here (not inline in the template JSON) because temporal
splits are where leakage bugs hide — this module is unit-tested.

All bounds are half-open: a row at timestamp ``t`` belongs to a window's
train slice when ``train_start <= t < train_end`` (same for test). By
construction ``train_end == test_start``, so train and test never overlap.
Only windows whose test block fits entirely inside the index span are
produced (no truncated last window — keeps per-window stats comparable).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestWindow:
    """One train/test split (half-open timestamp bounds)."""

    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def _check_positive(**kwargs: int) -> None:
    for name, value in kwargs.items():
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")


def _check_index(index: pd.DatetimeIndex) -> None:
    if len(index) == 0:
        raise ValueError("index is empty")


def _span_days(index: pd.DatetimeIndex) -> float:
    return float((index.max() - index.min()) / pd.Timedelta(days=1))


def expanding_windows(
    index: pd.DatetimeIndex,
    *,
    initial_train_days: int,
    test_days: int,
    step_days: int,
    max_windows: int,
) -> list[BacktestWindow]:
    """Train anchored at the start and growing by ``step_days`` per window."""
    _check_positive(
        initial_train_days=initial_train_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
    )
    _check_index(index)
    start = index.min()
    end = index.max()
    out: list[BacktestWindow] = []
    k = 0
    while len(out) < max_windows:
        train_end = start + pd.Timedelta(days=initial_train_days + k * step_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        # Half-open: the last row inside the test block is test_end - 1 tick;
        # require it to exist within the index span (hourly data assumed).
        if test_end > end + pd.Timedelta(hours=1):
            break
        out.append(
            BacktestWindow(
                index=len(out),
                train_start=start,
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
            )
        )
        k += 1
    if not out:
        need = initial_train_days + test_days
        raise ValueError(
            f"No expanding window fits: the period spans "
            f"{_span_days(index):.1f} days but the first window needs "
            f"initial_train_days + test_days = {need} days. Reduce "
            f"EXPANDING_INITIAL_TRAIN_DAYS / EXPANDING_TEST_DAYS or widen "
            f"DATE_START..DATE_END."
        )
    return out


def sliding_windows(
    index: pd.DatetimeIndex,
    *,
    train_days: int,
    test_days: int,
    step_days: int,
    max_windows: int,
) -> list[BacktestWindow]:
    """Fixed-size train sliding forward by ``step_days`` per window."""
    _check_positive(
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
    )
    _check_index(index)
    start = index.min()
    end = index.max()
    out: list[BacktestWindow] = []
    k = 0
    while len(out) < max_windows:
        train_start = start + pd.Timedelta(days=k * step_days)
        train_end = train_start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > end + pd.Timedelta(hours=1):
            break
        out.append(
            BacktestWindow(
                index=len(out),
                train_start=train_start,
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
            )
        )
        k += 1
    if not out:
        need = train_days + test_days
        raise ValueError(
            f"No sliding window fits: the period spans "
            f"{_span_days(index):.1f} days but one window needs "
            f"train_days + test_days = {need} days. Reduce "
            f"SLIDING_TRAIN_DAYS / SLIDING_TEST_DAYS or widen "
            f"DATE_START..DATE_END."
        )
    return out


__all__ = ["BacktestWindow", "expanding_windows", "sliding_windows"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_backtest.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/backtest.py tests/test_notebook_backtest.py
git commit -m "feat(notebooks): expanding/sliding backtesting window generators"
```

---

### Task 3: .ipynb converter module

**Files:**
- Create: `src/era5_etl/notebooks/ipynb_export.py`
- Test: `tests/test_notebook_ipynb_export.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notebook_ipynb_export.py`:

```python
"""Stored-notebook -> Jupyter .ipynb conversion."""

from __future__ import annotations

import pytest

nbformat = pytest.importorskip("nbformat")

from era5_etl.notebooks.ipynb_export import ipynb_filename, notebook_to_ipynb


def _doc(cells):
    return {"id": "abc123", "name": "My NB", "cells": cells, "runs": []}


def test_filename_slug():
    assert ipynb_filename("Meu Notebook (v2)!") == "meu-notebook-v2.ipynb"
    assert ipynb_filename("") == "notebook.ipynb"
    assert ipynb_filename("---") == "notebook.ipynb"


def test_markdown_and_code_cells_map():
    doc = _doc(
        [
            {"id": "c1", "type": "markdown", "source": "# Title", "outputs": []},
            {"id": "c2", "type": "code", "source": "print(1)", "outputs": []},
        ]
    )
    nb = notebook_to_ipynb(doc)
    nbformat.validate(nb)  # well-formed v4
    assert nb.cells[0].cell_type == "markdown"
    assert nb.cells[0].source == "# Title"
    assert nb.cells[1].cell_type == "code"
    assert nb.cells[1].source == "print(1)"


def test_sql_cell_becomes_code_with_sql_magic():
    doc = _doc([{"id": "c1", "type": "sql", "source": "SELECT 1", "outputs": []}])
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].cell_type == "code"
    assert nb.cells[0].source == "%%sql\nSELECT 1"


def test_collapsed_flag_carried_to_metadata():
    doc = _doc(
        [{"id": "c1", "type": "code", "source": "x=1", "outputs": [], "collapsed": True}]
    )
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].metadata.get("collapsed") is True


def test_stream_error_and_display_outputs_map():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "run()",
                "outputs": [
                    {"type": "stream", "name": "stdout", "text": "hi\n"},
                    {"type": "stream", "name": "warning", "text": "careful\n"},
                    {
                        "type": "error",
                        "ename": "ValueError",
                        "evalue": "bad",
                        "traceback": ["tb1", "tb2"],
                    },
                    {
                        "type": "display",
                        "mime": "application/vnd.plotly.v1+json",
                        "data": {"figure": {"data": [], "layout": {}}},
                    },
                    {
                        "type": "display",
                        "mime": "application/vnd.dataframe+json",
                        "data": {
                            "schema": [{"name": "a", "dtype": "int64"}],
                            "rows": [[1], [2]],
                            "index": [0, 1],
                            "index_name": "",
                            "ellipsis_after": None,
                            "float_precision": 2,
                            "truncated": False,
                            "total_rows": 2,
                        },
                    },
                    {"type": "done", "cell_id": "c1", "duration_s": 0.1},
                ],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    nbformat.validate(nb)
    outs = nb.cells[0].outputs
    # "done" is internal bookkeeping and must be dropped.
    assert len(outs) == 5
    assert outs[0].output_type == "stream" and outs[0].name == "stdout"
    assert outs[1].name == "stderr"  # warning -> stderr
    assert outs[2].output_type == "error" and outs[2].ename == "ValueError"
    assert "application/vnd.plotly.v1+json" in outs[3].data
    html = outs[4].data["text/html"]
    assert "<table" in html and "<td>1</td>" in html
    assert "text/plain" in outs[4].data


def test_dataframe_html_escapes_and_ellipsis():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "df",
                "outputs": [
                    {
                        "type": "display",
                        "mime": "application/vnd.dataframe+json",
                        "data": {
                            "schema": [{"name": "<b>", "dtype": "object"}],
                            "rows": [["<x>"], ["y"]],
                            "index": [0, 1],
                            "index_name": "",
                            "ellipsis_after": 1,
                            "float_precision": 2,
                            "truncated": True,
                            "total_rows": 100,
                        },
                    }
                ],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    html = nb.cells[0].outputs[0].data["text/html"]
    assert "&lt;x&gt;" in html and "&lt;b&gt;" in html  # escaped
    assert "…" in html  # ellipsis row


def test_unknown_display_degrades_to_text_plain():
    doc = _doc(
        [
            {
                "id": "c1",
                "type": "code",
                "source": "obj",
                "outputs": [{"type": "display", "mime": "text/plain", "data": "Foo()"}],
            }
        ]
    )
    nb = notebook_to_ipynb(doc)
    assert nb.cells[0].outputs[0].data["text/plain"] == "Foo()"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_ipynb_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'era5_etl.notebooks.ipynb_export'`

- [ ] **Step 3: Implement the module**

Create `src/era5_etl/notebooks/ipynb_export.py`:

```python
"""Convert a stored notebook document into a Jupyter ``.ipynb`` (nbformat v4).

Mapping (internal JSON -> ipynb):

* ``markdown`` cell -> markdown cell.
* ``code`` cell     -> code cell; outputs converted below.
* ``sql`` cell      -> code cell whose first line is ``%%sql`` (jupysql
  convention — Jupyter has no native SQL cell).
* output ``stream``  -> ``stream`` output (our ``warning`` stream -> stderr).
* output ``error``   -> ``error`` output.
* Plotly display     -> ``display_data`` with the standard plotly MIME
  (renders natively in JupyterLab).
* DataFrame display  -> ``display_data`` with a static ``text/html`` table
  rebuilt from the stored rows + a ``text/plain`` fallback.
* output ``done``    -> dropped (internal bookkeeping).

Unknown output shapes degrade to ``text/plain`` — the export never fails on
exotic outputs.
"""

from __future__ import annotations

import html
import re
from typing import Any

import nbformat
from nbformat import v4

PLOTLY_MIME = "application/vnd.plotly.v1+json"
DATAFRAME_MIME = "application/vnd.dataframe+json"


def ipynb_filename(name: str) -> str:
    """Slugify a notebook name into a safe ``.ipynb`` filename."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return f"{slug or 'notebook'}.ipynb"


def _dataframe_html(data: dict[str, Any]) -> str:
    """Static HTML table from the kernel's DataFrame payload.

    Payload shape (see ``kernel_runner._serialize_dataframe``): ``schema``
    (list of {name, dtype}), ``rows``, ``index``, ``index_name``,
    ``ellipsis_after`` (row position of the Jupyter-style ``…`` row).
    """
    schema = data.get("schema") or []
    rows = data.get("rows") or []
    index = data.get("index") or []
    index_name = html.escape(str(data.get("index_name") or ""))
    ellipsis_after = data.get("ellipsis_after")
    head = "".join(
        f"<th>{html.escape(str(c.get('name', '')))}</th>" for c in schema
    )
    body: list[str] = []
    for i, row in enumerate(rows):
        if ellipsis_after is not None and i == ellipsis_after:
            cells = "".join("<td>…</td>" for _ in schema)
            body.append(f"<tr><th>…</th>{cells}</tr>")
        idx_val = html.escape(str(index[i])) if i < len(index) else ""
        cells = "".join(
            f"<td>{'' if v is None else html.escape(str(v))}</td>" for v in row
        )
        body.append(f"<tr><th>{idx_val}</th>{cells}</tr>")
    return (
        f'<table border="1"><thead><tr><th>{index_name}</th>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _convert_output(out: dict[str, Any]) -> nbformat.NotebookNode | None:
    kind = out.get("type")
    if kind == "stream":
        name = "stderr" if out.get("name") in ("stderr", "warning") else "stdout"
        return v4.new_output("stream", name=name, text=str(out.get("text", "")))
    if kind == "error":
        return v4.new_output(
            "error",
            ename=str(out.get("ename", "Error")),
            evalue=str(out.get("evalue", "")),
            traceback=[str(t) for t in out.get("traceback") or []],
        )
    if kind == "display":
        mime = out.get("mime")
        data = out.get("data")
        if mime == PLOTLY_MIME and isinstance(data, dict):
            return v4.new_output(
                "display_data", data={PLOTLY_MIME: data.get("figure") or {}}
            )
        if mime == DATAFRAME_MIME and isinstance(data, dict):
            total = data.get("total_rows", len(data.get("rows") or []))
            return v4.new_output(
                "display_data",
                data={
                    "text/html": _dataframe_html(data),
                    "text/plain": f"DataFrame: {total} rows",
                },
            )
        return v4.new_output("display_data", data={"text/plain": str(data)})
    return None  # "done" and anything unknown carries no user content


def notebook_to_ipynb(doc: dict[str, Any]) -> nbformat.NotebookNode:
    """Build a validated nbformat-v4 notebook from a stored notebook dict."""
    cells: list[nbformat.NotebookNode] = []
    for cell in doc.get("cells") or []:
        ctype = cell.get("type", "code")
        source = str(cell.get("source", ""))
        metadata = {"collapsed": True} if cell.get("collapsed") else {}
        if ctype == "markdown":
            cells.append(v4.new_markdown_cell(source, metadata=metadata))
            continue
        if ctype == "sql":
            source = "%%sql\n" + source
        outputs = []
        for out in cell.get("outputs") or []:
            converted = _convert_output(out)
            if converted is not None:
                outputs.append(converted)
        cells.append(v4.new_code_cell(source, outputs=outputs, metadata=metadata))
    node = v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3",
                "language": "python",
            },
            "language_info": {"name": "python"},
            "era5_etl": {
                "notebook_id": str(doc.get("id", "")),
                "name": str(doc.get("name", "")),
            },
        },
    )
    nbformat.validate(node)
    return node


__all__ = ["ipynb_filename", "notebook_to_ipynb"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_ipynb_export.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/ipynb_export.py tests/test_notebook_ipynb_export.py
git commit -m "feat(notebooks): notebook -> .ipynb (nbformat v4) converter"
```

---

### Task 4: Export endpoint

**Files:**
- Modify: `src/era5_etl/web/routes/notebooks.py`
- Test: `tests/test_notebook_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notebook_routes.py`:

```python
def test_export_ipynb(client):
    nbformat = pytest.importorskip("nbformat")
    r = client.post("/api/notebooks", json={"name": "Meu Notebook"})
    nb_id = r.json()["id"]
    client.put(
        f"/api/notebooks/{nb_id}",
        json={
            "cells": [
                {"id": "c1", "type": "markdown", "source": "# t", "outputs": []},
                {"id": "c2", "type": "sql", "source": "SELECT 1", "outputs": []},
            ]
        },
    )
    r = client.get(f"/api/notebooks/{nb_id}/export/ipynb")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and 'filename="meu-notebook.ipynb"' in cd
    nb = nbformat.reads(r.text, as_version=4)
    assert len(nb.cells) == 2
    assert nb.cells[1].source.startswith("%%sql\n")


def test_export_ipynb_unknown_notebook_404(client):
    assert client.get("/api/notebooks/nope/export/ipynb").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_routes.py -v -k export_ipynb`
Expected: FAIL — both tests get 404 / missing route (`test_export_ipynb` fails on status 404 with valid id).

- [ ] **Step 3: Implement the endpoint**

In `src/era5_etl/web/routes/notebooks.py`:

Add imports (top of file, near the other imports):

```python
import nbformat
from fastapi import APIRouter, Header, HTTPException, Request, Response

from era5_etl.notebooks.ipynb_export import ipynb_filename, notebook_to_ipynb
```

(Replace the existing `from fastapi import APIRouter, Header, HTTPException, Request`
line with the version that also imports `Response`.)

Add the endpoint after the `delete` handler (around line 115):

```python
# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.get("/{notebook_id}/export/ipynb")
def export_ipynb(notebook_id: str) -> Response:
    nb = notebook_store.get_notebook(notebook_id)
    if nb is None:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    node = notebook_to_ipynb(nb)
    filename = ipynb_filename(nb.get("name", ""))
    return Response(
        content=nbformat.writes(node),
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_routes.py -v`
Expected: all pass (existing tests too).

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/web/routes/notebooks.py tests/test_notebook_routes.py
git commit -m "feat(web): GET /api/notebooks/{id}/export/ipynb download endpoint"
```

---

### Task 5: `collapsed` cell field (backend)

**Files:**
- Modify: `src/era5_etl/web/notebook_store.py` (`make_cell`, ~line 183)
- Modify: `src/era5_etl/web/models/__init__.py` (`NotebookCellOut`, ~line 84)
- Modify: `src/era5_etl/web/routes/notebooks.py` (`create`, ~line 73)
- Test: `tests/test_notebook_store.py`, `tests/test_notebook_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notebook_store.py`:

```python
def test_make_cell_collapsed_default_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path))
    from era5_etl.web import notebook_store

    plain = notebook_store.make_cell("code", source="x=1")
    assert plain["collapsed"] is False
    folded = notebook_store.make_cell("code", source="x=1", collapsed=True)
    nb = notebook_store.create_notebook("t", cells=[folded])
    again = notebook_store.get_notebook(nb["id"])
    assert again["cells"][0]["collapsed"] is True
```

Append to `tests/test_notebook_routes.py`:

```python
def test_collapsed_roundtrips_through_api(client):
    nb_id = client.post("/api/notebooks", json={"name": "c"}).json()["id"]
    cells = [
        {"id": "c1", "type": "code", "source": "x=1", "outputs": [], "collapsed": True},
        {"id": "c2", "type": "code", "source": "y=2", "outputs": []},
    ]
    r = client.put(f"/api/notebooks/{nb_id}", json={"cells": cells})
    assert r.status_code == 200
    got = client.get(f"/api/notebooks/{nb_id}").json()["cells"]
    assert got[0]["collapsed"] is True
    assert got[1]["collapsed"] is False  # default when omitted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_store.py tests/test_notebook_routes.py -v -k collapsed`
Expected: FAIL (`KeyError: 'collapsed'` / assertion on missing field).

- [ ] **Step 3: Implement**

`src/era5_etl/web/models/__init__.py` — add the field to `NotebookCellOut`:

```python
class NotebookCellOut(BaseModel):
    id: str
    type: Literal["code", "sql", "markdown"]
    source: str
    outputs: list[dict] = Field(default_factory=list)
    collapsed: bool = False
```

`src/era5_etl/web/notebook_store.py` — extend `make_cell`:

```python
def make_cell(
    cell_type: CellType,
    source: str = "",
    outputs: list[dict[str, Any]] | None = None,
    collapsed: bool = False,
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "type": cell_type,
        "source": source,
        "outputs": list(outputs or []),
        "collapsed": bool(collapsed),
    }
```

`src/era5_etl/web/routes/notebooks.py` — in `create`, pass the template flag
through:

```python
        cells = [
            notebook_store.make_cell(
                cell_type=c.get("type", "code"),
                source=c.get("source", ""),
                outputs=c.get("outputs"),
                collapsed=bool(c.get("collapsed", False)),
            )
            for c in tpl.get("cells", [])
        ]
```

(Old notebook JSON files lack the key; `NotebookCellOut`'s default fills it
on read — `schema_version` stays 1.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_store.py tests/test_notebook_routes.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/web/notebook_store.py src/era5_etl/web/models/__init__.py src/era5_etl/web/routes/notebooks.py tests/test_notebook_store.py tests/test_notebook_routes.py
git commit -m "feat(notebooks): persist per-cell collapsed flag"
```

---

### Task 6: MLflow runs reader + panel merge

**Files:**
- Create: `src/era5_etl/web/mlflow_runs.py`
- Modify: `src/era5_etl/web/routes/notebooks.py` (`get`, ~line 87)
- Test: `tests/test_notebook_mlflow_runs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notebook_mlflow_runs.py`:

```python
"""MLflow file-store runs merged into the notebook Model-runs panel."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
mlflow = pytest.importorskip("mlflow")

from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(app)


def _seed_mlflow_run(notebook_id: str) -> str:
    from era5_etl.web.mlflow_runs import mlflow_tracking_uri

    mlflow.set_tracking_uri(mlflow_tracking_uri())
    mlflow.set_experiment(f"nb_{notebook_id}")
    with mlflow.start_run(run_name="parent") as parent:
        mlflow.set_tags(
            {
                "model_name": "xgboost_optuna_windows",
                "notes": "minha nota",
                "load_source": "db query",
            }
        )
        mlflow.log_params({"station_id": "A726"})
        mlflow.log_metrics({"rmse": 1.5, "duration_s": 12.0})
        with mlflow.start_run(run_name="expanding", nested=True):
            mlflow.log_metric("rmse_mean", 1.0)
    return parent.info.run_id


def test_tracking_uri_is_file_store_under_config_dir(tmp_path):
    from era5_etl.web.mlflow_runs import mlflow_tracking_uri

    uri = mlflow_tracking_uri()
    assert uri.startswith("file:")
    assert "mlruns" in uri


def test_get_notebook_merges_mlflow_parent_runs(client):
    nb_id = client.post("/api/notebooks", json={"name": "ml"}).json()["id"]
    run_id = _seed_mlflow_run(nb_id)

    runs = client.get(f"/api/notebooks/{nb_id}").json()["runs"]
    assert len(runs) == 1  # nested child filtered out
    run = runs[0]
    assert run["id"] == run_id
    assert run["model_name"] == "xgboost_optuna_windows"
    assert run["notes"] == "minha nota"
    assert run["params"]["station_id"] == "A726"
    assert run["metrics"]["rmse"] == 1.5
    # duration_s metric is promoted to the panel field, not left in metrics
    assert run["duration_s"] == 12.0
    assert "duration_s" not in run["metrics"]
    # string tag folded back where the panel reads it
    assert run["metrics"]["load_source"] == "db query"


def test_legacy_json_runs_still_listed_without_mlflow_store(client):
    nb_id = client.post("/api/notebooks", json={"name": "legacy"}).json()["id"]
    # No mlruns dir at all -> only legacy runs (none here) and no 500.
    r = client.get(f"/api/notebooks/{nb_id}")
    assert r.status_code == 200
    assert r.json()["runs"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_mlflow_runs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'era5_etl.web.mlflow_runs'`

- [ ] **Step 3: Implement the reader**

Create `src/era5_etl/web/mlflow_runs.py`:

```python
"""Read MLflow runs for the notebook Model-runs panel.

The "XGBoost With Optuna and Windows" template logs to a local MLflow file
store at ``<config_dir>/mlruns`` (one experiment per notebook, named
``nb_<notebook_id>``). This module maps the experiment's *top-level* runs
(child runs of the per-method studies are filtered out) into the same dict
shape as the legacy JSON runs, so the panel renders both alike.

Any failure (mlflow missing, store unreadable, no experiment) yields ``[]``
— the panel then shows legacy runs only, never a 500.
"""

from __future__ import annotations

import logging
from typing import Any

from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

# String tags folded back into ``metrics`` (the panel reads them there).
_TAG_METRIC_KEYS = ("load_source",)
_MAX_RUNS = 500


def mlflow_tracking_uri() -> str:
    """``file://`` URI of the local MLflow store (created on first log)."""
    return (_config_dir() / "mlruns").resolve().as_uri()


def list_runs_for_notebook(notebook_id: str) -> list[dict[str, Any]]:
    """Panel-shaped dicts for the notebook's top-level MLflow runs."""
    try:
        # Imported lazily: mlflow is heavy and only needed on this path.
        from mlflow.tracking import MlflowClient

        client = MlflowClient(tracking_uri=mlflow_tracking_uri())
        exp = client.get_experiment_by_name(f"nb_{notebook_id}")
        if exp is None:
            return []
        runs = client.search_runs([exp.experiment_id], max_results=_MAX_RUNS)
    except Exception:
        logger.exception("Failed to read MLflow runs for notebook %s", notebook_id)
        return []

    out: list[dict[str, Any]] = []
    for run in runs:
        tags = dict(run.data.tags)
        if tags.get("mlflow.parentRunId"):
            continue  # per-method child runs stay MLflow-UI-only
        metrics: dict[str, Any] = dict(run.data.metrics)
        duration_s = metrics.pop("duration_s", None)
        if duration_s is None:
            end = run.info.end_time or run.info.start_time
            duration_s = max(0.0, (end - run.info.start_time) / 1000.0)
        for key in _TAG_METRIC_KEYS:
            if key in tags:
                metrics[key] = tags[key]
        out.append(
            {
                "id": run.info.run_id,
                "ts": int(run.info.start_time),
                "model_name": tags.get("model_name", "mlflow"),
                "params": dict(run.data.params),
                "metrics": metrics,
                "duration_s": float(duration_s),
                "notes": tags.get("notes", ""),
            }
        )
    out.sort(key=lambda r: r["ts"])
    return out


__all__ = ["list_runs_for_notebook", "mlflow_tracking_uri"]
```

- [ ] **Step 4: Merge in the GET endpoint**

In `src/era5_etl/web/routes/notebooks.py`, add the import:

```python
from era5_etl.web.mlflow_runs import list_runs_for_notebook
```

and replace the `get` handler:

```python
@router.get("/{notebook_id}", response_model=NotebookOut)
def get(notebook_id: str) -> NotebookOut:
    nb = notebook_store.get_notebook(notebook_id)
    if nb is None:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    # Legacy JSON runs (other templates' log_model_run) + MLflow parent runs.
    runs = list(nb.get("runs") or []) + list_runs_for_notebook(notebook_id)
    runs.sort(key=lambda r: r["ts"])
    return NotebookOut(**{**nb, "runs": runs})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_mlflow_runs.py tests/test_notebook_routes.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/web/mlflow_runs.py src/era5_etl/web/routes/notebooks.py tests/test_notebook_mlflow_runs.py
git commit -m "feat(web): Model-runs panel merges MLflow parent runs with legacy JSON runs"
```

---

### Task 7: Kernel env (`MLFLOW_TRACKING_URI`, `ERA5_NB_NAME`)

**Files:**
- Modify: `src/era5_etl/notebooks/kernel_manager.py`
- Modify: `src/era5_etl/web/routes/notebooks.py` (`run_cell` ~line 173, `kernel_restart` ~line 151)
- Test: `tests/test_notebook_kernel.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notebook_kernel.py`:

```python
def test_kernel_build_env_includes_extra_env(tmp_path):
    from era5_etl.notebooks.kernel_manager import _Kernel

    k = _Kernel(
        "nb1",
        tmp_path,
        "http://x/runs",
        extra_env={"MLFLOW_TRACKING_URI": "file:///tmp/mlruns", "ERA5_NB_NAME": "Meu NB"},
    )
    env = k._build_env()
    assert env["ERA5_NB_ID"] == "nb1"
    assert env["MLFLOW_TRACKING_URI"] == "file:///tmp/mlruns"
    assert env["ERA5_NB_NAME"] == "Meu NB"
    assert "PATH" in env  # parent env inherited
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_notebook_kernel.py -v -k build_env`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'extra_env'`

- [ ] **Step 3: Implement in kernel_manager.py**

`_Kernel.__init__` gains the parameter (store it):

```python
    def __init__(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.notebook_id = notebook_id
        self.data_dir = data_dir
        self.runs_url = runs_url
        self.extra_env = dict(extra_env or {})
        self.token = secrets.token_urlsafe(32)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()  # serialise cell execution
        self._running_cell: str | None = None
        self.last_activity: float = time.time()
        self.started_at: float = time.time()
```

Extract env construction from `start()` into a testable method, and use it:

```python
    def _build_env(self) -> dict[str, str]:
        import os

        env = {
            "ERA5_NB_DATA_DIR": str(self.data_dir),
            "ERA5_NB_ID": self.notebook_id,
            "ERA5_NB_RUNS_URL": self.runs_url,
            "ERA5_NB_RUNS_TOKEN": self.token,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        env.update(self.extra_env)
        # Inherit the parent env (PATH, etc.) but override our keys.
        return {**os.environ, **env}

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "era5_etl.notebooks.kernel_runner"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._build_env(),
            text=True,
            encoding="utf-8",
            bufsize=1,  # line-buffered
        )
        # Drain the boot phase (anything emitted before "ready").
        self._consume_boot()
        self.started_at = time.time()
        self.last_activity = self.started_at
```

`KernelManager.get_or_start` and `restart` pass it through:

```python
    def get_or_start(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
        extra_env: dict[str, str] | None = None,
    ) -> _Kernel:
        with self._lock:
            kernel = self._kernels.get(notebook_id)
            if kernel and kernel.is_alive():
                return kernel
            if kernel is not None:
                # dead — drop the reference so we start fresh
                self._kernels.pop(notebook_id, None)
            kernel = _Kernel(notebook_id, data_dir, runs_url, extra_env=extra_env)
            kernel.start()
            self._kernels[notebook_id] = kernel
            self._ensure_reaper()
            return kernel
```

```python
    def restart(
        self,
        notebook_id: str,
        data_dir: Path,
        runs_url: str,
        extra_env: dict[str, str] | None = None,
    ) -> _Kernel:
        self.stop(notebook_id)
        return self.get_or_start(notebook_id, data_dir, runs_url, extra_env=extra_env)
```

- [ ] **Step 4: Wire from the routes**

In `src/era5_etl/web/routes/notebooks.py` (import of `mlflow_tracking_uri`
goes next to the `list_runs_for_notebook` import added in Task 6):

```python
from era5_etl.web.mlflow_runs import list_runs_for_notebook, mlflow_tracking_uri
```

Add a helper under `_runs_url`:

```python
def _kernel_extra_env(notebook_id: str) -> dict[str, str]:
    """Extra env for the kernel: MLflow store + human-readable name tag."""
    nb = notebook_store.get_notebook(notebook_id)
    return {
        "MLFLOW_TRACKING_URI": mlflow_tracking_uri(),
        "ERA5_NB_NAME": str((nb or {}).get("name", "")),
    }
```

In `kernel_restart`:

```python
    MANAGER.restart(
        notebook_id,
        data_dir,
        _runs_url(request, notebook_id),
        extra_env=_kernel_extra_env(notebook_id),
    )
```

In `run_cell`:

```python
        kernel = MANAGER.get_or_start(
            notebook_id, data_dir, runs_url, extra_env=_kernel_extra_env(notebook_id)
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_kernel.py tests/test_notebook_routes.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/notebooks/kernel_manager.py src/era5_etl/web/routes/notebooks.py tests/test_notebook_kernel.py
git commit -m "feat(notebooks): pass MLFLOW_TRACKING_URI and ERA5_NB_NAME into the kernel env"
```

---

### Task 8: MLflow UI launcher

**Files:**
- Create: `src/era5_etl/web/routes/mlflow_ui.py`
- Modify: `src/era5_etl/web/server.py` (router registration ~line 106, shutdown handler)
- Test: `tests/test_notebook_mlflow_ui.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notebook_mlflow_ui.py`:

```python
"""On-demand `mlflow ui` subprocess endpoints (Popen mocked — no real server)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture(autouse=True)
def _reset_mlflow_ui_state():
    from era5_etl.web.routes import mlflow_ui

    yield
    mlflow_ui.shutdown()


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(app)


class _FakeProc:
    def __init__(self):
        self.terminated = False
        self.stderr = None

    def poll(self):
        return 1 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def test_status_initially_not_running(client):
    r = client.get("/api/mlflow/ui/status")
    assert r.status_code == 200
    assert r.json() == {"running": False, "url": None}


def test_start_is_idempotent_and_status_reports_url(client, monkeypatch):
    from era5_etl.web.routes import mlflow_ui

    proc = _FakeProc()
    monkeypatch.setattr(mlflow_ui, "_spawn", lambda port: proc)
    monkeypatch.setattr(mlflow_ui, "_port_open", lambda port: True)

    r1 = client.post("/api/mlflow/ui/start")
    assert r1.status_code == 200
    url = r1.json()["url"]
    assert url.startswith("http://127.0.0.1:")

    # Second start returns the same URL without spawning again.
    monkeypatch.setattr(
        mlflow_ui, "_spawn", lambda port: pytest.fail("spawned twice")
    )
    assert client.post("/api/mlflow/ui/start").json()["url"] == url
    assert client.get("/api/mlflow/ui/status").json() == {"running": True, "url": url}

    mlflow_ui.shutdown()
    assert proc.terminated
    assert client.get("/api/mlflow/ui/status").json()["running"] is False


def test_start_failure_returns_502(client, monkeypatch):
    import io

    from era5_etl.web.routes import mlflow_ui

    class _DeadProc(_FakeProc):
        def __init__(self):
            super().__init__()
            self.stderr = io.StringIO("boom: port in use")

        def poll(self):
            return 1

    monkeypatch.setattr(mlflow_ui, "_spawn", lambda port: _DeadProc())
    r = client.post("/api/mlflow/ui/start")
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_notebook_mlflow_ui.py -v`
Expected: FAIL with `ImportError: cannot import name 'mlflow_ui'` (or 404s).

- [ ] **Step 3: Implement the route module**

Create `src/era5_etl/web/routes/mlflow_ui.py`:

```python
"""On-demand MLflow UI subprocess (singleton).

``POST /api/mlflow/ui/start`` spawns ``python -m mlflow ui`` against the
local file store (``<config_dir>/mlruns``) on a free localhost port and
returns its URL; subsequent calls are idempotent while the process lives.
``shutdown()`` is registered as a FastAPI shutdown handler in ``server.py``.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException

from era5_etl.web.mlflow_runs import mlflow_tracking_uri

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mlflow/ui", tags=["mlflow"])

_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None
_URL: str | None = None
_START_TIMEOUT_S = 30.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _spawn(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "mlflow",
            "ui",
            "--backend-store-uri",
            mlflow_tracking_uri(),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


@router.post("/start")
def start() -> dict[str, str]:
    global _PROC, _URL
    with _LOCK:
        if _PROC is not None and _PROC.poll() is None and _URL:
            return {"url": _URL}
        port = _free_port()
        proc = _spawn(port)
        deadline = time.time() + _START_TIMEOUT_S
        while time.time() < deadline:
            if proc.poll() is not None:
                err = (proc.stderr.read() if proc.stderr else "")[-2000:]
                raise HTTPException(
                    status_code=502, detail=f"mlflow ui exited during boot: {err}"
                )
            if _port_open(port):
                break
            time.sleep(0.25)
        else:
            proc.terminate()
            raise HTTPException(status_code=502, detail="mlflow ui did not start in time")
        _PROC = proc
        _URL = f"http://127.0.0.1:{port}"
        logger.info("mlflow ui started at %s", _URL)
        return {"url": _URL}


@router.get("/status")
def status() -> dict[str, object]:
    with _LOCK:
        running = _PROC is not None and _PROC.poll() is None
        return {"running": running, "url": _URL if running else None}


def shutdown() -> None:
    """Terminate the UI subprocess (no-op when not running)."""
    global _PROC, _URL
    with _LOCK:
        proc = _PROC
        _PROC = None
        _URL = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
```

- [ ] **Step 4: Register in server.py**

In `src/era5_etl/web/server.py` add the import (alphabetical block, after
`inventory`):

```python
from era5_etl.web.routes import (
    mlflow_ui as mlflow_ui_routes,
)
```

and after the existing `include_router` calls (~line 107):

```python
    app.include_router(mlflow_ui_routes.router)
    app.add_event_handler("shutdown", mlflow_ui_routes.shutdown)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_notebook_mlflow_ui.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/web/routes/mlflow_ui.py src/era5_etl/web/server.py tests/test_notebook_mlflow_ui.py
git commit -m "feat(web): on-demand MLflow UI subprocess with start/status endpoints"
```

---

### Task 9: New template "XGBoost With Optuna and Windows"

**Files:**
- Create: `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` (generated)
- Create (temporary, deleted at the end): `tmp_template_cells/` with cell sources + `assemble.py`
- Test: `tests/test_notebook_templates.py` (append)

The template is a copy of `xgboost_optuna_forecast.json` (18 cells) with:
content replaced at original indices 0 (intro), 6 (MLflow setup replaces
`log_model_run`), 12 (studies), 13 (refit), 15 (predictions fig), 17 (MLflow
logging); an appended block on cell 2 (config); and two new cells inserted
(windows preview before the studies, comparison after). Final order (20 cells):

```
0 intro(md) · 1 hardware · 2 config+CAPS · 3 md · 4 join helper · 5 plot helper
6 MLflow setup/repeat · 7 load · 8 validate · 9 features · 10 preview
11 holdout · 12 windows preview (NEW) · 13 two Optuna studies · 14 stats+compare (NEW)
15 winner refit · 16 timeline · 17 predictions fig · 18 importance · 19 MLflow logging
```

The original template's `train_window_days` search dimension is gone: the
temporal structure is governed by the backtest CAPS parameters (an expanding
window grows by definition). Cells 14/16 of the original (timeline,
importance) reference only `clean`/`test`/`best_feats`/`final_model`, all
still defined — they are kept verbatim.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notebook_templates.py`:

```python
def test_xgboost_optuna_windows_template():
    from era5_etl.notebooks.templates import list_templates, load_template

    ids = {t["id"]: t for t in list_templates()}
    assert "xgboost_optuna_windows" in ids
    assert ids["xgboost_optuna_windows"]["name"] == "XGBoost With Optuna and Windows"

    tpl = load_template("xgboost_optuna_windows")
    sources = [c["source"] for c in tpl["cells"]]
    assert len(tpl["cells"]) == 20
    joined = "\n".join(sources)
    # MLflow replaces the manual panel logger.
    assert "log_model_run" not in joined
    assert "mlflow.set_experiment" in joined
    assert "REPEAT_RUN_ID" in joined
    # Backtesting managed by Optuna over the tested window generators.
    assert "from era5_etl.notebooks.backtest import" in joined
    assert "EXPANDING_INITIAL_TRAIN_DAYS" in joined
    assert "SLIDING_TRAIN_DAYS" in joined
    # The removed search dimension must not resurface.
    assert "train_window_days" not in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -v -k windows_template`
Expected: FAIL (`assert "xgboost_optuna_windows" in ids`).

- [ ] **Step 3: Create the cell source files**

Create directory `tmp_template_cells/` at the repo root with the files below.
**Write the file contents exactly as given** (they are plain text/Python, the
assembly script JSON-encodes them).

`tmp_template_cells/cell00_intro.md`:

```markdown
# XGBoost + Optuna + Backtesting (Expanding/Sliding) + MLflow

Este template estende o **"XGBoost with Optuna"** com validação por
**backtesting temporal gerida pelo Optuna** e **tracking profissional com
MLflow**:

1. **Detecção de hardware** (primeira célula de código) escolhe GPU se houver
   build CUDA do XGBoost, senão CPU.
2. Carrega observações INMET unidas às 4 células ERA5-LAND vizinhas.
3. Constrói **features de lag com cutoff** (target em D+1 usa apenas dados até
   D−6 — sem vazamento) e features cíclicas de calendário.
4. **Backtesting com 2 métodos**, em sequência, ambos geridos pelo Optuna:
   - **STUDY 1 — Expanding Window:** o treino cresce a cada janela;
   - **STUDY 2 — Sliding Window:** treino de tamanho fixo desliza no tempo.
   O objetivo de cada trial é a **média do erro entre as janelas** do método.
5. Calcula **estatísticas por método** (média, desvio padrão, mínimo, máximo,
   mediana, coeficiente de variação) e **gráficos comparativos**.
6. Refit do **método vencedor** + avaliação no holdout final intocado.
7. **Tudo é registrado no MLflow**: 1 run *pai* por execução (params, métricas,
   gráficos, CSVs) + 2 runs *filhos* (expanding/sliding) com métricas por
   janela. O painel **Model runs** lê os runs pai; o botão **MLflow UI** abre
   a interface completa.
8. **Repetir um experimento:** cole o `run_id` de um run pai em
   `REPEAT_RUN_ID` na célula de configuração — a busca é pulada e os
   parâmetros salvos são reavaliados (novo run com tag `repeat_of`).

> Edite `STATION_ID`, `DATE_START`, `DATE_END`, `N_TRIALS` e os parâmetros de
> **BACKTESTING** em MAIÚSCULAS na célula de configuração, e rode tudo.
```

`tmp_template_cells/cell02_config_append.py`:

```python
# --- Repetir experimento (MLflow) ------------------------------------
# Cole aqui o run_id de um run PAI do MLflow para REPETIR aquele
# experimento: a busca Optuna e PULADA e os hiperparametros salvos sao
# reavaliados nas mesmas janelas + refit final (o novo run recebe a tag
# repeat_of). Vazio ("") = experimento NOVO "do zero" (busca completa).
REPEAT_RUN_ID = ""

# ===== BACKTESTING — validacao temporal (gerida pelo Optuna) =========
# Cada trial do Optuna treina 1 modelo POR JANELA e otimiza a MEDIA do
# erro entre as janelas. CUSTO TOTAL ~= N_TRIALS x n_janelas x 2 metodos
# treinos de XGBoost (ex.: 30 trials x 5 janelas x 2 = 300 treinos).
# Ajuste o orcamento com cuidado.
#
# As janelas sao cortadas APENAS do trecho train+val; o holdout final
# (TEST_FRACTION) permanece intocado ate o refit do metodo vencedor.
#
# Expanding Window: o treino comeca no inicio do periodo e CRESCE a cada
# janela; o teste e sempre o bloco seguinte. Simula "re-treinar com todo
# o historico disponivel".
EXPANDING_INITIAL_TRAIN_DAYS = 60   # tamanho inicial do treino (dias)
EXPANDING_TEST_DAYS          = 15   # tamanho de cada bloco de teste (dias)
EXPANDING_STEP_DAYS          = 15   # avanco entre janelas (dias)

# Sliding Window: o treino tem tamanho FIXO e desliza junto com o teste.
# Simula "re-treinar apenas com o historico recente".
SLIDING_TRAIN_DAYS = 60   # tamanho fixo do treino (dias)
SLIDING_TEST_DAYS  = 15   # tamanho de cada bloco de teste (dias)
SLIDING_STEP_DAYS  = 15   # avanco entre janelas (dias)

MAX_WINDOWS = 6   # teto de janelas por metodo (controla o custo da busca)

print(f"Backtesting: expanding {EXPANDING_INITIAL_TRAIN_DAYS}+{EXPANDING_TEST_DAYS}d "
      f"(passo {EXPANDING_STEP_DAYS}d) | sliding {SLIDING_TRAIN_DAYS}+{SLIDING_TEST_DAYS}d "
      f"(passo {SLIDING_STEP_DAYS}d) | max {MAX_WINDOWS} janelas/metodo")
if REPEAT_RUN_ID:
    print(f"REPEAT_RUN_ID definido: {REPEAT_RUN_ID} (a busca sera pulada)")
```

`tmp_template_cells/cell06_mlflow.py`:

```python
# --- MLflow: setup do tracking + repetir experimento ------------------
# Substitui o log_model_run() manual: cada execucao completa vira um run
# "pai" no MLflow (com 2 runs filhos, um por metodo de backtesting). O
# painel "Model runs" desta pagina le os runs pai diretamente do MLflow.
import os
import json
import mlflow
from mlflow.tracking import MlflowClient

# URI injetada pelo servidor; fallback local para .ipynb exportado.
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "file:./mlruns")
mlflow.set_tracking_uri(MLFLOW_URI)
_EXP_NAME = f"nb_{os.environ.get('ERA5_NB_ID', 'standalone')}"
mlflow.set_experiment(_EXP_NAME)
_client = MlflowClient()
_exp = _client.get_experiment_by_name(_EXP_NAME)
_client.set_experiment_tag(_exp.experiment_id, "notebook_name",
                           os.environ.get("ERA5_NB_NAME", ""))


def _mlflow_safe_params(d):
    """MLflow grava params como string; listas/dicts viram JSON legivel."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (list, tuple, dict)):
            out[str(k)] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            out[str(k)] = str(v)
    return out


def load_experiment_config(run_id):
    """Le os params de um run pai armazenado, para repetir o experimento."""
    run = _client.get_run(run_id)
    p = dict(run.data.params)
    return {
        "STATION_ID": p["station_id"],
        "DATE_START": p["date_start"],
        "DATE_END": p["date_end"],
        "TARGET_VAR": p["target_var"],
        "TEST_FRACTION": float(p["test_fraction"]),
        "ERA5_LAND_CUTOFF_HOURS": int(p["era5_land_cutoff_hours"]),
        "TARGET_METRIC": p.get("target_metric", "rmse"),
        "best_params": {
            "expanding": json.loads(p["expanding_best_params"]),
            "sliding": json.loads(p["sliding_best_params"]),
        },
    }


REPEAT_CONFIG = None
if REPEAT_RUN_ID:
    REPEAT_CONFIG = load_experiment_config(REPEAT_RUN_ID)
    STATION_ID = REPEAT_CONFIG["STATION_ID"]
    DATE_START = REPEAT_CONFIG["DATE_START"]
    DATE_END = REPEAT_CONFIG["DATE_END"]
    TARGET_VAR = REPEAT_CONFIG["TARGET_VAR"]
    TEST_FRACTION = REPEAT_CONFIG["TEST_FRACTION"]
    ERA5_LAND_CUTOFF_HOURS = REPEAT_CONFIG["ERA5_LAND_CUTOFF_HOURS"]
    TARGET_METRIC = REPEAT_CONFIG["TARGET_METRIC"]
    print(f"[repeat] Repetindo experimento {REPEAT_RUN_ID}:")
    print(f"[repeat]   station={STATION_ID}, {DATE_START}..{DATE_END}, "
          f"target={TARGET_VAR}, test_fraction={TEST_FRACTION}")
    print("[repeat] A busca Optuna sera PULADA; os hiperparametros salvos "
          "serao reavaliados nas janelas e no refit final.")
else:
    print(f"MLflow pronto: experiment '{_EXP_NAME}' em {MLFLOW_URI}")
    print("Novo experimento 'do zero' (REPEAT_RUN_ID vazio).")
```

`tmp_template_cells/cell12_windows.py`:

```python
# --- Backtesting: construir as janelas temporais ----------------------
# As janelas sao cortadas APENAS de train+val; o holdout final (test)
# permanece intocado ate o refit final. Limites half-open: uma linha em
# t pertence ao treino quando train_start <= t < train_end.
from era5_etl.notebooks.backtest import expanding_windows, sliding_windows

WINDOWS = {
    "expanding": expanding_windows(
        trainval.index,
        initial_train_days=EXPANDING_INITIAL_TRAIN_DAYS,
        test_days=EXPANDING_TEST_DAYS,
        step_days=EXPANDING_STEP_DAYS,
        max_windows=MAX_WINDOWS,
    ),
    "sliding": sliding_windows(
        trainval.index,
        train_days=SLIDING_TRAIN_DAYS,
        test_days=SLIDING_TEST_DAYS,
        step_days=SLIDING_STEP_DAYS,
        max_windows=MAX_WINDOWS,
    ),
}
for _method, _wins in WINDOWS.items():
    print(f"{_method}: {len(_wins)} janelas")

windows_df = pd.DataFrame([
    {
        "method": m,
        "window": w.index,
        "train_start": w.train_start,
        "train_end": w.train_end,
        "test_start": w.test_start,
        "test_end": w.test_end,
        "train_days": (w.train_end - w.train_start).days,
        "test_days": (w.test_end - w.test_start).days,
    }
    for m, ws in WINDOWS.items()
    for w in ws
])
windows_df
```

`tmp_template_cells/cell13_studies.py`:

```python
# --- Optuna gerencia o backtesting: 2 studies sequenciais --------------
# STUDY 1 (expanding) e depois STUDY 2 (sliding). O objetivo de cada
# trial e a MEDIA do TARGET_METRIC sobre as janelas do metodo: cada
# avaliacao de hiperparametros treina 1 modelo POR JANELA (CV temporal).
# Em modo repeat (REPEAT_RUN_ID preenchido) as buscas sao puladas e os
# params salvos sao reavaliados nas mesmas janelas.
import time
import optuna
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

optuna.logging.set_verbosity(optuna.logging.WARNING)


def _rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def _features_from_flags(flags):
    """Reconstroi a lista de features a partir dos flags use__/lag__."""
    sel_vars = [v for v in ACTIVE_VARS if flags.get(f"use__{v}", False)]
    sel_lags = [lag for lag in LAG_HOURS if flags.get(f"lag__{lag}h", False)]
    feats = [f"{v}_lag_{lag}h" for v in sel_vars for lag in sel_lags
             if f"{v}_lag_{lag}h" in LAG_FEATURE_COLS]
    return feats + CYCLICAL_COLS, sel_vars, sel_lags


def _split_flags_hyper(params):
    """Separa flags de selecao (use__/lag__) dos hiperparametros XGBoost."""
    flags = {k: v for k, v in params.items() if k.startswith(("use__", "lag__"))}
    hyper = {k: v for k, v in params.items() if not k.startswith(("use__", "lag__"))}
    return flags, hyper


def _eval_windows(method, params):
    """Treina 1 modelo por janela; devolve metricas por janela (ou None)."""
    flags, hyper = _split_flags_hyper(params)
    feats, sel_vars, sel_lags = _features_from_flags(flags)
    if not sel_vars or not sel_lags:
        return None  # precisa de ao menos 1 variavel meteorologica
    rows = []
    for w in WINDOWS[method]:
        tr = trainval[(trainval.index >= w.train_start) & (trainval.index < w.train_end)]
        te = trainval[(trainval.index >= w.test_start) & (trainval.index < w.test_end)]
        model = xgb.XGBRegressor(**hyper, tree_method="hist", device=DEVICE,
                                 random_state=OPTUNA_SEED)
        model.fit(tr[feats], tr[TARGET_VAR])
        y_true = te[TARGET_VAR].to_numpy()
        y_pred = predict_aligned(model, te[feats])
        rows.append({
            "window": int(w.index),
            "rmse": _rmse(y_true, y_pred),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "r2": float(r2_score(y_true, y_pred)),
            "n_train": int(len(tr)),
            "n_test": int(len(te)),
        })
    return rows


def _suggest_all(trial):
    params = {}
    for v in ACTIVE_VARS:
        params[f"use__{v}"] = trial.suggest_categorical(f"use__{v}", [True, False])
    for lag in LAG_HOURS:
        params[f"lag__{lag}h"] = trial.suggest_categorical(f"lag__{lag}h", [True, False])
    params.update(
        n_estimators=trial.suggest_int("n_estimators", 100, 800, step=50),
        max_depth=trial.suggest_int("max_depth", 3, 10),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        subsample=trial.suggest_float("subsample", 0.5, 1.0),
        colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
        min_child_weight=trial.suggest_int("min_child_weight", 1, 10),
        gamma=trial.suggest_float("gamma", 0.0, 5.0),
        reg_alpha=trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        reg_lambda=trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
    )
    return params


def _make_objective(method):
    def objective(trial):
        rows = _eval_windows(method, _suggest_all(trial))
        if rows is None:
            return float("inf")
        return float(np.mean([r[TARGET_METRIC] for r in rows]))
    return objective


def _make_progress_callback(method, t0):
    """Progresso ao vivo + parada por meta (STOP_MODE == 'threshold')."""
    seen_best = {"v": float("inf")}

    def _cb(study, trial):
        n_done = len(study.trials)
        best = study.best_value
        improved = best < seen_best["v"] - 1e-12
        seen_best["v"] = min(seen_best["v"], best)
        if improved or n_done % PROGRESS_EVERY == 0:
            elapsed = time.perf_counter() - t0
            cur = trial.value
            cur_str = f"{cur:.4f}" if cur is not None else "inf"
            mark = "  <-- novo melhor" if improved else ""
            print(f"[{method}] trial {n_done} | media {TARGET_METRIC}={cur_str} | "
                  f"melhor={best:.4f} | {elapsed:5.1f}s{mark}", flush=True)
        if STOP_MODE == "threshold" and best <= TARGET_METRIC_VALUE:
            print(f"[{method}] meta atingida ({best:.4f} <= {TARGET_METRIC_VALUE}) "
                  f"apos {n_done} trials -> parando.", flush=True)
            study.stop()

    return _cb


_budget_trials = N_TRIALS if STOP_MODE == "trials" else N_TRIALS_CAP
BACKTEST = {}
for _method in ("expanding", "sliding"):
    _t0 = time.perf_counter()
    if REPEAT_CONFIG is not None:
        _best_params = dict(REPEAT_CONFIG["best_params"][_method])
        print(f"[{_method}] repeat: reavaliando params salvos em "
              f"{len(WINDOWS[_method])} janelas...", flush=True)
        _study = None
        _rows = _eval_windows(_method, _best_params)
        _n_trials_done = 0
    else:
        print(f"[{_method}] busca Optuna: ate {_budget_trials} trials x "
              f"{len(WINDOWS[_method])} janelas...", flush=True)
        _study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=OPTUNA_SEED),
        )
        _study.optimize(_make_objective(_method), n_trials=_budget_trials,
                        callbacks=[_make_progress_callback(_method, _t0)],
                        show_progress_bar=False)
        _best_params = dict(_study.best_params)
        _rows = _eval_windows(_method, _best_params)
        _n_trials_done = len(_study.trials)
    if _rows is None:
        raise ValueError(
            f"[{_method}] nenhuma configuracao valida (nenhuma variavel/lag "
            f"selecionada). Aumente N_TRIALS ou revise LAG_HOURS."
        )
    _best_value = float(np.mean([r[TARGET_METRIC] for r in _rows]))
    BACKTEST[_method] = {
        "study": _study,
        "best_params": _best_params,
        "best_value": _best_value,
        "rows": _rows,
        "n_trials": _n_trials_done,
        "duration_s": time.perf_counter() - _t0,
    }
    print(f"[{_method}] melhor media {TARGET_METRIC}={_best_value:.4f} | "
          f"{BACKTEST[_method]['duration_s']:.1f}s", flush=True)
```

`tmp_template_cells/cell14_compare.py`:

```python
# --- Backtesting: estatisticas + graficos comparativos ----------------
# Media, desvio padrao, minimo, maximo, mediana e coeficiente de variacao
# das metricas por janela, por metodo — e 3 visoes comparando os metodos.
from plotly.subplots import make_subplots
import plotly.graph_objects as go

_stats_rows = []
for _method, _res in BACKTEST.items():
    _bt = pd.DataFrame(_res["rows"])
    for _metric in ("rmse", "mae", "r2"):
        _s = _bt[_metric]
        _mean = float(_s.mean())
        _std = float(_s.std(ddof=0))
        _stats_rows.append({
            "method": _method, "metric": _metric,
            "mean": _mean, "std": _std,
            "min": float(_s.min()), "max": float(_s.max()),
            "median": float(_s.median()),
            "cv": float(_std / abs(_mean)) if _mean else float("nan"),
            "n_windows": int(len(_s)),
        })
backtest_stats = pd.DataFrame(_stats_rows)
print(backtest_stats.to_string(index=False))

_COLORS = {"expanding": "#2563eb", "sliding": "#f59e0b"}
fig_backtest = make_subplots(
    rows=1, cols=3,
    subplot_titles=(f"{TARGET_METRIC} por janela",
                    f"distribuicao do {TARGET_METRIC}",
                    f"media +/- desvio ({TARGET_METRIC})"),
)
for _method, _res in BACKTEST.items():
    _bt = pd.DataFrame(_res["rows"])
    fig_backtest.add_trace(
        go.Scatter(x=_bt["window"], y=_bt[TARGET_METRIC], mode="lines+markers",
                   name=_method, legendgroup=_method,
                   line=dict(color=_COLORS[_method])),
        row=1, col=1)
    fig_backtest.add_trace(
        go.Box(y=_bt[TARGET_METRIC], name=_method, legendgroup=_method,
               showlegend=False, marker_color=_COLORS[_method]),
        row=1, col=2)
    _row_m = backtest_stats[(backtest_stats["method"] == _method)
                            & (backtest_stats["metric"] == TARGET_METRIC)].iloc[0]
    fig_backtest.add_trace(
        go.Bar(x=[_method], y=[_row_m["mean"]],
               error_y=dict(type="data", array=[_row_m["std"]]),
               name=_method, legendgroup=_method, showlegend=False,
               marker_color=_COLORS[_method]),
        row=1, col=3)
fig_backtest.update_layout(
    template="plotly_white", height=420,
    title="Backtesting: Expanding vs Sliding Window",
    margin=dict(t=90, b=40),
)
fig_backtest
```

`tmp_template_cells/cell15_refit.py`:

```python
# --- Refit final: metodo vencedor + avaliacao no holdout de teste ------
# Vencedor = menor media do TARGET_METRIC entre as janelas do proprio
# metodo. O refit usa TODO o train+val; o holdout final segue intocado.
winner = min(BACKTEST, key=lambda m: BACKTEST[m]["best_value"])
_flags, hyperparams = _split_flags_hyper(BACKTEST[winner]["best_params"])
best_feats, best_vars, best_lags = _features_from_flags(_flags)
print(f"Metodo vencedor: {winner} "
      f"(media {TARGET_METRIC}={BACKTEST[winner]['best_value']:.4f})")

fit_df = trainval
# Monitoramento do treino: erro por rodada de boosting em treino
# (validation_0) e teste (validation_1). Sem early stopping, o eval_set
# nao altera o modelo -> serve so para visualizar a convergencia.
_eval_metric = "mae" if TARGET_METRIC == "mae" else "rmse"
final_model = xgb.XGBRegressor(
    **hyperparams, tree_method="hist", device=DEVICE, random_state=OPTUNA_SEED,
    eval_metric=_eval_metric,
)
_t0 = time.perf_counter()
final_model.fit(
    fit_df[best_feats], fit_df[TARGET_VAR],
    eval_set=[(fit_df[best_feats], fit_df[TARGET_VAR]),
              (test[best_feats], test[TARGET_VAR])],
    verbose=TRAIN_PRINT_EVERY,
)
duration_s = time.perf_counter() - _t0

y_true = test[TARGET_VAR].to_numpy()
y_pred = predict_aligned(final_model, test[best_feats])
rmse = _rmse(y_true, y_pred)
mae = float(mean_absolute_error(y_true, y_pred))
r2 = float(r2_score(y_true, y_pred))
metrics = {
    "rmse": rmse, "mae": mae, "r2": r2,
    "best_val_rmse": float(BACKTEST[winner]["best_value"]),
    "test_fraction": float(TEST_FRACTION),
    "n_train": int(len(fit_df)),
    "n_test": int(len(test)),
    "num_days": int((pd.to_datetime(DATE_END) - pd.to_datetime(DATE_START)).days) + 1,
    "n_features": int(len(best_feats)),
    "n_trials": int(sum(res["n_trials"] for res in BACKTEST.values())),
    "expanding_rmse_mean": float(np.mean([r["rmse"] for r in BACKTEST["expanding"]["rows"]])),
    "sliding_rmse_mean": float(np.mean([r["rmse"] for r in BACKTEST["sliding"]["rows"]])),
}
print(f"Refit final em {duration_s:.2f}s | {len(fit_df):,} linhas, "
      f"{len(best_feats)} features")
print(metrics)
print("best_vars:", best_vars)
print("best_lags:", best_lags)
```

`tmp_template_cells/cell17_predictions.py`:

```python
# --- Predictions vs reality + residuals (Plotly) -----------------------
plot_df = test.copy()
plot_df["date"] = plot_df.index.date
plot_df["hour_utc"] = plot_df.index.hour
fig_pred = plot_predictions(plot_df, y_true, y_pred)
fig_pred
```

`tmp_template_cells/cell19_log.py`:

```python
# --- MLflow: registrar o experimento (run pai + 2 filhos) --------------
# Pai: inputs do usuario, hiperparametros vencedores, metricas do holdout,
# medias por metodo, graficos e CSVs. Filhos (expanding/sliding): metricas
# por janela (step = indice da janela), estatisticas agregadas, trials do
# Optuna e historico da otimizacao.
_load_info = globals().get("__last_load_info__", {"source": "unknown", "duration_s": 0.0})
total_duration_s = duration_s + sum(res["duration_s"] for res in BACKTEST.values())
_run_name = (f"{STATION_ID} {DATE_START}..{DATE_END} "
             + ("repeat" if REPEAT_RUN_ID else "search"))

with mlflow.start_run(run_name=_run_name) as _parent:
    mlflow.set_tags({
        "model_name": "xgboost_optuna_windows",
        "notebook_name": os.environ.get("ERA5_NB_NAME", ""),
        "load_source": str(_load_info.get("source", "unknown")),
        "device": DEVICE,
        "winner_method": winner,
        "notes": f"backtest expanding+sliding; station={STATION_ID}; D+1 from <=D-6",
    })
    if REPEAT_RUN_ID:
        mlflow.set_tag("repeat_of", REPEAT_RUN_ID)

    mlflow.log_params(_mlflow_safe_params({
        "station_id": STATION_ID,
        "date_start": DATE_START,
        "date_end": DATE_END,
        "target_var": TARGET_VAR,
        "test_fraction": TEST_FRACTION,
        "era5_land_cutoff_hours": ERA5_LAND_CUTOFF_HOURS,
        "target_metric": TARGET_METRIC,
        "stop_mode": STOP_MODE,
        "n_trials_budget": _budget_trials,
        "max_windows": MAX_WINDOWS,
        "expanding_initial_train_days": EXPANDING_INITIAL_TRAIN_DAYS,
        "expanding_test_days": EXPANDING_TEST_DAYS,
        "expanding_step_days": EXPANDING_STEP_DAYS,
        "sliding_train_days": SLIDING_TRAIN_DAYS,
        "sliding_test_days": SLIDING_TEST_DAYS,
        "sliding_step_days": SLIDING_STEP_DAYS,
        "era5_land_vars": ACTIVE_VARS,
        "lag_hours": LAG_HOURS,
        "best_vars": best_vars,
        "best_lags": best_lags,
        "features": best_feats,
        "expanding_best_params": BACKTEST["expanding"]["best_params"],
        "sliding_best_params": BACKTEST["sliding"]["best_params"],
        **{f"xgb_{k}": v for k, v in hyperparams.items()},
    }))

    mlflow.log_metrics({k: float(v) for k, v in metrics.items()
                        if np.isfinite(float(v))})
    mlflow.log_metric("duration_s", float(total_duration_s))
    mlflow.log_metric("load_duration_s", float(_load_info.get("duration_s", 0.0)))

    mlflow.log_figure(fig_backtest, "plots/backtest_comparison.html")
    mlflow.log_figure(fig_pred, "plots/predictions.html")
    mlflow.log_text(backtest_stats.to_csv(index=False), "backtest_stats.csv")

    for _method, _res in BACKTEST.items():
        with mlflow.start_run(run_name=_method, nested=True):
            mlflow.set_tag("model_name", f"xgboost_optuna_windows_{_method}")
            mlflow.log_params(_mlflow_safe_params({
                "best_params": _res["best_params"],
                "n_windows": len(_res["rows"]),
            }))
            for _r in _res["rows"]:
                mlflow.log_metrics(
                    {"rmse": _r["rmse"], "mae": _r["mae"], "r2": _r["r2"]},
                    step=int(_r["window"]),
                )
            _meth_stats = backtest_stats[backtest_stats["method"] == _method]
            for _, _srow in _meth_stats.iterrows():
                _m = _srow["metric"]
                _vals = {
                    f"{_m}_mean": _srow["mean"], f"{_m}_std": _srow["std"],
                    f"{_m}_min": _srow["min"], f"{_m}_max": _srow["max"],
                    f"{_m}_median": _srow["median"], f"{_m}_cv": _srow["cv"],
                }
                mlflow.log_metrics({k: float(v) for k, v in _vals.items()
                                    if np.isfinite(float(v))})
            mlflow.log_text(pd.DataFrame(_res["rows"]).to_csv(index=False),
                            "windows.csv")
            if _res["study"] is not None:
                mlflow.log_text(
                    _res["study"].trials_dataframe().to_csv(index=False),
                    "optuna_trials.csv",
                )
                try:
                    from optuna.visualization import plot_optimization_history
                    mlflow.log_figure(plot_optimization_history(_res["study"]),
                                      "plots/optuna_history.html")
                except Exception as _exc:
                    print(f"[mlflow] historico do Optuna indisponivel: {_exc}")

    parent_run_id = _parent.info.run_id

print(f"MLflow: run pai registrado: {parent_run_id}")
print(f'Para REPETIR este experimento: REPEAT_RUN_ID = "{parent_run_id}"')
print("Abra o botao 'MLflow UI' no topo da pagina para explorar os runs.")
```

`tmp_template_cells/assemble.py`:

```python
"""One-off: build xgboost_optuna_windows.json from xgboost_optuna_forecast.json.

Run from the repo root: ``python tmp_template_cells/assemble.py``
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
TPL_DIR = Path("src/era5_etl/_data/notebook_templates")

src = json.loads(
    (TPL_DIR / "xgboost_optuna_forecast.json").read_text(encoding="utf-8")
)
cells = src["cells"]
assert len(cells) == 18, f"expected 18 cells in the source template, got {len(cells)}"


def read(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8").rstrip("\n")


# Replacements at ORIGINAL indices (before any insertion).
cells[0]["source"] = read("cell00_intro.md")
cells[2]["source"] = cells[2]["source"].rstrip("\n") + "\n\n" + read("cell02_config_append.py")
cells[6]["source"] = read("cell06_mlflow.py")
cells[12]["source"] = read("cell13_studies.py")
cells[13]["source"] = read("cell15_refit.py")
cells[15]["source"] = read("cell17_predictions.py")
cells[17]["source"] = read("cell19_log.py")

# Insertions: windows preview before the studies cell, comparison after it.
cells.insert(12, {"type": "code", "source": read("cell12_windows.py")})
cells.insert(14, {"type": "code", "source": read("cell14_compare.py")})

out = {
    "name": "XGBoost With Optuna and Windows",
    "description": (
        "Tudo do 'XGBoost with Optuna', mais: backtesting temporal "
        "(Expanding e Sliding Windows) gerido pelo Optuna em 2 studies "
        "sequenciais, tracking profissional com MLflow (parametros, "
        "metricas, graficos e artefatos por run) e repeticao de "
        "experimentos passados via REPEAT_RUN_ID. Os runs aparecem no "
        "painel Model runs e na MLflow UI."
    ),
    "cells": cells,
}
target = TPL_DIR / "xgboost_optuna_windows.json"
target.write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"wrote {target} ({len(cells)} cells)")
```

- [ ] **Step 4: Assemble the template**

Run: `py -3.12 tmp_template_cells/assemble.py`
Expected: `wrote src\era5_etl\_data\notebook_templates\xgboost_optuna_windows.json (20 cells)`

- [ ] **Step 5: Run the template tests**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -v`
Expected: all pass (including the new `test_xgboost_optuna_windows_template`).

- [ ] **Step 6: Sanity-compile every code cell**

Run:

```bash
py -3.12 -c "import json; [compile(c['source'].replace(chr(0x2212),'-'), '<cell>', 'exec') for c in json.load(open('src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json', encoding='utf-8'))['cells'] if c['type'] == 'code']; print('all code cells compile')"
```

Expected: `all code cells compile`

- [ ] **Step 7: Delete the temp dir and commit**

```bash
rm -rf tmp_template_cells
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json tests/test_notebook_templates.py
git commit -m "feat(notebooks): XGBoost With Optuna and Windows template (MLflow + backtesting)"
```

---

### Task 10: Frontend API client + types

**Files:**
- Modify: `web-ui/src/lib/api.ts`

- [ ] **Step 1: Extend the NotebookCell type** (~line 817)

```typescript
export type NotebookCell = {
  id: string;
  type: "code" | "sql" | "markdown";
  source: string;
  outputs?: CellOutput[];
  collapsed?: boolean;
};
```

- [ ] **Step 2: Add exportIpynb under `api.notebooks`** (after `templates`, ~line 775)

```typescript
    exportIpynb: async (id: string, name: string) => {
      const r = await fetch(`/api/notebooks/${id}/export/ipynb`);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j.detail) detail = String(j.detail);
        } catch {
          // ignore
        }
        throw new Error(detail);
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const slug =
        name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "notebook";
      a.href = url;
      a.download = `${slug}.ipynb`;
      a.click();
      URL.revokeObjectURL(url);
    },
```

- [ ] **Step 3: Add the mlflow client** (new top-level key in the `api` object,
right after the `notebooks` block):

```typescript
  mlflow: {
    start: () =>
      request<{ url: string }>("/api/mlflow/ui/start", { method: "POST" }),
    status: () =>
      request<{ running: boolean; url: string | null }>("/api/mlflow/ui/status"),
  },
```

- [ ] **Step 4: Type-check / build**

Run (in `web-ui/`): `bun run build` (fallback: `NODE_OPTIONS="--use-system-ca" npm run build` per project memory)
Expected: build succeeds, no TS errors.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/lib/api.ts
git commit -m "feat(web-ui): api client for ipynb export, mlflow ui, collapsed cell field"
```

---

### Task 11: Frontend — collapse/expand cells + editor header buttons

> **Invoke the `frontend-design:frontend-design` skill before this task**
> (user request for all web-interface work). Keep the existing visual
> language: `card`, `btn-outline`, `btn-primary`, ink/ocean palette,
> lucide icons, i18n via `useTranslation`.

**Files:**
- Modify: `web-ui/src/pages/NotebookEditor.tsx`
- Modify: `web-ui/src/i18n/locales/en.ts` (notebooks.editor section, ~line 817)
- Modify: `web-ui/src/i18n/locales/pt.ts` (same section)

- [ ] **Step 1: Add i18n keys**

In `en.ts` inside `notebooks.editor`:

```typescript
      export: "Export .ipynb",
      exportTitle: "Download this notebook as a Jupyter file",
      mlflow: "MLflow UI",
      mlflowTitle: "Open the MLflow experiment tracker in a new tab",
      mlflowStarting: "Starting…",
      mlflowError: "Failed to start the MLflow UI",
      collapseCell: "Collapse cell",
      expandCell: "Expand cell",
      collapsedOutputs: "{{count}} output(s) hidden",
```

In `pt.ts` (same keys):

```typescript
      export: "Exportar .ipynb",
      exportTitle: "Baixar este notebook como arquivo Jupyter",
      mlflow: "MLflow UI",
      mlflowTitle: "Abrir o tracker de experimentos MLflow em nova aba",
      mlflowStarting: "Iniciando…",
      mlflowError: "Falha ao iniciar a MLflow UI",
      collapseCell: "Colapsar célula",
      expandCell: "Expandir célula",
      collapsedOutputs: "{{count}} output(s) ocultos",
```

- [ ] **Step 2: Editor header — Export + MLflow UI buttons**

In `NotebookEditor.tsx`:

Add icons to the lucide import: `Download`, `FlaskConical`.

Add a mutation near `saveMut` (~line 108):

```typescript
  const mlflowMut = useMutation({
    mutationFn: api.mlflow.start,
    onSuccess: ({ url }) => window.open(url, "_blank", "noopener"),
    onError: () => alert(t("notebooks.editor.mlflowError")),
  });
```

In the header's right-hand button group (before the "Run all" button):

```tsx
          <button
            type="button"
            className="btn-outline inline-flex items-center gap-1.5"
            onClick={() => void api.notebooks.exportIpynb(notebookId, name)}
            title={t("notebooks.editor.exportTitle")}
          >
            <Download className="h-4 w-4" />
            {t("notebooks.editor.export")}
          </button>
          <button
            type="button"
            className="btn-outline inline-flex items-center gap-1.5"
            onClick={() => mlflowMut.mutate()}
            disabled={mlflowMut.isPending}
            title={t("notebooks.editor.mlflowTitle")}
          >
            {mlflowMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FlaskConical className="h-4 w-4" />
            )}
            {mlflowMut.isPending
              ? t("notebooks.editor.mlflowStarting")
              : t("notebooks.editor.mlflow")}
          </button>
```

- [ ] **Step 3: Per-cell collapse toggle**

In the cell header's left group, insert the chevron button **before** the
run-status icon (first child of the `div.flex.items-center.gap-2`):

```tsx
                <button
                  type="button"
                  className="text-ink-400 hover:text-ink-600"
                  onClick={() =>
                    updateCell(cell.id, { collapsed: !cell.collapsed })
                  }
                  title={
                    cell.collapsed
                      ? t("notebooks.editor.expandCell")
                      : t("notebooks.editor.collapseCell")
                  }
                >
                  {cell.collapsed ? (
                    <ChevronRight className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                </button>
```

Then wrap the editor + outputs in the collapsed conditional. Replace:

```tsx
            <CellEditor
              value={cell.source}
              ...
            />
            {cell.outputs && cell.outputs.length > 0 && (
              <div className="border-t border-ink-100 p-3 space-y-2">
                {cell.outputs.map((out, i) => (
                  <CellOutput key={i} output={out} />
                ))}
              </div>
            )}
```

with:

```tsx
            {cell.collapsed ? (
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left"
                onClick={() => updateCell(cell.id, { collapsed: false })}
                title={t("notebooks.editor.expandCell")}
              >
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-400">
                  {cell.source.split("\n").find((l) => l.trim()) ?? "…"}
                </span>
                {(cell.outputs?.length ?? 0) > 0 && (
                  <span className="shrink-0 rounded-full bg-ink-100 px-2 py-0.5 text-[10px] text-ink-500">
                    {t("notebooks.editor.collapsedOutputs", {
                      count: cell.outputs?.length ?? 0,
                    })}
                  </span>
                )}
              </button>
            ) : (
              <>
                <CellEditor
                  value={cell.source}
                  onChange={(s) => updateCell(cell.id, { source: s })}
                  language={
                    cell.type === "code"
                      ? "python"
                      : cell.type === "sql"
                        ? "sql"
                        : "markdown"
                  }
                  path={`${notebookId}/${cell.id}`}
                  onRunRequested={() => onRunCellRef.current(cell)}
                />
                {cell.outputs && cell.outputs.length > 0 && (
                  <div className="border-t border-ink-100 p-3 space-y-2">
                    {cell.outputs.map((out, i) => (
                      <CellOutput key={i} output={out} />
                    ))}
                  </div>
                )}
              </>
            )}
```

(The collapsed state travels in `cells` and is persisted by the existing
Save button — no extra wiring. Running a collapsed cell still works: the
Run button stays in the header.)

- [ ] **Step 4: Build**

Run (in `web-ui/`): `bun run build`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/pages/NotebookEditor.tsx web-ui/src/i18n/locales/en.ts web-ui/src/i18n/locales/pt.ts
git commit -m "feat(web-ui): per-cell collapse, ipynb export and MLflow UI buttons in editor"
```

---

### Task 12: Frontend — download button on notebook cards

> **Invoke the `frontend-design:frontend-design` skill before this task.**

**Files:**
- Modify: `web-ui/src/pages/Notebooks.tsx`
- Modify: `web-ui/src/i18n/locales/en.ts` / `pt.ts` (notebooks.card section)

- [ ] **Step 1: i18n keys**

`en.ts` inside `notebooks.card`:

```typescript
      export: "Export .ipynb",
```

`pt.ts`:

```typescript
      export: "Exportar .ipynb",
```

- [ ] **Step 2: Card button**

In `Notebooks.tsx`: add `Download` to the lucide import. In the card, next to
the delete button (inside the same flex container, before the Trash2 button):

```tsx
                <button
                  type="button"
                  className="opacity-0 transition group-hover:opacity-100"
                  title={t("notebooks.card.export")}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    void api.notebooks.exportIpynb(nb.id, nb.name);
                  }}
                >
                  <Download className="h-4 w-4 text-ink-400 hover:text-ocean-600" />
                </button>
```

(Both icon buttons sit in the card's right-side group; wrap them in a
`<div className="flex shrink-0 items-center gap-2">` if they aren't already
siblings.)

- [ ] **Step 3: Build**

Run (in `web-ui/`): `bun run build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/pages/Notebooks.tsx web-ui/src/i18n/locales/en.ts web-ui/src/i18n/locales/pt.ts
git commit -m "feat(web-ui): export .ipynb button on notebook cards"
```

---

### Task 13: Full verification + docs touch-up

- [ ] **Step 1: Run the whole backend suite**

Run: `py -3.12 -m pytest`
Expected: all tests pass (≈178 pre-existing + ~20 new).

- [ ] **Step 2: Rebuild the SPA once more and smoke-test**

Run (in `web-ui/`): `bun run build`
Then start the app with `era5 ui` and manually verify: notebook card download works; in the editor the collapse
chevron folds a cell to its one-line preview; "Export .ipynb" downloads a
file that opens in Jupyter; "MLflow UI" opens a new tab (after the new
template has logged at least one run, the Model runs panel lists it).

- [ ] **Step 3: Note the new architecture facts in CLAUDE.md**

Append to the "Architectural anchors" section of `CLAUDE.md`:

```markdown
- **Notebook experiment tracking is MLflow-backed for the "Windows" template.**
  MLflow uses a local file store at `<config_dir>/mlruns` (one experiment per
  notebook, `nb_<id>`); `web/mlflow_runs.py` maps parent runs into the Model
  runs panel (merged with legacy JSON runs — other templates still POST
  `/runs`). `web/routes/mlflow_ui.py` runs `mlflow ui` on demand. Backtest
  window maths lives in `notebooks/backtest.py` (tested), not in template
  JSON. `.ipynb` export goes through `notebooks/ipynb_export.py`.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note MLflow tracking, backtest module and ipynb export in CLAUDE.md"
```

---

## Plan self-review (done at write time)

- **Spec coverage:** export (.ipynb) → Tasks 3/4/10/12; collapse → Tasks 5/11;
  MLflow infra + panel merge + kernel env + UI launcher → Tasks 1/6/7/8;
  repeat → Task 9 (cells 2/6/13); backtesting + stats + comparison charts +
  Optuna management + CAPS params → Tasks 2/9. Template-name requirement
  ("XGBoost With Optuna and Windows", original untouched) → Task 9.
- **Defaults note:** the spec's CAPS example used 365-day windows; the
  template's default period (2025-01-01..2025-06-30) is ~180 days, so the
  shipped defaults are 60/15/15 to produce ~5 windows out of the box.
- **Type consistency:** `BacktestWindow` fields, `_eval_windows` rows keys
  (`window/rmse/mae/r2/n_train/n_test`), `BACKTEST[method]` keys
  (`study/best_params/best_value/rows/n_trials/duration_s`), and
  `backtest_stats` columns are used consistently across cells 13/14/15/19.
  `mlflow_tracking_uri`/`list_runs_for_notebook` names match between Tasks 6–8.
