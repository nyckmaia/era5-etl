"""Tests for storage components."""

from datetime import date
from pathlib import Path

import polars as pl

from era5_etl.config import DatabaseConfig
from era5_etl.storage.duckdb_manager import DuckDBManager
from era5_etl.storage.parquet_manager import ParquetManager, merge_into_partitioned_parquet

# -- ParquetManager tests --


def test_parquet_manager_initialization(tmp_path: Path):
    """Test ParquetManager initialization."""
    manager = ParquetManager(tmp_path, "era5-land")

    # Dataset name is preserved as-is (with hyphen)
    assert manager.dataset == "era5-land"
    assert manager.parquet_dir.exists()
    # Lives under the canonical storage root
    assert "climate_data_store_db" in str(manager.parquet_dir)
    assert manager.parquet_dir.name == "era5-land"


def test_parquet_manager_manifest_tracking(tmp_path: Path):
    """Test ParquetManager manifest tracking."""
    manager = ParquetManager(tmp_path, "era5-land")

    assert len(manager.get_processed_files()) == 0

    manager.mark_processed("file1.nc")
    manager.mark_processed("file2.nc")

    processed = manager.get_processed_files()
    assert len(processed) == 2
    assert "file1.nc" in processed
    assert "file2.nc" in processed


def test_parquet_manager_manifest_idempotent(tmp_path: Path):
    """Test marking same file twice doesn't duplicate."""
    manager = ParquetManager(tmp_path, "era5-land")

    manager.mark_processed("file1.nc")
    manager.mark_processed("file1.nc")

    assert len(manager.get_processed_files()) == 1


def test_parquet_manager_remove_processed(tmp_path: Path):
    """Test removing a file from processed list."""
    manager = ParquetManager(tmp_path, "era5-land")

    manager.mark_processed("file1.nc")
    manager.mark_processed("file2.nc")
    manager.remove_processed("file1.nc")

    processed = manager.get_processed_files()
    assert len(processed) == 1
    assert "file2.nc" in processed


def test_parquet_manager_clear_manifest(tmp_path: Path):
    """Test clearing the manifest."""
    manager = ParquetManager(tmp_path, "era5-land")

    manager.mark_processed("file1.nc")
    manager.mark_processed("file2.nc")
    manager.clear_manifest()

    assert len(manager.get_processed_files()) == 0


def test_parquet_manager_glob_pattern(tmp_path: Path):
    """Test glob pattern generation."""
    manager = ParquetManager(tmp_path, "era5-land")

    pattern = manager.get_glob_pattern()
    assert pattern.endswith("*.parquet")
    assert "**" in pattern


def test_parquet_manager_storage_stats_empty(tmp_path: Path):
    """Test storage stats with no files."""
    manager = ParquetManager(tmp_path, "era5-land")

    stats = manager.get_storage_stats()
    assert stats.total_files == 0
    assert stats.total_size_bytes == 0


def test_parquet_manager_storage_stats_with_files(tmp_path: Path):
    """Test storage stats with Parquet files."""
    manager = ParquetManager(tmp_path, "era5-land")

    # Create fake Parquet files in Hive partitions
    partition_dir = manager.parquet_dir / "date=2020-01-15"
    partition_dir.mkdir(parents=True)
    df = pl.DataFrame({"a": [1, 2, 3]})
    df.write_parquet(partition_dir / "data.parquet")

    stats = manager.get_storage_stats()
    assert stats.total_files == 1
    assert stats.total_size_bytes > 0


def test_parquet_manager_list_files(tmp_path: Path):
    """Test listing Parquet files."""
    manager = ParquetManager(tmp_path, "era5-land")

    assert manager.list_parquet_files() == []

    # Create a Parquet file
    df = pl.DataFrame({"a": [1]})
    df.write_parquet(manager.parquet_dir / "test.parquet")

    files = manager.list_parquet_files()
    assert len(files) == 1


def test_parquet_manager_exists(tmp_path: Path):
    """Test exists() method."""
    manager = ParquetManager(tmp_path, "era5-land")

    assert manager.exists() is False

    df = pl.DataFrame({"a": [1]})
    df.write_parquet(manager.parquet_dir / "test.parquet")

    assert manager.exists() is True


# -- ParquetManager.write_dataframe / merge_into_partitioned_parquet --


