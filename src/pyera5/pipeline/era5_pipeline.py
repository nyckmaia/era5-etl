"""Complete ERA5/ERA5-Land data processing pipeline."""

from pyera5.config import PipelineConfig
from pyera5.core.context import PipelineContext
from pyera5.core.pipeline import Pipeline
from pyera5.core.stage import Stage
from pyera5.download.cds_downloader import CDSDownloader
from pyera5.storage.duckdb_manager import DuckDBManager
from pyera5.storage.parquet_writer import ParquetWriter
from pyera5.transform.netcdf_processor import NetCDFProcessor


class DownloadStage(Stage):
    """Stage for downloading ERA5 data from CDS."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Download ERA5 Data")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute download stage."""
        downloader = CDSDownloader(self.config.download)
        files = downloader.download()
        context.set("downloaded_files", files)
        context.set_metadata("download_count", len(files))
        self.logger.info(f"Downloaded {len(files)} files")
        return context


class ProcessStage(Stage):
    """Stage for processing NetCDF files."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Process NetCDF Files")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute processing stage."""
        processor = NetCDFProcessor(self.config.processing)
        stats = processor.process_directory()
        context.set("processing_stats", stats)
        context.set_metadata("processed_count", stats["processed"])
        self.logger.info(f"Processed {stats['processed']} NetCDF files")
        return context


class ParquetStage(Stage):
    """Stage for converting to Parquet."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Convert to Parquet")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute Parquet conversion stage."""
        writer = ParquetWriter(self.config.storage)

        # Process all CSV files in processing output directory
        csv_files = list(self.config.processing.output_dir.glob("*.csv"))
        converted = 0

        for csv_file in csv_files:
            try:
                writer.write_csv_to_parquet(csv_file)
                converted += 1
            except Exception as e:
                self.logger.error(f"Failed to convert {csv_file}: {e}")

        context.set("parquet_converted", converted)
        context.set_metadata("parquet_count", converted)
        self.logger.info(f"Converted {converted} files to Parquet")
        return context


class DatabaseStage(Stage):
    """Stage for loading into DuckDB."""

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__("Load into DuckDB")
        self.config = config

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Execute database loading stage."""
        db_manager = DuckDBManager(self.config.database)

        with db_manager:
            # Register all parquet directories as tables
            parquet_dirs = [d for d in self.config.storage.parquet_dir.glob("*") if d.is_dir()]

            table_count = 0
            for table_dir in parquet_dirs:
                table_name = table_dir.name
                db_manager.register_parquet(table_dir, table_name)
                table_count += 1

            context.set("database_tables", table_count)
            context.set_metadata("tables_loaded", table_count)
            self.logger.info(f"Loaded {table_count} tables into DuckDB")

        return context


class ERA5Pipeline(Pipeline[PipelineConfig]):
    """Complete ERA5/ERA5-Land data processing pipeline.

    Orchestrates:
    1. Download ERA5/ERA5-Land data from CDS
    2. Process NetCDF files
    3. Convert to Parquet format
    4. Load into DuckDB database

    Example:
        ```python
        from pyera5 import ERA5Pipeline
        from pyera5.config import PipelineConfig, DownloadConfig, ...

        config = PipelineConfig(...)
        pipeline = ERA5Pipeline(config)
        result = pipeline.run()
        ```
    """

    def setup_stages(self) -> None:
        """Set up all pipeline stages."""
        self.add_stage(DownloadStage(self.config))
        self.add_stage(ProcessStage(self.config))
        self.add_stage(ParquetStage(self.config))
        self.add_stage(DatabaseStage(self.config))

        self.logger.info(f"Pipeline configured with {len(self._stages)} stages")
