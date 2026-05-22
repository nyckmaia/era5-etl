"""Smoke tests for the FastAPI web app.

These tests use ``fastapi.testclient.TestClient``; no network calls are made
to the Copernicus CDS, so they run anywhere.
"""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")  # required by TestClient

from fastapi.testclient import TestClient

from era5_etl.__version__ import __version__
from era5_etl.web.server import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Isolate the user-views store so the suite never reads the real
    # user's ~/.era5-etl/user_views.json (a persisted view/macro there
    # would leak into "no data" assertions).
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    app = create_app(tmp_path)
    return TestClient(app)


def test_version_endpoint(client: TestClient):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"version": __version__}


def test_list_datasets(client: TestClient):
    r = client.get("/api/datasets")
    assert r.status_code == 200
    payload = r.json()
    names = [d["name"] for d in payload]
    assert "era5" in names
    assert "era5-land" in names


def test_get_dataset_era5_land(client: TestClient):
    r = client.get("/api/datasets/era5-land")
    assert r.status_code == 200
    payload = r.json()
    assert payload["cds_dataset_id"] == "reanalysis-era5-land"
    assert payload["grid_resolution_deg"] == 0.1
    api_names = [v["api_name"] for v in payload["variables"]]
    assert "soil_temperature_level_1" in api_names


def test_get_unknown_dataset_returns_404(client: TestClient):
    r = client.get("/api/datasets/nope")
    assert r.status_code == 404


def test_stats_empty_dataset(client: TestClient):
    r = client.get("/api/stats/era5-land")
    assert r.status_code == 200
    payload = r.json()
    assert payload["dataset"] == "era5-land"
    assert payload["parquet_files"] == 0
    assert payload["manifest_chunks"] == 0