def _sample_grid_df(
    *,
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
    date_str: str = "2024-01-01",
    hour: int = 12,
    var_name: str = "t2m",
    var_value: float = 273.15,
    step: float = 0.1,
) -> pl.DataFrame:
    """Build a synthetic grid DataFrame for write tests."""
    lats: list[float] = []
    lons: list[float] = []
    lat = lat_range[0]
    while lat <= lat_range[1] + 1e-9:
        lon = lon_range[0]
        while lon <= lon_range[1] + 1e-9:
            lats.append(round(lat, 3))
            lons.append(round(lon, 3))
            lon += step
        lat += step
    return pl.DataFrame({
        "latitude": lats,
        "longitude": lons,
        "date": [date_str] * len(lats),
        "hour_utc": [hour] * len(lats),
        var_name: [var_value] * len(lats),
    })


def test_write_then_read_back(tmp_path: Path):
    """Sanity: write a batch and read it back via ParquetManager glob."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5))

    manager.write_dataframe(df)

    files = manager.list_parquet_files()
    assert len(files) == 1
    readback = pl.read_parquet(files[0])
    assert len(readback) == len(df)


def test_overlap_does_not_duplicate(tmp_path: Path):
    """Two writes covering an overlapping region collapse to no duplicates."""
    manager = ParquetManager(tmp_path, "era5-land")

    # Batch A: -22..-21.5 N, -44..-43.5 E (small SP-ish square).
    a = _sample_grid_df(lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5), var_value=300.0)
    # Batch B: -21.7..-21.2 N, -43.7..-43.2 E (overlaps A on -21.7..-21.5 N, -43.7..-43.5 E).
    b = _sample_grid_df(lat_range=(-21.7, -21.2), lon_range=(-43.7, -43.2), var_value=310.0)

    manager.write_dataframe(a)
    manager.write_dataframe(b)

    files = manager.list_parquet_files()
    # The partition should now contain a single merged file (old file got deleted).
    assert len(files) == 1
    final = pl.read_parquet(files[0])

    # Every (latitude, longitude, hour_utc) must be unique.
    keys = final.select(["latitude", "longitude", "hour_utc"])
    assert len(keys) == len(keys.unique())

    # Row count = |union(A, B)| (no dup) >= max(|A|, |B|) and < |A| + |B|.
    assert len(final) < len(a) + len(b)
    assert len(final) >= max(len(a), len(b))


def test_overlap_new_value_wins(tmp_path: Path):
    """For conflicting (lat, lon, hour_utc), the second write's value wins."""
    manager = ParquetManager(tmp_path, "era5-land")

    a = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), var_value=300.0)
    b = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), var_value=310.0)

    manager.write_dataframe(a)
    manager.write_dataframe(b)

    final = pl.read_parquet(manager.list_parquet_files()[0])
    assert (final["t2m"] == 310.0).all()


def test_variable_disjoint_columns_merge(tmp_path: Path):
    """Two writes with disjoint variable columns produce rows with both columns filled."""
    manager = ParquetManager(tmp_path, "era5-land")

    a = _sample_grid_df(
        lat_range=(-22.0, -21.9),
        lon_range=(-44.0, -43.9),
        var_name="t2m",
        var_value=300.0,
    )
    b = _sample_grid_df(
        lat_range=(-22.0, -21.9),
        lon_range=(-44.0, -43.9),
        var_name="tp",
        var_value=0.0035,
    )

    manager.write_dataframe(a)
    manager.write_dataframe(b)

    final = pl.read_parquet(manager.list_parquet_files()[0])
    assert "t2m" in final.columns and "tp" in final.columns
    assert final["t2m"].null_count() == 0
    assert final["tp"].null_count() == 0


def test_write_creates_partition_directory(tmp_path: Path):
    """Partition directories follow the date=YYYY-MM-DD naming."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9))
    manager.write_dataframe(df)
    expected = manager.parquet_dir / "date=2024-01-01"
    assert expected.exists() and expected.is_dir()


def test_write_handles_date_typed_column(tmp_path: Path):
    """A Polars Date column should be cast to string for partition naming."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9))
    df = df.with_columns(pl.col("date").str.to_date().alias("date"))
    manager.write_dataframe(df)
    assert (manager.parquet_dir / "date=2024-01-01").exists()


