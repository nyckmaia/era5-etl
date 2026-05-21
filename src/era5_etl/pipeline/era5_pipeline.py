"""Complete ERA5/ERA5-Land data processing pipeline."""

from collections.abc import Callable
from typing import Any

import duckdb

from era5_etl.config import PipelineConfig
from era5_etl.core.context import PipelineContext
from era5_etl.core.pipeline import Pipeline
from era5_etl.core.stage import Stage
from era5_etl.pipeline.source_handlers import REFRESH_STATIONS, get_handler
from era5_etl.storage.coverage import rebuild_from_parquet
from era5_etl.storage.manifest import Manifest
from era5_etl.storage.parquet_manager import ParquetManager
from era5_etl.storage.paths import view_name_for
from era5_etl.storage.stations import (
    rebuild_from_parquet as rebuild_stations_from_parquet,
)

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
        handler = get_handler(self.config.dataset_name)
        downloader = handler.make_downloader(
            self.config.download,
            manifest,
            self.progress_callback,
        )
        files = downloader.download(
            apply_diff=self.apply_diff,
            base_dir=self.config.storage.database_dir,
        )
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
        handler = get_handler(self.config.dataset_name)
        converter = handler.make_converter(
            self.config.transform,
            self.config.storage,
            output_dir,
            self.config.dataset_name,
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
            cleanup=not self.config.keep_temp_files,
        )
        context.set("conversion_stats", stats)
        context.set_metadata("converted_count", stats["converted"])
        self.logger.info(
            f"Converted {stats['converted']}/{stats['total']} files to Parquet"
        )
        return context


def _emit_finalizing(
    progress_callback: ProgressCallback | None, message: str
) -> None:
    """Push a ``stage="finalizing"`` event so the UI can show a "wait…" line
    between the convert bar hitting 100% and the success card. Cheap no-op
    when there is no callback (CLI invocation)."""
    if progress_callback is not None:
        progress_callback({"stage": "finalizing", "message": message})


class RefreshCoverageStage(Stage):
    """Refresh the per-cell coverage index from the on-disk parquets.

    Runs in a single process AFTER the parallel ConvertToParquetStage so we
    don't fight DuckDB's single-writer lock on `_coverage.duckdb`. Coverage
    is derived state -- the parquet files are canonical -- so a failure
    here is logged but does not fail the pipeline.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__("Refresh coverage index")
        self.config = config
        self.progress_callback = progress_callback

    def _execute(self, context: PipelineContext) -> PipelineContext:
        from era5_etl.storage.paths import resolve_dataset_dir

        base_dir = self.config.storage.database_dir
        dataset = self.config.dataset_name
        parquet_dir = resolve_dataset_dir(base_dir, dataset)
        _emit_finalizing(
            self.progress_callback,
            f"Atualizando índice de cobertura ({dataset})…",
        )
        self.logger.info(
            "Refreshing coverage index for %s from %s", dataset, parquet_dir
        )
        try:
            stats = rebuild_from_parquet(dataset, base_dir, logger=self.logger)
            context.set_metadata("coverage_stats", stats)
            self.logger.info(
                "Coverage index refreshed: %s rows from %s parquet file(s) "
                "(%s cells, %s dates, %s vars)",
                stats.get("total_rows", "?"),
                stats.get("files_processed", "?"),
                stats.get("n_cells", "?"),
                stats.get("n_dates", "?"),
                stats.get("n_variables", "?"),
            )
            if stats.get("total_rows", 0) == 0 and stats.get(
                "files_processed", 0
            ):
                # Parquet existed but nothing was indexed -> /inventory
                # would wrongly show "no data". Make this loud.
                self.logger.error(
                    "Coverage refresh produced 0 rows despite %s parquet "
                    "file(s) in %s -- inventory will appear empty. Check "
                    "the parquet schema (latitude/longitude/hour_utc/date "
                    "+ variable columns).",
                    stats.get("files_processed"),
                    parquet_dir,
                )
        except Exception as exc:
            self.logger.warning(
                "Coverage index refresh failed (non-fatal); run "
                "`era5 coverage rebuild` manually to recover: %s",
                exc,
                exc_info=True,
            )
        return context


class RefreshStationIndexStage(Stage):
    """Refresh the per-station index from on-disk parquet (INMET).

    The non-grid analogue of :class:`RefreshCoverageStage`. INMET is stored
    one parquet per ``station=<id>/<id>_<year>.parquet`` (no ``date=``
    partition), so the grid coverage index does not apply -- the
    ``_stations.duckdb`` index is rebuilt here instead. Derived state: a
    failure is logged but never fails the pipeline.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__("Refresh station index")
        self.config = config
        self.progress_callback = progress_callback

    def _execute(self, context: PipelineContext) -> PipelineContext:
        from era5_etl.storage.paths import resolve_dataset_dir

        base_dir = self.config.storage.database_dir
        dataset = self.config.dataset_name
        parquet_dir = resolve_dataset_dir(base_dir, dataset)
        _emit_finalizing(
            self.progress_callback,
            "Atualizando índice de estações INMET (pode levar ~1 minuto)…",
        )
        self.logger.info(
            "Refreshing station index for %s from %s", dataset, parquet_dir
        )
        try:
            stats = rebuild_stations_from_parquet(
                dataset, base_dir, logger=self.logger
            )
            context.set_metadata("station_index_stats", stats)
            self.logger.info(
                "Station index refreshed: %s station(s), %s file(s)",
                stats.get("n_stations", "?"),
                stats.get("files_processed", "?"),
            )
        except Exception as exc:
            self.logger.warning(
                "Station index refresh failed (non-fatal); run "
                "`era5 coverage rebuild` equivalent manually to recover: %s",
                exc,
                exc_info=True,
            )
        return context


