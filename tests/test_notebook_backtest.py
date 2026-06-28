"""Expanding/Sliding window generators for the backtesting template."""

from __future__ import annotations

import pandas as pd
import pytest

from era5_etl.notebooks.backtest import (
    expanding_windows,
    sliding_windows,
    SweepConfig,
    build_sweep_grid,
)


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
