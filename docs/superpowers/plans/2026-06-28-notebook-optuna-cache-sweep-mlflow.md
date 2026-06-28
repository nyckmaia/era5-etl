# Notebook Optuna Cache + Window Sweep + MLflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent Optuna search cache, a cheap "winner-hyperparameter" window-config sweep with RMSE-vs-train-months learning curves, and per-config MLflow comparison to the "XGBoost With Optuna and Windows" notebook template.

**Architecture:** Testable logic goes into modules under `src/era5_etl/notebooks/` (`optuna_cache.py` new; `backtest.py` and `helpers_module.py` extended). The template JSON only orchestrates: it computes a fingerprint, opens a cached Optuna SQLite study and runs only the remaining trials, reuses a cached feature-selection result, runs a sweep that re-evaluates the winning hyperparameters across a grid of sliding window configs, plots faceted learning curves, and logs one MLflow child run per config plus a figure/CSV on the parent.

**Tech Stack:** Python 3.12, Optuna (SQLite storage), XGBoost (CUDA), pandas, numpy 1.26.4, Plotly, MLflow 3.x, pytest.

## Global Constraints

- numpy stays **1.26.4** — never let any change bump numpy to 2.x (breaks scipy/xgboost import in this env).
- Backtest/window/cache math lives in `src/era5_etl/notebooks/` modules, **never inline** in template JSON (CLAUDE.md anchor).
- Template JSON is written with `json.dumps(obj, ensure_ascii=False, indent=2) + "\n"` (trailing newline). The runtime notebook `<config_dir>/notebooks/6d1169c493984849a5e56e7ec7229128.json` is written with **no** trailing newline (matches `web/notebook_store._write_atomic`).
- Every template/notebook cell-source edit must keep all code cells compiling (`compile(src, "<cell>", "exec")`).
- All cell changes are applied to **both** the template `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` **and** the runtime notebook `6d1169c493984849a5e56e7ec7229128.json` (located via `era5_etl.web.user_config._config_dir() / "notebooks"`).
- Tests run with `py -3.12 -m pytest` (no venv). Coverage addopts are active; do not pass `-p no:cov`.
- Commit only the git-tracked files (the runtime notebook under `<config_dir>` is **not** in the repo).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/era5_etl/notebooks/optuna_cache.py` (new) | Fingerprints, JSON cache I/O, Optuna study cache (open/resume/reset, trial counting) |
| `src/era5_etl/notebooks/backtest.py` (modify) | Add `SweepConfig`, `build_sweep_grid()`, `summarize_sweep()` next to the window generators |
| `src/era5_etl/notebooks/helpers_module.py` (modify) | Add `plot_learning_curves()` and inject it into the kernel namespace |
| `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` (modify) | Config flags, cached search, sweep cells, MLflow additions |
| `<config_dir>/notebooks/6d1169c493984849a5e56e7ec7229128.json` (modify, not git) | Same cell edits applied to the live notebook |
| `tests/test_optuna_cache.py` (new) | Unit tests for `optuna_cache.py` |
| `tests/test_backtest.py` (modify) | Unit tests for `build_sweep_grid` / `summarize_sweep` |
| `tests/test_notebook_templates.py` (modify) | Assert new config flags + sweep cells exist and compile |

A reusable cell-injection helper script is provided in Task 6 and reused verbatim (only the per-cell strings change) in Tasks 7–9.

---

## Task 0: Baseline commit of existing template edits

The working tree already contains the earlier cupy-diagnostic (cell 2) and MLflow `name="model"` (cell 20) edits to the template. Commit them first so this plan's commits stay clean.

- [ ] **Step 1: Confirm the only staged-worthy change is the template**

Run: `git status --short src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json`
Expected: ` M src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json`

- [ ] **Step 2: Commit it**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json
git commit -m "feat(notebooks): GPU hardware diagnostic cell + MLflow name= in Windows template"
```

---

## Task 1: `optuna_cache.py` — fingerprints + JSON cache I/O

**Files:**
- Create: `src/era5_etl/notebooks/optuna_cache.py`
- Test: `tests/test_optuna_cache.py`

**Interfaces:**
- Produces:
  - `data_fingerprint(df: pandas.DataFrame, target_col: str) -> str`
  - `config_fingerprint(payload: dict, data_fp: str) -> str`
  - `load_json_cache(path) -> dict | None`
  - `save_json_cache(path, obj: dict) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_optuna_cache.py`:

```python
import numpy as np
import pandas as pd
import pytest

from era5_etl.notebooks import optuna_cache as oc


def _df(n=24, target=0.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    return pd.DataFrame({"temp_ar": np.full(n, target, dtype=np.float64)}, index=idx)


def test_data_fingerprint_is_deterministic():
    assert oc.data_fingerprint(_df(), "temp_ar") == oc.data_fingerprint(_df(), "temp_ar")


def test_data_fingerprint_changes_with_values():
    a = oc.data_fingerprint(_df(target=0.0), "temp_ar")
    b = oc.data_fingerprint(_df(target=1.0), "temp_ar")
    assert a != b


def test_data_fingerprint_changes_with_length_and_span():
    base = oc.data_fingerprint(_df(n=24), "temp_ar")
    assert base != oc.data_fingerprint(_df(n=48), "temp_ar")


def test_config_fingerprint_stable_under_key_reordering():
    fp1 = oc.config_fingerprint({"a": 1, "b": [1, 2]}, "DATA")
    fp2 = oc.config_fingerprint({"b": [1, 2], "a": 1}, "DATA")
    assert fp1 == fp2


def test_config_fingerprint_changes_with_value_and_data():
    base = oc.config_fingerprint({"a": 1}, "DATA")
    assert base != oc.config_fingerprint({"a": 2}, "DATA")
    assert base != oc.config_fingerprint({"a": 1}, "OTHER")


def test_json_cache_roundtrip_and_missing(tmp_path):
    p = tmp_path / "x.json"
    assert oc.load_json_cache(p) is None          # missing
    oc.save_json_cache(p, {"k": [1, 2], "s": "v"})
    assert oc.load_json_cache(p) == {"k": [1, 2], "s": "v"}
    p.write_text("{not json", encoding="utf-8")    # corrupt
    assert oc.load_json_cache(p) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_optuna_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'era5_etl.notebooks.optuna_cache'`

- [ ] **Step 3: Write minimal implementation**

Create `src/era5_etl/notebooks/optuna_cache.py`:

