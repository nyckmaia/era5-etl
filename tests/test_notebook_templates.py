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


def test_xgboost_optuna_windows_template():
    from era5_etl.notebooks.templates import list_templates, load_template

    ids = {t["id"]: t for t in list_templates()}
    assert "xgboost_optuna_windows" in ids
    assert ids["xgboost_optuna_windows"]["name"] == "XGBoost With Optuna and Windows"

    tpl = load_template("xgboost_optuna_windows")
    sources = [c["source"] for c in tpl["cells"]]
    assert len(tpl["cells"]) == 22
    joined = "\n".join(sources)
    # MLflow replaces the manual panel logger.
    assert "log_model_run" not in joined
    assert "mlflow.set_experiment" in joined
    assert "REPEAT_RUN_ID" in joined
    # Backtesting managed by Optuna over the tested window generators.
    assert "from era5_etl.notebooks.backtest import" in joined
    assert "EXPANDING_INITIAL_TRAIN_DAYS" in joined
    assert "SLIDING_TRAIN_DAYS" in joined
    # The removed search dimension must not resurface.
    assert "train_window_days" not in joined


def test_windows_template_has_cache_and_sweep_config():
    import json, pathlib
    p = pathlib.Path("src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json")
    src = "\n".join(c["source"] for c in json.loads(p.read_text(encoding="utf-8"))["cells"]
                    if c["type"] == "code")
    for token in ("USE_OPTUNA_CACHE", "OPTUNA_CACHE_RESET", "RUN_WINDOW_SWEEP",
                  "SWEEP_TRAIN_MONTHS", "SWEEP_SLIDE_STEPS_DAYS",
                  "SWEEP_TEST_DAYS", "SWEEP_MAX_WINDOWS"):
        assert token in src, token


# --- "XGBoost - Target IBUTG" template -------------------------------------


def test_xgboost_target_ibutg_template():
    from era5_etl.notebooks.templates import list_templates, load_template

    ids = {t["id"]: t for t in list_templates()}
    assert "xgboost_target_ibutg" in ids
    assert ids["xgboost_target_ibutg"]["name"] == "XGBoost - Target IBUTG"

    tpl = load_template("xgboost_target_ibutg")
    assert len(tpl["cells"]) == 27

    src = _code_sources("xgboost_target_ibutg")
    for token in (
        '"inmet_ibutg"',            # alvo derivado
        "WORKING_HOUR_START",
        "WORKING_HOUR_STOP",
        "INMET_CUTOFF_HOURS",
        "rmse_working_hours",
        "mae_working_hours",        # metricas WH extras (Melhoria 04)
        "r2_working_hours",
        "fig_metrics_cmp",          # comparativo 24h vs WH (Melhoria 04)
        "PERM_WH_REPEATS",          # importancia por permutacao nas WH
        "TEST_FRACTION = 0.005",    # Melhoria 01 (rodada 2)
        '"wind_speed_10m": True',   # Melhoria 02 (default de features)
        '"wind_u_10m": False',
        "MONITOR_EVERY",            # monitor de convergencia
        "OPTUNA_STAGNATION_PATIENCE",
        "update_display(",          # grafico Optuna ao vivo in-place (rodada 3)
        "optuna-monitor-",          # display_id do grafico ao vivo
        "plot_param_importances",   # celula de diagnostico do espaco de busca
        "plot_parallel_coordinate",
        "N_JOBS = max(",            # deixa 1 nucleo livre p/ a MLflow UI
        'pd.DataFrame({"coluna": training_cols})',  # tabela sem indice redundante
        "derived_vars",
        "FEATURE_GROUPS",
        "0.57175",                  # coeficiente Tn (pyinmet)
        "1.374385",                 # coeficiente Tg (pyinmet)
        "0.7 * tn + 0.2 * tg",      # IBUTG (pyinmet)
        "273.15",                   # Kelvin -> Celsius
        "17.625",                   # Magnus (umidade relativa ERA5-LAND)
        "mlflow.set_experiment",
        "from era5_etl.notebooks.backtest import",
        "REPEAT_RUN_ID",
        "bilinear_weights(",        # macro builtin exigida pelo TODO (Task 0)
        'STATION_ID    = "A701"',   # default de estacao
        "N_SEEDS_PER_WINDOW = 3",   # barras de erro no estudo de tamanho
        "anchored_end_windows",     # estudo de tamanho de treino (fim fixo)
        "RUN_TRAIN_SIZE_STUDY",
        "STUDY_TRAIN_MONTHS",
        "plot_train_size_study",
    ):
        assert token in src, f"template must contain {token!r}"
    assert "log_model_run" not in src  # MLflow-only, como o template base
    # Rodada 3 / M02: o monitor MLflow ao vivo por-trial foi REMOVIDO
    # (o grafico ao vivo no proprio notebook o substitui) para nao contender
    # com a MLflow UI durante a busca.
    assert "MONITOR_MLFLOW_LIVE" not in src
    assert "_MONITOR_RUN_ID" not in src
    # Sliding foi removido deste template (so expanding CV + estudo fim-fixo).
    assert "sliding" not in src.lower()
    assert "SLIDING_TRAIN_DAYS" not in src
    assert "SHARE_HYPERPARAMS_ACROSS_METHODS" not in src


