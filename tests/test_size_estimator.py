"""Tests for CDS download size estimation and geographic area splitting."""

import math

import pytest

from era5_etl.download.size_estimator import (
    BYTES_PER_VALUE,
    DEFAULT_MAX_REQUEST_FIELDS,
    ERA5_LAND_RESOLUTION,
    ERA5_RESOLUTION,
    AreaSplit,
    calculate_splits_needed,
    estimate_grid_points,
    estimate_request_size,
    request_fields,
    split_area,
)


class TestRequestFields:
    """Tests for the CDS fields helper (variables × hours × days)."""

    def test_arithmetic_basic(self):
        assert request_fields(4, 24, 31) == 4 * 24 * 31  # 2976

    def test_zero_variables_yields_zero(self):
        assert request_fields(0, 24, 31) == 0

    def test_zero_days_yields_zero(self):
        assert request_fields(4, 24, 0) == 0

    def test_independent_of_area(self):
        # ``request_fields`` takes no area argument by design — fields
        # depend only on variable/hour/day counts.
        assert request_fields(2, 12, 10) == 240

    def test_default_limit_constant(self):
        # The CDS documented item cap. The byte/value ceiling is the
        # binding constraint for realistic requests; this is the backstop.
        assert DEFAULT_MAX_REQUEST_FIELDS == 12_000


class TestSizeEstimateFieldsCount:
    """Tests for SizeEstimate.fields_count + exceeds_field_limit."""

    def test_fields_count_populated(self):
        est = estimate_request_size(
            num_variables=4, num_hours=24, num_days=31,
            area=[6.0, -74.0, -34.0, -34.0], dataset="era5-land",
        )
        assert est.fields_count == 2976

    def test_field_limit_breach_flips_exceeds(self):
        est = estimate_request_size(
            num_variables=50, num_hours=24, num_days=31,
            area=[0.0, 0.0, 0.0, 0.0],  # single point → bytes irrelevant
            dataset="era5",
            max_bytes=10**12,            # effectively unlimited
            max_fields=10_000,
        )
        assert est.fields_count == 50 * 24 * 31
        assert est.exceeds_field_limit is True
        assert est.exceeds_bytes_limit is False
        assert est.exceeds_limit is True

    def test_bytes_limit_only(self):
        est = estimate_request_size(
            num_variables=2, num_hours=4, num_days=2,
            area=[6.0, -74.0, -34.0, -34.0],
            dataset="era5-land",
            max_bytes=1_000,             # silly-low byte ceiling
            max_fields=10_000,
        )
        assert est.exceeds_bytes_limit is True
        assert est.exceeds_field_limit is False
        assert est.exceeds_limit is True


class TestEstimateGridPoints:
    """Tests for estimate_grid_points()."""

    def test_small_area_era5(self):
        # 1x1 degree area at 0.25 resolution = 5x5 = 25 points
        area = [1.0, 0.0, 0.0, 1.0]  # N, W, S, E
        points = estimate_grid_points(area, ERA5_RESOLUTION)
        assert points == 25  # (1/0.25 + 1) * (1/0.25 + 1) = 5*5

    def test_small_area_era5_land(self):
        # 1x1 degree area at 0.1 resolution = 11x11 = 121 points
        area = [1.0, 0.0, 0.0, 1.0]
        points = estimate_grid_points(area, ERA5_LAND_RESOLUTION)
        assert points == 121  # (1/0.1 + 1) * (1/0.1 + 1) = 11*11

    def test_brazil_bbox_era5_land(self):
        area = [6.0, -74.0, -34.0, -34.0]  # Brazil
        points = estimate_grid_points(area, ERA5_LAND_RESOLUTION)
        # lat: 40deg/0.1 + 1 = 401, lon: 40deg/0.1 + 1 = 401
        assert points == 401 * 401

    def test_minimum_one_point(self):
        area = [0.0, 0.0, 0.0, 0.0]  # Point location
        points = estimate_grid_points(area, ERA5_RESOLUTION)
        assert points >= 1