```python
"""Persistent caching for the "XGBoost With Optuna and Windows" template.

Two things are cached, both keyed by a fingerprint of everything that affects
the result (search config + a cheap fingerprint of the training data):

* the Optuna study itself (native SQLite storage, resumed across runs);
* JSON side-artifacts (the resolved feature selection, sweep bookkeeping).

The logic lives here (not inline in the template JSON) so it is unit-tested.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def data_fingerprint(df: pd.DataFrame, target_col: str) -> str:
    """Cheap, stable fingerprint of the training data.

    Combines row count, time span, and a hash of the target column's raw
    bytes. Changes whenever the underlying parquet changes, so the cache
    auto-invalidates without comparing whole frames.
    """
    h = hashlib.sha256()
    h.update(str(len(df)).encode())
    h.update(str(df.index.min()).encode())
    h.update(str(df.index.max()).encode())
    h.update(df[target_col].to_numpy().tobytes())
    return h.hexdigest()[:16]


def config_fingerprint(payload: dict[str, Any], data_fp: str) -> str:
    """SHA-256 over canonical JSON of the config payload + the data fingerprint."""
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.sha256()
    h.update(blob.encode("utf-8"))
    h.update(b"|")
    h.update(data_fp.encode("utf-8"))
    return h.hexdigest()[:16]


def load_json_cache(path) -> dict | None:
    """Return the parsed JSON dict at ``path``, or ``None`` if missing/corrupt."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_json_cache(path, obj: dict) -> None:
    """Atomically write ``obj`` as JSON to ``path`` (creating parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(p)


__all__ = [
    "data_fingerprint",
    "config_fingerprint",
    "load_json_cache",
    "save_json_cache",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_optuna_cache.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/optuna_cache.py tests/test_optuna_cache.py
git commit -m "feat(notebooks): fingerprint + JSON cache helpers for Optuna caching"
```

---

## Task 2: `optuna_cache.py` — study cache (open / resume / reset)

**Files:**
- Modify: `src/era5_etl/notebooks/optuna_cache.py`
- Test: `tests/test_optuna_cache.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `completed_trials(study) -> int`
  - `remaining_trials(study, budget: int) -> int`
  - `open_cached_study(*, method: str, fingerprint: str, db_path, sampler, direction: str = "minimize", reset: bool = False) -> optuna.Study`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_optuna_cache.py`:

```python
import optuna


def _sampler():
    return optuna.samplers.TPESampler(seed=0)


def test_remaining_and_completed_trials(tmp_path):
    study = oc.open_cached_study(
        method="expanding", fingerprint="abc",
        db_path=tmp_path / "nb.db", sampler=_sampler(),
    )
    assert oc.completed_trials(study) == 0
    assert oc.remaining_trials(study, 5) == 5
    study.optimize(lambda t: (t.suggest_float("x", 0, 1) - 0.5) ** 2, n_trials=3)
    assert oc.completed_trials(study) == 3
    assert oc.remaining_trials(study, 5) == 2
    assert oc.remaining_trials(study, 2) == 0   # over budget clamps to 0


def test_open_cached_study_resumes_across_opens(tmp_path):
    db = tmp_path / "nb.db"
    s1 = oc.open_cached_study(method="m", fingerprint="fp",
                              db_path=db, sampler=_sampler())
    s1.optimize(lambda t: t.suggest_float("x", 0, 1), n_trials=4)
    s2 = oc.open_cached_study(method="m", fingerprint="fp",
                              db_path=db, sampler=_sampler())
    assert oc.completed_trials(s2) == 4          # second open sees first's trials
    s3 = oc.open_cached_study(method="m", fingerprint="fp", db_path=db,
                              sampler=_sampler(), reset=True)
    assert oc.completed_trials(s3) == 0          # reset discards them


def test_open_cached_study_separates_by_method_and_fingerprint(tmp_path):
    db = tmp_path / "nb.db"
    a = oc.open_cached_study(method="m", fingerprint="fp1", db_path=db, sampler=_sampler())
    a.optimize(lambda t: t.suggest_float("x", 0, 1), n_trials=2)
    b = oc.open_cached_study(method="m", fingerprint="fp2", db_path=db, sampler=_sampler())
    assert oc.completed_trials(b) == 0           # different fingerprint = different study
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_optuna_cache.py -q -k "trials or resumes or separates"`
Expected: FAIL — `AttributeError: module 'era5_etl.notebooks.optuna_cache' has no attribute 'open_cached_study'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/era5_etl/notebooks/optuna_cache.py` (above `__all__`), and import optuna at top of file:

```python
import optuna


def completed_trials(study: "optuna.Study") -> int:
    """Number of COMPLETE trials in the study."""
    return sum(
        1 for t in study.get_trials(deepcopy=False)
        if t.state == optuna.trial.TrialState.COMPLETE
    )


def remaining_trials(study: "optuna.Study", budget: int) -> int:
    """Trials still to run to reach ``budget`` COMPLETE trials (never negative)."""
    return max(0, budget - completed_trials(study))


def _storage_url(db_path) -> str:
    p = Path(db_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p.as_posix()}"


def open_cached_study(
    *,
    method: str,
    fingerprint: str,
    db_path,
    sampler,
    direction: str = "minimize",
    reset: bool = False,
) -> "optuna.Study":
    """Open (or create) a persistent study named ``<method>__<fingerprint>``.

    With ``load_if_exists=True`` an identical re-run resumes the same study.
    ``reset=True`` deletes any existing study with that name first.
    """
    storage = _storage_url(db_path)
    study_name = f"{method}__{fingerprint}"
    if reset:
        try:
            optuna.delete_study(study_name=study_name, storage=storage)
        except KeyError:
            pass
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        sampler=sampler,
        direction=direction,
        load_if_exists=True,
    )
```

Extend `__all__` with `"completed_trials"`, `"remaining_trials"`, `"open_cached_study"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_optuna_cache.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/optuna_cache.py tests/test_optuna_cache.py
git commit -m "feat(notebooks): persistent Optuna study cache with resume/reset"
```

---

## Task 3: `backtest.py` — `SweepConfig` + `build_sweep_grid`

**Files:**
- Modify: `src/era5_etl/notebooks/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces:
  - `SweepConfig` (frozen dataclass: `train_months:int, train_days:int, step_days:int, test_days:int, max_windows:int, label:str`)
  - `build_sweep_grid(*, train_months: list[int], slide_steps_days: list[int], test_days: int, max_windows: int, days_per_month: int = 30) -> list[SweepConfig]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from era5_etl.notebooks.backtest import SweepConfig, build_sweep_grid