class CreateViewStage(Stage):
    """Stage for creating a DuckDB VIEW pointing to Parquet files."""

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__("Create DuckDB View")
        self.config = config
        self.progress_callback = progress_callback

    def _execute(self, context: PipelineContext) -> PipelineContext:
        """Create DuckDB VIEW from Parquet files."""
        view_name = view_name_for(self.config.dataset_name)
        db_path = self.config.get_database_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        manager = ParquetManager(self.config.storage.database_dir, self.config.dataset_name)

        if not manager.exists():
            self.logger.warning("No Parquet files found. Skipping VIEW creation.")
            return context

        _emit_finalizing(
            self.progress_callback, f"Criando VIEW '{view_name}' no DuckDB…"
        )
        conn = duckdb.connect(str(db_path))
        try:
            manager.create_duckdb_view(conn, view_name)
            context.set_metadata("view_name", view_name)
            context.set_metadata("database_path", str(db_path))
            self.logger.info(f"Created VIEW '{view_name}' in {db_path}")
        finally:
            conn.close()
        _emit_finalizing(self.progress_callback, "Pronto — preparando view final…")

        return context


class ExtractGridStage(Stage):
    """Convert a freshly downloaded NetCDF into a tiny ``(lat, lon)`` parquet.

    Used by the INMET auto-bootstrap path to materialise the ERA5 /
    ERA5-LAND grid without writing anything into the user's actual dataset
    directory. The resulting parquet lives at
    ``<base>/climate_data_store_db/_grids/<dataset>_grid.parquet`` and is
    later consulted by the INMET converter (see
    :class:`era5_etl.storage.grid_index.GridIndex`).

    The NetCDF is deleted after the grid is extracted so no transient
    files survive on disk.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        super().__init__("Extract grid points")
        self.config = config
        self.progress_callback = progress_callback

    def _execute(self, context: PipelineContext) -> PipelineContext:
        import shutil

        import numpy as np
        import polars as pl
        import xarray as xr

        from era5_etl.datasets import DatasetRegistry
        from era5_etl.storage.grid_index import grid_parquet_path

        files = list(context.get("downloaded_files") or [])
        if not files:
            self.logger.warning(
                "ExtractGridStage: no files downloaded -- skipping grid write."
            )
            return context

        dataset = self.config.dataset_name
        decimals = DatasetRegistry.get(dataset).latlon_decimals
        _emit_finalizing(
            self.progress_callback,
            f"Extraindo grade de pontos do {dataset.upper()} (dependência)…",
        )

        # Read every downloaded NetCDF and union their lat/lon. The
        # bootstrap normally downloads a single file (1 var x 1 day x 1
        # hour x Brazil), but the loop is cheap and lets a planner-split
        # request work the same way.
        lats: list[float] = []
        lons: list[float] = []
        for path in files:
            with xr.open_dataset(path, engine="netcdf4") as ds:
                lats.extend(np.asarray(ds["latitude"].values).ravel().tolist())
                lons.extend(np.asarray(ds["longitude"].values).ravel().tolist())

        if not lats or not lons:
            self.logger.error(
                "ExtractGridStage: NetCDF(s) had no latitude/longitude data."
            )
            return context

        # Uppercase ``LAT/LON`` is the numpy convention for meshgrid
        # 2-D arrays (vs lowercase 1-D inputs); kept here for clarity.
        lat_grid, lon_grid = np.meshgrid(
            np.unique(np.round(np.array(lats, dtype=np.float64), decimals)),
            np.unique(np.round(np.array(lons, dtype=np.float64), decimals)),
            indexing="ij",
        )
        df = (
            pl.DataFrame(
                {
                    "latitude": pl.Series(
                        lat_grid.ravel().astype(np.float32), dtype=pl.Float32
                    ),
                    "longitude": pl.Series(
                        lon_grid.ravel().astype(np.float32), dtype=pl.Float32
                    ),
                }
            )
            .unique(subset=["latitude", "longitude"])
            .sort(["latitude", "longitude"])
        )

        out_path = grid_parquet_path(self.config.storage.database_dir, dataset)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(
            out_path, compression=self.config.storage.parquet_compression
        )
        context.set_metadata("grid_parquet_path", str(out_path))
        context.set_metadata("grid_point_count", df.height)
        self.logger.info(
            "Bootstrap grid for %s: %d points -> %s",
            dataset,
            df.height,
            out_path,
        )

        # Clean up the temp NetCDFs so the bootstrap leaves no residue in
        # the user's storage. Skip with ``keep_temp_files=True`` only when
        # the user explicitly opts in (parity with the full pipeline).
        if not self.config.keep_temp_files:
            nc_dir = self.config.download.output_dir
            if nc_dir.exists():
                shutil.rmtree(nc_dir, ignore_errors=True)
        return context


class BootstrapGridPipeline(Pipeline[PipelineConfig]):
    """Two-stage pipeline used by the INMET auto-bootstrap.

    Downloads the minimal CDS request (1 var x 1 day x 1 hour x Brazil),
    extracts its grid into ``<base>/climate_data_store_db/_grids/
    <dataset>_grid.parquet`` and drops the NetCDF. Does NOT write anything
    into ``<base>/climate_data_store_db/<dataset>/``, leaving that
    directory exclusively for data the user downloads on purpose.
    """

    def __init__(
        self,
        config: PipelineConfig,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.progress_callback = progress_callback
        super().__init__(config)

    def setup_stages(self) -> None:
        self.add_stage(
            DownloadStage(
                self.config,
                progress_callback=self.progress_callback,
                apply_diff=False,
            )
        )
        self.add_stage(
            ExtractGridStage(
                self.config, progress_callback=self.progress_callback
            )
        )
        self.logger.info(
            f"Bootstrap pipeline configured with {len(self._stages)} stages"
        )


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
        # The post-convert refresh stage depends on the source kind:
        # gridded sources get the cell coverage index; station sources
        # (INMET) get the station index.
        if get_handler(self.config.dataset_name).refresh_kind == REFRESH_STATIONS:
            self.add_stage(
                RefreshStationIndexStage(
                    self.config, progress_callback=self.progress_callback
                )
            )
        else:
            self.add_stage(
                RefreshCoverageStage(
                    self.config, progress_callback=self.progress_callback
                )
            )
        self.add_stage(
            CreateViewStage(self.config, progress_callback=self.progress_callback)
        )
        self.logger.info(f"Pipeline configured with {len(self._stages)} stages")
