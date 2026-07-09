"""Device-resident matrices for the notebook training hot loop.

The module must mirror EXACTLY the pandas semantics the templates used before:
boolean-mask window slicing (>= start, < end), the early-stopping tail split
``n_val = max(1, int(n * frac))`` and the skip rule ``len(tr) < 50 or
len(te) == 0``. Tests run on the numpy/CPU path — the cupy/GPU path is the
same code with a different array module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from era5_etl.notebooks.backtest import (
    anchored_end_windows,
    expanding_windows,
    sliding_windows,
)
from era5_etl.notebooks.device_data import (
    DeviceDataset,
    WindowMatrixCache,
    es_split,
    window_bounds,
)


def _gapped_hourly_frame(days: int, n_features: int = 4, gap_every: int = 13):
    """Hourly frame with rows dropped (like post-dropna data): index has gaps."""
    idx = pd.date_range("2025-01-01", periods=days * 24, freq="h")
    keep = np.ones(len(idx), dtype=bool)
    keep[::gap_every] = False  # remove ~7% of the rows
    idx = idx[keep]
    rng = np.random.default_rng(42)
    data = {f"v{i}": rng.random(len(idx)) for i in range(n_features)}
    frame = pd.DataFrame(data, index=idx)
    frame["alvo"] = frame["v0"] * 2.0 + frame["v1"] + 0.1 * rng.standard_normal(len(idx))
    return frame


FEATS = ["v0", "v1", "v2", "v3"]


# ---------------------------------------------------------------- DeviceDataset

def test_from_frame_float32_contiguous_cpu():
    frame = _gapped_hourly_frame(30)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    assert ds.X.dtype == np.float32 and ds.y.dtype == np.float32
    assert ds.X.flags["C_CONTIGUOUS"]
    assert ds.X.shape == (len(frame), len(FEATS))
    assert ds.y.shape == (len(frame),)
    assert ds.xp is np
    assert ds.on_gpu is False
    assert ds.feature_cols == FEATS
    assert ds.index.equals(frame.index)


def test_from_frame_requires_monotonic_index():
    frame = _gapped_hourly_frame(10).sample(frac=1.0, random_state=1)
    with pytest.raises(ValueError, match="monot"):
        DeviceDataset.from_frame(frame, FEATS, "alvo")


def test_from_frame_without_gpu_falls_back_to_numpy():
    frame = _gapped_hourly_frame(10)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo", device="cuda", cupy_ok=False)
    assert ds.on_gpu is False
    assert ds.xp is np


# ------------------------------------------------------------- window_bounds

def test_window_bounds_match_boolean_mask_on_gapped_index():
    frame = _gapped_hourly_frame(120)
    idx = frame.index
    windows = (
        expanding_windows(idx, initial_train_days=60, test_days=15,
                          step_days=15, max_windows=10)
        + sliding_windows(idx, train_days=60, test_days=15,
                          step_days=15, max_windows=10)
        + anchored_end_windows(idx, train_days_list=[30, 60, 90], test_days=15)
    )
    assert windows
    for w in windows:
        lo_tr, hi_tr, lo_te, hi_te = window_bounds(idx, w)
        tr_mask = frame[(idx >= w.train_start) & (idx < w.train_end)]
        te_mask = frame[(idx >= w.test_start) & (idx < w.test_end)]
        assert frame.iloc[lo_tr:hi_tr].index.equals(tr_mask.index)
        assert frame.iloc[lo_te:hi_te].index.equals(te_mask.index)


# ------------------------------------------------------------------ es_split

@pytest.mark.parametrize("n", [2, 50, 51, 100, 4400])
@pytest.mark.parametrize("frac", [0.1, 0.2, 0.5, 0.99])
def test_es_split_mirrors_iloc_math(n, frac):
    n_val = max(1, int(n * frac))
    assert es_split(n, frac) == n - n_val


# --------------------------------------------------------- WindowMatrixCache

def _one_window(idx, train_days=60, test_days=15):
    (w,) = expanding_windows(idx, initial_train_days=train_days,
                             test_days=test_days, step_days=test_days,
                             max_windows=1)
    return w


def test_cache_skips_small_train_and_empty_test():
    frame = _gapped_hourly_frame(90)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    cache = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=True)

    w = _one_window(frame.index)
    tiny_train = type(w)(index=0, train_start=w.train_start,
                         train_end=w.train_start + pd.Timedelta(hours=10),
                         test_start=w.test_start, test_end=w.test_end)
    assert cache.get(tiny_train) is None  # n_train < 50

    empty_test = type(w)(index=1, train_start=w.train_start,
                         train_end=w.train_end,
                         test_start=w.test_end, test_end=w.test_end)
    assert cache.get(empty_test) is None  # n_test == 0


def test_cache_memoizes_by_window_bounds():
    frame = _gapped_hourly_frame(90)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    cache = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=True)
    w = _one_window(frame.index)

    first = cache.get(w)
    again = cache.get(w)
    assert first is again                    # same object, no rebuild
    assert len(cache) == 1

    cache.clear()
    assert len(cache) == 0
    rebuilt = cache.get(w)
    assert rebuilt is not first              # rebuilt after clear


def test_cache_early_stopping_split_sizes():
    frame = _gapped_hourly_frame(90)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    idx = frame.index
    w = _one_window(idx)
    n_train = int(((idx >= w.train_start) & (idx < w.train_end)).sum())
    n_test = int(((idx >= w.test_start) & (idx < w.test_end)).sum())

    with_es = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=True)
    wm = with_es.get(w)
    n_fit = es_split(n_train, 0.2)
    assert wm.n_train == n_train and wm.n_test == n_test
    assert wm.dtrain.num_row() == n_fit
    assert wm.dval is not None and wm.dval.num_row() == n_train - n_fit
    assert wm.X_test.shape == (n_test, len(FEATS))
    assert wm.y_test.shape == (n_test,)
    assert np.shares_memory(ds.X, wm.X_test)  # slice, not a copy

    without_es = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=False)
    wm2 = without_es.get(w)
    assert wm2.dtrain.num_row() == n_train
    assert wm2.dval is None


def test_cache_exactly_min_rows_window_keeps_but_disables_es():
    """len(tr) == 50 hoje NAO e pulada (< 50) mas treina SEM early stopping
    (> 50): a assimetria do template precisa ser preservada."""
    frame = _gapped_hourly_frame(90)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    idx = frame.index
    w = _one_window(idx)
    train_end = idx[idx.searchsorted(w.train_start) + 50]
    exactly_50 = type(w)(index=0, train_start=w.train_start, train_end=train_end,
                         test_start=w.test_start, test_end=w.test_end)
    cache = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=True)
    wm = cache.get(exactly_50)
    assert wm is not None
    assert wm.n_train == 50
    assert wm.dtrain.num_row() == 50
    assert wm.dval is None                   # sem ES para janela de 50 linhas


# ----------------------------------------------------- end-to-end (CPU path)

def test_native_train_path_end_to_end_cpu():
    frame = _gapped_hourly_frame(120)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    cache = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=True)
    wm = cache.get(_one_window(frame.index))

    params = dict(tree_method="hist", device="cpu", n_jobs=2,
                  objective="reg:squarederror", eval_metric="rmse",
                  random_state=42, learning_rate=0.1, max_depth=4)
    booster = xgb.train(params, wm.dtrain, num_boost_round=500,
                        evals=[(wm.dval, "val")], early_stopping_rounds=20,
                        verbose_eval=False)
    assert booster.best_iteration >= 0

    pred = booster.inplace_predict(
        wm.X_test, iteration_range=(0, booster.best_iteration + 1))
    assert isinstance(pred, np.ndarray) and len(pred) == wm.n_test

    # metricas inline (as mesmas formulas que as celulas usam) vs sklearn
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    d = (wm.y_test - pred).astype(np.float64)
    yt = wm.y_test.astype(np.float64)
    rmse = float(np.sqrt((d ** 2).mean()))
    mae = float(np.abs(d).mean())
    ssr = float((d ** 2).sum())
    sst = float(((yt - yt.mean()) ** 2).sum())
    r2 = (1.0 - ssr / sst) if sst > 0 else (1.0 if ssr == 0 else 0.0)
    assert abs(rmse - float(np.sqrt(mean_squared_error(yt, pred)))) < 1e-6
    assert abs(mae - float(mean_absolute_error(yt, pred))) < 1e-6
    assert abs(r2 - float(r2_score(yt, pred))) < 1e-6


def test_native_train_without_es_has_no_best_iteration():
    frame = _gapped_hourly_frame(90)
    ds = DeviceDataset.from_frame(frame, FEATS, "alvo")
    cache = WindowMatrixCache(ds, es_val_fraction=0.2, use_early_stopping=False)
    wm = cache.get(_one_window(frame.index))
    booster = xgb.train(dict(tree_method="hist", device="cpu", n_jobs=2),
                        wm.dtrain, num_boost_round=8)
    assert getattr(booster, "best_iteration", None) is None
    pred = booster.inplace_predict(wm.X_test)
    assert len(pred) == wm.n_test
