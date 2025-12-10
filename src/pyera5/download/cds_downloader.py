"""CDS API downloader for ERA5/ERA5-Land data."""

import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import cdsapi
from tqdm import tqdm

from pyera5.config import DownloadConfig
from pyera5.exceptions import CDSAPIError, DownloadError


class CDSDownloader:
    """Download ERA5/ERA5-Land data from Copernicus Climate Data Store.

    Uses the CDS API to download ERA5 reanalysis and ERA5-Land data.
    Requires valid CDS API credentials configured in ~/.cdsapirc
    """

    def __init__(self, config: DownloadConfig) -> None:
        """Initialize the downloader.

        Args:
            config: Download configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Create output directory
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize CDS API client
        try:
            self.client = cdsapi.Client(timeout=config.timeout)
        except Exception as e:
            raise CDSAPIError(f"Failed to initialize CDS API client: {e}") from e

    def download(self) -> list[Path]:
        """Download ERA5/ERA5-Land data for configured period.

        Returns:
            List of downloaded file paths

        Raises:
            DownloadError: If download fails
        """
        self.logger.info("Starting ERA5 data download from CDS")

        # Parse dates
        start_date = datetime.strptime(self.config.start_date, "%Y-%m-%d")
        if self.config.end_date:
            end_date = datetime.strptime(self.config.end_date, "%Y-%m-%d")
        else:
            end_date = datetime.now()

        # Generate list of years and months to download
        download_periods = self._generate_download_periods(start_date, end_date)

        self.logger.info(
            f"Downloading {len(download_periods)} period(s) from "
            f"{start_date.date()} to {end_date.date()}"
        )

        downloaded_files: list[Path] = []

        # Download each period
        for year, month in tqdm(download_periods, desc="Downloading periods"):
            try:
                output_file = self._download_period(year, month)
                downloaded_files.append(output_file)
            except Exception as e:
                self.logger.error(f"Failed to download {year}-{month:02d}: {e}")
                if not self.config.override:
                    raise DownloadError(f"Download failed for {year}-{month:02d}: {e}") from e

        self.logger.info(f"Downloaded {len(downloaded_files)} files successfully")
        return downloaded_files

    def _generate_download_periods(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[int, int]]:
        """Generate list of (year, month) tuples to download.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of (year, month) tuples
        """
        periods = []
        current = start_date

        while current <= end_date:
            periods.append((current.year, current.month))

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return periods

    def _download_period(self, year: int, month: int) -> Path:
        """Download data for a specific year and month.

        Args:
            year: Year to download
            month: Month to download

        Returns:
            Path to downloaded file

        Raises:
            DownloadError: If download fails
        """
        # Build output filename
        dataset_short = self.config.dataset.replace("-", "")
        output_file = (
            self.config.output_dir / f"{dataset_short}_{year}{month:02d}.nc"
        )

        # Skip if already exists
        if output_file.exists() and not self.config.override:
            self.logger.debug(f"Skipping (already exists): {output_file.name}")
            return output_file

        self.logger.info(f"Downloading: {year}-{month:02d}")

        # Use temporary file for download
        temp_file = self.config.output_dir / f"temp_{year}{month:02d}.download"
        temp_dir = self.config.output_dir / f"temp_extract_{year}{month:02d}"

        try:
            # Build CDS API request
            request = self._build_cds_request(year, month)

            # Download using CDS API
            self.client.retrieve(
                self.config.get_cds_dataset_name(),
                request,
                str(temp_file),
            )

            # Check if downloaded file is a ZIP
            if zipfile.is_zipfile(temp_file):
                self.logger.info("ZIP file detected, extracting...")
                temp_dir.mkdir(exist_ok=True)

                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                # Find .nc files
                nc_files = list(temp_dir.glob("*.nc"))

                if not nc_files:
                    raise RuntimeError("No .nc file found in ZIP archive!")

                if len(nc_files) == 1:
                    # Move single file to output
                    shutil.move(str(nc_files[0]), str(output_file))
                    self.logger.info(f"Extracted single file: {output_file.name}")
                else:
                    # Multiple files - use first one or merge them
                    # For now, just use the first file
                    self.logger.warning(
                        f"Multiple .nc files found ({len(nc_files)}), using first one"
                    )
                    shutil.move(str(nc_files[0]), str(output_file))

                # Clean up temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)
                temp_file.unlink()
            else:
                # Not a ZIP, just rename to final name
                temp_file.rename(output_file)

            self.logger.info(
                f"Downloaded: {output_file.name} "
                f"({output_file.stat().st_size / 1024 / 1024:.2f} MB)"
            )

            return output_file

        except Exception as e:
            self.logger.error(f"Download failed for {year}-{month:02d}: {e}")
            # Clean up partial downloads
            if temp_file.exists():
                temp_file.unlink()
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if output_file.exists():
                output_file.unlink()
            raise DownloadError(f"Failed to download {year}-{month:02d}: {e}") from e

    def _build_cds_request(self, year: int, month: int) -> dict:
        """Build CDS API request dictionary.

        Args:
            year: Year
            month: Month

        Returns:
            CDS API request dictionary
        """
        # Get days in month
        if month in [1, 3, 5, 7, 8, 10, 12]:
            days = list(range(1, 32))
        elif month in [4, 6, 9, 11]:
            days = list(range(1, 31))
        else:  # February
            # Simple leap year check
            if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
                days = list(range(1, 30))
            else:
                days = list(range(1, 29))

        # Build request
        request = {
            "product_type": "reanalysis",
            "data_format": "netcdf",
            "download_format": "unarchived",
            "variable": self.config.variables,
            "year": str(year),
            "month": f"{month:02d}",
            "day": [f"{d:02d}" for d in days],
            "time": self.config.hours,
            "area": self.config.area,  # [North, West, South, East]
        }

        return request

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"CDSDownloader(dataset={self.config.dataset}, "
            f"output_dir={self.config.output_dir})"
        )
