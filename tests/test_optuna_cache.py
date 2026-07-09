import numpy as np
import pandas as pd
import pytest
import optuna

from era5_etl.notebooks import optuna_cache as oc


def _df(n=24, target=0.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    return pd.DataFrame({"temp_ar": np.full(n, target, dtype=np.float64)}, index=idx)


def test_data_fingerprint_is_deterministic():
    assert oc.data_fingerprint(_df(), "temp_ar") == oc.data_fingerprint(_df(), "temp_ar")


def test_data_fingerprint_changes_with_values():
    a = oc.data_fingerprint(_df(target=0.0), "temp_ar")
    b = oc.data_fingerprint(_df(target=1.0), "temp_ar")
    assert a != b


def test_data_fingerprint_changes_with_length_and_span():
    base = oc.data_fingerprint(_df(n=24), "temp_ar")
    assert base != oc.data_fingerprint(_df(n=48), "temp_ar")


def test_config_fingerprint_stable_under_key_reordering():
    fp1 = oc.config_fingerprint({"a": 1, "b": [1, 2]}, "DATA")
    fp2 = oc.config_fingerprint({"b": [1, 2], "a": 1}, "DATA")
    assert fp1 == fp2


def test_config_fingerprint_changes_with_value_and_data():
    base = oc.config_fingerprint({"a": 1}, "DATA")
    assert base != oc.config_fingerprint({"a": 2}, "DATA")
    assert base != oc.config_fingerprint({"a": 1}, "OTHER")


def test_json_cache_roundtrip_and_missing(tmp_path):
    p = tmp_path / "x.json"
    assert oc.load_json_cache(p) is None          # missing
    oc.save_json_cache(p, {"k": [1, 2], "s": "v"})
    assert oc.load_json_cache(p) == {"k": [1, 2], "s": "v"}
    p.write_text("{not json", encoding="utf-8")    # corrupt
    assert oc.load_json_cache(p) is None


def _sampler():
    return optuna.samplers.TPESampler(seed=0)


def test_remaining_and_completed_trials(tmp_path):
    study = oc.open_cached_study(
        method="expanding", fingerprint="abc",
        db_path=tmp_path / "nb.db", sampler=_sampler(),
    )
    assert oc.completed_trials(study) == 0
    assert oc.remaining_trials(study, 5) == 5
    study.optimize(lambda t: (t.suggest_float("x", 0, 1) - 0.5) ** 2, n_trials=3)
    assert oc.completed_trials(study) == 3
    assert oc.remaining_trials(study, 5) == 2
    assert oc.remaining_trials(study, 2) == 0   # over budget clamps to 0


def test_open_cached_study_resumes_across_opens(tmp_path):
    db = tmp_path / "nb.db"
    s1 = oc.open_cached_study(method="m", fingerprint="fp",
                              db_path=db, sampler=_sampler())
    s1.optimize(lambda t: t.suggest_float("x", 0, 1), n_trials=4)
    s2 = oc.open_cached_study(method="m", fingerprint="fp",
                              db_path=db, sampler=_sampler())
    assert oc.completed_trials(s2) == 4          # second open sees first's trials
    s3 = oc.open_cached_study(method="m", fingerprint="fp", db_path=db,
                              sampler=_sampler(), reset=True)
    assert oc.completed_trials(s3) == 0          # reset discards them


def test_open_cached_study_separates_by_method_and_fingerprint(tmp_path):
    db = tmp_path / "nb.db"
    a = oc.open_cached_study(method="m", fingerprint="fp1", db_path=db, sampler=_sampler())
    a.optimize(lambda t: t.suggest_float("x", 0, 1), n_trials=2)
    b = oc.open_cached_study(method="m", fingerprint="fp2", db_path=db, sampler=_sampler())
    assert oc.completed_trials(b) == 0           # different fingerprint = different study


def _pruning_objective(trial):
    """Poda os trials impares; completa os pares."""
    x = trial.suggest_float("x", 0, 1)
    trial.report(x, step=0)
    if trial.number % 2 == 1:
        raise optuna.TrialPruned()
    return x


def test_finished_trials_counts_pruned(tmp_path):
    study = oc.open_cached_study(
        method="m", fingerprint="fp", db_path=tmp_path / "nb.db",
        sampler=_sampler(),
    )
    study.optimize(_pruning_objective, n_trials=6)
    assert oc.completed_trials(study) == 3        # so os pares
    assert oc.finished_trials(study) == 6         # COMPLETE + PRUNED


def test_remaining_trials_include_pruned(tmp_path):
    study = oc.open_cached_study(
        method="m", fingerprint="fp", db_path=tmp_path / "nb.db",
        sampler=_sampler(),
    )
    study.optimize(_pruning_objective, n_trials=6)
    # default (back-compat): orcamento em trials COMPLETE
    assert oc.remaining_trials(study, 5) == 2
    # com pruning ligado o orcamento conta trials TERMINADOS (senao a retomada
    # do cache re-roda indefinidamente estudos com muita poda)
    assert oc.remaining_trials(study, 5, include_pruned=True) == 0
    assert oc.remaining_trials(study, 10, include_pruned=True) == 4


def test_wilcoxon_pruner_prunes_paired_window_reports(tmp_path):
    """Pino do desenho dos templates: valores POR JANELA (passo = indice) +
    WilcoxonPruner (pareado vs o melhor trial) devem podar trials ruins mesmo
    com dificuldade variavel entre janelas — o cenario em que o MedianPruner
    ('best-so-far' vs mediana) nao poda nada."""
    import warnings

    import numpy as np

    base = np.array([2.45, 2.65, 2.60, 2.95, 3.00, 3.05])  # janela 0 facil
    rng = np.random.default_rng(0)

    def objective(trial):
        q = trial.suggest_float("q", 0.0, 1.0)
        vals = []
        for step, b in enumerate(base):
            v = float(b + q * 0.6 + rng.normal(0, 0.02))
            vals.append(v)
            trial.report(v, step=step)
            done = trial.study.get_trials(
                deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,))
            if len(done) >= 5 and trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(vals))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # WilcoxonPruner e experimental
        pruner = optuna.pruners.WilcoxonPruner(p_threshold=0.1, n_startup_steps=2)
    study = oc.open_cached_study(
        method="m", fingerprint="fp", db_path=tmp_path / "nb.db",
        sampler=optuna.samplers.TPESampler(seed=42), pruner=pruner,
    )
    study.optimize(objective, n_trials=30)
    states = [t.state for t in study.trials]
    n_pruned = sum(1 for s in states if s == optuna.trial.TrialState.PRUNED)
    assert n_pruned >= 5                       # poda de verdade
    assert oc.finished_trials(study) == 30     # podados contam no orcamento
    assert study.best_trial.state == optuna.trial.TrialState.COMPLETE


def test_open_cached_study_passes_pruner(tmp_path):
    pruner = optuna.pruners.MedianPruner(n_startup_trials=2, n_warmup_steps=1)
    study = oc.open_cached_study(
        method="m", fingerprint="fp", db_path=tmp_path / "nb.db",
        sampler=_sampler(), pruner=pruner,
    )
    assert study.pruner is pruner
    # default continua funcionando (pruner=None -> default do optuna, inerte
    # sem chamadas a trial.report)
    other = oc.open_cached_study(
        method="m2", fingerprint="fp", db_path=tmp_path / "nb.db",
        sampler=_sampler(),
    )
    other.optimize(lambda t: t.suggest_float("x", 0, 1), n_trials=1)
    assert oc.completed_trials(other) == 1