class TestEstimateRequestSize:
    """Tests for estimate_request_size()."""

    def test_small_request_under_limit(self):
        estimate = estimate_request_size(
            num_variables=2,
            num_hours=4,
            num_days=5,
            area=[1.0, 0.0, 0.0, 1.0],
            dataset="era5",
        )
        assert not estimate.exceeds_limit
        assert estimate.estimated_bytes > 0
        assert estimate.num_grid_points == 25

    def test_large_request_exceeds_limit(self):
        estimate = estimate_request_size(
            num_variables=10,
            num_hours=24,
            num_days=31,
            area=[6.0, -74.0, -34.0, -34.0],  # Brazil
            dataset="era5-land",
            max_bytes=100 * 1024 * 1024,  # 100 MB limit
        )
        assert estimate.exceeds_limit
        assert estimate.estimated_mb > 100

    def test_era5_land_has_more_grid_points(self):
        area = [1.0, 0.0, 0.0, 1.0]
        est_era5 = estimate_request_size(
            num_variables=1, num_hours=1, num_days=1,
            area=area, dataset="era5",
        )
        est_land = estimate_request_size(
            num_variables=1, num_hours=1, num_days=1,
            area=area, dataset="era5-land",
        )
        assert est_land.num_grid_points > est_era5.num_grid_points

    def test_estimated_bytes_calculation(self):
        estimate = estimate_request_size(
            num_variables=2, num_hours=3, num_days=5,
            area=[1.0, 0.0, 0.0, 1.0], dataset="era5",
        )
        expected = 2 * 3 * 5 * 25 * BYTES_PER_VALUE
        assert estimate.estimated_bytes == expected

    def test_properties(self):
        estimate = estimate_request_size(
            num_variables=1, num_hours=1, num_days=1,
            area=[1.0, 0.0, 0.0, 1.0], dataset="era5",
        )
        assert estimate.estimated_mb == estimate.estimated_bytes / (1024 * 1024)
        assert estimate.limit_mb == estimate.limit_bytes / (1024 * 1024)


class TestSplitArea:
    """Tests for split_area()."""

    def test_split_into_two(self):
        area = [10.0, 0.0, 0.0, 10.0]
        splits = split_area(area, 2)
        assert len(splits) == 2

    def test_split_into_four(self):
        area = [10.0, 0.0, 0.0, 10.0]
        splits = split_area(area, 4)
        assert len(splits) == 4

    def test_splits_cover_original_area(self):
        area = [10.0, -5.0, -10.0, 5.0]
        splits = split_area(area, 4)

        # All splits should be within original bounds
        for s in splits:
            assert s.north <= area[0] + 0.001
            assert s.south >= area[2] - 0.001
            assert s.west >= area[1] - 0.001
            assert s.east <= area[3] + 0.001

        # Top-left corner should match
        norths = [s.north for s in splits]
        assert max(norths) == pytest.approx(area[0], abs=0.001)

        # Bottom-right corner should match
        souths = [s.south for s in splits]
        easts = [s.east for s in splits]
        assert min(souths) == pytest.approx(area[2], abs=0.001)
        assert max(easts) == pytest.approx(area[3], abs=0.001)

    def test_as_list(self):
        split = AreaSplit(north=10.0, west=-5.0, south=0.0, east=5.0)
        assert split.as_list() == [10.0, -5.0, 0.0, 5.0]

    def test_no_gaps_between_splits(self):
        area = [10.0, 0.0, 0.0, 10.0]
        splits = split_area(area, 4)

        # Total area of splits should equal original area
        total_split_area = sum(
            abs(s.north - s.south) * abs(s.east - s.west) for s in splits
        )
        original_area = abs(area[0] - area[2]) * abs(area[3] - area[1])
        assert total_split_area == pytest.approx(original_area, rel=1e-6)


class TestCalculateSplitsNeeded:
    """Tests for calculate_splits_needed()."""

    def test_no_split_needed(self):
        estimate = estimate_request_size(
            num_variables=1, num_hours=1, num_days=1,
            area=[1.0, 0.0, 0.0, 1.0], dataset="era5",
        )
        assert calculate_splits_needed(estimate) == 1

    def test_split_needed(self):
        estimate = estimate_request_size(
            num_variables=10, num_hours=24, num_days=31,
            area=[6.0, -74.0, -34.0, -34.0],
            dataset="era5-land",
            max_bytes=100 * 1024 * 1024,
        )
        splits = calculate_splits_needed(estimate)
        assert splits >= 2

    def test_conservative_margin(self):
        # With 20% safety margin, the split count should be higher than the raw ratio
        estimate = estimate_request_size(
            num_variables=10, num_hours=24, num_days=31,
            area=[6.0, -74.0, -34.0, -34.0],
            dataset="era5-land",
            max_bytes=100 * 1024 * 1024,
        )
        raw_ratio = estimate.estimated_bytes / estimate.limit_bytes
        splits = calculate_splits_needed(estimate)
        assert splits >= math.ceil(raw_ratio)
