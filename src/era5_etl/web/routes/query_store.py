"""Server-backed SQL-editor history + templates (M03).

Shares the ``/api/query`` prefix with :mod:`era5_etl.web.routes.query`.
History is appended by the frontend after each successful run (datasus
precedent), so this router never touches DuckDB.
"""

from __future__ import annotations

from fastapi import APIRouter

from era5_etl.web import query_store
from era5_etl.web.models import (
    QueryHistoryAppendIn,
    QueryHistoryEntry,
    QueryHistoryPatch,
    TemplateItem,
)

router = APIRouter(prefix="/api/query", tags=["query"])


@router.get("/templates", response_model=list[TemplateItem])
def get_templates() -> list[dict]:
    return query_store.list_templates()


@router.get("/history/{view}", response_model=list[QueryHistoryEntry])
def get_history(view: str) -> list[dict]:
    return query_store.list_history(view)


@router.post("/history/{view}", response_model=list[QueryHistoryEntry])
def post_history(view: str, body: QueryHistoryAppendIn) -> list[dict]:
    return query_store.append_history(
        view, body.sql, body.rows, body.elapsed_ms
    )


@router.patch(
    "/history/{view}/{entry_id}", response_model=list[QueryHistoryEntry]
)
def patch_history_entry(
    view: str, entry_id: str, body: QueryHistoryPatch
) -> list[dict]:
    kwargs: dict = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.favorite is not None:
        kwargs["favorite"] = body.favorite
    return query_store.patch_history(view, entry_id, **kwargs)


@router.delete(
    "/history/{view}/{entry_id}", response_model=list[QueryHistoryEntry]
)
def delete_history_entry(view: str, entry_id: str) -> list[dict]:
    return query_store.delete_history(view, entry_id)


@router.delete("/history/{view}", response_model=list[QueryHistoryEntry])
def clear_history(view: str) -> list[dict]:
    return query_store.clear_history(view)