def test_build_sweep_grid_enumerates_product():
    grid = build_sweep_grid(
        train_months=[1, 2], slide_steps_days=[7, 30],
        test_days=15, max_windows=6,
    )
    assert len(grid) == 4
    assert all(isinstance(c, SweepConfig) for c in grid)
    # train_days = train_months * days_per_month (default 30)
    by_label = {c.label: c for c in grid}
    assert by_label["slide=7d, train=1m"].train_days == 30
    assert by_label["slide=30d, train=2m"].train_days == 60
    assert by_label["slide=7d, train=1m"].step_days == 7
    assert by_label["slide=30d, train=2m"].test_days == 15
    assert by_label["slide=7d, train=1m"].max_windows == 6


def test_build_sweep_grid_respects_days_per_month():
    grid = build_sweep_grid(
        train_months=[3], slide_steps_days=[1],
        test_days=10, max_windows=3, days_per_month=28,
    )
    assert grid[0].train_days == 84
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k sweep_grid`
Expected: FAIL — `ImportError: cannot import name 'SweepConfig'`

- [ ] **Step 3: Write minimal implementation**

In `src/era5_etl/notebooks/backtest.py`, add after the `BacktestWindow` dataclass:

```python
@dataclass(frozen=True)
class SweepConfig:
    """One sliding-window configuration evaluated in the learning-curve sweep."""

    train_months: int
    train_days: int
    step_days: int
    test_days: int
    max_windows: int
    label: str


def build_sweep_grid(
    *,
    train_months: list[int],
    slide_steps_days: list[int],
    test_days: int,
    max_windows: int,
    days_per_month: int = 30,
) -> list[SweepConfig]:
    """Cartesian product of (train size x slide step) sliding configs.

    Pure enumeration — does not touch any data. ``train_days`` is
    ``train_months * days_per_month``. The label is stable and used as the
    panel/run identifier downstream.
    """
    grid: list[SweepConfig] = []
    for step in slide_steps_days:
        for months in train_months:
            grid.append(
                SweepConfig(
                    train_months=months,
                    train_days=months * days_per_month,
                    step_days=step,
                    test_days=test_days,
                    max_windows=max_windows,
                    label=f"slide={step}d, train={months}m",
                )
            )
    return grid
```

Add `"SweepConfig"` and `"build_sweep_grid"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k sweep_grid`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/backtest.py tests/test_backtest.py
git commit -m "feat(notebooks): build_sweep_grid + SweepConfig for window sweep"
```

---

## Task 4: `backtest.py` — `summarize_sweep`

**Files:**
- Modify: `src/era5_etl/notebooks/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: per-window records `{slide_step_days:int, train_months:int, rmse:float, mae:float, r2:float}`.
- Produces: `summarize_sweep(records: list[dict]) -> pandas.DataFrame` with columns `slide_step_days, train_months, n_windows, rmse_mean, rmse_std, mae_mean, r2_mean`, one row per `(slide_step_days, train_months)`, sorted by those two columns.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
from era5_etl.notebooks.backtest import summarize_sweep


def test_summarize_sweep_aggregates_per_config():
    records = [
        {"slide_step_days": 7, "train_months": 1, "rmse": 2.0, "mae": 1.0, "r2": 0.5},
        {"slide_step_days": 7, "train_months": 1, "rmse": 4.0, "mae": 3.0, "r2": 0.7},
        {"slide_step_days": 7, "train_months": 2, "rmse": 1.0, "mae": 0.5, "r2": 0.9},
    ]
    df = summarize_sweep(records)
    assert list(df.columns) == [
        "slide_step_days", "train_months", "n_windows",
        "rmse_mean", "rmse_std", "mae_mean", "r2_mean",
    ]
    row = df[(df.slide_step_days == 7) & (df.train_months == 1)].iloc[0]
    assert row.n_windows == 2
    assert row.rmse_mean == 3.0
    assert abs(row.rmse_std - 1.0) < 1e-9        # population std (ddof=0)
    assert df[(df.train_months == 2)].iloc[0].n_windows == 1


def test_summarize_sweep_empty_returns_typed_columns():
    df = summarize_sweep([])
    assert list(df.columns) == [
        "slide_step_days", "train_months", "n_windows",
        "rmse_mean", "rmse_std", "mae_mean", "r2_mean",
    ]
    assert len(df) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k summarize_sweep`
Expected: FAIL — `ImportError: cannot import name 'summarize_sweep'`

- [ ] **Step 3: Write minimal implementation**

In `src/era5_etl/notebooks/backtest.py`, add:

```python
_SWEEP_COLUMNS = [
    "slide_step_days", "train_months", "n_windows",
    "rmse_mean", "rmse_std", "mae_mean", "r2_mean",
]


def summarize_sweep(records: list[dict]) -> pd.DataFrame:
    """Aggregate per-window sweep records into one row per config.

    ``rmse_std`` is the population std (ddof=0) across the config's windows.
    Returns an empty frame with the canonical columns when ``records`` is empty.
    """
    if not records:
        return pd.DataFrame(columns=_SWEEP_COLUMNS)
    df = pd.DataFrame.from_records(records)
    grouped = (
        df.groupby(["slide_step_days", "train_months"], as_index=False)
        .agg(
            n_windows=("rmse", "size"),
            rmse_mean=("rmse", "mean"),
            rmse_std=("rmse", lambda s: float(s.std(ddof=0))),
            mae_mean=("mae", "mean"),
            r2_mean=("r2", "mean"),
        )
        .sort_values(["slide_step_days", "train_months"])
        .reset_index(drop=True)
    )
    return grouped[_SWEEP_COLUMNS]
```

