"""Per-dataset variable presets: store CRUD + API.

Isolated ERA5_ETL_CONFIG_DIR (matches the test_user_views precedent); no
network, no DuckDB.
"""

import pytest
from fastapi.testclient import TestClient

import era5_etl.web.variable_presets_store as store
from era5_etl.web.server import create_app

# Real CDS api_names (the wizard checkboxes use api_name, so presets do too).
T2M = "2m_temperature"
D2M = "2m_dewpoint_temperature"
ERA5_T2M = "2m_temperature"


@pytest.fixture(autouse=True)
def _isolated_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


# --- store ----------------------------------------------------------------


def test_add_list_update_delete():
    p = store.add_preset("era5-land", "My set", [T2M, D2M])
    assert p["id"] and p["dataset"] == "era5-land"
    assert p["variables"] == [T2M, D2M]
    assert [x["name"] for x in store.list_presets("era5-land")] == ["My set"]

    store.update_preset(p["id"], "Renamed", [T2M])
    got = store.list_presets("era5-land")[0]
    assert got["name"] == "Renamed" and got["variables"] == [T2M]
    assert got["updated_ts"] >= got["created_ts"]

    store.delete_preset(p["id"])
    assert store.list_presets("era5-land") == []


def test_presets_are_per_dataset():
    store.add_preset("era5-land", "L", [T2M])
    store.add_preset("era5", "E", [ERA5_T2M])
    assert [x["name"] for x in store.list_presets("era5-land")] == ["L"]
    assert [x["name"] for x in store.list_presets("era5")] == ["E"]


def test_duplicate_name_per_dataset_rejected():
    store.add_preset("era5-land", "dup", [T2M])
    with pytest.raises(store.PresetError):
        store.add_preset("era5-land", "dup", [D2M])
    # Same name on a *different* dataset is fine.
    store.add_preset("era5", "dup", [ERA5_T2M])


def test_unknown_variables_filtered():
    p = store.add_preset("era5-land", "x", [T2M, "not_a_real_variable"])
    assert "not_a_real_variable" not in p["variables"]
    assert T2M in p["variables"]


def test_duplicate_variables_collapsed_order_preserved():
    p = store.add_preset("era5-land", "x", [D2M, T2M, D2M])
    assert p["variables"] == [D2M, T2M]


def test_empty_name_rejected():
    with pytest.raises(store.PresetError):
        store.add_preset("era5-land", "   ", [T2M])


def test_unknown_dataset_rejected():
    with pytest.raises(store.PresetError):
        store.add_preset("does-not-exist", "x", [])


def test_non_gridded_dataset_rejected():
    # INMET has no selectable CDS variables.
    with pytest.raises(store.PresetError):
        store.add_preset("inmet", "x", [])


def test_update_unknown_id_rejected():
    with pytest.raises(store.PresetError):
        store.update_preset("nope", "x", [T2M])


# --- API ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "apicfg"))
    return TestClient(create_app(tmp_path))


def test_api_crud(client):
    r = client.post(
        "/api/variable-presets",
        json={"dataset": "era5-land", "name": "synoptic", "variables": [T2M]},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    listed = client.get(
        "/api/variable-presets", params={"dataset": "era5-land"}
    ).json()
    assert any(x["name"] == "synoptic" for x in listed)

    # Not visible under another dataset (per-dataset scoping).
    assert (
        client.get("/api/variable-presets", params={"dataset": "era5"}).json()
        == []
    )

    r2 = client.put(
        f"/api/variable-presets/{pid}",
        json={"name": "synoptic2", "variables": [T2M, D2M]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "synoptic2"
    assert r2.json()["variables"] == [T2M, D2M]

    assert client.delete(f"/api/variable-presets/{pid}").status_code == 200
    assert (
        client.get(
            "/api/variable-presets", params={"dataset": "era5-land"}
        ).json()
        == []
    )


def test_api_rejects_bad(client):
    assert (
        client.post(
            "/api/variable-presets",
            json={"dataset": "era5-land", "name": "", "variables": []},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/variable-presets",
            json={"dataset": "inmet", "name": "x", "variables": []},
        ).status_code
        == 400
    )
