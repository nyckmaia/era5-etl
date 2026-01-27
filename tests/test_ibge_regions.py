"""Tests for IBGE region lookup."""

import pytest
import polars as pl

from era5_etl.utils.ibge_regions import (
    RegionType,
    list_regions,
    load_region_data,
    lookup_region_bbox,
)


class TestLoadRegionData:
    """Tests for loading IBGE region CSV files."""

    def test_load_municipio(self):
        df = load_region_data(RegionType.MUNICIPIO)
        assert isinstance(df, pl.DataFrame)
        assert len(df) > 0
        assert "municipio" in df.columns
        assert "north" in df.columns
        assert "south" in df.columns

    def test_load_uf(self):
        df = load_region_data(RegionType.UF)
        assert isinstance(df, pl.DataFrame)
        assert len(df) > 0
        assert "uf" in df.columns

    def test_load_rg_imediata(self):
        df = load_region_data(RegionType.RG_IMEDIATA)
        assert isinstance(df, pl.DataFrame)
        assert len(df) > 0
        assert "rg_imediata" in df.columns

    def test_load_pais(self):
        df = load_region_data(RegionType.PAIS)
        assert isinstance(df, pl.DataFrame)
        assert len(df) > 0


class TestLookupRegionBbox:
    """Tests for region bounding box lookup."""

    def test_lookup_municipio(self):
        bbox = lookup_region_bbox(RegionType.MUNICIPIO, "Sorriso", uf="MT")
        assert len(bbox) == 4
        north, west, south, east = bbox
        assert north > south
        assert east > west

    def test_lookup_uf(self):
        bbox = lookup_region_bbox(RegionType.UF, "MT")
        assert len(bbox) == 4
        north, west, south, east = bbox
        assert north > south

    def test_lookup_case_insensitive(self):
        bbox1 = lookup_region_bbox(RegionType.UF, "mt")
        bbox2 = lookup_region_bbox(RegionType.UF, "MT")
        assert bbox1 == bbox2

    def test_lookup_not_found(self):
        with pytest.raises(ValueError, match="not found"):
            lookup_region_bbox(RegionType.UF, "XX")

    def test_lookup_pais(self):
        bbox = lookup_region_bbox(RegionType.PAIS, "Brasil")
        assert len(bbox) == 4


class TestListRegions:
    """Tests for listing regions."""

    def test_list_uf(self):
        df = list_regions(RegionType.UF)
        assert isinstance(df, pl.DataFrame)
        assert len(df) > 0