def test_pipeline_estimate(client: TestClient):
    body = {
        "dataset": "era5-land",
        "variables": ["2m_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "area": [-10.0, -50.0, -20.0, -40.0],
        "hours": ["00:00", "12:00"],
        "max_request_bytes": 500 * 1024 * 1024,
    }
    r = client.post("/api/pipeline/estimate", json=body)
    assert r.status_code == 200
    payload = r.json()
    assert payload["total_chunks"] >= 1
    assert payload["chunks"][0]["dataset" if False else "year"] == 2024


def test_pipeline_estimate_exposes_fields_count(client: TestClient):
    """Each EstimateChunkOut returns `fields_count` (var × hour × day)."""
    body = {
        "dataset": "era5-land",
        "variables": ["2m_temperature", "2m_dewpoint_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "area": [-10.0, -50.0, -20.0, -40.0],
        "hours": ["00:00", "12:00"],
    }
    r = client.post("/api/pipeline/estimate", json=body)
    assert r.status_code == 200
    payload = r.json()
    assert payload["total_chunks"] >= 1
    for c in payload["chunks"]:
        assert "fields_count" in c
        # 2 vars × 2 hours × n_days_in_chunk
        assert c["fields_count"] == 2 * 2 * len(c["days"])


def test_pipeline_estimate_tight_field_budget_forces_split(client: TestClient):
    """Setting max_request_fields below the natural request forces splits."""
    body = {
        "dataset": "era5-land",
        "variables": ["2m_temperature", "2m_dewpoint_temperature", "skin_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "area": [0.5, 0.0, 0.0, 0.5],
        "hours": [f"{h:02d}:00" for h in range(24)],
        "max_request_fields": 100,
        "max_request_bytes": 1024 * 1024 * 1024,
    }
    r = client.post("/api/pipeline/estimate", json=body)
    assert r.status_code == 200
    payload = r.json()
    # 3 vars × 24h × 31d = 2232 fields → must split into many chunks.
    assert payload["total_chunks"] >= 22
    for c in payload["chunks"]:
        assert c["fields_count"] <= 100


def test_pipeline_estimate_accepts_clip_regions(client: TestClient):
    body = {
        "dataset": "era5-land",
        "variables": ["2m_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "area": [-19.78, -53.10, -25.31, -44.16],
        "hours": ["00:00", "12:00"],
        "clip_regions": ["SP", "RJ"],
    }
    r = client.post("/api/pipeline/estimate", json=body)
    assert r.status_code == 200


def test_pipeline_run_rejects_clip_regions_for_inmet(client: TestClient):
    body = {
        "dataset": "inmet",
        "variables": [],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "area": [0, 0, 0, 0],
        "hours": [],
        "apply_diff": False,
        "clip_regions": ["SP"],
    }
    r = client.post("/api/pipeline/run", json=body)
    assert r.status_code == 400
    assert "gridded" in r.json()["detail"].lower()


def test_pipeline_run_rejects_unknown_region(client: TestClient):
    body = {
        "dataset": "era5",
        "variables": ["2m_temperature"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
        "area": [-19.78, -53.10, -25.31, -44.16],
        "hours": ["00:00"],
        "apply_diff": False,
        "clip_regions": ["XX"],
    }
    r = client.post("/api/pipeline/run", json=body)
    assert r.status_code == 400
    assert "unknown region" in r.json()["detail"].lower()


def test_regions_clip_available_gridded(client: TestClient):
    r = client.get("/api/regions/clip-available?dataset=era5")
    assert r.status_code == 200
    regions = r.json()["regions"]
    assert "BR" in regions
    assert "SP" in regions
    assert len(regions) == 28


def test_regions_clip_available_inmet_returns_empty(client: TestClient):
    r = client.get("/api/regions/clip-available?dataset=inmet")
    assert r.status_code == 200
    assert r.json() == {"regions": []}


def test_regions_clip_available_unknown_dataset(client: TestClient):
    r = client.get("/api/regions/clip-available?dataset=nope")
    assert r.status_code == 400


# --- Variable groups in /api/datasets ---------------------------------


def test_era5_dataset_returns_variable_groups(client: TestClient):
    r = client.get("/api/datasets/era5")
    assert r.status_code == 200
    payload = r.json()
    groups = payload["variable_groups"]
    ids = [g["id"] for g in groups]
    assert ids[0] == "popular"
    assert "temperature_pressure" in ids
    assert "wind" in ids
    assert "ocean_waves" in ids
    assert "other" in ids
    assert len(groups) == 15
    # Order must be preserved.
    assert groups == sorted(groups, key=lambda g: g["order"])


def test_era5_variable_2m_temperature_in_multiple_groups(client: TestClient):
    r = client.get("/api/datasets/era5")
    payload = r.json()
    t2m = next(v for v in payload["variables"] if v["api_name"] == "2m_temperature")
    assert "popular" in t2m["groups"]
    assert "temperature_pressure" in t2m["groups"]


def test_era5_land_has_no_variable_groups(client: TestClient):
    """ERA5-LAND ships an ungrouped YAML; the API echoes an empty list."""
    r = client.get("/api/datasets/era5-land")
    payload = r.json()
    assert payload["variable_groups"] == []
    # Variables also report empty groups (default factory).
    assert all(v["groups"] == [] for v in payload["variables"])


def test_era5_variable_count():
    """Lock down the number of ERA5 single-level variables (regression guard)."""
    from era5_etl.datasets import DatasetRegistry

    assert len(DatasetRegistry.get("era5").variables) == 262


def test_validate_path(client: TestClient, tmp_path: Path):
    r = client.get("/api/settings/validate-path", params={"path": str(tmp_path)})
    assert r.status_code == 200
    payload = r.json()
    assert payload["exists"] is True
    assert payload["is_dir"] is True
    assert payload["is_writable"] is True


def test_validate_missing_path(client: TestClient, tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    r = client.get("/api/settings/validate-path", params={"path": str(missing)})
    assert r.status_code == 200
    payload = r.json()
    assert payload["exists"] is False
    assert payload["is_writable"] is False


def test_query_rejects_non_select(client: TestClient):
    r = client.post(
        "/api/query",
        json={"dataset": "era5-land", "sql": "DROP TABLE foo", "limit": 10},
    )
    assert r.status_code == 400


def test_query_rejects_disallowed_keyword_inside_select(client: TestClient):
    r = client.post(
        "/api/query",
        json={"dataset": "era5-land", "sql": "SELECT 1; DROP TABLE foo;", "limit": 10},
    )
    assert r.status_code == 400


def test_query_without_data_returns_404(client: TestClient):
    r = client.post(
        "/api/query",
        json={"dataset": "era5-land", "sql": "SELECT 1", "limit": 10},
    )
    assert r.status_code == 404


def test_settings_save_and_get(client: TestClient, tmp_path: Path, monkeypatch):
    # Redirect config storage to a temp directory so we don't touch the real home dir.
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    body = {"data_dir": str(tmp_path), "default_dataset": "era5"}
    r = client.post("/api/settings", json=body)
    assert r.status_code == 200
    assert r.json()["default_dataset"] == "era5"
    r2 = client.get("/api/settings")
    assert r2.status_code == 200
    assert r2.json()["default_dataset"] == "era5"


# ---------------------------------------------------------------------------
# Credentials (Melhoria 02)
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch):
    """Point Path.home() at tmp so credentials writes never touch the real ~."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows
    monkeypatch.delenv("CDSAPI_URL", raising=False)
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


def test_credentials_status_none_when_unset(client: TestClient, isolated_home: Path):
    r = client.get("/api/credentials/status")
    assert r.status_code == 200
    payload = r.json()
    assert payload["has_credentials"] is False
    assert payload["source"] == "none"
    assert payload["url"] is None
    assert "cdsapirc" in payload["file_path"]


def test_credentials_status_env(client: TestClient, isolated_home: Path, monkeypatch):
    monkeypatch.setenv("CDSAPI_URL", "https://cds.example/api")
    monkeypatch.setenv("CDSAPI_KEY", "abcdef12345")
    r = client.get("/api/credentials/status")
    assert r.status_code == 200
    payload = r.json()
    assert payload["has_credentials"] is True
    assert payload["source"] == "env"
    assert payload["url"] == "https://cds.example/api"


def test_credentials_save_writes_file(client: TestClient, isolated_home: Path):
    body = {"url": "https://cds.climate.copernicus.eu/api", "key": "uid:abcdef123"}
    r = client.post("/api/credentials", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["has_credentials"] is True
    assert payload["source"] == "file"
    assert payload["url"] == body["url"]

    cdsapirc = isolated_home / ".cdsapirc"
    assert cdsapirc.exists()
    contents = cdsapirc.read_text(encoding="utf-8")
    assert "url: https://cds.climate.copernicus.eu/api" in contents
    assert "key: uid:abcdef123" in contents


def test_credentials_save_rejects_bad_url(client: TestClient, isolated_home: Path):
    body = {"url": "ftp://wrong.scheme/api", "key": "uid:abcdef123"}
    r = client.post("/api/credentials", json=body)
    assert r.status_code == 422


def test_credentials_save_overwrites_existing(client: TestClient, isolated_home: Path):
    cdsapirc = isolated_home / ".cdsapirc"
    cdsapirc.write_text("url: https://old/api\nkey: old:value\n", encoding="utf-8")

    new = {"url": "https://new.example/api", "key": "new:value123"}
    r = client.post("/api/credentials", json=new)
    assert r.status_code == 200
    contents = cdsapirc.read_text(encoding="utf-8")
    assert "old/api" not in contents
    assert "https://new.example/api" in contents


def test_credentials_test_no_creds(client: TestClient, isolated_home: Path):
    r = client.post("/api/credentials/test")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is False
    assert "credentials" in payload["message"].lower()


def test_credentials_test_uses_httpx(client: TestClient, isolated_home: Path, monkeypatch):
    """The /test endpoint should make a single httpx.get with PRIVATE-TOKEN header."""
    cdsapirc = isolated_home / ".cdsapirc"
    cdsapirc.write_text("url: https://example/api\nkey: test:key\n", encoding="utf-8")

    captured = {}

    class _FakeResp:
        status_code = 200
        text = ""

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResp()

    import httpx as httpx_module

    monkeypatch.setattr(httpx_module, "get", fake_get)

    r = client.post("/api/credentials/test")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert captured["headers"]["PRIVATE-TOKEN"] == "test:key"
    assert "catalogue" in captured["url"]


def test_credentials_test_rejects_bad_key(client: TestClient, isolated_home: Path, monkeypatch):
    cdsapirc = isolated_home / ".cdsapirc"
    cdsapirc.write_text("url: https://example/api\nkey: bad:key\n", encoding="utf-8")

    class _FakeResp:
        status_code = 401
        text = "unauthorized"

    import httpx as httpx_module

    monkeypatch.setattr(httpx_module, "get", lambda *a, **kw: _FakeResp())

    r = client.post("/api/credentials/test")
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is False
    assert payload["status_code"] == 401
