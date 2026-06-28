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
