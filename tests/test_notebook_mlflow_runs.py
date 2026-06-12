"""MLflow file-store runs merged into the notebook Model-runs panel."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
mlflow = pytest.importorskip("mlflow")

from fastapi.testclient import TestClient

from era5_etl.web.server import create_app


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ERA5_ETL_CONFIG_DIR", str(tmp_path / "cfg"))
    # MLflow 3.x requires explicit opt-in to the local file-store backend.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    return TestClient(app)


def _seed_mlflow_run(notebook_id: str) -> str:
    from era5_etl.web.mlflow_runs import mlflow_tracking_uri

    mlflow.set_tracking_uri(mlflow_tracking_uri())
    mlflow.set_experiment(f"nb_{notebook_id}")
    with mlflow.start_run(run_name="parent") as parent:
        mlflow.set_tags(
            {
                "model_name": "xgboost_optuna_windows",
                "notes": "minha nota",
                "load_source": "db query",
            }
        )
        mlflow.log_params({"station_id": "A726"})
        mlflow.log_metrics({"rmse": 1.5, "duration_s": 12.0})
        with mlflow.start_run(run_name="expanding", nested=True):
            mlflow.log_metric("rmse_mean", 1.0)
    return parent.info.run_id


def test_tracking_uri_is_file_store_under_config_dir(tmp_path):
    from era5_etl.web.mlflow_runs import mlflow_tracking_uri

    uri = mlflow_tracking_uri()
    assert uri.startswith("file:")
    assert "mlruns" in uri


def test_get_notebook_merges_mlflow_parent_runs(client):
    nb_id = client.post("/api/notebooks", json={"name": "ml"}).json()["id"]
    run_id = _seed_mlflow_run(nb_id)

    runs = client.get(f"/api/notebooks/{nb_id}").json()["runs"]
    assert len(runs) == 1  # nested child filtered out
    run = runs[0]
    assert run["id"] == run_id
    assert run["model_name"] == "xgboost_optuna_windows"
    assert run["notes"] == "minha nota"
    assert run["params"]["station_id"] == "A726"
    assert run["metrics"]["rmse"] == 1.5
    # duration_s metric is promoted to the panel field, not left in metrics
    assert run["duration_s"] == 12.0
    assert "duration_s" not in run["metrics"]
    # string tag folded back where the panel reads it
    assert run["metrics"]["load_source"] == "db query"


def test_legacy_json_runs_still_listed_without_mlflow_store(client):
    nb_id = client.post("/api/notebooks", json={"name": "legacy"}).json()["id"]
    # No mlruns dir at all -> only legacy runs (none here) and no 500.
    r = client.get(f"/api/notebooks/{nb_id}")
    assert r.status_code == 200
    assert r.json()["runs"] == []