Add `"summarize_sweep"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k summarize_sweep`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/notebooks/backtest.py tests/test_backtest.py
git commit -m "feat(notebooks): summarize_sweep tidy aggregation for sweep results"
```

---

## Task 5: `helpers_module.py` — `plot_learning_curves`

**Files:**
- Modify: `src/era5_etl/notebooks/helpers_module.py`
- Test: `tests/test_backtest.py` (structural figure check; no new test file needed)

**Interfaces:**
- Consumes: `sweep_df` (output of `summarize_sweep`), `expanding_rows` (list of dicts with `n_train` hours + `rmse`).
- Produces: `plot_learning_curves(sweep_df, expanding_rows, *, metric: str = "rmse", hours_per_month: int = 720) -> plotly.graph_objects.Figure`. One subplot per unique `slide_step_days` + one `"expanding (treino cresce)"` subplot. Also exposed in the kernel namespace as `plot_learning_curves`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
def test_plot_learning_curves_panels(monkeypatch):
    pd_mod = pytest.importorskip("pandas")
    pytest.importorskip("plotly")
    # build the helper namespace the kernel would build
    from era5_etl.notebooks import helpers_module
    ns: dict = {}
    helpers_module.install(ns)            # see Step 3 for `install`
    plot = ns["plot_learning_curves"]

    sweep_df = pd_mod.DataFrame({
        "slide_step_days": [7, 7, 30, 30],
        "train_months": [1, 2, 1, 2],
        "n_windows": [3, 3, 2, 2],
        "rmse_mean": [2.0, 1.8, 2.5, 2.1],
        "rmse_std": [0.2, 0.1, 0.3, 0.2],
        "mae_mean": [1.0, 0.9, 1.3, 1.1],
        "r2_mean": [0.8, 0.85, 0.7, 0.75],
    })
    expanding_rows = [
        {"n_train": 720, "rmse": 2.4}, {"n_train": 1440, "rmse": 2.0},
    ]
    fig = plot(sweep_df, expanding_rows)
    # 2 slide steps (7, 30) + 1 expanding panel = 3 subplot titles
    assert len(fig.layout.annotations) == 3
    assert any("expanding" in a.text.lower() for a in fig.layout.annotations)
    assert len(fig.data) >= 3             # at least one trace per panel
```

> Note: `tests/test_notebook_mlflow_runs.py` already imports `helpers_module`; if it relies on a different install entry point, keep that working — only **add** `install`/`plot_learning_curves`, do not rename existing helpers.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k learning_curves`
Expected: FAIL — `AttributeError`/`KeyError: 'plot_learning_curves'`

- [ ] **Step 3: Inspect the existing helper wiring, then implement**

First read how helpers are currently exposed:

Run: `py -3.12 -c "import era5_etl.notebooks.helpers_module as h; print([n for n in dir(h) if not n.startswith('__')])"`

The module builds `ns["plot_predictions"]`, `ns["log_model_run"]`, `ns["inmet_with_era5_land"]` inside a builder function and assigns them near the bottom (the `ns[...] = ...` block). Identify that builder (the function that receives the namespace dict — referred to here as `install(ns)`; use the real name found in the file). Add `plot_learning_curves` **inside** it next to `plot_predictions`, and register `ns["plot_learning_curves"] = plot_learning_curves`.

Implementation to add (inside the builder, mirroring `plot_predictions`'s `_require` pattern):

```python
    def plot_learning_curves(sweep_df, expanding_rows, *, metric="rmse",
                             hours_per_month=720):
        """Faceted learning curves: one panel per slide step (X = months of
        training, Y = mean test RMSE +/- std) plus an 'expanding' panel built
        from the expanding backtest windows (train grows)."""
        _require("pandas")
        go = _require("plotly").graph_objects  # type: ignore
        from plotly.subplots import make_subplots

        steps = sorted(sweep_df["slide_step_days"].unique().tolist()) \
            if len(sweep_df) else []
        titles = [f"sliding: slide={s}d" for s in steps] + ["expanding (treino cresce)"]
        n = len(titles)
        fig = make_subplots(rows=1, cols=n, subplot_titles=titles,
                            shared_yaxes=True)
        mean_col = f"{metric}_mean"
        std_col = f"{metric}_std"
        for col, step in enumerate(steps, start=1):
            sub = sweep_df[sweep_df["slide_step_days"] == step] \
                .sort_values("train_months")
            fig.add_trace(
                go.Scatter(
                    x=sub["train_months"], y=sub[mean_col],
                    error_y=dict(type="data", array=sub[std_col]),
                    mode="lines+markers", name=f"slide={step}d",
                    showlegend=False,
                ),
                row=1, col=col,
            )
        # expanding panel: X = months of training (n_train hours -> months)
        exp = sorted(expanding_rows, key=lambda r: r["n_train"])
        fig.add_trace(
            go.Scatter(
                x=[r["n_train"] / hours_per_month for r in exp],
                y=[r[metric] for r in exp],
                mode="lines+markers", name="expanding", showlegend=False,
                line=dict(color="#16a34a"),
            ),
            row=1, col=n,
        )
        fig.update_xaxes(title_text="meses de treino")
        fig.update_yaxes(title_text=metric.upper(), row=1, col=1)
        fig.update_layout(
            template="plotly_white", height=380,
            title=f"Curvas de aprendizado: {metric.upper()} x meses de treino",
            margin=dict(t=90, b=40),
        )
        return fig
```

And in the `ns[...]` registration block add:

```python
    ns["plot_learning_curves"] = plot_learning_curves
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_backtest.py -q -k learning_curves`
Expected: PASS

- [ ] **Step 5: Run the existing notebook helper tests (no regression)**

Run: `py -3.12 -m pytest tests/test_notebook_mlflow_runs.py tests/test_notebook_templates.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/notebooks/helpers_module.py tests/test_backtest.py
git commit -m "feat(notebooks): plot_learning_curves faceted sweep figure helper"
```

---

## Task 6: Config-cell additions (template + notebook) + cell-injection helper

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` (cell idx 2)
- Modify: `<config_dir>/notebooks/6d1169c493984849a5e56e7ec7229128.json` (cell idx 2)
- Modify: `tests/test_notebook_templates.py`

**Interfaces:**
- Produces (runtime globals available to later cells): `USE_OPTUNA_CACHE`, `OPTUNA_CACHE_RESET`, `RUN_WINDOW_SWEEP`, `SWEEP_TRAIN_MONTHS`, `SWEEP_SLIDE_STEPS_DAYS`, `SWEEP_TEST_DAYS`, `SWEEP_MAX_WINDOWS`.

This task introduces the **reusable injection helper** used by Tasks 6–9. Save it once as a scratch script and reuse it (only the per-call arguments change).

- [ ] **Step 1: Write the injection helper script**

Create `scripts/_inject_cell.py` (temporary tooling; deleted in Task 10):

