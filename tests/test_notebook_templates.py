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


# --- "XGBoost with Optuna" template ---------------------------------------


def test_optuna_template_present_and_named():
    from era5_etl.notebooks.templates import list_templates

    by_id = {t["id"]: t for t in list_templates()}
    assert "xgboost_optuna_forecast" in by_id
    assert by_id["xgboost_optuna_forecast"]["name"] == "XGBoost with Optuna"


def test_optuna_template_logs_new_run_metrics():
    src = _code_sources("xgboost_optuna_forecast")
    for key in ("test_fraction", "n_train", "n_test", "num_days"):
        assert f'"{key}"' in src, f"template must log metric {key!r}"


def test_optuna_template_logs_reproduction_inputs():
    src = _code_sources("xgboost_optuna_forecast")
    for key in (
        "station_id",
        "date_start",
        "date_end",
        "target_var",
        "test_fraction",
        "era5_land_vars",
    ):
        assert f'"{key}"' in src, f"log_model_run must record input {key!r}"


def test_optuna_template_does_optuna_search():
    """The whole point: it must actually run an Optuna study."""
    src = _code_sources("xgboost_optuna_forecast")
    assert "import optuna" in src
    assert "optuna.create_study" in src
    assert "study.optimize" in src
    assert "N_TRIALS" in src
    # The run is tagged so the Model runs panel distinguishes it.
    assert '"xgboost_optuna"' in src


def test_optuna_template_detects_device():
    """A top cell must auto-detect GPU vs CPU and feed XGBoost via device=."""
    src = _code_sources("xgboost_optuna_forecast")
    assert "DEVICE" in src
    assert 'device="cuda"' in src
    assert "device=DEVICE" in src


def test_optuna_template_aligns_device_for_prediction():
    """A GPU-trained booster must predict on the data's device, so we don't
    emit XGBoost's 'mismatched devices' warning / pay a host->device copy.

    Regression guard for the predict_aligned helper (the fix XGBoost itself
    recommends: set the booster device before inplace_predict).
    """
    src = _code_sources("xgboost_optuna_forecast")
    assert "predict_aligned" in src
    assert 'set_param({"device": "cpu"})' in src
    # The helper is actually used for both validation and test prediction.
    assert "predict_aligned(model, _tv_val[feats])" in src
    assert "predict_aligned(final_model, test[best_feats])" in src


def test_optuna_template_builds_cyclical_features():
    src = _code_sources("xgboost_optuna_forecast")
    for feat in ("hora_sin", "hora_cos", "dia_ano_sin", "dia_ano_cos"):
        assert feat in src, f"cyclical feature {feat!r} must be built"


def test_optuna_template_builds_cutoff_offset_lags():
    """Lags keep short names but are offset by the D-6 cutoff (no leakage)."""
    src = _code_sources("xgboost_optuna_forecast")
    # The cutoff variable is named to make clear it applies to ERA5-LAND data.
    assert "ERA5_LAND_CUTOFF_HOURS" in src
    # The familiar lag naming the user asked for.
    assert "_lag_" in src
    # The shift is cutoff + lag, not just the raw lag.
    assert "cutoff + lag" in src


# --- INMET variable selector + pure-date column (both templates) ----------

ALL_TEMPLATES = ("xgboost_temperature_forecast", "xgboost_optuna_forecast")


def test_templates_have_inmet_vars_selector():
    """Both templates expose an ``inmet_vars`` dict (default: only ``temp_ar``)
    that controls which INMET columns are read from the view. ``date`` and
    ``hour_utc`` are JOIN keys, always read (never toggled)."""
    for tid in ALL_TEMPLATES:
        src = _code_sources(tid)
        assert "inmet_vars = {" in src, f"{tid}: missing inmet_vars dict"
        assert '"temp_ar": True' in src, f"{tid}: temp_ar must default True"
        # Every other INMET variable defaults to False.
        assert '"umidade_relativa": False' in src, tid
        assert '"vento_velocidade": False' in src, tid
        # JOIN keys are structural, not part of the toggle dict.
        assert "_INMET_KEY_COLS" in src, tid
        assert '"date", "hour_utc"' in src, tid
        # The selection drives the inmet SELECT (so extras stay out).
        assert "SELECT {inmet_select}" in src, tid
        assert "df = inmet_with_era5_land(station_id, start, end, vars_dict, inmet_vars_dict)" in src, tid


def test_templates_join_date_is_pure_date():
    """After the JOIN, the joined frame's 'date' is a pure date (no time);
    the hour lives in hour_utc."""
    for tid in ALL_TEMPLATES:
        src = _code_sources(tid)
        assert 'pd.to_datetime(out["date"]).dt.date' in src, (
            f"{tid}: joined 'date' must be converted to a pure date"
        )
