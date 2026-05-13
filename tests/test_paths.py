"""Tests for the centralized storage path helpers."""

from pathlib import Path

import pytest

from era5_etl.storage.paths import (
    NETCDF_TMP_DIRNAME,
    STORAGE_ROOT_DIRNAME,
    ensure_dataset_dirs,
    resolve_base_dir,
    resolve_dataset_dir,
    resolve_duckdb_path,
    resolve_manifest_path,
    resolve_netcdf_temp_dir,
    resolve_storage_root,
)


def test_resolve_base_dir_is_absolute(tmp_path: Path):
    base = resolve_base_dir(tmp_path)
    assert base.is_absolute()


def test_storage_root_appends_climate_data_store_db(tmp_path: Path):
    root = resolve_storage_root(tmp_path)
    assert root.name == STORAGE_ROOT_DIRNAME
    assert root.parent == tmp_path.resolve()


def test_storage_root_idempotent_when_pointing_at_root(tmp_path: Path):
    nested = tmp_path / STORAGE_ROOT_DIRNAME
    nested.mkdir()
    root = resolve_storage_root(nested)
    assert root == nested.resolve()


def test_dataset_dir_for_era5(tmp_path: Path):
    p = resolve_dataset_dir(tmp_path, "era5")
    assert p == tmp_path.resolve() / STORAGE_ROOT_DIRNAME / "era5"


def test_dataset_dir_for_era5_land_preserves_hyphen(tmp_path: Path):
    p = resolve_dataset_dir(tmp_path, "era5-land")
    assert p == tmp_path.resolve() / STORAGE_ROOT_DIRNAME / "era5-land"
    # No silent "era5land" anywhere
    assert "era5land" not in str(p)


def test_manifest_path(tmp_path: Path):
    p = resolve_manifest_path(tmp_path, "era5")
    assert p.name == "_manifest.json"
    assert p.parent == resolve_dataset_dir(tmp_path, "era5")


def test_duckdb_path_uses_dataset_filename(tmp_path: Path):
    p = resolve_duckdb_path(tmp_path, "era5-land")
    assert p.name == "era5-land.duckdb"


def test_netcdf_temp_dir(tmp_path: Path):
    p = resolve_netcdf_temp_dir(tmp_path, "era5")
    assert p == tmp_path.resolve() / NETCDF_TMP_DIRNAME / "era5"


def test_ensure_dataset_dirs_creates_both(tmp_path: Path):
    dataset_dir, tmp_dir = ensure_dataset_dirs(tmp_path, "era5-land")
    assert dataset_dir.exists() and dataset_dir.is_dir()
    assert tmp_dir.exists() and tmp_dir.is_dir()


@pytest.mark.parametrize("bad", ["", "../escape", "evil/path", "evil\\path"])
def test_invalid_dataset_name_rejected(tmp_path: Path, bad: str):
    with pytest.raises(ValueError):
        resolve_dataset_dir(tmp_path, bad)
