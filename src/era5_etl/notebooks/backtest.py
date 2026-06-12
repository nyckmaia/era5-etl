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
