"""NetCDF to Parquet converter for ERA5/ERA5-Land data.

Converts ERA5 NetCDF files directly to Hive-partitioned Parquet format,
eliminating the intermediate CSV step.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
import polars as pl
import xarray as xr

from era5_etl.config import StorageConfig, TransformConfig
from era5_etl.constants import KELVIN_TO_CELSIUS
from era5_etl.datasets import DatasetRegistry
from era5_etl.exceptions import ProcessingError
from era5_etl.utils.variables import get_var_name_map

# CDS ERA5 NetCDF often carries these scalar coords (ensemble member /
# ERA5-vs-ERA5T flag). They are never used downstream; drop before Parquet.
_UNUSED_NETCDF_COLS = ("number", "expver")


def _convert_single_file(
    nc_path: Path,
    transform_config: TransformConfig,
    storage_config: StorageConfig,
    output_dir: Path,
    dataset: str | None = None,
) -> tuple[str, bool, str]:
    """Convert a single NetCDF file to Parquet (top-level function for multiprocessing).

    Args:
        nc_path: Path to the NetCDF file.
        transform_config: Transformation settings.
        storage_config: Storage/compression settings.
        output_dir: Directory for Parquet output.
        dataset: Dataset name (era5/era5-land); drives lat/lon decimal
            rounding. ``None`` keeps the dataset-agnostic behavior.

    Returns:
        Tuple of (filename, success, error_message).
    """
    try:
        converter = NetCDFToParquetConverter(
            transform_config=transform_config,
            storage_config=storage_config,
            output_dir=output_dir,
            dataset=dataset,
        )
        converter.convert_file(nc_path)
        return (nc_path.name, True, "")
    except Exception as e:
        return (nc_path.name, False, str(e))


class NetCDFToParquetConverter:
    """Convert ERA5/ERA5-Land NetCDF files directly to Parquet.

    Handles:
    - NetCDF file reading with xarray
    - Unit conversions (Kelvin to Celsius)
    - Wind speed calculation from U/V components
    - Direct conversion to Parquet (no intermediate CSV)
    - Hive-style partitioning by date (date=YYYY-MM-DD)
    """

    def __init__(
        self,
        transform_config: TransformConfig,
        storage_config: StorageConfig,
        output_dir: Path,
        dataset: str | None = None,
    ) -> None:
        """Initialize the converter.

        Args:
            transform_config: Transformation settings
            storage_config: Storage/compression settings
            output_dir: Directory for Parquet output
            dataset: Dataset name (era5/era5-land). When set, latitude and
                longitude are rounded to the dataset's grid precision
                (ERA5=2dp, ERA5-LAND=1dp) and cast to Float32 before
                writing. ``None`` keeps the legacy dataset-agnostic path
                (used by unit tests that feed synthetic frames).
        """
        self.transform_config = transform_config
        self.storage_config = storage_config
        self.output_dir = output_dir
        self.dataset = dataset
        self.logger = logging.getLogger(__name__)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def convert_file(self, netcdf_file: Path) -> Path:
        """Convert a single NetCDF file to partitioned Parquet.

        Args:
            netcdf_file: Path to input NetCDF file

        Returns:
            Path to output Parquet directory

        Raises:
            ProcessingError: If conversion fails
        """
        self.logger.info(f"Converting: {netcdf_file.name}")

        try:
            ds = xr.open_dataset(netcdf_file, engine="netcdf4")
            ds = self._process_dataset(ds)
            df = self._dataset_to_dataframe(ds)
            ds.close()

            df = self._drop_unused_columns(df)
            df = self._round_latlon(df)
            df = self._apply_float_precision(df)

            self._write_partitioned_parquet(df)

            self.logger.info(f"Converted: {netcdf_file.name} -> {len(df):,} rows")
            return self.output_dir

        except Exception as e:
            raise ProcessingError(
                f"NetCDF to Parquet conversion failed for {netcdf_file}: {e}"
            ) from e

    def convert_directory(
        self,
        input_dir: Path,
        max_workers: int | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        cleanup: bool = False,
    ) -> dict[str, int]:
        """Convert all NetCDF files in a directory.

        Uses ProcessPoolExecutor for parallel conversion when multiple files exist.

        Args:
            input_dir: Directory containing .nc files
            max_workers: Maximum number of worker processes (None=auto based on CPU count)
            on_progress: Optional ``(files_done, files_total, message)`` callback,
                invoked from the main process after each file completes (both
                sequential and parallel paths). Used by the web UI to drive a
                conversion progress bar.
            cleanup: When True, delete each ``.nc`` file immediately after it
                converts **successfully**. Files that FAILED to convert are
                kept on disk so the user can inspect/retry them. Deletion
                happens in the main process (safe under the parallel path).

        Returns:
            Statistics dict with counts
        """
        netcdf_files = sorted(input_dir.glob("*.nc"))
        if not netcdf_files:
            self.logger.warning(f"No NetCDF files found in {input_dir}")
            if on_progress is not None:
                on_progress(0, 0, "No NetCDF files to convert")
            return {"total": 0, "converted": 0, "skipped": 0, "failed": 0}

        self.logger.info(f"Found {len(netcdf_files)} NetCDF files to convert")

        total = len(netcdf_files)
        stats = {"total": total, "converted": 0, "skipped": 0, "failed": 0}
        done = 0

        def _cleanup(nc_file: Path) -> None:
            if not cleanup:
                return
            try:
                nc_file.unlink()
                self.logger.debug("Removed temp NetCDF %s", nc_file.name)
            except OSError as exc:
                self.logger.warning(
                    "Could not delete temp NetCDF %s: %s", nc_file.name, exc
                )

        def _tick(name: str) -> None:
            nonlocal done
            done += 1
            if on_progress is not None:
                on_progress(done, total, f"Converted {done}/{total}: {name}")

        if on_progress is not None:
            on_progress(0, total, f"Converting {total} file(s) to Parquet")

        if len(netcdf_files) == 1 or max_workers == 1:
            # Single file or explicit single-worker mode: convert sequentially
            for nc_file in netcdf_files:
                try:
                    self.convert_file(nc_file)
                    stats["converted"] += 1
                    _cleanup(nc_file)
                except Exception as e:
                    stats["failed"] += 1
                    self.logger.error(f"Failed: {nc_file.name}: {e}")
                _tick(nc_file.name)
        else:
            # Parallel conversion
            from concurrent.futures import ProcessPoolExecutor, as_completed

            effective_workers = max_workers  # None lets ProcessPoolExecutor choose

            self.logger.info(
                f"Starting parallel conversion with "
                f"{effective_workers or 'auto'} workers"
            )

            futures = {}
            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                for nc_file in netcdf_files:
                    future = executor.submit(
                        _convert_single_file,
                        nc_file,
                        self.transform_config,
                        self.storage_config,
                        self.output_dir,
                        self.dataset,
                    )
                    futures[future] = nc_file

                for future in as_completed(futures):
                    nc_file = futures[future]
                    try:
                        filename, success, error_msg = future.result()
                        if success:
                            stats["converted"] += 1
                            self.logger.info(f"Converted: {filename}")
                            _cleanup(nc_file)
                        else:
                            stats["failed"] += 1
                            self.logger.error(f"Failed: {filename}: {error_msg}")
                    except Exception as e:
                        stats["failed"] += 1
                        self.logger.error(f"Failed: {nc_file.name}: {e}")
                    _tick(nc_file.name)

        self.logger.info(
            f"Conversion complete: {stats['converted']} converted, "
            f"{stats['skipped']} skipped, {stats['failed']} failed"
        )

        # After a fully successful run, remove the now-empty temp tree:
        # the per-dataset dir and its `_tmp_netcdf` parent (only if empty,
        # so a sibling dataset's temp dir is never clobbered). Skipped when
        # any file failed -- those .nc were intentionally kept for retry.
        if cleanup and stats["failed"] == 0:
            self._remove_empty_temp_tree(input_dir)

        return stats

    def _remove_empty_temp_tree(self, input_dir: Path) -> None:
        """rmdir ``input_dir`` and its ``_tmp_netcdf`` parent if both empty.

        Uses ``Path.rmdir`` (not ``rmtree``) so a non-empty directory --
        e.g. one still holding a failed .nc -- is left untouched.
        """
        from era5_etl.storage.paths import NETCDF_TMP_DIRNAME

        try:
            input_dir.rmdir()
            self.logger.info("Removed empty temp dir %s", input_dir)
        except OSError:
            return  # not empty (failed files) or already gone -- keep it
        parent = input_dir.parent
        if parent.name == NETCDF_TMP_DIRNAME:
            try:
                parent.rmdir()
                self.logger.info("Removed empty temp dir %s", parent)
            except OSError:
                pass  # another dataset's temp dir still present

    def _process_dataset(self, ds: xr.Dataset) -> xr.Dataset:
        """Apply transforms: rename variables, convert units, calc wind speed."""
        ds = self._rename_variables(ds)
        if self.transform_config.convert_kelvin_to_celsius:
            ds = self._convert_temperature(ds)
        if self.transform_config.calculate_wind_speed:
            ds = self._calculate_wind_speed(ds)
        return ds

    def _rename_variables(self, ds: xr.Dataset) -> xr.Dataset:
        """Rename variables from NetCDF short names to friendly names."""
        var_map = get_var_name_map()
        rename_map = {}
        for var in ds.data_vars:
            if str(var) in var_map:
                rename_map[var] = var_map[str(var)]
        if rename_map:
            ds = ds.rename(rename_map)
            self.logger.debug(f"Renamed variables: {rename_map}")
        return ds

    def _convert_temperature(self, ds: xr.Dataset) -> xr.Dataset:
        """Convert temperature variables from Kelvin to Celsius."""
        temp_vars = [
            var
            for var in ds.data_vars
            if "temperature" in str(var).lower() or "temp" in str(var).lower()
        ]
        for var in temp_vars:
            attrs = ds[var].attrs
            if attrs.get("units") in ["K", "Kelvin"]:
                ds[var] = ds[var] + KELVIN_TO_CELSIUS
                ds[var].attrs = attrs
                ds[var].attrs["units"] = "°C"
                self.logger.debug(f"Converted {var} from Kelvin to Celsius")
        return ds

    def _calculate_wind_speed(self, ds: xr.Dataset) -> xr.Dataset:
        """Calculate wind speed from U/V components."""
        u_vars = [var for var in ds.data_vars if "wind_u" in str(var).lower()]
        v_vars = [var for var in ds.data_vars if "wind_v" in str(var).lower()]

        if u_vars and v_vars:
            for u_var, v_var in zip(u_vars, v_vars, strict=False):
                wind_speed: xr.DataArray = np.sqrt(ds[u_var] ** 2 + ds[v_var] ** 2)  # type: ignore[assignment]
                wind_speed.attrs["units"] = ds[u_var].attrs.get("units", "m/s")
                wind_speed.attrs["long_name"] = "Wind speed"
                wind_var_name = str(u_var).replace("_u_", "_speed_")
                ds[wind_var_name] = wind_speed
                self.logger.debug(f"Calculated {wind_var_name} from {u_var} and {v_var}")
        return ds

    def _drop_unused_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """Drop the CDS ``number`` / ``expver`` coords if present (M03).

        Defensive: older NetCDF without them is unaffected.
        """
        to_drop = [c for c in _UNUSED_NETCDF_COLS if c in df.columns]
        if to_drop:
            self.logger.debug("Dropping unused NetCDF columns: %s", to_drop)
            df = df.drop(to_drop)
        return df

    def _round_latlon(self, df: pl.DataFrame) -> pl.DataFrame:
        """Round latitude/longitude to the dataset grid precision as Float32.

        ERA5 (0.25 deg) -> 2 dp, ERA5-LAND (0.1 deg) -> 1 dp. No-op when the
        converter was built without a ``dataset`` (legacy dataset-agnostic
        path used by synthetic-frame unit tests). Runs before
        ``_apply_float_precision``; since lat/lon are then already Float32,
        that method (which only touches Float64) leaves them untouched --
        no double rounding.
        """
        if self.dataset is None:
            return df
        if not ({"latitude", "longitude"} <= set(df.columns)):
            return df
        dec = DatasetRegistry.get(self.dataset).latlon_decimals
        return df.with_columns(
            [
                pl.col("latitude").round(dec).cast(pl.Float32),
                pl.col("longitude").round(dec).cast(pl.Float32),
            ]
        )

    def _apply_float_precision(self, df: pl.DataFrame) -> pl.DataFrame:
        """Cast Float64 columns to Float32 and round to configured decimal places.

        Reads precision configuration from the YAML config file:
        - enabled: Whether to apply precision reduction (default True)
        - decimal_places: Number of decimal places to keep (default 4)

        All Float64 (DOUBLE) columns are rounded and then cast to Float32.
        """
        from era5_etl.utils.variables import get_float_precision_config

        precision_config = get_float_precision_config()
        if not precision_config.get("enabled", True):
            return df

        decimal_places = precision_config.get("decimal_places", 4)

        float64_cols = [
            col for col in df.columns
            if df[col].dtype == pl.Float64
        ]

        if float64_cols:
            df = df.with_columns([
                pl.col(col).round(decimal_places).cast(pl.Float32).alias(col)
                for col in float64_cols
            ])
            self.logger.debug(
                f"Applied float precision: {len(float64_cols)} columns "
                f"rounded to {decimal_places} decimal places and cast to Float32"
            )

        return df

    def _dataset_to_dataframe(self, ds: xr.Dataset) -> pl.DataFrame:
        """Convert xarray Dataset to Polars DataFrame with date and hour_utc columns.

        Creates:
            - date (Date): Date extracted from the time/valid_time column
            - hour_utc (Int8): Hour (UTC) as integer from the time/valid_time column

        The original time/valid_time column is dropped from the output.
        """
        df_pandas = ds.to_dataframe().reset_index()
        df = pl.from_pandas(df_pandas)

        # Determine the time source column: prefer "valid_time", fall back to "time"
        time_col = None
        if "valid_time" in df.columns:
            time_col = "valid_time"
        elif "time" in df.columns:
            time_col = "time"

        if time_col:
            df = df.with_columns([
                pl.col(time_col).cast(pl.Date).alias("date"),
                pl.col(time_col).dt.hour().cast(pl.Int8).alias("hour_utc"),
            ])
            # Drop original time columns from output
            cols_to_drop = [c for c in ["time", "valid_time"] if c in df.columns]
            df = df.drop(cols_to_drop)

        return df

    def _write_partitioned_parquet(self, df: pl.DataFrame) -> None:
        """Write DataFrame to Hive-partitioned Parquet files.

        Delegates to :func:`merge_into_partitioned_parquet`, which merges
        against any existing partition data on ``(latitude, longitude,
        hour_utc)``. Two downloads covering the same grid cell at the same
        date+hour collapse into one row, so overlapping IBGE regions
        (e.g., SP + RJ) never produce duplicates.

        Falls back to a single ``data.parquet`` file when ``date`` is absent
        from the input (legacy non-partitioned mode).
        """
        if "date" in df.columns and "date" in self.storage_config.partition_cols:
            from era5_etl.storage.parquet_manager import merge_into_partitioned_parquet

            merge_into_partitioned_parquet(
                df,
                self.output_dir,
                compression=self.storage_config.parquet_compression,
                logger=self.logger,
            )
        else:
            output_file = self.output_dir / "data.parquet"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(
                output_file,
                compression=self.storage_config.parquet_compression,
            )

    def __repr__(self) -> str:
        """String representation."""
        return f"NetCDFToParquetConverter(output_dir={self.output_dir})"
