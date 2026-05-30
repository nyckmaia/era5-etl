"""Scan and delete the on-disk Parquet caches produced by /notebooks runs.

Layout (written by the notebook cache cell ``load_inmet_with_cache``)::

    <data_dir>/_nb_cache/<notebook_id>/<file>.parquet

Each immediate subdirectory is one notebook's cache. Loose ``*.parquet`` files
directly under ``_nb_cache/`` come from the older flat layout and are grouped
under the synthetic id ``"_root"``. A group is an *orphan* when its id does not
match a known notebook (the ``_unknown`` and ``_root`` ids are always orphans).

Pure functions over a ``data_dir``; no FastAPI / app-state coupling so they
unit-test directly. All deletes are best-effort and path-safe.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

CACHE_DIRNAME = "_nb_cache"
ROOT_GROUP_ID = "_root"


def cache_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / CACHE_DIRNAME


def _file_entry(path: Path, rel_path: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "name": path.name,
        "rel_path": rel_path,
        "size_bytes": int(st.st_size),
        "modified_ts": int(st.st_mtime),
    }


def scan(data_dir: str | Path, notebook_names: dict[str, str]) -> dict[str, Any]:
    """Return cache groups + grand total. See module docstring for shape."""
    root = cache_root(data_dir)
    if not root.is_dir():
        return {"groups": [], "total_bytes": 0}

    groups: list[dict[str, Any]] = []
    total = 0

    # Subdirectory groups (one per notebook id).
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        files = [
            _file_entry(f, f"{sub.name}/{f.name}")
            for f in sub.glob("*.parquet")
            if f.is_file()
        ]
        if not files:
            continue
        files.sort(key=lambda e: e["size_bytes"], reverse=True)
        subtotal = sum(e["size_bytes"] for e in files)
        total += subtotal
        groups.append(
            {
                "notebook_id": sub.name,
                "notebook_name": notebook_names.get(sub.name),
                "is_orphan": sub.name not in notebook_names,
                "subtotal_bytes": subtotal,
                "files": files,
            }
        )

    # Loose root files from the old flat layout.
    root_files = [
        _file_entry(f, f.name)
        for f in root.glob("*.parquet")
        if f.is_file()
    ]
    if root_files:
        root_files.sort(key=lambda e: e["size_bytes"], reverse=True)
        subtotal = sum(e["size_bytes"] for e in root_files)
        total += subtotal
        groups.append(
            {
                "notebook_id": ROOT_GROUP_ID,
                "notebook_name": None,
                "is_orphan": True,
                "subtotal_bytes": subtotal,
                "files": root_files,
            }
        )

    groups.sort(key=lambda g: g["subtotal_bytes"], reverse=True)
    return {"groups": groups, "total_bytes": total}


def _safe_under_root(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and ensure it stays inside ``root``; else ValueError."""
    root_resolved = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"Path escapes cache root: {candidate}")
    return resolved


def delete_file(data_dir: str | Path, rel_path: str) -> int:
    """Delete one cache file given its scan ``rel_path``. Returns freed bytes."""
    root = cache_root(data_dir)
    target = _safe_under_root(root, root / rel_path)
    if target == root.resolve() or not target.is_file():
        return 0
    size = int(target.stat().st_size)
    target.unlink()
    return size


def delete_notebook(data_dir: str | Path, notebook_id: str) -> int:
    """Delete a whole group. For ``_root`` only loose files are removed."""
    if "/" in notebook_id or "\\" in notebook_id or notebook_id in ("", ".", ".."):
        raise ValueError(f"Invalid notebook id: {notebook_id!r}")
    root = cache_root(data_dir)
    if not root.is_dir():
        return 0
    freed = 0
    if notebook_id == ROOT_GROUP_ID:
        for f in root.glob("*.parquet"):
            if f.is_file():
                freed += int(f.stat().st_size)
                f.unlink()
        return freed
    sub = _safe_under_root(root, root / notebook_id)
    if not sub.is_dir():
        return 0
    for f in sub.rglob("*"):
        if f.is_file():
            freed += int(f.stat().st_size)
    shutil.rmtree(sub)
    return freed


def clear_all(data_dir: str | Path) -> int:
    """Remove the entire ``_nb_cache/`` tree. Returns freed bytes."""
    root = cache_root(data_dir)
    if not root.is_dir():
        return 0
    freed = sum(
        int(f.stat().st_size) for f in root.rglob("*") if f.is_file()
    )
    shutil.rmtree(root)
    return freed


__all__ = [
    "CACHE_DIRNAME",
    "ROOT_GROUP_ID",
    "cache_root",
    "scan",
    "delete_file",
    "delete_notebook",
    "clear_all",
]
