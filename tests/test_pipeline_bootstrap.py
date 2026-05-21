"""Tests for the INMET auto-bootstrap orchestrator in ``routes/pipeline.py``.

These exercise ``_build_phases`` (plans the ordered sub-pipelines) and the
``PipelineRun.set_phase`` integration (each event is stamped with the
active phase) without touching the CDS — ``ERA5Pipeline.run`` is patched
out so no real download happens.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

httpx = pytest.importorskip("httpx")  # required by TestClient
from fastapi.testclient import TestClient

from era5_etl.storage.grid_index import grid_parquet_path
from era5_etl.storage.paths import resolve_dataset_dir
from era5_etl.web.models import PipelineRunIn
from era5_etl.web.routes.pipeline import _build_phases, _format_phase_error
from era5_etl.web.runtime import PipelineRun
from era5_etl.web.server import create_app


def _seed_grid_parquet(base: Path, dataset: str) -> None:
    """Write a bootstrap grid parquet so ``missing_grids`` says it's present."""
    p = grid_parquet_path(base, dataset)
    p.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "latitude": pl.Series([-15.0], dtype=pl.Float32),
            "longitude": pl.Series([-47.0], dtype=pl.Float32),
        }
    ).write_parquet(p)


def _seed_grid(base: Path, dataset: str) -> None:
    """Write a parquet to the PER-DATASET folder (NOT the grid parquet).

    Used by ``test_prereq_does_not_count_data_in_dataset_folder`` to assert
    that only the grid parquet under ``_grids/`` counts as a prerequisite,
    not user data in the dataset folder.
    """
    d = resolve_dataset_dir(base, dataset) / "date=2024-01-01"
    d.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"latitude": [0.0]}).write_parquet(
        d / f"{dataset}_2024-01-01_part-001.parquet"
    )


def _inmet_body() -> PipelineRunIn:
    return PipelineRunIn(
        dataset="inmet",
        variables=[],
        start_date="2024-01-01",
        end_date="2024-12-31",
        area=[0, 0, 0, 0],
        hours=[],
        years=[2024],
    )


# ---- _build_phases ------------------------------------------------------


def test_build_phases_no_grids_present_runs_three(tmp_path: Path):
    phases = _build_phases(_inmet_body(), tmp_path)
    assert [p.name for p in phases] == [
        "bootstrap-era5",
        "bootstrap-era5-land",
        "inmet",
    ]
    # Bootstrap phases must skip smart-diff (coverage is empty for them anyway).
    assert phases[0].apply_diff is False
    assert phases[1].apply_diff is False
    # Bootstrap phases must be flagged so the orchestrator picks
    # BootstrapGridPipeline (NOT ERA5Pipeline, which would write to the
    # per-dataset folder).
    assert phases[0].is_bootstrap is True
    assert phases[1].is_bootstrap is True
    assert phases[2].is_bootstrap is False
    # Bootstrap configs target the cheap defaults.
    assert phases[0].config.dataset_name == "era5"
    assert phases[0].config.download.start_date == "2024-01-01"
    assert phases[0].config.download.end_date == "2024-01-01"
    assert phases[0].config.download.hours == ["12:00"]
    assert phases[0].config.download.variables == ["2m_temperature"]
    assert phases[0].config.transform.clip_regions == ["BR"]


def test_build_phases_only_era5_present_skips_one(tmp_path: Path):
    _seed_grid_parquet(tmp_path, "era5")
    phases = _build_phases(_inmet_body(), tmp_path)
    assert [p.name for p in phases] == ["bootstrap-era5-land", "inmet"]


def test_build_phases_both_grids_present_runs_single_inmet(tmp_path: Path):
    _seed_grid_parquet(tmp_path, "era5")
    _seed_grid_parquet(tmp_path, "era5-land")
    phases = _build_phases(_inmet_body(), tmp_path)
    assert [p.name for p in phases] == ["inmet"]


def test_prereq_does_not_count_data_in_dataset_folder(tmp_path: Path):
    """M02/M03: the per-dataset folder is not a signal — only the grid
    parquet in ``_grids/`` counts. This is what keeps the /inventory map
    showing only data the user downloaded intentionally."""
    _seed_grid(tmp_path, "era5")  # writes to <base>/<dataset>/, NOT _grids/
    phases = _build_phases(_inmet_body(), tmp_path)
    assert "bootstrap-era5" in [p.name for p in phases]
    assert "bootstrap-era5-land" in [p.name for p in phases]


def test_build_phases_non_inmet_dataset_is_single_phase(tmp_path: Path):
    body = PipelineRunIn(
        dataset="era5",
        variables=["2m_temperature"],
        start_date="2024-01-01",
        end_date="2024-01-02",
        area=[-10.0, -50.0, -20.0, -40.0],
        hours=["00:00"],
    )
    phases = _build_phases(body, tmp_path)
    assert [p.name for p in phases] == ["era5"]