```python
"""Apply an exact-substring replacement (or full-cell replace) to BOTH the
template JSON and the runtime notebook JSON, preserving each file's format.

Usage is via import from the task steps, e.g.:
    from scripts._inject_cell import patch_cell
    patch_cell(cell_idx=2, anchor=OLD, replacement=NEW)         # substring edit
    patch_cell(cell_idx=2, full_source=NEW_SOURCE)              # whole-cell replace
"""
import json
from pathlib import Path
from era5_etl.web.user_config import _config_dir

TEMPLATE = Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json")
NOTEBOOK = _config_dir() / "notebooks" / "6d1169c493984849a5e56e7ec7229128.json"


def _apply(path: Path, cell_idx, anchor, replacement, full_source, clear_outputs):
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    cell = data["cells"][cell_idx]
    assert cell.get("type") == "code", f"cell {cell_idx} is not code"
    if full_source is not None:
        cell["source"] = full_source
    else:
        assert cell["source"].count(anchor) == 1, (
            f"anchor not unique in {path.name} cell {cell_idx}")
        cell["source"] = cell["source"].replace(anchor, replacement)
    if clear_outputs and "outputs" in cell:
        cell["outputs"] = []
    for i, c in enumerate(data["cells"]):
        if c.get("type") == "code":
            compile(c["source"], f"<cell {i}>", "exec")
    trailing = "\n" if raw.endswith("\n") else ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + trailing,
                    encoding="utf-8")


def patch_cell(*, cell_idx, anchor=None, replacement=None, full_source=None):
    _apply(TEMPLATE, cell_idx, anchor, replacement, full_source, clear_outputs=False)
    _apply(NOTEBOOK, cell_idx, anchor, replacement, full_source, clear_outputs=True)
    print(f"patched cell {cell_idx} in template + notebook")
```

- [ ] **Step 2: Run the injection for the config cell**

Run this one-off (the anchor is the last line of the current config cell, the `SHARE_HYPERPARAMS_ACROSS_METHODS` assignment):

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

anchor = 'SHARE_HYPERPARAMS_ACROSS_METHODS = True'
addition = anchor + '''


# --- Cache do Optuna (Pergunta 01) -----------------------------------
# Grava a busca em SQLite (storage nativo do Optuna) com chave = config +
# fingerprint dos dados. Re-rodar a MESMA config reusa os trials (instantaneo)
# e uma busca longa interrompida retoma de onde parou. Tambem cacheia a
# selecao de features e o resultado do sweep sob a mesma chave.
USE_OPTUNA_CACHE   = True
OPTUNA_CACHE_RESET = False   # True = ignora/apaga o cache e roda do zero

# --- Sweep de janelas: curvas RMSE x meses de treino (Perguntas 02/03) ---
# A busca pesada roda 1x; o sweep apenas REAVALIA os hiperparametros
# vencedores numa grade (tamanho de treino x passo de slide). Custo =
# n_configs x janelas (sem nova busca). Cada passo de slide vira um painel;
# eixo X = meses de treino, eixo Y = RMSE medio +/- desvio entre janelas.
RUN_WINDOW_SWEEP       = True
SWEEP_TRAIN_MONTHS     = [1, 2, 3, 4, 5, 6]   # eixo X (meses inteiros, x30 dias)
SWEEP_SLIDE_STEPS_DAYS = [1, 7, 30]           # 1 painel por passo
SWEEP_TEST_DAYS        = SLIDING_TEST_DAYS     # mesmo bloco de teste do sliding
SWEEP_MAX_WINDOWS      = MAX_WINDOWS           # teto de janelas por config'''

patch_cell(cell_idx=2, anchor=anchor, replacement=addition)
PY
```

Expected output: `patched cell 2 in template + notebook`

- [ ] **Step 3: Add a template assertion test**

In `tests/test_notebook_templates.py`, add (adapt to the file's existing helper that loads a template by name):

```python
def test_windows_template_has_cache_and_sweep_config():
    import json, pathlib
    p = pathlib.Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json")
    src = "\n".join(c["source"] for c in json.loads(p.read_text(encoding="utf-8"))["cells"]
                    if c["type"] == "code")
    for token in ("USE_OPTUNA_CACHE", "OPTUNA_CACHE_RESET", "RUN_WINDOW_SWEEP",
                  "SWEEP_TRAIN_MONTHS", "SWEEP_SLIDE_STEPS_DAYS"):
        assert token in src, token
```

- [ ] **Step 4: Run the template tests**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json tests/test_notebook_templates.py scripts/_inject_cell.py
git commit -m "feat(notebooks): config flags for Optuna cache + window sweep"
```

---

## Task 7: Cached search + feature-selection cache (template + notebook)

**Files:**
- Modify: `xgboost_optuna_windows.json` (cell idx 13) + the runtime notebook (cell idx 13)

**Interfaces:**
- Consumes: `optuna_cache` (Task 1–2), `trainval`, `TARGET_VAR`, all config from Task 6, and the existing `_select_features`, `_run_search`, `_make_objective`, `_budget_trials`.
- Produces: globals `_FINGERPRINT`, `_OPTUNA_DB` used by Tasks 8–9; unchanged `BACKTEST`, `SELECTED_FEATS`.

- [ ] **Step 1: Add imports + fingerprint + cache paths**

Anchor (existing line in cell 13): `optuna.logging.set_verbosity(optuna.logging.WARNING)`

Run:

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

anchor = 'optuna.logging.set_verbosity(optuna.logging.WARNING)'
replacement = anchor + '''

from pathlib import Path as _Path
from era5_etl.notebooks import optuna_cache as _oc

# Diretorio do cache (mesmo config_dir do servidor; fallback p/ .ipynb solto).
try:
    from era5_etl.web.user_config import _config_dir as _cfgdir
    _OPTUNA_DIR = _cfgdir() / "optuna"
except Exception:
    _OPTUNA_DIR = _Path("./optuna")
_NB_ID = os.environ.get("ERA5_NB_ID", "standalone")
_OPTUNA_DB = _OPTUNA_DIR / f"nb_{_NB_ID}.db"

# Fingerprint = config (deterministica) + fingerprint barato dos dados. Usa a
# CONFIG de selecao de features (nao as features resolvidas, que oscilam em GPU).
_DATA_FP = _oc.data_fingerprint(trainval, TARGET_VAR)
_FP_PAYLOAD = {
    "station": STATION_ID, "date_start": DATE_START, "date_end": DATE_END,
    "target": TARGET_VAR, "test_fraction": TEST_FRACTION,
    "cutoff": ERA5_LAND_CUTOFF_HOURS, "lag_hours": LAG_HOURS,
    "feature_selection": FEATURE_SELECTION, "fs_top_k": FS_TOP_K,
    "fs_perm_n_repeats": FS_PERM_N_REPEATS, "fs_perm_min_sigma": FS_PERM_MIN_SIGMA,
    "fs_perm_seed": FS_PERM_SEED, "fixed_lags": FIXED_LAGS, "active_vars": ACTIVE_VARS,
    "expanding": [EXPANDING_INITIAL_TRAIN_DAYS, EXPANDING_TEST_DAYS, EXPANDING_STEP_DAYS],
    "sliding": [SLIDING_TRAIN_DAYS, SLIDING_TEST_DAYS, SLIDING_STEP_DAYS],
    "max_windows": MAX_WINDOWS, "optuna_seed": OPTUNA_SEED,
    "target_metric": TARGET_METRIC, "n_seeds": N_SEEDS_PER_WINDOW,
    "seeds": BASE_SEEDS[:max(1, N_SEEDS_PER_WINDOW)],
    "early_stopping": [USE_EARLY_STOPPING, N_ESTIMATORS_CAP, EARLY_STOPPING_ROUNDS, ES_VAL_FRACTION],
    "share_hyper": SHARE_HYPERPARAMS_ACROSS_METHODS,
    "stop_mode": STOP_MODE, "budget": (N_TRIALS if STOP_MODE == "trials" else N_TRIALS_CAP),
    "search_space_version": "v1",   # bump if _suggest_hyper changes
}
_FINGERPRINT = _oc.config_fingerprint(_FP_PAYLOAD, _DATA_FP)
print(f"[cache] fingerprint={_FINGERPRINT} | db={_OPTUNA_DB} | "
      f"on={USE_OPTUNA_CACHE} reset={OPTUNA_CACHE_RESET}")'''

