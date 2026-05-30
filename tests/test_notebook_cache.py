"""Tests for the notebook-cache scan/delete helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from era5_etl.web import notebook_cache as nc


def _make_cache(tmp_path: Path) -> Path:
    root = tmp_path / "_nb_cache"
    # Named notebook subdir with two files.
    (root / "nbA").mkdir(parents=True)
    (root / "nbA" / "f1.parquet").write_bytes(b"x" * 100)
    (root / "nbA" / "f2.parquet").write_bytes(b"y" * 50)
    # _unknown subdir (always orphan).
    (root / "_unknown").mkdir()
    (root / "_unknown" / "f3.parquet").write_bytes(b"z" * 10)
    # Loose root file (old flat layout -> "_root" orphan group).
    (root / "old.parquet").write_bytes(b"w" * 5)
    return root


def test_scan_groups_and_totals(tmp_path):
    _make_cache(tmp_path)
    out = nc.scan(tmp_path, {"nbA": "Notebook A"})
    groups = {g["notebook_id"]: g for g in out["groups"]}
    assert out["total_bytes"] == 165
    assert groups["nbA"]["subtotal_bytes"] == 150
    assert groups["nbA"]["notebook_name"] == "Notebook A"
    assert groups["nbA"]["is_orphan"] is False
    assert {f["name"] for f in groups["nbA"]["files"]} == {"f1.parquet", "f2.parquet"}
    assert groups["_unknown"]["is_orphan"] is True
    assert groups["_root"]["is_orphan"] is True
    assert groups["_root"]["subtotal_bytes"] == 5
    # groups sorted by subtotal desc
    assert [g["notebook_id"] for g in out["groups"]][0] == "nbA"


def test_scan_missing_dir(tmp_path):
    out = nc.scan(tmp_path, {})
    assert out == {"groups": [], "total_bytes": 0}


def test_delete_file(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_file(tmp_path, "nbA/f1.parquet")
    assert freed == 100
    assert not (tmp_path / "_nb_cache" / "nbA" / "f1.parquet").exists()


def test_delete_file_rejects_traversal(tmp_path):
    _make_cache(tmp_path)
    with pytest.raises(ValueError):
        nc.delete_file(tmp_path, "../secret.txt")
    with pytest.raises(ValueError):
        nc.delete_file(tmp_path, "nbA/../../escape.txt")


def test_delete_notebook(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_notebook(tmp_path, "nbA")
    assert freed == 150
    assert not (tmp_path / "_nb_cache" / "nbA").exists()


def test_delete_notebook_root_only_removes_loose_files(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_notebook(tmp_path, "_root")
    assert freed == 5
    assert not (tmp_path / "_nb_cache" / "old.parquet").exists()
    # subdirs untouched
    assert (tmp_path / "_nb_cache" / "nbA").exists()


def test_delete_notebook_rejects_traversal(tmp_path):
    _make_cache(tmp_path)
    with pytest.raises(ValueError):
        nc.delete_notebook(tmp_path, "../x")


def test_clear_all(tmp_path):
    _make_cache(tmp_path)
    freed = nc.clear_all(tmp_path)
    assert freed == 165
    assert not (tmp_path / "_nb_cache").exists()


def test_delete_missing_returns_zero(tmp_path):
    (tmp_path / "_nb_cache").mkdir()
    assert nc.delete_file(tmp_path, "nbA/nope.parquet") == 0
    assert nc.delete_notebook(tmp_path, "ghost") == 0
    assert nc.clear_all(tmp_path) == 0  # empty dir -> 0 bytes freed (dir removed)


# --- route smoke tests -------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from era5_etl.web.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import era5_etl.web.notebook_store as ns

    monkeypatch.setattr(ns, "_config_dir", lambda: tmp_path / "cfg")
    app = create_app(tmp_path / "data")
    # cache lives under app.state.data_dir; create some files there
    data_dir = tmp_path / "data"
    root = data_dir / "_nb_cache" / "nbX"
    root.mkdir(parents=True)
    (root / "a.parquet").write_bytes(b"x" * 200)
    with TestClient(app) as c:
        yield c, data_dir


def test_route_list_and_delete_file(client):
    c, data_dir = client
    r = c.get("/api/settings/nb-cache")
    assert r.status_code == 200
    body = r.json()
    assert body["total_bytes"] == 200
    assert body["groups"][0]["notebook_id"] == "nbX"
    rel = body["groups"][0]["files"][0]["rel_path"]
    d = c.request("DELETE", f"/api/settings/nb-cache/file", params={"path": rel})
    assert d.status_code == 200
    assert d.json() == {"deleted": True, "freed_bytes": 200}


def test_route_delete_file_traversal_400(client):
    c, _ = client
    d = c.request("DELETE", "/api/settings/nb-cache/file", params={"path": "../x"})
    assert d.status_code == 400


def test_route_delete_notebook_and_clear(client):
    c, data_dir = client
    d = c.request("DELETE", "/api/settings/nb-cache/notebook/nbX")
    assert d.status_code == 200 and d.json()["freed_bytes"] == 200
    # clear-all on now-empty tree
    d2 = c.request("DELETE", "/api/settings/nb-cache")
    assert d2.status_code == 200
