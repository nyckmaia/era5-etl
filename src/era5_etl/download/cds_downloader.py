"""CDS API downloader for ERA5/ERA5-Land data."""

import calendar
import logging
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

import cdsapi
from tqdm import tqdm

from era5_etl.config import DownloadConfig
from era5_etl.download.size_estimator import (
    calculate_splits_needed,
    estimate_request_size,
    split_area,
)
from era5_etl.exceptions import CDSAPIError, DownloadError


class CDSDownloader:
    """Download ERA5/ERA5-Land data from Copernicus Climate Data Store.

    Uses the CDS API to download ERA5 reanalysis and ERA5-Land data.
    Requires valid CDS API credentials configured in ~/.cdsapirc
    or via CDSAPI_URL/CDSAPI_KEY environment variables.
    """

    def __init__(self, config: DownloadConfig) -> None:
        """Initialize the downloader.

        Args:
            config: Download configuration

        Raises:
            CDSAPIError: If CDS API credentials are missing or client init fails
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Create output directory
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Validate credentials before initializing client
        self._validate_credentials()

        # Initialize CDS API client
        try:
            self.client = cdsapi.Client(timeout=config.timeout)
        except Exception as e:
            raise CDSAPIError(f"Failed to initialize CDS API client: {e}") from e

    def _validate_credentials(self) -> None:
        """Validate CDS API credentials exist.

        Checks for ~/.cdsapirc file or CDSAPI_URL/CDSAPI_KEY env vars.

        Raises:
            CDSAPIError: If no credentials are found
        """
        # Check environment variables
        has_env = os.environ.get("CDSAPI_URL") and os.environ.get("CDSAPI_KEY")
        if has_env:
            return

        # Check ~/.cdsapirc file
        cdsapirc = Path.home() / ".cdsapirc"
        if cdsapirc.exists():
            return

        raise CDSAPIError(
            "CDS API credentials not found. Either:\n"
            "  1. Create ~/.cdsapirc with url and key fields, or\n"
            "  2. Set CDSAPI_URL and CDSAPI_KEY environment variables.\n"
            "See: https://cds.climate.copernicus.eu/how-to-api"
        )

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

    def _estimate_and_split(self, year: int, month: int) -> list[list[float]]:
        """Estimate request size and split area if it exceeds the limit.

        Args:
            year: Year for the download period.
            month: Month for the download period.

        Returns:
            List of area bounds. Single-element list if no split needed,
            multiple elements if the area was split into sub-regions.
        """
        _, num_days = calendar.monthrange(year, month)

        estimate = estimate_request_size(
            num_variables=len(self.config.variables),
            num_hours=len(self.config.hours),
            num_days=num_days,
            area=self.config.area,
            dataset=self.config.dataset,
            max_bytes=self.config.max_request_bytes,
        )

        self.logger.info(
            f"Size estimate for {year}-{month:02d}: "
            f"{estimate.estimated_mb:.1f} MB "
            f"({estimate.num_grid_points:,} grid points, "
            f"{estimate.num_variables} vars, "
            f"{estimate.num_hours} hours/day, "
            f"{estimate.num_days} days)"
        )

        if estimate.exceeds_limit:
            num_splits = calculate_splits_needed(estimate)
            splits = split_area(self.config.area, num_splits)
            self.logger.warning(
                f"Request exceeds {estimate.limit_mb:.0f} MB limit. "
                f"Splitting area into {len(splits)} sub-regions."
            )
            return [s.as_list() for s in splits]

        return [self.config.area]

    def _download_period(self, year: int, month: int) -> Path:
        """Download data for a specific year and month.

        If the request is too large, the geographic area is automatically
        split into sub-regions. Each sub-region is downloaded as a separate
        NetCDF file and stored with a region suffix.

        Args:
            year: Year to download.
            month: Month to download.

        Returns:
            Path to downloaded file (or first file if split).

        Raises:
            DownloadError: If download fails after all retries.
        """
        dataset_short = self.config.dataset.replace("-", "")
        output_file = self.config.output_dir / f"{dataset_short}_{year}{month:02d}.nc"

        # Skip if already exists
        if output_file.exists() and not self.config.override:
            self.logger.debug(f"Skipping (already exists): {output_file.name}")
            return output_file

        self.logger.info(f"Downloading: {year}-{month:02d}")

        # Estimate size and split if needed
        areas = self._estimate_and_split(year, month)

        downloaded_files: list[Path] = []
        for idx, area in enumerate(areas):
            if len(areas) > 1:
                suffix = f"_part{idx + 1}"
                part_file = self.config.output_dir / f"{dataset_short}_{year}{month:02d}{suffix}.nc"
                self.logger.info(
                    f"Downloading sub-region {idx + 1}/{len(areas)}: "
                    f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}"
                )
            else:
                part_file = output_file

            if part_file.exists() and not self.config.override:
                self.logger.debug(f"Skipping (already exists): {part_file.name}")
                downloaded_files.append(part_file)
                continue

            temp_file = self.config.output_dir / f"temp_{year}{month:02d}_p{idx}.download"
            temp_dir = self.config.output_dir / f"temp_extract_{year}{month:02d}_p{idx}"

            try:
                request = self._build_cds_request(year, month)
                request["area"] = area  # Override with sub-region area

                self._retrieve_with_retry(request, temp_file, year, month)
                self._process_downloaded_file(temp_file, temp_dir, part_file)
                downloaded_files.append(part_file)

            except Exception as e:
                self.logger.error(f"Download failed for {year}-{month:02d} part {idx + 1}: {e}")
                # Clean up partial downloads
                for f in [temp_file, part_file]:
                    if f.exists():
                        f.unlink()
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                raise DownloadError(
                    f"Failed to download {year}-{month:02d} part {idx + 1}: {e}"
                ) from e

        return downloaded_files[0] if downloaded_files else output_file

    def _process_downloaded_file(
        self, temp_file: Path, temp_dir: Path, output_file: Path
    ) -> None:
        """Process a downloaded file: handle ZIP extraction or rename.

        Args:
            temp_file: Path to the temporary downloaded file.
            temp_dir: Directory for ZIP extraction.
            output_file: Final output path.
        """
        if zipfile.is_zipfile(temp_file):
            self.logger.info("ZIP file detected, extracting...")
            temp_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(temp_file, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            nc_files = list(temp_dir.glob("*.nc"))
            if not nc_files:
                raise RuntimeError("No .nc file found in ZIP archive!")

            if len(nc_files) > 1:
                self.logger.warning(
                    f"Multiple .nc files found ({len(nc_files)}), using first one"
                )

            shutil.move(str(nc_files[0]), str(output_file))
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_file.unlink()
        else:
            temp_file.rename(output_file)

        self.logger.info(
            f"Downloaded: {output_file.name} "
            f"({output_file.stat().st_size / 1024 / 1024:.2f} MB)"
        )

    def _retrieve_with_retry(
        self,
        request: dict[str, object],
        target: Path,
        year: int,
        month: int,
    ) -> None:
        """Download from CDS API with exponential backoff retry.

        Args:
            request: CDS API request dictionary
            target: Path to save downloaded file
            year: Year (for logging)
            month: Month (for logging)

        Raises:
            DownloadError: If all retries are exhausted
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                self.client.retrieve(
                    self.config.get_cds_dataset_name(),
                    request,
                    str(target),
                )
                return
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay * (2**attempt)
                    self.logger.warning(
                        f"Attempt {attempt + 1}/{self.config.max_retries + 1} "
                        f"failed for {year}-{month:02d}, "
                        f"retrying in {delay:.0f}s: {e}"
                    )
                    time.sleep(delay)

        raise DownloadError(
            f"All {self.config.max_retries + 1} attempts failed "
            f"for {year}-{month:02d}: {last_error}"
        )

    def _build_cds_request(self, year: int, month: int) -> dict[str, object]:
        """Build CDS API request dictionary.

        Args:
            year: Year
            month: Month

        Returns:
            CDS API request dictionary
        """
        # Get days in month
        _, num_days = calendar.monthrange(year, month)
        days = list(range(1, num_days + 1))

        # Build request
        request: dict[str, object] = {
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