patch_cell(cell_idx=13, anchor=anchor, replacement=replacement)
PY
```

- [ ] **Step 2: Cache the feature-selection result**

Anchor (existing line in cell 13): `SELECTED_FEATS, FS_RANKING_DF = _select_features()`

Run:

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

anchor = 'SELECTED_FEATS, FS_RANKING_DF = _select_features()'
replacement = '''_FEATS_CACHE = _OPTUNA_DIR / f"features_nb_{_NB_ID}_{_FINGERPRINT}.json"
_cached_feats = None if OPTUNA_CACHE_RESET else (
    _oc.load_json_cache(_FEATS_CACHE) if USE_OPTUNA_CACHE else None)
if _cached_feats is not None:
    SELECTED_FEATS = _cached_feats["selected_feats"]
    FS_RANKING_DF = (pd.read_json(_cached_feats["ranking_json"])
                     if _cached_feats.get("ranking_json") else None)
    print(f"[cache] selecao de features reaproveitada ({len(SELECTED_FEATS)} feats).")
else:
    SELECTED_FEATS, FS_RANKING_DF = _select_features()
    if USE_OPTUNA_CACHE:
        _oc.save_json_cache(_FEATS_CACHE, {
            "selected_feats": SELECTED_FEATS,
            "ranking_json": (FS_RANKING_DF.to_json() if FS_RANKING_DF is not None else None),
        })'''

patch_cell(cell_idx=13, anchor=anchor, replacement=replacement)
PY
```

- [ ] **Step 3: Make `_run_search` use the cached study**

Anchor (the body of `_run_search` — the `study = optuna.create_study(...)` call through `study.optimize(...)`). Replace the in-memory study + full optimize with cache-aware logic:

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

anchor = '''    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(
            seed=OPTUNA_SEED, multivariate=True, group=True,
            n_startup_trials=max(5, _budget_trials // 4),
        ),
    )
    study.optimize(_make_objective(method), n_trials=_budget_trials,
                   callbacks=[_make_progress_callback(method, t0)],
                   show_progress_bar=False)'''

replacement = '''    _sampler = optuna.samplers.TPESampler(
        seed=OPTUNA_SEED, multivariate=True, group=True,
        n_startup_trials=max(5, _budget_trials // 4),
    )
    if USE_OPTUNA_CACHE:
        study = _oc.open_cached_study(
            method=method, fingerprint=_FINGERPRINT, db_path=_OPTUNA_DB,
            sampler=_sampler, direction="minimize", reset=OPTUNA_CACHE_RESET,
        )
        _todo = _oc.remaining_trials(study, _budget_trials)
        _have = _oc.completed_trials(study)
        if _todo == 0:
            print(f"[{method}] cache: {_have} trials ja prontos -> busca pulada.",
                  flush=True)
        else:
            print(f"[{method}] cache: {_have} prontos, rodando +{_todo} trials...",
                  flush=True)
            study.optimize(_make_objective(method), n_trials=_todo,
                           callbacks=[_make_progress_callback(method, t0)],
                           show_progress_bar=False)
    else:
        study = optuna.create_study(direction="minimize", sampler=_sampler)
        study.optimize(_make_objective(method), n_trials=_budget_trials,
                       callbacks=[_make_progress_callback(method, t0)],
                       show_progress_bar=False)'''

patch_cell(cell_idx=13, anchor=anchor, replacement=replacement)
PY
```

- [ ] **Step 4: Verify cells still compile + template tests pass**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -q`
Expected: PASS (the injection helper already compiled every code cell; this confirms the suite)

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json
git commit -m "feat(notebooks): cache Optuna search + feature selection by fingerprint"
```

---

## Task 8: Sweep compute + plot cells (template + notebook)

**Files:**
- Modify: `xgboost_optuna_windows.json` + runtime notebook — **insert two new code cells** after the final-refit cell (current idx 15).

**Interfaces:**
- Consumes: `winner`, `BACKTEST`, `_eval_windows`, `WINDOWS`-style window builders, `SELECTED_FEATS`, `_FINGERPRINT`, `_OPTUNA_DIR`, `_NB_ID`, the sweep config (Task 6), and `summarize_sweep`/`build_sweep_grid` (Tasks 3–4), `plot_learning_curves` (Task 5), `sliding_windows`.
- Produces: globals `sweep_df` (tidy DataFrame) and `fig_learning` (Plotly figure) for Task 9.

Because the injection helper only does same-index edits, inserting **new** cells uses a dedicated one-off below.

- [ ] **Step 0: Refactor `_eval_windows` to take a windows list (reuse, no duplication)**

The sweep must evaluate *arbitrary* sliding windows, but the existing
`_eval_windows(method, hyper)` is hardcoded to `WINDOWS[method]`. Refactor it
to accept an explicit windows list so the sweep reuses it instead of
re-implementing the per-window slice/guard/fit loop. Edit cell idx 13 via
`patch_cell`:

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

# 1) change the signature + iteration
patch_cell(cell_idx=13,
    anchor='def _eval_windows(method, hyper):',
    replacement='def _eval_windows(windows, hyper):')
patch_cell(cell_idx=13,
    anchor='    for w in WINDOWS[method]:',
    replacement='    for w in windows:')

# 2) update the three call sites to pass WINDOWS[...]
patch_cell(cell_idx=13,
    anchor='        rows = _eval_windows(method, hyper)',
    replacement='        rows = _eval_windows(WINDOWS[method], hyper)')
PY
```

