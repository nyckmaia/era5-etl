"""Source-kind dispatch + pipeline stage wiring."""

from __future__ import annotations

from era5_etl.config import PipelineConfig
from era5_etl.pipeline.era5_pipeline import (
    ERA5Pipeline,
    RefreshCoverageStage,
    RefreshStationIndexStage,
)
from era5_etl.pipeline.source_handlers import (
    REFRESH_COVERAGE,
    REFRESH_STATIONS,
    get_handler,
)


def test_handler_lookup_by_source_kind():
    assert get_handler("era5").refresh_kind == REFRESH_COVERAGE
    assert get_handler("era5-land").refresh_kind == REFRESH_COVERAGE
    assert get_handler("inmet").refresh_kind == REFRESH_STATIONS


def test_inmet_factories_build_inmet_classes(tmp_path):
    h = get_handler("inmet")
    cfg = PipelineConfig.create(
        tmp_path, dataset="inmet", start_date="2000-01-01", end_date="2000-12-31"
    )
    dl = h.make_downloader(cfg.download, None, None)
    conv = h.make_converter(
        cfg.transform, cfg.storage, cfg.get_parquet_dir(), "inmet"
    )
    assert type(dl).__name__ == "InmetPortalDownloader"
    assert type(conv).__name__ == "InmetToParquetConverter"


def _stage_types(pipeline):
    pipeline.setup_stages()  # invoked by run(); call directly for inspection
    return [type(s) for s in pipeline.stages]


def test_inmet_pipeline_uses_station_refresh(tmp_path):
    cfg = PipelineConfig.create(
        tmp_path, dataset="inmet", start_date="2000-01-01", end_date="2000-12-31"
    )
    types = _stage_types(ERA5Pipeline(cfg))
    assert RefreshStationIndexStage in types
    assert RefreshCoverageStage not in types


def test_era5_pipeline_uses_coverage_refresh(tmp_path):
    cfg = PipelineConfig.create(
        tmp_path, dataset="era5", start_date="2020-01-01", end_date="2020-01-02"
    )
    types = _stage_types(ERA5Pipeline(cfg))
    assert RefreshCoverageStage in types
    assert RefreshStationIndexStage not in types
