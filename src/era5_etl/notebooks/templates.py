"""Loader for bundled notebook templates."""

from __future__ import annotations

import json
from importlib.resources import as_file, files
from typing import Any


def list_templates() -> list[dict[str, Any]]:
    """Return a small summary list of bundled templates."""
    out: list[dict[str, Any]] = []
    resource = files("era5_etl._data.notebook_templates")
    with as_file(resource) as path:
        for f in sorted(path.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                {
                    "id": f.stem,
                    "name": data.get("name", f.stem),
                    "description": data.get("description", ""),
                }
            )
    return out


def load_template(template_id: str) -> dict[str, Any] | None:
    """Return the full template body or ``None`` if unknown."""
    if not template_id or "/" in template_id or "\\" in template_id:
        return None
    resource = files("era5_etl._data.notebook_templates").joinpath(
        f"{template_id}.json"
    )
    try:
        with as_file(resource) as f:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


__all__ = ["list_templates", "load_template"]
