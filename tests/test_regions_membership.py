"""Smoke tests for the bundled grid_membership parquet + runtime loader."""

from __future__ import annotations

import polars as pl
import pytest

from era5_etl.regions.membership import (
    _load_all,
    available_regions,
    latlon_set,
    validate_regions,
)


def test_loader_returns_float32_latlon():
    df = _load_all("era5")
    assert df.schema["latitude"] == pl.Float32
    assert df.schema["longitude"] == pl.Float32
    assert df.schema["region"] == pl.Utf8
    assert df.height > 0


def test_available_regions_includes_all_ufs_and_br():
    regions = available_regions("era5")
    # 26 states + DF + BR
    assert len(regions) == 28
    expected_ufs = {
        "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
        "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
        "RO", "RR", "RS", "SC", "SE", "SP", "TO",
    }
    assert set(regions) == expected_ufs | {"BR"}


def test_available_regions_same_for_both_datasets():
    assert available_regions("era5") == available_regions("era5-land")


def test_latlon_set_dedupes_overlapping_regions():
    # SP and RJ are adjacent; their unioned latlon_set must dedupe.
    sp = latlon_set("era5", ["SP"]).height
    rj = latlon_set("era5", ["RJ"]).height
    both = latlon_set("era5", ["SP", "RJ"]).height
    assert both <= sp + rj  # union must not exceed sum
    # Result schema invariants are preserved.
    df = latlon_set("era5", ["SP", "RJ"])
    assert df.schema["latitude"] == pl.Float32
    assert df.schema["longitude"] == pl.Float32
    assert df.columns == ["latitude", "longitude"]


def test_latlon_set_era5_land_is_denser_than_era5():
    # 0.1 deg vs 0.25 deg => ERA5-LAND should have ~6x more cells per UF.
    sp_era5 = latlon_set("era5", ["SP"]).height
    sp_land = latlon_set("era5-land", ["SP"]).height
    assert sp_land > sp_era5 * 3  # very conservative lower bound


def test_br_covers_more_cells_than_any_single_uf():
    counts = {r: latlon_set("era5", [r]).height for r in available_regions("era5")}
    br = counts.pop("BR")
    assert br > max(counts.values())


def test_unknown_dataset_raises():
    with pytest.raises(ValueError, match="Unknown dataset"):
        _load_all("inmet")  # not a gridded dataset


def test_unknown_region_raises():
    with pytest.raises(ValueError, match="Unknown region"):
        validate_regions("era5", ["XX"])
    with pytest.raises(ValueError, match="Unknown region"):
        latlon_set("era5", ["SP", "XX"])


def test_empty_regions_list_raises():
    with pytest.raises(ValueError, match="at least one"):
        latlon_set("era5", [])
