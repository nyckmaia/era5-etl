"""Apply an exact-substring replacement (or full-cell replace) to BOTH the
template JSON and the runtime notebook JSON, preserving each file's format.

Usage is via import from the task steps, e.g.:
    from scripts._inject_cell import patch_cell
    patch_cell(cell_idx=2, anchor=OLD, replacement=NEW)         # substring edit
    patch_cell(cell_idx=2, full_source=NEW_SOURCE)              # whole-cell replace
"""
import json
from pathlib import Path
from era5_etl.web.user_config import _config_dir

TEMPLATE = Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json")
NOTEBOOK = _config_dir() / "notebooks" / "6d1169c493984849a5e56e7ec7229128.json"


def _apply(path: Path, cell_idx, anchor, replacement, full_source, clear_outputs):
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    cell = data["cells"][cell_idx]
    assert cell.get("type") == "code", f"cell {cell_idx} is not code"
    if full_source is not None:
        cell["source"] = full_source
    else:
        if full_source is None and anchor is None:
            raise ValueError("patch_cell: supply either anchor=... or full_source=...")
        assert cell["source"].count(anchor) == 1, (
            f"anchor not unique in {path.name} cell {cell_idx}")
        cell["source"] = cell["source"].replace(anchor, replacement)
    if clear_outputs and "outputs" in cell:
        cell["outputs"] = []
    for i, c in enumerate(data["cells"]):
        if c.get("type") == "code":
            compile(c["source"], f"<cell {i}>", "exec")
    trailing = "\n" if raw.endswith("\n") else ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + trailing,
                    encoding="utf-8")


def patch_cell(*, cell_idx, anchor=None, replacement=None, full_source=None):
    _apply(TEMPLATE, cell_idx, anchor, replacement, full_source, clear_outputs=False)
    _apply(NOTEBOOK, cell_idx, anchor, replacement, full_source, clear_outputs=True)
    print(f"patched cell {cell_idx} in template + notebook")
