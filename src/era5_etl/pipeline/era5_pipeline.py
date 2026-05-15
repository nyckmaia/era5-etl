"""Complete ERA5/ERA5-Land data processing pipeline."""

from collections.abc import Callable
from typing import Any

import duckdb

from era5_etl.config import PipelineConfig
from era5_etl.core.context import PipelineContext
from era5_etl.core.pipeline import Pipeline
from era5_etl.core.stage import Stage
from era5_etl.download.cds_downloader import CDSDownloader
from era5_etl.storage.coverage import rebuild_from_parquet
from era5_etl.storage.manifest import Manifest
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter

ProgressCallback = Callable[[dict[str, Any]], None]


class DownloadStage(Stage):
    """Stage for downloading ERA5 data from CDS."""

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
        apply_diff: bool = False,
    ) -> None:
        super().__init__("Download ERA5 Data")
        self.config = config
        self.progress_callback = progress_callback
        self.apply_diff = apply_diff

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute download stage."""
        manifest = Manifest(self.config.storage.database_dir, self.config.dataset_name)
        downloader = CDSDownloader(
            self.config.download,
            manifest=manifest,
            on_event=self.progress_callback,
        )
        if self.apply_diff:
            files = downloader.download(
                apply_diff=True, base_dir=self.config.storage.database_dir
            )
        else:
            files = downloader.download()
        context.set("downloaded_files", files)
        context.set_metadata("download_count", len(files))
        self.logger.info(f"Downloaded {len(files)} files")
        return context


class ConvertToParquetStage(Stage):
    """Stage for converting NetCDF directly to Parquet (no CSV intermediate)."""

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__("Convert NetCDF to Parquet")
        self.config = config
        self.progress_callback = progress_callback

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute conversion stage."""
        output_dir = self.config.get_parquet_dir()
        converter = NetCDFToParquetConverter(
            transform_config=self.config.transform,
            storage_config=self.config.storage,
            output_dir=output_dir,
        )

        on_progress = None
        if self.progress_callback is not None:
            cb = self.progress_callback

            def on_progress(done: int, total: int, message: str) -> None:
                cb(
                    {
                        "stage": "convert",
                        "files_done": done,
                        "files_total": total,
                        "message": message,
                    }
                )

        stats = converter.convert_directory(
            self.config.download.output_dir,
            max_workers=self.config.transform.max_workers,
            on_progress=on_progress,
        )
        context.set("conversion_stats", stats)
        context.set_metadata("converted_count", stats["converted"])
        self.logger.info(
            f"Converted {stats['converted']}/{stats['total']} files to Parquet"
        )
        return context


class RefreshCoverageStage(Stage):
    """Refresh the per-cell coverage index from the on-disk parquets.

    Runs in a single process AFTER the parallel ConvertToParquetStage so we
    don't fight DuckDB's single-writer lock on `_coverage.duckdb`. Coverage
    is derived state -- the parquet files are canonical -- so a failure
    here is logged but does not fail the pipeline.
    """

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Refresh coverage index")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        try:
            stats = rebuild_from_parquet(
                self.config.dataset_name,
                self.config.storage.database_dir,
                logger=self.logger,
            )
            context.set_metadata("coverage_stats", stats)
            self.logger.info(
                "Coverage index refreshed: %s rows / %s files",
                stats.get("total_rows", "?"),
                stats.get("n_files", "?"),
            )
        except Exception as exc:  # noqa: BLE001 -- coverage is derived; never fail the pipeline
            self.logger.warning(
                "Coverage index refresh failed (non-fatal); run "
                "`era5 coverage rebuild` manually to recover: %s",
                exc,
            )
        return context


class CreateViewStage(Stage):
    """Stage for creating a DuckDB VIEW pointing to Parquet files."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Create DuckDB View")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Create DuckDB VIEW from Parquet files."""
        view_name = self.config.dataset_name.replace("-", "_") + "_view"
        db_path = self.config.get_database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        manager = ParquetManager(self.config.storage.database_dir, self.config.dataset_name)

        if not manager.exists():
            self.logger.warning("No Parquet files found. Skipping VIEW creation.")
            return context

        conn = duckdb.connect(str(db_path))
        try:
            manager.create_duckdb_view(conn, view_name)
            context.set_metadata("view_name", view_name)
            context.set_metadata("database_path", str(db_path))
            self.logger.info(f"Created VIEW '{view_name}' in {db_path}")
        finally:
            conn.close()

        return context


class ERA5Pipeline(Pipeline[PipelineConfig]):
    """Complete ERA5/ERA5-Land data processing pipeline.

    Orchestrates:
    1. Download ERA5/ERA5-Land data from CDS
    2. Convert NetCDF directly to Parquet format
    3. Create DuckDB VIEW pointing to Parquet files

    Pass ``progress_callback`` to receive per-chunk lifecycle events
    (``submitting``, ``queued``, ``running``, ``downloading``,
    ``completed``, ``failed``) -- used by the web UI to render live
    progress. The callback is invoked from the download thread; it must
    be thread-safe.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
        apply_diff: bool = False,
    ) -> None:
        self.progress_callback = progress_callback
        self.apply_diff = apply_diff
        super().__init__(config)

    def setup_stages(self) -> None:
        """Set up all pipeline stages."""
        self.add_stage(
            DownloadStage(
                self.config,
                progress_callback=self.progress_callback,
                apply_diff=self.apply_diff,
            )
        )
        self.add_stage(
            ConvertToParquetStage(
                self.config, progress_callback=self.progress_callback
            )
        )
        self.add_stage(RefreshCoverageStage(self.config))
        self.add_stage(CreateViewStage(self.config))
        self.logger.info(f"Pipeline configured with {len(self._stages)} stages")
