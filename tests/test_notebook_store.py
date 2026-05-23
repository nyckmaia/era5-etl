"""CRUD + atomic persistence of user notebooks."""

from __future__ import annotations

import os

import pytest

from era5_etl.web import notebook_store


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path))


def test_create_and_get_notebook():
    nb = notebook_store.create_notebook(name="My notebook")
    assert nb["id"]
    assert nb["name"] == "My notebook"
    assert nb["cells"] == []
    assert nb["runs"] == []

    loaded = notebook_store.get_notebook(nb["id"])
    assert loaded is not None
    assert loaded["id"] == nb["id"]


def test_list_orders_by_recent():
    a = notebook_store.create_notebook(name="A")
    b = notebook_store.create_notebook(name="B")
    items = notebook_store.list_notebooks()
    assert [i["id"] for i in items] == [b["id"], a["id"]]


def test_save_updates_cells_and_name():
    nb = notebook_store.create_notebook(name="Initial")
    cell = notebook_store.make_cell("code", source="print('hi')")
    updated = notebook_store.save_notebook(
        nb["id"], name="Renamed", cells=[cell]
    )
    assert updated["name"] == "Renamed"
    assert len(updated["cells"]) == 1
    assert updated["cells"][0]["source"] == "print('hi')"
    assert updated["updated_ts"] >= nb["updated_ts"]


def test_save_unknown_id_raises():
    with pytest.raises(FileNotFoundError):
        notebook_store.save_notebook("missing", cells=[])


def test_delete_notebook():
    nb = notebook_store.create_notebook(name="Doomed")
    assert notebook_store.delete_notebook(nb["id"]) is True
    assert notebook_store.get_notebook(nb["id"]) is None
    assert notebook_store.delete_notebook(nb["id"]) is False


def test_append_run_persists_metrics():
    nb = notebook_store.create_notebook(name="ML")
    run = notebook_store.append_run(
        nb["id"],
        params={"max_depth": 6, "n_estimators": 100},
        metrics={"rmse": 1.23, "r2": 0.95},
        duration_s=12.5,
        notes="first try",
    )
    assert run["params"]["max_depth"] == 6
    assert run["metrics"]["rmse"] == 1.23

    loaded = notebook_store.get_notebook(nb["id"])
    assert loaded is not None
    assert len(loaded["runs"]) == 1
    assert loaded["runs"][0]["id"] == run["id"]


def test_invalid_id_rejected():
    with pytest.raises(ValueError, match="Invalid notebook id"):
        notebook_store.get_notebook("../escape")


def test_tmp_file_does_not_appear_in_list(tmp_path):
    notebook_store.create_notebook(name="ok")
    # Drop a leftover ``.tmp`` next to it — list_notebooks must skip it.
    nb_dir = tmp_path / "notebooks"
    (nb_dir / "stray.json.tmp").write_text("{}", encoding="utf-8")
    items = notebook_store.list_notebooks()
    assert all(not i["id"].endswith(".tmp") for i in items)
