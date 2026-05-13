"""CDS API downloader for ERA5/ERA5-Land data.

The download is driven by a list of :class:`RequestChunk` produced by
:func:`era5_etl.download.request_planner.plan_requests`. Each chunk fits the
configured Request size budget; the downloader iterates over them, retries
on failure, and rewrites ZIP responses to plain NetCDF.
"""

from __future__ import annotations

import calendar
import logging
import os
import shutil
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cdsapi
from tqdm import tqdm

from era5_etl.config import DownloadConfig
from era5_etl.download.cds_log_capture import CDSEventCapture
from era5_etl.download.request_planner import RequestChunk, plan_requests
from era5_etl.exceptions import CDSAPIError, DownloadError
from era5_etl.storage.manifest import ChunkRecord, Manifest

# CDS only accepts the literal string "netcdf"; never GRIB in this project.
_CDS_DATA_FORMAT = "netcdf"
_CDS_DOWNLOAD_FORMAT = "unarchived"


class CDSDownloader:
    """Download ERA5/ERA5-Land data from Copernicus Climate Data Store."""

    def __init__(
        self,
        config: DownloadConfig,
        manifest: Manifest | None = None,
        on_event: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> None:
        self.config = config
        self.manifest = manifest
        self.on_event = on_event
        self.logger = logging.getLogger(__name__)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        self._validate_credentials()
        try:
            self.client = cdsapi.Client(timeout=config.timeout)
        except Exception as e:  # pragma: no cover - exercised via mocks elsewhere
            raise CDSAPIError(f"Failed to initialize CDS API client: {e}") from e

    # ---- credential check --------------------------------------------------

    def _validate_credentials(self) -> None:
        if os.environ.get("CDSAPI_URL") and os.environ.get("CDSAPI_KEY"):
            return
        if (Path.home() / ".cdsapirc").exists():
            return
        raise CDSAPIError(
            "CDS API credentials not found. Either:\n"
            "  1. Create ~/.cdsapirc with url and key fields, or\n"
            "  2. Set CDSAPI_URL and CDSAPI_KEY environment variables.\n"
            "See: https://cds.climate.copernicus.eu/how-to-api"
        )

    # ---- public API --------------------------------------------------------

    def download(self) -> list[Path]:
        """Download every chunk planned for the current configuration."""
        chunks = plan_requests(self.config)
        self.logger.info(
            "Starting CDS download: %d chunk(s), dataset=%s",
            len(chunks),
            self.config.dataset,
        )
        return self._download_all(chunks)

    def download_chunks(self, chunks: list[RequestChunk]) -> list[Path]:
        """Download a pre-built list of chunks (used by the ``update`` command)."""
        return self._download_all(chunks)

    def _download_all(self, chunks: list[RequestChunk]) -> list[Path]:
        capture: CDSEventCapture | None = None
        cdsapi_logger = logging.getLogger("cdsapi")
        if self.on_event is not None:
            capture = CDSEventCapture(self.on_event)
            cdsapi_logger.addHandler(capture)
            # Ensure cdsapi.INFO messages reach our handler even if upstream
            # configured the logger at WARNING.
            if cdsapi_logger.level > logging.INFO or cdsapi_logger.level == 0:
                self._prev_cdsapi_level: int | None = cdsapi_logger.level
                cdsapi_logger.setLevel(logging.INFO)
            else:
                self._prev_cdsapi_level = None

        downloaded: list[Path] = []
        total = len(chunks)
        try:
            for idx, chunk in enumerate(chunks, start=1):
                if capture is not None:
                    capture.set_chunk_context(chunk.chunk_id, idx, total)
                self._emit(
                    {
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": idx,
                        "chunks_total": total,
                        "phase": "submitting",
                        "message": f"Submitting {chunk.chunk_id} to CDS",
                    }
                )
                try:
                    downloaded.append(self._download_chunk(chunk))
                except DownloadError as exc:
                    self._emit(
                        {
                            "chunk_id": chunk.chunk_id,
                            "chunk_index": idx,
                            "chunks_total": total,
                            "phase": "failed",
                            "message": str(exc),
                        }
                    )
                    if self.config.override:
                        self.logger.warning(
                            "Continuing past failed chunk %s", chunk.chunk_id
                        )
                        continue
                    raise
                self._emit(
                    {
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": idx,
                        "chunks_total": total,
                        "phase": "completed",
                        "message": f"{chunk.chunk_id} done",
                    }
                )
        finally:
            if capture is not None:
                cdsapi_logger.removeHandler(capture)
                prev_level = getattr(self, "_prev_cdsapi_level", None)
                if prev_level is not None:
                    cdsapi_logger.setLevel(prev_level)

        self.logger.info("Downloaded %d/%d chunk(s)", len(downloaded), total)
        return downloaded

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(payload)
        except Exception:  # pragma: no cover - never crash the downloader
            self.logger.exception("Progress callback raised")

    # ---- chunk download ----------------------------------------------------

    def _download_chunk(self, chunk: RequestChunk) -> Path:
        output_file = self.config.output_dir / f"{chunk.chunk_id}.nc"
        if output_file.exists() and not self.config.override:
            self.logger.debug("Skipping (already exists): %s", output_file.name)
            return output_file

        temp_file = self.config.output_dir / f".tmp_{chunk.chunk_id}.download"
        temp_dir = self.config.output_dir / f".tmp_extract_{chunk.chunk_id}"

        request = self._build_cds_request_from_chunk(chunk)
        try:
            self._retrieve_with_retry(request, temp_file, chunk.year, chunk.month)
            self._process_downloaded_file(temp_file, temp_dir, output_file)
        except Exception as exc:
            for p in (temp_file, output_file):
                if p.exists():
                    p.unlink(missing_ok=True)
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise DownloadError(
                f"Failed to download chunk {chunk.chunk_id}: {exc}"
            ) from exc

        if self.manifest is not None:
            record = ChunkRecord.from_request_chunk(chunk)
            record.netcdf_filename = output_file.name
            try:
                record.size_bytes = output_file.stat().st_size
            except OSError:
                pass
            self.manifest.record(record)
            self.manifest.save()
        return output_file

    # ---- CDS request building ----------------------------------------------

    def _build_cds_request_from_chunk(self, chunk: RequestChunk) -> dict[str, object]:
        return {
            "product_type": "reanalysis",
            "data_format": _CDS_DATA_FORMAT,
            "download_format": _CDS_DOWNLOAD_FORMAT,
            "variable": list(chunk.variables),
            "year": f"{chunk.year:04d}",
            "month": f"{chunk.month:02d}",
            "day": [f"{d:02d}" for d in chunk.days],
            "time": list(chunk.hours),
            "area": list(chunk.area),
        }

    def _build_cds_request(self, year: int, month: int) -> dict[str, object]:
        """Backward-compatible helper that builds a full-month, full-config request.

        Kept for the existing test suite (``test_download.py``) which calls it
        directly. The runtime path uses ``_build_cds_request_from_chunk``.
        """
        _, num_days = calendar.monthrange(year, month)
        return {
            "product_type": "reanalysis",
            "data_format": _CDS_DATA_FORMAT,
            "download_format": _CDS_DOWNLOAD_FORMAT,
            "variable": self.config.variables,
            "year": str(year),
            "month": f"{month:02d}",
            "day": [f"{d:02d}" for d in range(1, num_days + 1)],
            "time": self.config.hours,
            "area": self.config.area,
        }

    # ---- HTTP + filesystem helpers -----------------------------------------

    def _process_downloaded_file(self, temp_file: Path, temp_dir: Path, output_file: Path) -> None:
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
                    "Multiple .nc files found (%d), using first one", len(nc_files)
                )
            shutil.move(str(nc_files[0]), str(output_file))
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_file.unlink()
        else:
            temp_file.rename(output_file)

        size_mb = output_file.stat().st_size / 1024 / 1024
        self.logger.info("Downloaded: %s (%.2f MB)", output_file.name, size_mb)

    def _retrieve_with_retry(
        self,
        request: dict[str, object],
        target: Path,
        year: int,
        month: int,
    ) -> None:
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
                        "Attempt %d/%d failed for %d-%02d, retrying in %.0fs: %s",
                        attempt + 1,
                        self.config.max_retries + 1,
                        year,
                        month,
                        delay,
                        e,
                    )
                    time.sleep(delay)

        raise DownloadError(
            f"All {self.config.max_retries + 1} attempts failed for {year}-{month:02d}: {last_error}"
        )

    def __repr__(self) -> str:
        return f"CDSDownloader(dataset={self.config.dataset}, output_dir={self.config.output_dir})"
