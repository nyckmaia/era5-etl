"""Guard: bundled notebook templates log the metrics the UI table expects."""

from __future__ import annotations

from era5_etl.notebooks.templates import load_template


def _code_sources(template_id: str) -> str:
    tpl = load_template(template_id)
    assert tpl is not None, f"template {template_id!r} not found"
    return "\n".join(
        c.get("source", "")
        for c in tpl.get("cells", [])
        if c.get("type") == "code"
    )


def test_xgboost_template_logs_new_run_metrics():
    src = _code_sources("xgboost_temperature_forecast")
    for key in ("test_fraction", "n_train", "n_test", "num_days"):
        assert f'"{key}"' in src, f"template must log metric {key!r}"


def test_xgboost_cache_key_includes_full_config():
    """Cache must key on the variable selection, target and test fraction.

    Regression guard: keeping only (station, start, end) served a stale frame
    when the user toggled era5_land_vars but kept the same dates.
    """
    src = _code_sources("xgboost_temperature_forecast")
    # A digest helper folds the config into the cache filename...
    assert "_config_digest(" in src, "cache filename must include a config digest"
    assert "{digest}" in src, "cache filename must interpolate the digest"
    # ...and load_inmet_with_cache must accept the config that drives it.
    for param in ("vars_dict", "target_var", "test_fraction"):
        assert param in src, f"load_inmet_with_cache must take {param!r}"


def test_xgboost_load_label_is_not_csv():
    """The cache holds parquet, not csv — the provenance label says so."""
    src = _code_sources("xgboost_temperature_forecast")
    assert "csv cache" not in src, "stale 'csv cache' label"
    assert '"cache data"' in src, "load_source label must be 'cache data'"


def test_xgboost_logs_reproduction_inputs():
    """The run record must carry every input needed to reproduce the run.

    The Model runs panel reads these from ``run.params`` to show a per-run
    inputs dialog and a copy-able config block.
    """
    src = _code_sources("xgboost_temperature_forecast")
    for key in (
        "station_id",
        "date_start",
        "date_end",
        "target_var",
        "test_fraction",
        "era5_land_vars",
    ):
        assert f'"{key}"' in src, f"log_model_run must record input {key!r}"
