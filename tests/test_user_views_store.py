"""User-defined view/macro store: persistence + validation.

Uses an isolated ERA5_ETL_CONFIG_DIR (matches the test_query_store
precedent); no network, no DuckDB.
"""

import pytest

import era5_etl.web.user_views_store as store


@pytest.fixture(autouse=True)
def _isolated_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))


def test_add_list_update_delete():
    obj = store.add_object(
        name="my_view",
        kind="view",
        sql="CREATE OR REPLACE VIEW my_view AS SELECT 1 AS a",
    )
    assert obj["id"] and obj["name"] == "my_view" and obj["kind"] == "view"
    assert [o["name"] for o in store.list_objects()] == ["my_view"]

    store.update_object(
        obj["id"],
        name="renamed",
        kind="view",
        sql="CREATE OR REPLACE VIEW renamed AS SELECT 2 AS b",
    )
    assert store.list_objects()[0]["name"] == "renamed"

    store.delete_object(obj["id"])
    assert store.list_objects() == []


def test_duplicate_name_rejected():
    store.add_object(
        name="dup", kind="view",
        sql="CREATE OR REPLACE VIEW dup AS SELECT 1",
    )
    with pytest.raises(store.UserObjectError):
        store.add_object(
            name="dup", kind="macro",
            sql="CREATE OR REPLACE MACRO dup() AS 1",
        )


def test_reserved_name_rejected():
    for reserved in ("era5", "era5_land", "inmet", "era5_inmet"):
        with pytest.raises(store.UserObjectError):
            store.add_object(
                name=reserved, kind="view",
                sql=f"CREATE OR REPLACE VIEW {reserved} AS SELECT 1",
            )


def test_unsafe_sql_rejected():
    with pytest.raises(store.UserObjectError):
        store.add_object(
            name="evil", kind="view",
            sql="CREATE VIEW evil AS SELECT 1; DROP TABLE x",
        )
    with pytest.raises(store.UserObjectError):
        store.add_object(
            name="not_ddl", kind="view",
            sql="SELECT 1",
        )


def test_register_user_objects_captures_errors():
    store.add_object(
        name="ok_v", kind="view",
        sql="CREATE OR REPLACE VIEW ok_v AS SELECT 1 AS a",
    )
    store.add_object(
        name="bad_v", kind="view",
        sql="CREATE OR REPLACE VIEW bad_v AS SELECT * FROM does_not_exist",
    )
    import duckdb

    conn = duckdb.connect(":memory:")
    results = store.register_user_objects(conn)
    conn.close()
    by_name = {r["name"]: r for r in results}
    assert by_name["ok_v"]["ok"] is True
    assert by_name["bad_v"]["ok"] is False
    assert by_name["bad_v"]["error"]
