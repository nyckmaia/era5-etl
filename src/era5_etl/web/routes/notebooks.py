"""Notebook endpoints.

Provides CRUD over ``user_notebooks`` (stored in ``<config>/notebooks/``),
template listing/instantiation, and per-notebook kernel control with a
Server-Sent-Events stream of cell outputs.
"""

from __future__ import annotations

import json
import logging
import platform
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from era5_etl.notebooks.kernel_manager import (
    MANAGER,
    KernelBusyError,
    KernelDeadError,
)
from era5_etl.notebooks.templates import list_templates, load_template
from era5_etl.web import notebook_store
from era5_etl.web.models import (
    NotebookCreateIn,
    NotebookKernelStatusOut,
    NotebookListItemOut,
    NotebookOut,
    NotebookRunCellIn,
    NotebookRunOut,
    NotebookRunRecordIn,
    NotebookSaveIn,
    NotebookTemplateOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.get("/templates", response_model=list[NotebookTemplateOut])
def get_templates() -> list[NotebookTemplateOut]:
    return [NotebookTemplateOut(**t) for t in list_templates()]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[NotebookListItemOut])
def list_all() -> list[NotebookListItemOut]:
    return [NotebookListItemOut(**n) for n in notebook_store.list_notebooks()]


@router.post("", response_model=NotebookOut)
def create(body: NotebookCreateIn) -> NotebookOut:
    cells: list[dict] = []
    name = body.name
    if body.template_id:
        tpl = load_template(body.template_id)
        if tpl is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown template id: {body.template_id}",
            )
        cells = [
            notebook_store.make_cell(
                cell_type=c.get("type", "code"),
                source=c.get("source", ""),
                outputs=c.get("outputs"),
            )
            for c in tpl.get("cells", [])
        ]
        if not body.name or body.name == "Untitled notebook":
            name = tpl.get("name", body.name)
    nb = notebook_store.create_notebook(name=name, cells=cells)
    return NotebookOut(**nb)


@router.get("/{notebook_id}", response_model=NotebookOut)
def get(notebook_id: str) -> NotebookOut:
    nb = notebook_store.get_notebook(notebook_id)
    if nb is None:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    return NotebookOut(**nb)


@router.put("/{notebook_id}", response_model=NotebookOut)
def save(notebook_id: str, body: NotebookSaveIn) -> NotebookOut:
    try:
        nb = notebook_store.save_notebook(
            notebook_id,
            name=body.name,
            cells=[c.model_dump() for c in body.cells] if body.cells is not None else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NotebookOut(**nb)


@router.delete("/{notebook_id}")
def delete(notebook_id: str) -> dict[str, bool]:
    MANAGER.stop(notebook_id)
    ok = notebook_store.delete_notebook(notebook_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Kernel
# ---------------------------------------------------------------------------


def _runs_url(request: Request, notebook_id: str) -> str:
    # Build the loopback URL the kernel posts back to. We rely on the
    # uvicorn root + the request's host header (already validated for
    # local use). Falls back to 127.0.0.1 if not present.
    host = request.headers.get("host") or "127.0.0.1:8000"
    scheme = request.url.scheme or "http"
    return f"{scheme}://{host}/api/notebooks/{notebook_id}/runs"


@router.get("/{notebook_id}/kernel/status", response_model=NotebookKernelStatusOut)
def kernel_status(notebook_id: str) -> NotebookKernelStatusOut:
    return NotebookKernelStatusOut(
        notebook_id=notebook_id, status=MANAGER.status(notebook_id)
    )


@router.get("/{notebook_id}/kernel/info")
def kernel_info(notebook_id: str) -> dict[str, str]:
    """Human-readable kernel name shown at the top of the notebook.

    The kernel subprocess runs ``sys.executable`` — the same interpreter as
    the server — so the server's Python version is the one in use.
    """
    return {
        "notebook_id": notebook_id,
        "kernel_name": f"Python {platform.python_version()}",
    }


@router.post("/{notebook_id}/kernel/restart", response_model=NotebookKernelStatusOut)
def kernel_restart(notebook_id: str, request: Request) -> NotebookKernelStatusOut:
    if notebook_store.get_notebook(notebook_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    data_dir: Path = request.app.state.data_dir
    MANAGER.restart(notebook_id, data_dir, _runs_url(request, notebook_id))
    return NotebookKernelStatusOut(
        notebook_id=notebook_id, status=MANAGER.status(notebook_id)
    )


@router.delete("/{notebook_id}/kernel", response_model=NotebookKernelStatusOut)
def kernel_stop(notebook_id: str) -> NotebookKernelStatusOut:
    MANAGER.stop(notebook_id)
    return NotebookKernelStatusOut(notebook_id=notebook_id, status="dead")


# ---------------------------------------------------------------------------
# Cell execution (SSE)
# ---------------------------------------------------------------------------


@router.post("/{notebook_id}/run-cell")
def run_cell(notebook_id: str, body: NotebookRunCellIn, request: Request):
    if notebook_store.get_notebook(notebook_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown notebook: {notebook_id}")
    data_dir: Path = request.app.state.data_dir
    runs_url = _runs_url(request, notebook_id)
    try:
        kernel = MANAGER.get_or_start(notebook_id, data_dir, runs_url)
    except KernelDeadError as exc:
        raise HTTPException(status_code=500, detail=f"Kernel boot failed: {exc}") from exc

    try:
        stream = kernel.run_cell(body.cell_id, body.code, body.lang)
    except KernelBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KernelDeadError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _event_source():
        try:
            for msg in stream:
                # Each kernel message is already a dict — wrap as SSE event.
                yield {
                    "event": msg.get("type", "message"),
                    "data": json.dumps(msg),
                }
        except KernelDeadError as exc:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"ename": "KernelDeadError", "evalue": str(exc), "traceback": []}
                ),
            }
            yield {
                "event": "done",
                "data": json.dumps({"cell_id": body.cell_id, "duration_s": 0.0}),
            }

    return EventSourceResponse(_event_source())


# ---------------------------------------------------------------------------
# Run-log callback (called by the kernel via urllib)
# ---------------------------------------------------------------------------


@router.post("/{notebook_id}/runs", response_model=NotebookRunOut)
def append_run(
    notebook_id: str,
    body: NotebookRunRecordIn,
    x_notebook_token: str | None = Header(None),
) -> NotebookRunOut:
    kernel = MANAGER.get_existing(notebook_id)
    if kernel is None or not x_notebook_token or x_notebook_token != kernel.token:
        raise HTTPException(status_code=403, detail="Invalid notebook token")
    try:
        run = notebook_store.append_run(
            notebook_id,
            params=body.params,
            metrics=body.metrics,
            duration_s=body.duration_s,
            notes=body.notes,
            model_name=body.model_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NotebookRunOut(**run)
