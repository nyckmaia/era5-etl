"""Parquet storage manager for partitioned ERA5 data.

Manages partitioned Parquet files with Hive-style structure:
- Structure: {base_dir}/parquet/{dataset}/date={YYYY-MM-DD}/*.parquet
- Manifest tracking: _manifest.json for processed files
- DuckDB integration: creates VIEWs from Parquet glob patterns
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb


@dataclass
class ParquetStorageStats:
    """Statistics about Parquet storage."""

    total_files: int
    total_size_bytes: int
    partitions: list[str]
    file_count_by_partition: dict[str, int]


class ParquetManager:
    """Manager for partitioned Parquet storage.

    Provides:
    - Manifest tracking of processed source files
    - Listing of partitions and files
    - Glob patterns for read_parquet()
    - DuckDB VIEW creation for querying
    """

    MANIFEST_FILENAME = "_manifest.json"

    def __init__(self, base_dir: Path, dataset: str) -> None:
        """Initialize the Parquet manager.

        Args:
            base_dir: Base directory containing parquet/ folder
            dataset: ERA5 dataset name (era5, era5-land, era5land)
        """
        self.base_dir = Path(base_dir)
        self.dataset = dataset.lower().replace("-", "")
        if self.base_dir.name == "parquet":
            self.parquet_dir = self.base_dir / self.dataset
        else:
            self.parquet_dir = self.base_dir / "parquet" / self.dataset
        self.manifest_path = self.parquet_dir / self.MANIFEST_FILENAME
        self.logger = logging.getLogger(__name__)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

    def get_processed_files(self) -> set[str]:
        """Get set of source files that have been processed."""
        manifest = self._load_manifest()
        return set(manifest.get("processed_files", []))

    def mark_processed(self, source_file: str) -> None:
        """Mark a source file as processed in the manifest."""
        manifest = self._load_manifest()
        if "processed_files" not in manifest:
            manifest["processed_files"] = []
        if source_file not in manifest["processed_files"]:
            manifest["processed_files"].append(source_file)
            manifest["last_updated"] = datetime.now().isoformat()
        self._save_manifest(manifest)
        self.logger.debug(f"Marked as processed: {source_file}")

    def remove_processed(self, source_file: str) -> None:
        """Remove a source file from the processed list."""
        manifest = self._load_manifest()
        if "processed_files" in manifest and source_file in manifest["processed_files"]:
            manifest["processed_files"].remove(source_file)
            manifest["last_updated"] = datetime.now().isoformat()
            self._save_manifest(manifest)
            self.logger.debug(f"Removed from processed: {source_file}")

    def clear_manifest(self) -> None:
        """Clear all processed files from manifest."""
        manifest = {
            "dataset": self.dataset,
            "processed_files": [],
            "last_updated": datetime.now().isoformat(),
        }
        self._save_manifest(manifest)
        self.logger.info("Manifest cleared")

    def get_glob_pattern(self) -> str:
        """Get glob pattern for read_parquet() with Hive partitioning."""
        return str(self.parquet_dir / "**" / "*.parquet")

    def get_storage_stats(self) -> ParquetStorageStats:
        """Get statistics about Parquet storage."""
        total_files = 0
        total_size = 0
        file_count_by_partition: dict[str, int] = {}
        partitions: list[str] = []

        if self.parquet_dir.exists():
            for parquet_file in self.parquet_dir.rglob("*.parquet"):
                total_files += 1
                total_size += parquet_file.stat().st_size

                partition_dir = parquet_file.parent.name
                if "=" in partition_dir:
                    key = partition_dir
                    file_count_by_partition[key] = file_count_by_partition.get(key, 0) + 1
                    if key not in partitions:
                        partitions.append(key)

        return ParquetStorageStats(
            total_files=total_files,
            total_size_bytes=total_size,
            partitions=sorted(partitions),
            file_count_by_partition=file_count_by_partition,
        )

    def list_parquet_files(self) -> list[Path]:
        """List all Parquet files."""
        if not self.parquet_dir.exists():
            return []
        return sorted(self.parquet_dir.rglob("*.parquet"))

    def create_duckdb_view(
        self,
        conn: duckdb.DuckDBPyConnection,
        view_name: str,
    ) -> None:
        """Create a DuckDB VIEW from Parquet files.

        Args:
            conn: DuckDB connection
            view_name: Name for the VIEW to create
        """
        glob_pattern = self.get_glob_pattern()
        files = list(self.parquet_dir.rglob("*.parquet"))
        if not files:
            raise ValueError(f"No Parquet files found in {self.parquet_dir}")

        sql = f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM read_parquet(
                '{glob_pattern}',
                hive_partitioning=true
            )
        """
        conn.execute(sql)
        self.logger.info(f"Created VIEW {view_name} from {len(files)} Parquet files")

    def exists(self) -> bool:
        """Check if Parquet storage exists and has files."""
        if not self.parquet_dir.exists():
            return False
        return any(self.parquet_dir.rglob("*.parquet"))

    def _load_manifest(self) -> dict[str, Any]:
        """Load manifest from disk."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, encoding="utf-8") as f:
                    data: dict[str, Any] = json.load(f)
                    return data
            except (OSError, json.JSONDecodeError) as e:
                self.logger.warning(f"Failed to load manifest: {e}")
                return {"dataset": self.dataset, "processed_files": []}
        return {"dataset": self.dataset, "processed_files": []}

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        """Save manifest to disk."""
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except OSError as e:
            self.logger.error(f"Failed to save manifest: {e}")

    def __repr__(self) -> str:
        """String representation."""
        stats = self.get_storage_stats()
        return (
            f"ParquetManager(dataset={self.dataset}, "
            f"files={stats.total_files}, partitions={len(stats.partitions)})"
        )
