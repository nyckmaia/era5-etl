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
# String tags folded back into ``params`` (shown in the run-inputs dialog,
# mirroring the legacy log_model_run shape).
_TAG_PARAM_KEYS = ("device",)
_MAX_RUNS = 500


def mlflow_tracking_uri() -> str:
    """``file://`` URI of the local MLflow store (created on first log)."""
    return (_config_dir() / "mlruns").resolve().as_uri()


def list_runs_for_notebook(notebook_id: str) -> list[dict[str, Any]]:
    """Panel-shaped dicts for the notebook's top-level MLflow runs.

    Order is unspecified; the caller merges with legacy runs and sorts.
    """
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
        params: dict[str, Any] = dict(run.data.params)
        for key in _TAG_PARAM_KEYS:
            if key in tags:
                params.setdefault(key, tags[key])
        out.append(
            {
                "id": run.info.run_id,
                "ts": int(run.info.start_time),
                "model_name": tags.get("model_name", "mlflow"),
                "params": params,
                "metrics": metrics,
                "duration_s": float(duration_s),
                "notes": tags.get("notes", ""),
            }
        )
    return out


__all__ = ["list_runs_for_notebook", "mlflow_tracking_uri"]
