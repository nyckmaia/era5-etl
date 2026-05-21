"""User-views CRUD + preview + build-sql API.

TestClient + isolated ERA5_ETL_CONFIG_DIR; no network.
"""

import pytest
from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    return TestClient(create_app(tmp_path))


def test_crud_and_validation(client):
    r = client.post(
        "/api/user-views",
        json={
            "name": "k",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW k AS SELECT 1 AS a",
        },
    )
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    assert any(o["name"] == "k" for o in client.get("/api/user-views").json())

    bad = client.post(
        "/api/user-views",
        json={
            "name": "evil",
            "kind": "view",
            "sql": "CREATE VIEW evil AS SELECT 1; DROP TABLE x",
        },
    )
    assert bad.status_code == 400

    assert client.delete(f"/api/user-views/{oid}").status_code == 200
    assert client.get("/api/user-views").json() == []


def test_build_sql_endpoint(client):
    r = client.post(
        "/api/user-views/build-sql",
        json={
            "name": "cmp",
            "join_type": "LEFT",
            "sources": [
                {"view": "inmet", "alias": "i", "columns": ["value"]},
                {"view": "era5", "alias": "e", "columns": ["value"]},
            ],
            "joins": [
                {
                    "left": "i.latitude",
                    "right": "e.latitude",
                    "approx": True,
                    "epsilon": 1e-4,
                }
            ],
        },
    )
    assert r.status_code == 200
    assert 'abs(e."latitude" - i."latitude") < 0.0001' in r.json()["sql"]


def test_builder_spec_roundtrip(client):
    """The builder snapshot is persisted on create + returned by list/update."""
    spec = {
        "name": "v",
        "join_type": "LEFT",
        "sources": [{"view": "inmet", "alias": "i", "columns": ["a"]}],
        "joins": [],
    }
    r = client.post(
        "/api/user-views",
        json={
            "name": "v",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW v AS SELECT 1 AS a",
            "builder_spec": spec,
        },
    )
    assert r.status_code == 200, r.text
    obj = r.json()
    assert obj["builder_spec"] is not None
    assert obj["builder_spec"]["name"] == "v"

    listed = client.get("/api/user-views").json()
    assert listed[0]["builder_spec"]["sources"][0]["columns"] == ["a"]

    # Editing without builder_spec wipes the snapshot (the SQL came from
    # the SQL editor, not the builder).
    r2 = client.put(
        f"/api/user-views/{obj['id']}",
        json={
            "name": "v",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW v AS SELECT 2 AS a",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["builder_spec"] is None


def test_preview_reports_error_without_raising(client):
    r = client.post(
        "/api/user-views/preview",
        json={
            "name": "p",
            "kind": "view",
            "sql": "CREATE OR REPLACE VIEW p AS SELECT * FROM nope",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["error"]


def test_user_view_unwarns_after_dependency_is_downloaded(client, tmp_path):
    """Regression: a user VIEW that referenced an unregistered base view
    used to stay ``ok=False`` forever — the per-engine cache only
    re-replayed user objects when their DDL changed, ignoring the case
    where a base view just got registered. After M01/M02 of the SCHEMA
    work the user can see WARN badges; once they download the missing
    dataset, those badges must clear on the next /api/user-views call.
    """
    import polars as pl

    from era5_etl.storage.paths import resolve_dataset_dir
    from era5_etl.web import query_engine as qe

    # Reset the per-process engine cache so this test sees a fresh state.
    qe._CACHE.clear()

    # 1) Save a VIEW that depends on the ERA5-LAND base view. ERA5-LAND
    # has no parquet yet, so the view is "broken" on the first replay.
    create = client.post(
        "/api/user-views",
        json={
            "name": "vw_needs_era5_land",
            "kind": "view",
            "sql": (
                "CREATE OR REPLACE VIEW vw_needs_era5_land AS "
                "SELECT * FROM era5_land LIMIT 1"
            ),
        },
    )
    # Creation rejects when the dependency is missing — that's expected
    # at save-time. For the regression we want the case where the view
    # WAS created before the data existed, then the user downloads it.
    # Force the save via the store directly to bypass _validate_against_db.
    if create.status_code == 400:
        from era5_etl.web import user_views_store as uvs

        uvs.add_object(
            name="vw_needs_era5_land",
            kind="view",
            sql=(
                "CREATE OR REPLACE VIEW vw_needs_era5_land AS "
                "SELECT * FROM era5_land LIMIT 1"
            ),
        )

    listed = client.get("/api/user-views").json()
    target = next(o for o in listed if o["name"] == "vw_needs_era5_land")
    assert target["ok"] is False, "view should start broken (no era5-land yet)"

    # 2) Seed an ERA5-LAND parquet (simulates the user downloading it).
    d = resolve_dataset_dir(tmp_path, "era5-land") / "date=2024-01-01"
    d.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "latitude": pl.Series([-15.0], dtype=pl.Float32),
            "longitude": pl.Series([-47.0], dtype=pl.Float32),
            "hour_utc": [0],
            "temperature_2m": [22.5],
        }
    ).write_parquet(d / "era5-land_2024-01-01_part-001.parquet")

    # 3) Next /api/user-views call MUST re-replay the user view and clear
    #    the broken flag.
    listed = client.get("/api/user-views").json()
    target = next(o for o in listed if o["name"] == "vw_needs_era5_land")
    assert target["ok"] is True, (
        f"view should re-validate after dependency was downloaded; "
        f"error={target['error']}"
    )
    assert target["error"] is None