The two remaining call sites in the main loop both read
`_rows = _eval_windows(_method, _best_hyper)` (identical text appears twice, so
`patch_cell`'s uniqueness assert will fail on a plain replace). Replace them
with a small inline script that asserts a count of 2 and replaces all:

```bash
py -3.12 - <<'PY'
import json
from pathlib import Path
from era5_etl.web.user_config import _config_dir

old = '        _rows = _eval_windows(_method, _best_hyper)'
new = '        _rows = _eval_windows(WINDOWS[_method], _best_hyper)'
for path, trailing_ok in (
    (Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json"), True),
    (_config_dir() / "notebooks" / "6d1169c493984849a5e56e7ec7229128.json", False),
):
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    src = data["cells"][13]["source"]
    assert src.count(old) == 2, f"{path.name}: expected 2, got {src.count(old)}"
    data["cells"][13]["source"] = src.replace(old, new)
    for i, c in enumerate(data["cells"]):
        if c.get("type") == "code":
            compile(c["source"], f"<cell {i}>", "exec")
    trailing = "\n" if raw.endswith("\n") else ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + trailing, encoding="utf-8")
print("refactored _eval_windows call sites in both files")
PY
```

- [ ] **Step 1: Insert the two new cells after idx 15**

```bash
py -3.12 - <<'PY'
import json
from pathlib import Path
from era5_etl.web.user_config import _config_dir

compute_src = r'''# --- Sweep de janelas: RMSE x meses de treino (Perguntas 02/03) -------
# Reavalia os HIPERPARAMETROS VENCEDORES numa grade (tamanho de treino x passo
# de slide), reaproveitando _eval_windows. Custo = n_configs x janelas (sem
# nova busca). Resultado cacheado sob a mesma fingerprint (+ hash da grade).
from era5_etl.notebooks.backtest import build_sweep_grid, summarize_sweep
import hashlib as _hashlib

sweep_df = summarize_sweep([])   # vazio por default
if RUN_WINDOW_SWEEP:
    _winner_hyper = {k: v for k, v in BACKTEST[winner]["best_params"].items()
                     if not k.startswith("_")}
    _grid = build_sweep_grid(
        train_months=SWEEP_TRAIN_MONTHS, slide_steps_days=SWEEP_SLIDE_STEPS_DAYS,
        test_days=SWEEP_TEST_DAYS, max_windows=SWEEP_MAX_WINDOWS,
    )
    _grid_hash = _hashlib.sha256(
        repr((SWEEP_TRAIN_MONTHS, SWEEP_SLIDE_STEPS_DAYS, SWEEP_TEST_DAYS,
              SWEEP_MAX_WINDOWS, sorted(_winner_hyper.items()))).encode()
    ).hexdigest()[:12]
    _sweep_csv = _OPTUNA_DIR / f"sweep_nb_{_NB_ID}_{_FINGERPRINT}_{_grid_hash}.csv"

    _cached = (_sweep_csv.exists() and USE_OPTUNA_CACHE and not OPTUNA_CACHE_RESET)
    if _cached:
        sweep_df = pd.read_csv(_sweep_csv)
        print(f"[cache] sweep reaproveitado ({len(sweep_df)} configs).")
    else:
        from era5_etl.notebooks.backtest import sliding_windows
        _records = []
        for _cfg in _grid:
            try:
                _wins = sliding_windows(
                    trainval.index, train_days=_cfg.train_days,
                    test_days=_cfg.test_days, step_days=_cfg.step_days,
                    max_windows=_cfg.max_windows,
                )
            except ValueError as _exc:
                print(f"[sweep] pulando {_cfg.label}: {_exc}")
                continue
            # reusa _eval_windows (mesmos SELECTED_FEATS, early stopping, seeds);
            # cada row ja traz rmse/mae/r2 como media entre seeds.
            _cfg_rows = _eval_windows(_wins, _winner_hyper)
            for _r in _cfg_rows:
                _records.append({
                    "slide_step_days": _cfg.step_days,
                    "train_months": _cfg.train_months,
                    "rmse": _r["rmse"], "mae": _r["mae"], "r2": _r["r2"],
                })
            print(f"[sweep] {_cfg.label}: {len(_cfg_rows)} janelas")
        sweep_df = summarize_sweep(_records)
        if USE_OPTUNA_CACHE and len(sweep_df):
            _sweep_csv.parent.mkdir(parents=True, exist_ok=True)
            sweep_df.to_csv(_sweep_csv, index=False)
    print(sweep_df.to_string(index=False) if len(sweep_df) else "[sweep] nenhum config coube no periodo.")
else:
    print("RUN_WINDOW_SWEEP=False -> sweep pulado.")
'''

plot_src = r'''# --- Sweep: curvas de aprendizado (1 painel por passo + expanding) -----
fig_learning = None
if RUN_WINDOW_SWEEP and len(sweep_df):
    fig_learning = plot_learning_curves(
        sweep_df, BACKTEST["expanding"]["rows"], metric="rmse",
    )
fig_learning if fig_learning is not None else "Sweep vazio (nada a plotar)."
'''

def _insert(path: Path, clear_outputs: bool, with_ids: bool):
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    def _mk(src):
        cell = {"type": "code", "source": src}
        if with_ids:
            import uuid
            cell = {"id": uuid.uuid4().hex, "type": "code", "source": src}
            if clear_outputs:
                cell["outputs"] = []
        return cell
    # insert AFTER current idx 15 (refit) -> positions 16, 17
    data["cells"][16:16] = [_mk(compute_src), _mk(plot_src)]
    for i, c in enumerate(data["cells"]):
        if c.get("type") == "code":
            compile(c["source"], f"<cell {i}>", "exec")
    trailing = "\n" if raw.endswith("\n") else ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + trailing,
                    encoding="utf-8")

TEMPLATE = Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json")
NOTEBOOK = _config_dir() / "notebooks" / "6d1169c493984849a5e56e7ec7229128.json"
# template cells have only {type, source}; notebook cells have {id, type, source, outputs}
_insert(TEMPLATE, clear_outputs=False, with_ids=False)
_insert(NOTEBOOK, clear_outputs=True, with_ids=True)
print("inserted 2 sweep cells")
PY
```

- [ ] **Step 2: Verify the refit cell is at idx 15 before inserting**

Run:
```bash
py -3.12 -c "import json,pathlib; cs=json.loads(pathlib.Path('src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json').read_text(encoding='utf-8'))['cells']; print(15, cs[15]['source'].splitlines()[0])"
```
Expected: line 15 is the refit cell header (`# --- Refit final: ...`). If not, adjust the insert index in Step 1 accordingly.

- [ ] **Step 3: Run template tests**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json
git commit -m "feat(notebooks): window-sweep compute + learning-curve plot cells"
```

---

## Task 9: MLflow per-config child runs + figure/CSV (template + notebook)

**Files:**
- Modify: `xgboost_optuna_windows.json` (the MLflow logging cell — now shifted to idx 21 after the two inserts) + runtime notebook.

**Interfaces:**
- Consumes: `sweep_df`, `fig_learning`, `RUN_WINDOW_SWEEP`, `mlflow`.
- Produces: nested MLflow runs + parent artifacts.

- [ ] **Step 1: Locate the MLflow cell index**

Run:
```bash
py -3.12 -c "import json,pathlib; cs=json.loads(pathlib.Path('src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json').read_text(encoding='utf-8'))['cells']; print([(i,c['source'].splitlines()[0]) for i,c in enumerate(cs) if 'MLflow: registrar' in c['source']])"
```
Expected: one match, e.g. `[(21, '# --- MLflow: registrar o experimento ...')]`. Use that index below.

- [ ] **Step 2: Inject sweep logging before `parent_run_id = _parent.info.run_id`**

Anchor (unique line near the end of the MLflow parent `with` block): `    parent_run_id = _parent.info.run_id`

Run (replace `<MLFLOW_IDX>` with the index from Step 1):

```bash
py -3.12 - <<'PY'
from scripts._inject_cell import patch_cell

MLFLOW_IDX = 21  # <-- set from Step 1

anchor = '    parent_run_id = _parent.info.run_id'
replacement = '''    # -------- Sweep de janelas (Perguntas 02/03) --------
    if RUN_WINDOW_SWEEP and len(sweep_df):
        if fig_learning is not None:
            mlflow.log_figure(fig_learning, "plots/learning_curves.html")
        mlflow.log_text(sweep_df.to_csv(index=False), "sweep_results.csv")
        for _, _srow in sweep_df.iterrows():
            with mlflow.start_run(
                run_name=f"sweep slide={int(_srow['slide_step_days'])}d "
                         f"train={int(_srow['train_months'])}m", nested=True):
                mlflow.set_tags({"sweep": "true", "method": "sliding"})
                mlflow.log_params({
                    "slide_step_days": int(_srow["slide_step_days"]),
                    "train_months": int(_srow["train_months"]),
                    "n_windows": int(_srow["n_windows"]),
                })
                mlflow.log_metrics({
                    "test_rmse_mean": float(_srow["rmse_mean"]),
                    "test_rmse_std": float(_srow["rmse_std"]),
                    "test_mae_mean": float(_srow["mae_mean"]),
                    "test_r2_mean": float(_srow["r2_mean"]),
                })

''' + anchor

patch_cell(cell_idx=MLFLOW_IDX, anchor=anchor, replacement=replacement)
PY
```

- [ ] **Step 3: Run template + MLflow tests**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py tests/test_notebook_mlflow_runs.py tests/test_notebook_mlflow_ui.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json
git commit -m "feat(notebooks): log sweep configs as MLflow child runs + figure/CSV"
```

---

## Task 10: Full-suite verification + cleanup

**Files:**
- Delete: `scripts/_inject_cell.py`

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -m pytest -q`
Expected: PASS (previous count + the new tests; no failures)

- [ ] **Step 2: Smoke-check the template loads end-to-end via the API helpers**

Run:
```bash
py -3.12 -c "import json,pathlib; nb=json.loads(pathlib.Path('src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json').read_text(encoding='utf-8')); [compile(c['source'],'<c>','exec') for c in nb['cells'] if c['type']=='code']; print('cells:',len(nb['cells']),'all compile OK')"
```
Expected: `cells: 22 all compile OK` (20 original + 2 sweep cells)

- [ ] **Step 3: Remove the temporary injection script**

```bash
git rm scripts/_inject_cell.py
```
(If `scripts/` was created only for this and is now empty, also remove the directory.)

- [ ] **Step 4: Final commit**

```bash
git commit -m "chore(notebooks): remove temporary cell-injection script"
```

- [ ] **Step 5: Manual smoke test (human-in-the-loop, optional but recommended)**

Restart `era5 ui`, reload the notebook `6d1169c…`, Run All. Verify:
1. First run: `[cache] fingerprint=… db=…` prints; search runs.
2. Second run (no config change): `[<method>] cache: N trials ja prontos -> busca pulada.`
3. The learning-curve figure renders (panels per slide step + expanding).
4. MLflow UI shows the parent run with `sweep slide=…d train=…m` child runs and `plots/learning_curves.html` + `sweep_results.csv` artifacts.

---

## Self-Review

**Spec coverage:**
- Q1 Optuna cache → Tasks 1, 2, 7 (study cache + fingerprint + resume). ✅
- Q1 feature-selection cache + data fingerprint key → Tasks 1, 7. ✅
- Q1 sweep-result cache → Task 8. ✅
- Q2 sweep grid + summary → Tasks 3, 4, 8. ✅
- Q2 faceted learning-curve figure (per slide step + expanding) → Tasks 5, 8. ✅
- Q2 config flags + defaults → Task 6. ✅
- Q3 per-config MLflow child runs + figure/CSV on parent → Task 9. ✅
- Apply to template **and** runtime notebook → injection helper patches both (Tasks 6–9). ✅
- Tests for all module functions → Tasks 1–5; template assertion → Task 6. ✅

**Placeholder scan:** No TBD/TODO/placeholder lines. Task 8's `compute_src` is complete and runnable as written.

**Type consistency:** `data_fingerprint`/`config_fingerprint`/`open_cached_study`/`remaining_trials`/`completed_trials` (Tasks 1–2) are consumed with matching signatures in Task 7. `build_sweep_grid`/`SweepConfig`/`summarize_sweep` (Tasks 3–4) consumed in Task 8 with matching field names (`step_days`, `train_days`, `train_months`, `slide_step_days`). `summarize_sweep` output columns (`rmse_mean`, `rmse_std`, …) match what `plot_learning_curves` (Task 5) and the MLflow logging (Task 9) read. `plot_learning_curves(sweep_df, expanding_rows, ...)` signature matches the Task 8 call. ✅
