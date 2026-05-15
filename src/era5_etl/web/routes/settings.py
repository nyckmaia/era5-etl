"""User settings: data_dir picker, validation, persistence."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from era5_etl.web.models import (
    DatasetPrecisionIn,
    DatasetPrecisionOut,
    PathValidationOut,
    UserConfigIn,
    UserConfigOut,
)
from era5_etl.web.user_config import (
    get_dataset_precision,
    load_user_config,
    set_dataset_precision,
    update_user_config,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserConfigOut)
def get_settings() -> UserConfigOut:
    cfg = load_user_config()
    return UserConfigOut(data_dir=cfg.data_dir, default_dataset=cfg.default_dataset)


@router.post("", response_model=UserConfigOut)
def save_settings(body: UserConfigIn, request: Request) -> UserConfigOut:
    from era5_etl.storage.paths import STORAGE_ROOT_DIRNAME

    changes: dict[str, str] = {}
    if body.data_dir is not None:
        # Reject empty / clearly broken paths early.
        if not body.data_dir.strip():
            raise HTTPException(status_code=400, detail="data_dir must not be empty")
        resolved = Path(body.data_dir).expanduser()
        # The UI displays the path with `<root>/climate_data_store_db` appended
        # so the user can see exactly where data lives. Strip the suffix here
        # so the stored value remains the user-chosen parent, which is what
        # every other module in the package treats as ``base_dir``.
        if resolved.name.lower() == STORAGE_ROOT_DIRNAME.lower():
            resolved = resolved.parent
        changes["data_dir"] = str(resolved)
        # Update the live app state too so subsequent requests see the new dir.
        request.app.state.data_dir = resolved
    if body.default_dataset is not None:
        changes["default_dataset"] = body.default_dataset

    cfg = update_user_config(**changes)  # type: ignore[arg-type]
    return UserConfigOut(data_dir=cfg.data_dir, default_dataset=cfg.default_dataset)


@router.get("/validate-path", response_model=PathValidationOut)
def validate_path(path: str) -> PathValidationOut:
    p = Path(path).expanduser()
    exists = p.exists()
    is_dir = p.is_dir() if exists else False
    is_empty: bool | None = None
    if is_dir:
        is_empty = not any(p.iterdir())
    # Writable check: try to create a temp file (only if exists + is_dir)
    is_writable = False
    if is_dir:
        try:
            sentinel = p / ".era5_etl_write_check"
            sentinel.write_bytes(b"")
            sentinel.unlink(missing_ok=True)
            is_writable = True
        except OSError:
            is_writable = False
    return PathValidationOut(
        path=str(p),
        exists=exists,
        is_dir=is_dir,
        is_writable=is_writable,
        is_empty=is_empty,
    )


@router.post("/pick-directory", response_model=PathValidationOut)
def pick_directory() -> PathValidationOut:
    """Open an OS folder-picker dialog and return the chosen path.

    Implemented as a one-shot Python subprocess so tkinter's main-thread
    requirement on macOS does not collide with the FastAPI event loop. The
    subprocess is intentionally tiny so it stays portable.
    """
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "path = filedialog.askdirectory()\n"
        "print(path or '')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=dict(os.environ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=500, detail=f"Folder picker failed: {exc}") from exc

    chosen = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    if not chosen:
        raise HTTPException(status_code=400, detail="No directory selected")
    return validate_path(chosen)


@router.get("/precision", response_model=DatasetPrecisionOut)
def get_precision(dataset: str) -> DatasetPrecisionOut:
    """Return the display-precision config for a dataset (render-only)."""
    p = get_dataset_precision(dataset)
    return DatasetPrecisionOut(
        dataset=dataset,
        default_decimals=p["default_decimals"],
        default_method=p["default_method"],
        columns=p["columns"],
    )


@router.post("/precision", response_model=DatasetPrecisionOut)
def save_precision(body: DatasetPrecisionIn) -> DatasetPrecisionOut:
    """Persist the display-precision config for a dataset."""
    set_dataset_precision(
        body.dataset,
        {
            "default_decimals": body.default_decimals,
            "default_method": body.default_method,
            "columns": {
                k: v.model_dump() for k, v in body.columns.items()
            },
        },
    )
    p = get_dataset_precision(body.dataset)
    return DatasetPrecisionOut(
        dataset=body.dataset,
        default_decimals=p["default_decimals"],
        default_method=p["default_method"],
        columns=p["columns"],
    )
