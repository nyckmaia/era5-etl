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
    # SP and RJ are adjacent. With the strict "center inside polygon" rule
    # (no half-cell buffer) UF polygons are disjoint, so the union must
    # equal the sum — no shared points.
    sp = latlon_set("era5", ["SP"]).height
    rj = latlon_set("era5", ["RJ"]).height
    both = latlon_set("era5", ["SP", "RJ"]).height
    assert both == sp + rj
    # Result schema invariants are preserved.
    df = latlon_set("era5", ["SP", "RJ"])
    assert df.schema["latitude"] == pl.Float32
    assert df.schema["longitude"] == pl.Float32
    assert df.columns == ["latitude", "longitude"]


@pytest.mark.parametrize(
    ("dataset", "a", "b"),
    [
        ("era5", "SP", "MG"),
        ("era5", "SP", "RJ"),
        ("era5", "RS", "SC"),
        ("era5", "BA", "MG"),
        ("era5", "AM", "PA"),
        ("era5-land", "SP", "RJ"),
        ("era5-land", "RS", "SC"),
    ],
)
def test_adjacent_ufs_share_no_grid_points(dataset, a, b):
    # Each grid point must belong to at most one UF — this is the whole
    # point of removing the half-cell buffer. Adjacent UFs are the hardest
    # case.
    only_a = latlon_set(dataset, [a]).height
    only_b = latlon_set(dataset, [b]).height
    union = latlon_set(dataset, [a, b]).height
    assert union == only_a + only_b, (
        f"{dataset}: {a} and {b} share {only_a + only_b - union} grid point(s)"
    )


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
