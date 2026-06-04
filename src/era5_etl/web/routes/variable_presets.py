"""CRUD for per-dataset variable presets (download wizard).

Presets are named variable selections persisted by
:mod:`era5_etl.web.variable_presets_store` (plain JSON, no DuckDB). The
Variables step of the wizard loads/saves them so the user can reuse the
same selection across downloads. Scoped per gridded dataset.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from era5_etl.web import variable_presets_store as store
from era5_etl.web.models import (
    VariablePresetIn,
    VariablePresetOut,
    VariablePresetUpdateIn,
)

router = APIRouter(prefix="/api/variable-presets", tags=["variable-presets"])


@router.get("", response_model=list[VariablePresetOut])
def list_presets(dataset: str) -> list[VariablePresetOut]:
    return [VariablePresetOut(**p) for p in store.list_presets(dataset)]


@router.post("", response_model=VariablePresetOut)
def create_preset(body: VariablePresetIn) -> VariablePresetOut:
    try:
        preset = store.add_preset(body.dataset, body.name, body.variables)
    except store.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VariablePresetOut(**preset)


@router.put("/{preset_id}", response_model=VariablePresetOut)
def update_preset(
    preset_id: str, body: VariablePresetUpdateIn
) -> VariablePresetOut:
    try:
        preset = store.update_preset(preset_id, body.name, body.variables)
    except store.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VariablePresetOut(**preset)


@router.delete("/{preset_id}")
def delete_preset(preset_id: str) -> dict[str, bool]:
    store.delete_preset(preset_id)
    return {"ok": True}
