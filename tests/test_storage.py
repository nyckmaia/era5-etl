"""Tests for storage components."""

from pathlib import Path

import polars as pl
import pytest

from pyera5.config import DatabaseConfig, StorageConfig
from pyera5.storage.data_exporter import DataExporter
from pyera5.storage.duckdb_manager import DuckDBManager
from pyera5.storage.parquet_writer import ParquetWriter


def test_parquet_writer_initialization(storage_config: StorageConfig):
    """Test ParquetWriter initialization."""
    writer = ParquetWriter(storage_config)

    assert writer.config == storage_config
    assert writer.config.parquet_dir.exists()


def test_parquet_writer_ensure_partition_columns(storage_config: StorageConfig):
    """Test partition column creation."""
    writer = ParquetWriter(storage_config)

    # Create DataFrame with time column
    df = pl.DataFrame({
        "time": pl.datetime_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 10),
            interval="1d",
            eager=True,
        ),
        "value": range(10),
    })

    result = writer._ensure_partition_columns(df)

    # Check if partition columns were added
    assert "year" in result.columns
    assert "month" in result.columns


def test_parquet_writer_csv_to_parquet(storage_config: StorageConfig, tmp_path: Path):
    """Test CSV to Parquet conversion."""
    writer = ParquetWriter(storage_config)

    # Create sample CSV file with proper datetime and partition columns
    csv_file = tmp_path / "test.csv"
    df = pl.DataFrame({
        "time": pl.datetime_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 10),
            interval="1d",
            eager=True,
        ),
        "temperature": [20.0 + i for i in range(10)],
        "humidity": [60.0 + i for i in range(10)],
        "year": [2020] * 10,  # Add year column
        "month": [1] * 10,    # Add month column
    })

    df.write_csv(csv_file)

    # Convert to Parquet
    output_dir = writer.write_csv_to_parquet(csv_file, "test_data")

    assert output_dir.exists()
    assert output_dir.is_dir()


def test_duckdb_manager_connect_memory(database_config: DatabaseConfig):
    """Test DuckDB connection to in-memory database."""
    # Override with memory database
    database_config.db_path = None

    manager = DuckDBManager(database_config)
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

    # Connection should be closed after exiting context
    assert db._conn is None


def test_duckdb_manager_query(database_config: DatabaseConfig):
    """Test executing SQL query."""
    with DuckDBManager(database_config) as db:
        # Create simple test table
        db._conn.execute("CREATE TABLE test (id INTEGER, name VARCHAR)")
        db._conn.execute("INSERT INTO test VALUES (1, 'test1'), (2, 'test2')")

        # Query the table
        result = db.query("SELECT * FROM test ORDER BY id")

        assert isinstance(result, pl.DataFrame)
        assert len(result) == 2
        assert "id" in result.columns
        assert "name" in result.columns


def test_duckdb_manager_register_parquet(database_config: DatabaseConfig, tmp_path: Path):
    """Test registering Parquet file as table."""
    # Create sample Parquet file
    parquet_file = tmp_path / "test_data.parquet"
    df = pl.DataFrame({
        "id": [1, 2, 3],
        "value": [10.0, 20.0, 30.0],
    })
    df.write_parquet(parquet_file)

    with DuckDBManager(database_config) as db:
        # Register Parquet as table
        db.register_parquet(parquet_file, "test_table")

        # Query the registered table
        result = db.query("SELECT * FROM test_table ORDER BY id")

        assert len(result) == 3
        assert result["id"].to_list() == [1, 2, 3]


def test_data_exporter_export_to_csv(tmp_path: Path):
    """Test exporting DataFrame to CSV."""
    exporter = DataExporter()

    df = pl.DataFrame({
        "col1": [1, 2, 3],
        "col2": ["a", "b", "c"],
    })

    output_file = tmp_path / "export.csv"
    result = exporter.export_to_csv(df, output_file)

    assert result == output_file
    assert output_file.exists()

    # Verify exported data
    loaded = pl.read_csv(output_file)
    assert len(loaded) == 3
    assert loaded.columns == ["col1", "col2"]


def test_data_exporter_export_parquet_to_csv(tmp_path: Path):
    """Test exporting Parquet to CSV."""
    exporter = DataExporter()

    # Create sample Parquet file
    parquet_file = tmp_path / "test.parquet"
    df = pl.DataFrame({
        "col1": [1, 2, 3],
        "col2": [10.0, 20.0, 30.0],
    })
    df.write_parquet(parquet_file)

    # Export to CSV
    output_file = tmp_path / "output.csv"
    result = exporter.export_parquet_to_csv(parquet_file, output_file)

    assert result == output_file
    assert output_file.exists()

    # Verify data
    loaded = pl.read_csv(output_file)
    assert len(loaded) == 3


def test_data_exporter_export_parquet_directory(tmp_path: Path):
    """Test exporting directory of Parquet files to CSV."""
    exporter = DataExporter()

    # Create directory with multiple Parquet files
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()

    for i in range(3):
        df = pl.DataFrame({
            "id": [i * 10 + j for j in range(5)],
            "value": [float(i * 10 + j) for j in range(5)],
        })
        df.write_parquet(parquet_dir / f"part_{i}.parquet")

    # Export all to single CSV
    output_file = tmp_path / "combined.csv"
    result = exporter.export_parquet_to_csv(parquet_dir, output_file)

    assert result == output_file
    assert output_file.exists()

    # Verify combined data
    loaded = pl.read_csv(output_file)
    assert len(loaded) == 15  # 3 files × 5 rows