# ---- PipelineRun phase stamping ----------------------------------------


def test_pipeline_run_stamps_phase_on_emit_chunk_event():
    run = PipelineRun(run_id="r1", dataset="inmet")
    run.set_phase("bootstrap-era5", 1, 3)
    run.emit_chunk_event({"chunk_id": "c1", "phase": "downloading", "message": "x"})
    # Pull the queued event off the queue and check it carries the phase.
    ev = run._queue.get_nowait()
    assert ev.pipeline_phase == "bootstrap-era5"
    assert ev.phase_index == 1
    assert ev.phase_total == 3


def test_pipeline_run_default_phase_state_is_single():
    run = PipelineRun(run_id="r2", dataset="era5")
    assert run.pipeline_phase is None
    assert run.phase_index == 1
    assert run.phase_total == 1


# ---- error formatter ----------------------------------------------------


def test_format_phase_error_credentials_hint_for_bootstrap():
    msg = _format_phase_error("bootstrap-era5", RuntimeError("401 invalid api key"))
    assert "Configurações" in msg
    assert "bootstrap-era5" in msg


def test_format_phase_error_passes_through_for_inmet_phase():
    msg = _format_phase_error("inmet", RuntimeError("portal 502"))
    assert msg.startswith("Falha em inmet")
    assert "Configurações" not in msg


# ---- end-to-end: /run executes phases in order (ERA5Pipeline mocked) ----


def test_run_endpoint_executes_bootstrap_then_inmet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When INMET is requested and both grids are missing, ``/api/pipeline/run``
    should schedule three sequential phases. Both pipeline classes are
    mocked so the test does not require the CDS or a portal."""
    seen: list[str] = []

    class _FakePipeline:
        def __init__(self, config, progress_callback=None, apply_diff=False):
            self.config = config

        def run(self):
            seen.append(self.config.dataset_name)

    monkeypatch.setattr(
        "era5_etl.pipeline.era5_pipeline.ERA5Pipeline", _FakePipeline
    )
    monkeypatch.setattr(
        "era5_etl.pipeline.era5_pipeline.BootstrapGridPipeline", _FakePipeline
    )

    client = TestClient(create_app(tmp_path))
    r = client.post(
        "/api/pipeline/run",
        json={
            "dataset": "inmet",
            "variables": [],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area": [0, 0, 0, 0],
            "hours": [],
            "apply_diff": False,
            "years": [2024],
        },
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    # The /run handler spawns a daemon thread; consume the SSE stream
    # synchronously by talking to the PipelineRun queue directly. We just
    # need ``mark_completed`` to happen, which it does after every phase.
    from era5_etl.web.runtime import RUNTIME

    run = RUNTIME.get(run_id)
    assert run is not None
    # Wait for the thread to finish (queue receives the SENTINEL on completion).
    for _ in range(50):
        if run.status in ("completed", "failed"):
            break
        import time as _t

        _t.sleep(0.05)
    assert run.status == "completed", run.error
    assert seen == ["era5", "era5-land", "inmet"]


def test_run_endpoint_aborts_on_bootstrap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If a bootstrap phase fails, the INMET phase must not run and the run
    must report ``failed`` with a credentials-pointing message."""
    seen: list[str] = []

    class _FailingPipeline:
        def __init__(self, config, progress_callback=None, apply_diff=False):
            self.config = config

        def run(self):
            seen.append(self.config.dataset_name)
            if self.config.dataset_name == "era5":
                raise RuntimeError("401 invalid api key")

    monkeypatch.setattr(
        "era5_etl.pipeline.era5_pipeline.ERA5Pipeline", _FailingPipeline
    )
    monkeypatch.setattr(
        "era5_etl.pipeline.era5_pipeline.BootstrapGridPipeline", _FailingPipeline
    )

    client = TestClient(create_app(tmp_path))
    r = client.post(
        "/api/pipeline/run",
        json={
            "dataset": "inmet",
            "variables": [],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "area": [0, 0, 0, 0],
            "hours": [],
            "apply_diff": False,
            "years": [2024],
        },
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    from era5_etl.web.runtime import RUNTIME

    run = RUNTIME.get(run_id)
    assert run is not None
    for _ in range(50):
        if run.status in ("completed", "failed"):
            break
        import time as _t

        _t.sleep(0.05)
    assert run.status == "failed"
    assert "bootstrap-era5" in (run.error or "")
    assert "Configurações" in (run.error or "")
    # Only the first phase ran.
    assert seen == ["era5"]