def test_dedup_existing_partitions(tmp_path: Path):
    """dedup_existing_partitions collapses pre-existing duplicate rows."""
    manager = ParquetManager(tmp_path, "era5-land")
    partition_dir = manager.parquet_dir / "date=2024-01-01"
    partition_dir.mkdir(parents=True)

    base = _sample_grid_df(
        lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), var_value=300.0
    ).drop("date")
    # Simulate two old-style writes co-existing in the same partition (duplicates).
    base.write_parquet(partition_dir / "part-a.parquet")
    base.with_columns(pl.col("t2m") * 1.05).write_parquet(partition_dir / "part-b.parquet")

    stats = manager.dedup_existing_partitions()
    assert stats["partitions_processed"] == 1
    assert stats["rows_after"] == len(base)
    assert stats["rows_after"] < stats["rows_before"]

    files = sorted(partition_dir.glob("*.parquet"))
    assert len(files) == 1


def test_merge_into_partitioned_parquet_module_function(tmp_path: Path):
    """The module-level helper works without a ParquetManager."""
    parquet_dir = tmp_path / "demo_dataset"
    df = _sample_grid_df(lat_range=(0.0, 0.2), lon_range=(0.0, 0.2))
    merge_into_partitioned_parquet(df, parquet_dir)
    assert (parquet_dir / "date=2024-01-01").exists()


# -- semantic filename + sort (plan v0.5.0) ---------------------------------


