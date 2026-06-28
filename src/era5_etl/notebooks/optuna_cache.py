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
