"""NetCDF processor for ERA5/ERA5-Land data."""

import logging
from pathlib import Path

import numpy as np
import polars as pl
import xarray as xr

from pyera5.config import ProcessingConfig
from pyera5.constants import KELVIN_TO_CELSIUS, VAR_NAME_MAP
from pyera5.exceptions import ProcessingError


class NetCDFProcessor:
    """Process ERA5/ERA5-Land NetCDF files.

    Handles:
    - NetCDF file reading with xarray
    - Unit conversions (Kelvin to Celsius)
    - Wind speed calculation from U/V components
    - Temporal resampling
    - Conversion to tabular format (Polars DataFrame)
    """

    def __init__(self, config: ProcessingConfig) -> None:
        """Initialize the processor.

        Args:
            config: Processing configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Create output directory
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    def process_file(self, netcdf_file: Path) -> Path:
        """Process a single NetCDF file to CSV.

        Args:
            netcdf_file: Path to input NetCDF file

        Returns:
            Path to processed CSV file

        Raises:
            ProcessingError: If processing fails
        """
        output_file = self.config.output_dir / f"{netcdf_file.stem}_processed.csv"

        # Skip if already processed
        if output_file.exists() and not self.config.override:
            self.logger.debug(f"Skipping (already processed): {netcdf_file.name}")
            return output_file

        self.logger.info(f"Processing: {netcdf_file.name}")

        try:
            # Read NetCDF file
            ds = xr.open_dataset(netcdf_file, engine="netcdf4")

            # Process dataset
            ds = self._process_dataset(ds)

            # Convert to DataFrame
            df = self._dataset_to_dataframe(ds)

            # Close dataset
            ds.close()

            # Write CSV
            df.write_csv(output_file)

            self.logger.info(
                f"Processed: {output_file.name} ({len(df):,} rows, "
                f"{output_file.stat().st_size / 1024:.2f} KB)"
            )

            return output_file

        except Exception as e:
            self.logger.error(f"Failed to process {netcdf_file}: {e}")
            raise ProcessingError(f"Processing failed for {netcdf_file}: {e}") from e

    def process_directory(self, skip_errors: bool = True) -> dict[str, int]:
        """Process all NetCDF files in input directory.

        Args:
            skip_errors: Skip files that fail processing

        Returns:
            Statistics dict with counts
        """
        netcdf_files = list(self.config.input_dir.glob("*.nc"))

        if not netcdf_files:
            self.logger.warning(f"No NetCDF files found in {self.config.input_dir}")
            return {"total": 0, "processed": 0, "skipped": 0, "failed": 0}

        self.logger.info(f"Found {len(netcdf_files)} NetCDF files to process")

        stats = {"total": len(netcdf_files), "processed": 0, "skipped": 0, "failed": 0}

        for netcdf_file in netcdf_files:
            output_file = self.config.output_dir / f"{netcdf_file.stem}_processed.csv"

            # Check if already processed
            if output_file.exists() and not self.config.override:
                stats["skipped"] += 1
                continue

            try:
                self.process_file(netcdf_file)
                stats["processed"] += 1
            except Exception as e:
                stats["failed"] += 1
                if not skip_errors:
                    raise
                self.logger.error(f"Skipped {netcdf_file.name}: {e}")

        self.logger.info(
            f"Processing complete: {stats['processed']} processed, "
            f"{stats['skipped']} skipped, {stats['failed']} failed"
        )

        return stats

    def _process_dataset(self, ds: xr.Dataset) -> xr.Dataset:
        """Process xarray dataset.

        Args:
            ds: Input dataset

        Returns:
            Processed dataset
        """
        # Rename variables to friendly names
        ds = self._rename_variables(ds)

        # Convert temperature from Kelvin to Celsius
        if self.config.convert_kelvin_to_celsius:
            ds = self._convert_temperature(ds)

        # Calculate wind speed from U/V components
        if self.config.calculate_wind_speed:
            ds = self._calculate_wind_speed(ds)

        # Resample if configured
        if self.config.resample_frequency:
            ds = ds.resample(time=self.config.resample_frequency).mean()

        return ds

    def _rename_variables(self, ds: xr.Dataset) -> xr.Dataset:
        """Rename variables to friendly names.

        Args:
            ds: Input dataset

        Returns:
            Dataset with renamed variables
        """
        rename_map = {}

        for var in ds.data_vars:
            if str(var) in VAR_NAME_MAP:
                rename_map[var] = VAR_NAME_MAP[str(var)]

        if rename_map:
            ds = ds.rename(rename_map)
            self.logger.debug(f"Renamed variables: {rename_map}")

        return ds

    def _convert_temperature(self, ds: xr.Dataset) -> xr.Dataset:
        """Convert temperature variables from Kelvin to Celsius.

        Args:
            ds: Input dataset

        Returns:
            Dataset with converted temperatures
        """
        temp_vars = [
            var
            for var in ds.data_vars
            if "temperature" in str(var).lower() or "temp" in str(var).lower()
        ]

        for var in temp_vars:
            if ds[var].units in ["K", "Kelvin"]:
                ds[var] = ds[var] + KELVIN_TO_CELSIUS
                ds[var].attrs["units"] = "°C"
                self.logger.debug(f"Converted {var} from Kelvin to Celsius")

        return ds

    def _calculate_wind_speed(self, ds: xr.Dataset) -> xr.Dataset:
        """Calculate wind speed from U/V components.

        Args:
            ds: Input dataset

        Returns:
            Dataset with wind speed variable
        """
        # Look for U and V wind components
        u_vars = [var for var in ds.data_vars if "wind_u" in str(var).lower()]
        v_vars = [var for var in ds.data_vars if "wind_v" in str(var).lower()]

        if u_vars and v_vars:
            for u_var, v_var in zip(u_vars, v_vars):
                # Calculate wind speed: sqrt(u^2 + v^2)
                wind_speed = np.sqrt(ds[u_var] ** 2 + ds[v_var] ** 2)
                wind_speed.attrs["units"] = ds[u_var].attrs.get("units", "m/s")
                wind_speed.attrs["long_name"] = "Wind speed"

                # Add to dataset
                wind_var_name = str(u_var).replace("_u_", "_speed_")
                ds[wind_var_name] = wind_speed

                self.logger.debug(f"Calculated {wind_var_name} from {u_var} and {v_var}")

        return ds

    def _dataset_to_dataframe(self, ds: xr.Dataset) -> pl.DataFrame:
        """Convert xarray dataset to Polars DataFrame.

        Args:
            ds: Input dataset

        Returns:
            Polars DataFrame
        """
        # Convert to pandas DataFrame (flatten spatial dimensions)
        df_pandas = ds.to_dataframe().reset_index()

        # Convert to Polars
        df = pl.from_pandas(df_pandas)

        # Add year, month, day columns
        if "time" in df.columns:
            df = df.with_columns([
                pl.col("time").dt.year().alias("year"),
                pl.col("time").dt.month().alias("month"),
                pl.col("time").dt.day().alias("day"),
                pl.col("time").dt.hour().alias("hour"),
            ])

        return df

    def __repr__(self) -> str:
        """String representation."""
        return f"NetCDFProcessor(input_dir={self.config.input_dir})"