def test_ibutg_template_derivation_between_load_and_validation():
    """A celula de derivacao roda DEPOIS do load e ANTES da validacao
    (a validacao exige o alvo derivado inmet_ibutg nao-nulo)."""
    from era5_etl.notebooks.templates import load_template

    srcs = [c["source"] for c in load_template("xgboost_target_ibutg")["cells"]
            if c["type"] == "code"]
    i_load = next(i for i, s in enumerate(srcs) if "load_inmet_with_cache(" in s)
    i_der = next(i for i, s in enumerate(srcs) if "def calc_ibutg" in s)
    i_val = next(i for i, s in enumerate(srcs) if "VALIDACAO DE DADOS FALHOU" in s)
    assert i_load < i_der < i_val


def test_ibutg_derivation_cell_formulas():
    """Executa a celula de derivacao numa DataFrame sintetica e confere os
    valores contra a cadeia de formulas do pyinmet (sem arredondamento)."""
    import pandas as pd

    from era5_etl.notebooks.templates import load_template

    src = next(
        c["source"] for c in load_template("xgboost_target_ibutg")["cells"]
        if c["type"] == "code" and "def calc_ibutg" in c["source"]
    )
    df = pd.DataFrame({
        "era5_land_temperature_2m_bilinear": [303.15],  # 30 degC em Kelvin
        "era5_land_dewpoint_2m_bilinear": [293.15],     # 20 degC em Kelvin
        "era5_land_wind_u_10m_bilinear": [3.0],
        "era5_land_wind_v_10m_bilinear": [0.0],
        "temp_ar": [30.0],
        "temp_orvalho": [20.0],
        "umidade_relativa": [55.0],
        "vento_velocidade": [3.0],
    })
    ns = {
        "df": df,
        "era5_land_vars": {"temperature_2m": True},
        "inmet_vars": {"temp_ar": False},
        "derived_vars": {"era5_land_ibutg": True, "inmet_tn": False},
        "ERA5_LAND_CUTOFF_HOURS": 168,
        "INMET_CUTOFF_HOURS": 24,
    }
    exec(src, ns)  # fonte controlada: e o nosso proprio template
    out = ns["df"]

    # Referencia: formulas pyinmet sem round().
    vel15 = 3.0 * (1.5 / 10.0) ** 0.21
    tn = 0.57175 * 20 + 0.19447 * 30 - 0.26523 * vel15 - 0.05134 * 55 + 10.44966
    tg = 1.374385 * 30 + 0.083627 * 55 - 1.021632 * vel15
    ibutg = 0.7 * tn + 0.2 * tg + 0.1 * 30

    assert abs(out["inmet_tn"].iloc[0] - tn) < 1e-9
    assert abs(out["inmet_tg"].iloc[0] - tg) < 1e-9
    assert abs(out["inmet_ibutg"].iloc[0] - ibutg) < 1e-9
    # ERA5-LAND: mesma entrada fisica; UR via Magnus ~55.08% -> IBUTG proximo.
    assert abs(out["era5_land_ibutg"].iloc[0] - ibutg) < 0.05

    # FEATURE_GROUPS montado com origem e cutoff certos.
    groups = {base: (srccol, cut) for srccol, base, cut in ns["FEATURE_GROUPS"]}
    assert groups["temperature_2m"] == ("era5_land_temperature_2m_bilinear", 168)
    assert groups["era5_land_ibutg"] == ("era5_land_ibutg", 168)
