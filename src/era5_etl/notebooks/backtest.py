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
The index is assumed to be an hourly grid (the template feeds
``pd.date_range(..., freq="h")``); the fit check tolerates exactly one
missing trailing hour, so coarser resolutions are not supported.
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


def anchored_end_windows(
    index: pd.DatetimeIndex,
    *,
    train_days_list: list[int],
    test_days: int,
) -> list[BacktestWindow]:
    """Fixed most-recent test block; the train slice grows backwards per size.

    Every window shares the SAME test block — the last ``test_days`` of the
    index (anchored at the most recent data, just before the operational gap).
    For each entry in ``train_days_list`` the train slice is the ``train_days``
    immediately preceding that fixed test block. Sizes whose train slice would
    start before the index are skipped (not enough history). Bounds are
    half-open, like the other generators; windows are returned sorted by
    ascending train size (``index`` = position in that order).

    This answers "which training-interval size gives the best score?" with the
    evaluation point held fixed at the most recent data — unlike the
    walk-forward generators, whose test block moves forward.
    """
    _check_positive(test_days=test_days)
    _check_index(index)
    if not train_days_list:
        raise ValueError("train_days_list is empty")
    start = index.min()
    end = index.max()
    # Half-open test block: +1h so the most recent row is included.
    test_end = end + pd.Timedelta(hours=1)
    test_start = test_end - pd.Timedelta(days=test_days)
    if test_start <= start:
        raise ValueError(
            f"No anchored window fits: the period spans {_span_days(index):.1f} "
            f"days but the fixed test block alone needs test_days={test_days}. "
            f"Reduce STUDY_TEST_DAYS or widen DATE_START..DATE_END."
        )
    out: list[BacktestWindow] = []
    for train_days in sorted(dict.fromkeys(train_days_list)):
        _check_positive(train_days=train_days)
        train_start = test_start - pd.Timedelta(days=train_days)
        if train_start < start:
            continue  # not enough history for this training size
        out.append(
            BacktestWindow(
                index=len(out),
                train_start=train_start,
                train_end=test_start,
                test_start=test_start,
                test_end=test_end,
            )
        )
    if not out:
        raise ValueError(
            f"No anchored window fits: the period spans {_span_days(index):.1f} "
            f"days but even the smallest train size + fixed test block "
            f"({min(train_days_list)} + {test_days} days) does not fit. "
            f"Reduce STUDY_TRAIN_MONTHS / STUDY_TEST_DAYS or widen the period."
        )
    return out


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


__all__ = ["BacktestWindow", "expanding_windows", "sliding_windows", "anchored_end_windows", "SweepConfig", "build_sweep_grid", "summarize_sweep"]
