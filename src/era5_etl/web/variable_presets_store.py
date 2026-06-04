"""Persisted per-dataset variable presets for the download wizard.

A *preset* is a named set of CDS variable ``api_name``s for one gridded
dataset (ERA5 / ERA5-LAND). The Variables step of the download wizard lets
the user save the current checkbox selection under a name, then re-load it
in a later download. Presets are scoped **per dataset** -- an ERA5 preset is
never offered in the ERA5-LAND wizard (the two have different variable sets).

Stored as JSON at ``_config_dir()/variable_presets.json`` (next to
``user_views.json`` / ``query_store.json``), mirroring
:mod:`era5_etl.web.user_views_store`: thread-locked, atomic temp-file
replace, no DuckDB and no writable state on the data path.

Record shape::

    {"id", "dataset", "name", "variables": [api_name, ...],
     "created_ts", "updated_ts"}

Incoming ``variables`` are filtered to the dataset's valid ``api_name``s so a
stale preset can never inject an unknown variable into a download request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from era5_etl.datasets import DatasetRegistry
from era5_etl.web.user_config import _config_dir

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


class PresetError(ValueError):
    """Invalid preset (empty name, unknown/non-grid dataset, or duplicate)."""


def _store_path():
    return _config_dir() / "variable_presets.json"


def _load() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"presets": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s -- starting empty", path, exc)
        return {"presets": []}
    if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
        return {"presets": []}
    return data


def _save(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic on same volume


def _valid_variables(dataset: str) -> set[str]:
    """Return the set of valid CDS ``api_name``s for a **gridded** dataset.

    Raises :class:`PresetError` for an unknown dataset or a non-grid source
    (e.g. INMET has no selectable CDS variables).
    """
    try:
        cfg = DatasetRegistry.get(dataset)
    except KeyError as exc:
        raise PresetError(f"Unknown dataset: {dataset!r}") from exc
    if not cfg.is_gridded:
        raise PresetError(
            f"Dataset {dataset!r} has no selectable variables (not a grid source)."
        )
    return {v.api_name for v in cfg.variables}


def _clean(dataset: str, name: str, variables: list[str]) -> tuple[str, list[str]]:
    """Validate the name + dataset and filter ``variables`` to known ones.

    Order is preserved and duplicates dropped; unknown api_names are
    silently discarded so a stale preset never breaks a download.
    """
    name = (name or "").strip()
    if not name:
        raise PresetError("Preset name must not be empty.")
    valid = _valid_variables(dataset)
    filtered = [v for v in dict.fromkeys(variables or []) if v in valid]
    return name, filtered


def list_presets(dataset: str) -> list[dict[str, Any]]:
    """Presets for one dataset, oldest first."""
    with _LOCK:
        items = [p for p in _load()["presets"] if p.get("dataset") == dataset]
    return sorted(items, key=lambda p: p["created_ts"])


def find_by_name(dataset: str, name: str) -> dict[str, Any] | None:
    """Case-insensitive lookup within a dataset. ``None`` if no match."""
    target = (name or "").strip().lower()
    for p in list_presets(dataset):
        if p["name"].lower() == target:
            return p
    return None


def add_preset(dataset: str, name: str, variables: list[str]) -> dict[str, Any]:
    name, variables = _clean(dataset, name, variables)
    now = int(time.time() * 1000)
    preset = {
        "id": uuid.uuid4().hex,
        "dataset": dataset,
        "name": name,
        "variables": variables,
        "created_ts": now,
        "updated_ts": now,
    }
    with _LOCK:
        data = _load()
        if any(
            p["dataset"] == dataset and p["name"].lower() == name.lower()
            for p in data["presets"]
        ):
            raise PresetError(
                f"A preset named '{name}' already exists for {dataset}."
            )
        data["presets"].append(preset)
        _save(data)
    return preset


def update_preset(preset_id: str, name: str, variables: list[str]) -> dict[str, Any]:
    """Rename / re-set the variables of an existing preset.

    The preset's ``dataset`` is immutable; variables are re-validated
    against it.
    """
    with _LOCK:
        data = _load()
        target = next((p for p in data["presets"] if p["id"] == preset_id), None)
        if target is None:
            raise PresetError(f"Unknown preset id: {preset_id}")
        dataset = target["dataset"]
        name, variables = _clean(dataset, name, variables)
        if any(
            p["id"] != preset_id
            and p["dataset"] == dataset
            and p["name"].lower() == name.lower()
            for p in data["presets"]
        ):
            raise PresetError(
                f"A preset named '{name}' already exists for {dataset}."
            )
        target.update(
            name=name,
            variables=variables,
            updated_ts=int(time.time() * 1000),
        )
        _save(data)
    assert isinstance(target, dict)
    return target


def delete_preset(preset_id: str) -> None:
    with _LOCK:
        data = _load()
        data["presets"] = [p for p in data["presets"] if p["id"] != preset_id]
        _save(data)


__all__ = [
    "PresetError",
    "add_preset",
    "delete_preset",
    "find_by_name",
    "list_presets",
    "update_preset",
]
