"""Tests for storage components."""

from pathlib import Path

import polars as pl

from era5_etl.config import DatabaseConfig
from era5_etl.storage.duckdb_manager import DuckDBManager
from era5_etl.storage.parquet_manager import ParquetManager

# -- ParquetManager tests --


def test_parquet_manager_initialization(tmp_path: Path):
    """Test ParquetManager initialization."""
    manager = ParquetManager(tmp_path, "era5-land")

    assert manager.dataset == "era5land"
    assert manager.parquet_dir.exists()
    assert "parquet" in str(manager.parquet_dir)
    assert "era5land" in str(manager.parquet_dir)


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
