"""Visual-builder spec -> SQL generation (pure, no DB)."""

import pytest

from era5_etl.web.sql_builder import BuildSpec, JoinPair, SourceSel, build_view_sql


def test_single_source_projection():
    spec = BuildSpec(
        name="my_v",
        join_type="INNER",
        sources=[SourceSel(view="inmet", alias="i", columns=["date", "value"])],
        joins=[],
    )
    sql = build_view_sql(spec)
    assert sql.startswith('CREATE OR REPLACE VIEW "my_v" AS')
    assert 'i."date" AS "i_date"' in sql
    assert "FROM inmet AS i" in sql


def test_epsilon_join_two_sources():
    spec = BuildSpec(
        name="cmp",
        join_type="LEFT",
        sources=[
            SourceSel(view="inmet", alias="i", columns=["value"]),
            SourceSel(view="era5", alias="e", columns=["value"]),
        ],
        joins=[
            JoinPair(left="i.date", right="e.date", approx=False),
            JoinPair(
                left="i.latitude", right="e.latitude", approx=True, epsilon=1e-4
            ),
        ],
    )
    sql = build_view_sql(spec)
    assert "LEFT JOIN era5 AS e ON" in sql
    assert 'e."date" = i."date"' in sql
    assert 'abs(e."latitude" - i."latitude") < 0.0001' in sql
    assert 'e."value" AS "e_value"' in sql


def test_unsafe_identifier_rejected():
    spec = BuildSpec(
        name="bad",
        join_type="INNER",
        sources=[SourceSel(view="inmet; DROP", alias="i", columns=["a"])],
        joins=[],
    )
    with pytest.raises(ValueError):
        build_view_sql(spec)


def test_bad_join_type_rejected():
    spec = BuildSpec(
        name="v",
        join_type="CROSS",
        sources=[SourceSel(view="inmet", alias="i", columns=["a"])],
        joins=[],
    )
    with pytest.raises(ValueError):
        build_view_sql(spec)