def test_filename_pattern_dataset_date_part(tmp_path: Path):
    """The written file must follow ``<dataset>_<YYYY-MM-DD>_part-001.parquet``."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9))
    manager.write_dataframe(df)

    files = list((manager.parquet_dir / "date=2024-01-01").glob("*.parquet"))
    assert len(files) == 1
    assert files[0].name == "era5-land_2024-01-01_part-001.parquet"


def test_filename_pattern_for_era5(tmp_path: Path):
    """Dataset prefix must reflect the parquet dir name -- era5 (no hyphen)."""
    manager = ParquetManager(tmp_path, "era5")
    df = _sample_grid_df(lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9))
    manager.write_dataframe(df)
    files = list((manager.parquet_dir / "date=2024-01-01").glob("*.parquet"))
    assert files[0].name == "era5_2024-01-01_part-001.parquet"


def test_sort_inside_file(tmp_path: Path):
    """Rows inside the file must be sorted by (latitude, longitude, hour_utc)."""
    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(
        lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5), hour=0
    )
    # Inject a second hour to verify hour_utc sort kicks in at the tie-break level.
    df2 = _sample_grid_df(
        lat_range=(-22.0, -21.5), lon_range=(-44.0, -43.5), hour=12
    )
    manager.write_dataframe(pl.concat([df2, df]))  # write deliberately out of order

    read = pl.read_parquet(
        next((manager.parquet_dir / "date=2024-01-01").glob("*.parquet"))
    )
    # Polars' is_sorted on a struct of the 3 columns: build a key column.
    key = read.select(
        (pl.col("latitude") * 1e6 + pl.col("longitude") * 1e3 + pl.col("hour_utc"))
        .alias("k")
    )["k"].to_list()
    assert key == sorted(key)


def test_row_group_stats_are_tight_for_latitude(tmp_path: Path):
    """Sort by latitude → row-group min/max should partition the lat range."""
    import pyarrow.parquet as pq

    manager = ParquetManager(tmp_path, "era5-land")
    df = _sample_grid_df(
        lat_range=(-30.0, -10.0),  # 200 lat steps at 0.1°
        lon_range=(-60.0, -40.0),  # 200 lon steps at 0.1°
        step=0.1,
    )
    # Use a small row_group_size to force >= 2 row-groups for the assertion.
    manager.write_dataframe(df, row_group_size=10_000)

    file = next((manager.parquet_dir / "date=2024-01-01").glob("*.parquet"))
    meta = pq.ParquetFile(file).metadata
    assert meta.num_row_groups >= 2  # otherwise the test is uninformative

    # Find the index of the "latitude" column in the schema.
    schema_names = [meta.schema.column(i).name for i in range(meta.num_columns)]
    lat_idx = schema_names.index("latitude")

    mins, maxes = [], []
    for i in range(meta.num_row_groups):
        stats = meta.row_group(i).column(lat_idx).statistics
        assert stats is not None and stats.has_min_max
        mins.append(stats.min)
        maxes.append(stats.max)

    # Each row-group's lat range should be tighter than the full bbox.
    full_range = 20.0  # -30..-10
    avg_rg_range = sum(mx - mn for mn, mx in zip(mins, maxes, strict=False)) / len(mins)
    assert avg_rg_range < full_range / 2, (
        f"row-group lat ranges average {avg_rg_range}, expected << {full_range}"
    )


def test_dedup_preserves_filename_pattern(tmp_path: Path):
    """Legacy ``part-<uuid>.parquet`` should be replaced by the new naming."""
    manager = ParquetManager(tmp_path, "era5-land")
    partition_dir = manager.parquet_dir / "date=2024-01-01"
    partition_dir.mkdir(parents=True)

    base = _sample_grid_df(
        lat_range=(-22.0, -21.9), lon_range=(-44.0, -43.9), var_value=300.0
    ).drop("date")
    # Simulate the legacy uuid filename.
    base.write_parquet(partition_dir / "part-abc123def456.parquet")
    base.write_parquet(partition_dir / "part-789xyz000111.parquet")

    manager.dedup_existing_partitions()

    files = list(partition_dir.glob("*.parquet"))
    assert len(files) == 1
    assert files[0].name == "era5-land_2024-01-01_part-001.parquet"


def test_natural_date_query_via_duckdb(tmp_path: Path):
    """End-to-end: write 3 days, query a 2-day range, get only those days."""
    import duckdb

    manager = ParquetManager(tmp_path, "era5-land")
    for d in ("2024-01-15", "2024-01-16", "2024-01-17"):
        df = _sample_grid_df(
            lat_range=(-22.0, -21.9),
            lon_range=(-44.0, -43.9),
            date_str=d,
        )
        manager.write_dataframe(df)

    conn = duckdb.connect(":memory:")
    manager.create_duckdb_view(conn, "era5_land")
    result = conn.execute(
        "SELECT DISTINCT CAST(date AS VARCHAR) AS d FROM era5_land "
        "WHERE date BETWEEN '2024-01-15' AND '2024-01-16' "
        "ORDER BY d"
    ).fetchall()
    assert [r[0] for r in result] == ["2024-01-15", "2024-01-16"]
    conn.close()


# -- DuckDBManager tests --


def test_duckdb_manager_connect_memory():
    """Test DuckDB connection to in-memory database."""
    config = DatabaseConfig(db_path=None)
    manager = DuckDBManager(config)
    manager.connect()

    assert manager._conn is not None

    manager.disconnect()
    assert manager._conn is None


def test_duckdb_manager_connect_file(database_config: DatabaseConfig):
    """Test DuckDB connection to file database."""
    manager = DuckDBManager(database_config)
    manager.connect()

    assert manager._conn is not None
    assert database_config.db_path.exists()

    manager.disconnect()


def test_duckdb_manager_context_manager(database_config: DatabaseConfig):
    """Test DuckDB manager as context manager."""
    with DuckDBManager(database_config) as db:
        assert db._conn is not None

    assert db._conn is None


def test_duckdb_manager_query(database_config: DatabaseConfig):
    """Test executing SQL query."""
    with DuckDBManager(database_config) as db:
        db._conn.execute("CREATE TABLE test (id INTEGER, name VARCHAR)")
        db._conn.execute("INSERT INTO test VALUES (1, 'test1'), (2, 'test2')")

        result = db.query("SELECT * FROM test ORDER BY id")

        assert isinstance(result, pl.DataFrame)
        assert len(result) == 2
        assert "id" in result.columns
        assert "name" in result.columns


def test_duckdb_manager_register_parquet(database_config: DatabaseConfig, tmp_path: Path):
    """Test registering Parquet file as table."""
    parquet_file = tmp_path / "test_data.parquet"
    df = pl.DataFrame({"id": [1, 2, 3], "value": [10.0, 20.0, 30.0]})
    df.write_parquet(parquet_file)

    with DuckDBManager(database_config) as db:
        db.register_parquet(parquet_file, "test_table")
        result = db.query("SELECT * FROM test_table ORDER BY id")

        assert len(result) == 3
        assert result["id"].to_list() == [1, 2, 3]
