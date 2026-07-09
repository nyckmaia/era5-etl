"""Device-resident training matrices for the XGBoost notebook templates.

The templates' hot loop (Optuna trial x backtest window x seed) used to
re-slice a pandas DataFrame and re-upload it host->device on every fit. This
module lets a template upload the feature matrix ONCE (cupy when the GPU +
cupy are functional, numpy otherwise — same code both ways), slice windows by
integer position (zero-copy views) and cache one ``xgboost.QuantileDMatrix``
pair per window, reused across every trial and seed of the search.

The window maths must mirror EXACTLY what the templates did inline:

* window slicing == the boolean mask ``(index >= start) & (index < end)``
  (half-open, valid on the sorted-with-gaps post-dropna index);
* early-stopping tail split ``n_val = max(1, int(n * frac))``;
* skip rule ``len(train) < min_train_rows or len(test) == 0``;
* a window of exactly ``min_train_rows`` rows is kept but trained WITHOUT
  early stopping (the template gates ES on ``len(tr) > 50``, the skip on
  ``< 50`` — the asymmetry is intentional and preserved).

Like ``backtest.py``, the logic lives here (not inline in the template JSON)
so it is unit-tested; the templates only orchestrate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

__all__ = [
    "DeviceDataset",
    "WindowMatrices",
    "WindowMatrixCache",
    "es_split",
    "window_bounds",
]


def window_bounds(index: pd.DatetimeIndex, window) -> tuple[int, int, int, int]:
    """Integer positions ``(train_lo, train_hi, test_lo, test_hi)`` of a window.

    ``searchsorted(..., side="left")`` on a sorted index reproduces the
    half-open boolean mask ``(index >= start) & (index < end)`` even when the
    index has gaps (rows dropped by ``dropna``).
    """
    return (
        int(index.searchsorted(window.train_start, side="left")),
        int(index.searchsorted(window.train_end, side="left")),
        int(index.searchsorted(window.test_start, side="left")),
        int(index.searchsorted(window.test_end, side="left")),
    )


def es_split(n_train: int, val_fraction: float) -> int:
    """Rows in the FIT slice when the tail ``max(1, int(n*frac))`` guides ES."""
    return n_train - max(1, int(n_train * val_fraction))


@dataclass
class DeviceDataset:
    """Feature matrix + target resident on the training device.

    ``X`` is float32 C-contiguous ``(n, len(feature_cols))``; ``y`` float32
    ``(n,)``. Both are cupy arrays when ``on_gpu`` and numpy otherwise; the
    ``xp`` property gives the matching array module so metric formulas can be
    written once.
    """

    X: Any
    y: Any
    index: pd.DatetimeIndex
    feature_cols: list[str]
    target_col: str
    device: str
    on_gpu: bool

    @property
    def xp(self):
        if self.on_gpu:
            import cupy

            return cupy
        return np

    @classmethod
    def from_frame(
        cls,
        frame: pd.DataFrame,
        feature_cols,
        target_col: str,
        *,
        device: str = "cpu",
        cupy_ok: bool = False,
    ) -> "DeviceDataset":
        """One-time host->device upload of ``frame[feature_cols]`` + target.

        The GPU path only engages when ``device == "cuda"`` AND cupy is
        functional (the template's probe); otherwise the arrays stay numpy and
        XGBoost copies host->device internally exactly as before.
        """
        if not frame.index.is_monotonic_increasing:
            raise ValueError(
                "frame.index must be monotonic increasing (sorted) — "
                "window_bounds relies on searchsorted"
            )
        feature_cols = list(feature_cols)
        X = np.ascontiguousarray(frame[feature_cols].to_numpy(dtype=np.float32))
        y = np.ascontiguousarray(frame[target_col].to_numpy(dtype=np.float32))
        on_gpu = device == "cuda" and bool(cupy_ok)
        if on_gpu:
            import cupy

            X = cupy.asarray(X)
            y = cupy.asarray(y)
        return cls(
            X=X,
            y=y,
            index=frame.index,
            feature_cols=feature_cols,
            target_col=target_col,
            device=device,
            on_gpu=on_gpu,
        )


@dataclass
class WindowMatrices:
    """Per-window training inputs, built once and reused across trials/seeds.

    ``dval is None`` means "train this window WITHOUT early stopping" (either
    ES is globally off or the window has exactly ``min_train_rows`` rows).
    ``X_test``/``y_test`` are zero-copy row slices of the dataset arrays.
    ``n_train`` is the FULL train-window row count (before the ES tail split),
    matching the ``n_train`` the templates always reported.
    """

    dtrain: Any
    dval: Any | None
    X_test: Any
    y_test: Any
    n_train: int
    n_test: int


class WindowMatrixCache:
    """Memoized ``window -> WindowMatrices`` (keyed by the window bounds).

    Quantization (``max_bin``) is not a searched hyperparameter in the
    templates, so one QuantileDMatrix pair per window is valid for the whole
    study. Skipped windows memoize ``None``. Call :meth:`clear` after a phase
    with many distinct windows (config sweep, train-size study) to release
    device memory.
    """

    def __init__(
        self,
        dataset: DeviceDataset,
        *,
        es_val_fraction: float,
        use_early_stopping: bool,
        max_bin: int = 256,
        min_train_rows: int = 50,
    ):
        self.dataset = dataset
        self.es_val_fraction = float(es_val_fraction)
        self.use_early_stopping = bool(use_early_stopping)
        self.max_bin = int(max_bin)
        self.min_train_rows = int(min_train_rows)
        self._entries: dict[tuple[int, int, int, int], WindowMatrices | None] = {}

    @staticmethod
    def _key(window) -> tuple[int, int, int, int]:
        return (
            pd.Timestamp(window.train_start).value,
            pd.Timestamp(window.train_end).value,
            pd.Timestamp(window.test_start).value,
            pd.Timestamp(window.test_end).value,
        )

    def get(self, window) -> WindowMatrices | None:
        key = self._key(window)
        if key in self._entries:
            return self._entries[key]

        lo_tr, hi_tr, lo_te, hi_te = window_bounds(self.dataset.index, window)
        n_train = hi_tr - lo_tr
        n_test = hi_te - lo_te
        if n_train < self.min_train_rows or n_test == 0:
            self._entries[key] = None
            return None

        X, y = self.dataset.X, self.dataset.y
        if self.use_early_stopping and n_train > self.min_train_rows:
            n_fit = es_split(n_train, self.es_val_fraction)
            mid = lo_tr + n_fit
            dtrain = xgb.QuantileDMatrix(
                X[lo_tr:mid], label=y[lo_tr:mid], max_bin=self.max_bin
            )
            dval = xgb.QuantileDMatrix(X[mid:hi_tr], label=y[mid:hi_tr], ref=dtrain)
        else:
            dtrain = xgb.QuantileDMatrix(
                X[lo_tr:hi_tr], label=y[lo_tr:hi_tr], max_bin=self.max_bin
            )
            dval = None

        entry = WindowMatrices(
            dtrain=dtrain,
            dval=dval,
            X_test=X[lo_te:hi_te],
            y_test=y[lo_te:hi_te],
            n_train=n_train,
            n_test=n_test,
        )
        self._entries[key] = entry
        return entry

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
