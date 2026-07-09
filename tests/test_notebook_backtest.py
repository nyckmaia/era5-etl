"""Expanding/Sliding window generators for the backtesting template."""

from __future__ import annotations

import pandas as pd
import pytest

from era5_etl.notebooks.backtest import (
    expanding_windows,
    sliding_windows,
    anchored_end_windows,
    SweepConfig,
    build_sweep_grid,
    summarize_sweep,
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


def test_anchored_end_windows_fixed_test_grows_backwards():
    idx = _hourly_index(120)
    wins = anchored_end_windows(idx, train_days_list=[90, 30, 60], test_days=15)
    assert len(wins) == 3
    test_end = idx.max() + pd.Timedelta(hours=1)
    for w in wins:
        # every window shares the SAME fixed most-recent test block
        assert w.test_end == test_end
        assert w.test_start == test_end - pd.Timedelta(days=15)
        assert w.train_end == w.test_start          # contiguous, no gap
    # returned sorted ascending by train size, regardless of input order
    assert [(w.train_end - w.train_start).days for w in wins] == [30, 60, 90]
    assert [w.index for w in wins] == [0, 1, 2]


def test_anchored_end_windows_skips_sizes_that_dont_fit():
    idx = _hourly_index(90)
    # test=15 -> test_start at day 75; 30/60 fit, 80 would start before day 0.
    wins = anchored_end_windows(idx, train_days_list=[30, 60, 80], test_days=15)
    assert [(w.train_end - w.train_start).days for w in wins] == [30, 60]


def test_anchored_end_windows_raises_when_test_block_too_big():
    idx = _hourly_index(10)
    with pytest.raises(ValueError, match="No anchored window fits"):
        anchored_end_windows(idx, train_days_list=[5], test_days=15)


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


def test_plot_train_size_study_panels():
    pytest.importorskip("plotly")
    from era5_etl.notebooks import helpers_module

    study_df = pd.DataFrame({
        "train_months": [1, 2, 3],
        "train_days": [30, 60, 90],
        "rmse_mean": [2.5, 1.8, 2.1],
        "rmse_std": [0.3, 0.1, 0.2],
        "mae_mean": [1.3, 0.9, 1.1],
        "r2_mean": [0.7, 0.85, 0.8],
    })
    fig = helpers_module.plot_train_size_study(study_df)
    # 3 panels (RMSE / MAE / R²) -> 3 subplot-title annotations
    assert len(fig.layout.annotations) == 3
    assert any("rmse" in a.text.lower() for a in fig.layout.annotations)
    # RMSE + best-star + MAE + R² traces
    assert len(fig.data) >= 4
    # best size (min RMSE) is the 2-month one -> starred at x=2
    star = next(d for d in fig.data if getattr(d.marker, "symbol", None) == "star")
    assert list(star.x) == [2]


def test_install_helpers_registers_plot_train_size_study(tmp_path):
    from era5_etl.notebooks import helpers_module

    ns: dict = {}
    helpers_module.install_helpers(
        ns,
        data_dir=tmp_path,
        notebook_id="nb",
        runs_url="http://localhost/runs",
        runs_token="t",
    )
    assert ns["plot_train_size_study"] is helpers_module.plot_train_size_study


def test_plot_learning_curves_panels():
    pytest.importorskip("plotly")
    from era5_etl.notebooks import helpers_module

    sweep_df = pd.DataFrame({
        "slide_step_days": [7, 7, 30, 30],
        "train_months": [1, 2, 1, 2],
        "n_windows": [6, 6, 3, 3],
        "rmse_mean": [2.0, 1.6, 2.2, 1.9],
        "rmse_std": [0.2, 0.1, 0.3, 0.2],
        "mae_mean": [1.0, 0.8, 1.1, 0.9],
        "r2_mean": [0.6, 0.75, 0.55, 0.7],
    })
    expanding_rows = [
        {"window": 0, "n_train": 720, "n_test": 360,
         "rmse": 2.1, "mae": 1.0, "r2": 0.6},
        {"window": 1, "n_train": 1440, "n_test": 360,
         "rmse": 1.7, "mae": 0.8, "r2": 0.7},
    ]
    fig = helpers_module.plot_learning_curves(sweep_df, expanding_rows)
    # 1 painel por passo unico (7d, 30d) + 1 painel expanding = 3
    assert len(fig.layout.annotations) == 3
    titles = [a.text.lower() for a in fig.layout.annotations]
    assert any("expanding" in t for t in titles)
    assert any("7" in t for t in titles) and any("30" in t for t in titles)
    assert len(fig.data) >= 3
    # eixo x do painel expanding em meses: n_train / hours_per_month
    exp_trace = fig.data[-1]
    assert list(exp_trace.x) == [1.0, 2.0]


def test_plot_learning_curves_empty_expanding_rows():
    pytest.importorskip("plotly")
    from era5_etl.notebooks import helpers_module

    sweep_df = pd.DataFrame({
        "slide_step_days": [7],
        "train_months": [1],
        "n_windows": [6],
        "rmse_mean": [2.0],
        "rmse_std": [0.2],
        "mae_mean": [1.0],
        "r2_mean": [0.6],
    })
    fig = helpers_module.plot_learning_curves(sweep_df, [])
    assert len(fig.layout.annotations) == 2      # 1 passo + painel expanding


def test_install_helpers_registers_plot_learning_curves(tmp_path):
    from era5_etl.notebooks import helpers_module

    ns: dict = {}
    helpers_module.install_helpers(
        ns,
        data_dir=tmp_path,
        notebook_id="nb",
        runs_url="http://localhost/runs",
        runs_token="t",
    )
    assert ns["plot_learning_curves"] is helpers_module.plot_learning_curves
