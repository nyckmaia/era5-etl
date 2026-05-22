"""CDS API downloader for ERA5/ERA5-Land data.

The download is driven by a list of :class:`RequestChunk` produced by
:func:`era5_etl.download.request_planner.plan_requests`. Each chunk fits the
configured Request size budget; the downloader iterates over them, retries
on failure, and rewrites ZIP responses to plain NetCDF.
"""

from __future__ import annotations

import calendar
import contextlib
import logging
import os
import shutil
import time
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import cdsapi

from era5_etl.config import DownloadConfig
from era5_etl.download.cds_log_capture import CDSEventCapture
from era5_etl.download.request_planner import (
    RequestChunk,
    plan_requests,
    plan_with_diff,
)
from era5_etl.exceptions import CDSAPIError, CDSRequestTooLargeError, DownloadError
from era5_etl.storage.manifest import ChunkRecord, Manifest

# Substrings the CDS server uses in 403 responses for cost / size limits.
# Hits any of them → mid-flight adaptive split instead of retrying.
_CDS_TOO_LARGE_HINTS = (
    "cost limits exceeded",
    "your request is too large",
    "request is too large",
    "request too large",
    "exceeds the limit",
)


def _is_cds_too_large(exc: BaseException) -> bool:
    """Return True iff ``exc`` looks like a CDS 'cost limits exceeded' rejection.

    Matches on the error message text because cdsapi raises generic
    ``Exception`` subclasses without a structured status code on the
    catalogue endpoint. False positives are harmless — they trigger a
    one-time split which simply produces smaller chunks.
    """
    msg = str(exc).lower()
    return any(hint in msg for hint in _CDS_TOO_LARGE_HINTS)

# CDS only accepts the literal string "netcdf"; never GRIB in this project.
_CDS_DATA_FORMAT = "netcdf"
_CDS_DOWNLOAD_FORMAT = "unarchived"


class CDSDownloader:
    """Download ERA5/ERA5-Land data from Copernicus Climate Data Store."""

    def __init__(
        self,
        config: DownloadConfig,
        manifest: Manifest | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
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

    def download(
        self,
        apply_diff: bool = False,
        base_dir: Path | str | None = None,
    ) -> list[Path]:
        """Download every chunk planned for the current configuration.

        Parameters
        ----------
        apply_diff:
            When ``True``, route through :func:`plan_with_diff` to subtract
            cells already present in the per-dataset coverage index before
            issuing CDS requests. Defaults to ``False`` for backward
            compatibility -- existing callers (and tests) keep today's
            behaviour.
        base_dir:
            Required when ``apply_diff=True``. The base data directory used
            to locate the ``_coverage.duckdb`` file. Inferred from
            ``self.config.output_dir`` when omitted (assumes the standard
            ``<base>/_tmp_netcdf/<dataset>`` layout).
        """
        if apply_diff:
            resolved_base = (
                Path(base_dir)
                if base_dir is not None
                else self._infer_base_dir()
            )
            chunks = plan_with_diff(self.config, resolved_base)
            self.logger.info(
                "Starting CDS download (smart diff): %d chunk(s), dataset=%s",
                len(chunks),
                self.config.dataset,
            )
        else:
            chunks = plan_requests(self.config)
            self.logger.info(
                "Starting CDS download: %d chunk(s), dataset=%s",
                len(chunks),
                self.config.dataset,
            )
        return self._download_all(chunks)

    def _infer_base_dir(self) -> Path:
        """Best-effort recovery of the user-supplied base_dir from output_dir.

        Delegates to :func:`paths.base_dir_from_netcdf_dir`; falls back to
        ``output_dir`` if the layout doesn't match (callers using a custom
        ``output_dir`` should pass ``base_dir`` explicitly).
        """
        from era5_etl.storage.paths import base_dir_from_netcdf_dir
        return base_dir_from_netcdf_dir(self.config.output_dir) or self.config.output_dir

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

    def _download_chunk(self, chunk: RequestChunk, _depth: int = 0) -> Path:
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
        except CDSRequestTooLargeError as exc:
            # Clean partial files before splitting.
            for p in (temp_file, output_file):
                if p.exists():
                    p.unlink(missing_ok=True)
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return self._download_with_adaptive_split(chunk, exc, _depth)
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
            with contextlib.suppress(OSError):
                record.size_bytes = output_file.stat().st_size
            self.manifest.record(record)
            self.manifest.save()
        return output_file

    #: Maximum recursion depth for adaptive sub-splitting. Starting from
    #: a one-month chunk, depth 6 reaches ~1-day single-variable single
    #: sub-area requests — beyond that CDS is the problem, not us.
    _ADAPTIVE_SPLIT_MAX_DEPTH = 6

    def _download_with_adaptive_split(
        self,
        chunk: RequestChunk,
        cause: CDSRequestTooLargeError,
        depth: int,
    ) -> Path:
        """Split ``chunk`` and re-download each half.

        CDS rejected ``chunk`` as too large even though our planner
        passed it. Halve the chunk on the most-effective axis (days
        first, then variables) and recurse. Returns the path of the
        FIRST resulting sub-NetCDF — but every sub-chunk has been
        written individually and recorded in the manifest, so the
        converter picks them all up in the next stage.
        """
        if depth >= self._ADAPTIVE_SPLIT_MAX_DEPTH:
            raise DownloadError(
                f"CDS rejected {chunk.chunk_id} as too large and adaptive "
                f"split exhausted (depth {depth}). Last error: {cause}"
            )

        halves = self._halve_chunk(chunk)
        if halves is None:
            raise DownloadError(
                f"CDS rejected {chunk.chunk_id} as too large but it is "
                f"already a single variable on a single day — cannot "
                f"split further. Last error: {cause}"
            )

        self.logger.warning(
            "CDS rejected %s as too large; splitting into %d sub-chunk(s) "
            "and retrying. Cause: %s",
            chunk.chunk_id,
            len(halves),
            cause,
        )
        first_path: Path | None = None
        for sub in halves:
            self._emit(
                {
                    "chunk_id": sub.chunk_id,
                    "phase": "submitting",
                    "message": f"Adaptive split: submitting {sub.chunk_id} to CDS",
                }
            )
            path = self._download_chunk(sub, _depth=depth + 1)
            if first_path is None:
                first_path = path
        assert first_path is not None
        return first_path

    def _halve_chunk(self, chunk: RequestChunk) -> list[RequestChunk] | None:
        """Halve ``chunk`` on days, then hours, then variables — in that order.

        Splitting on **days** or **hours** keeps every sub-chunk's variable
        set intact, so each downloaded NetCDF — and the Parquet it converts
        to — carries the full schema. Splitting on **variables** fragments
        the schema: the per-date partition merge (`_merge_by_key`) does
        reunify variable-split chunks, but until it runs the intermediate
        files have partial columns, which is fragile if a run is
        interrupted. So variable-split is the last resort.

        Returns ``None`` when the chunk is already a single variable on a
        single hour of a single day — nothing left to halve.
        """
        if len(chunk.days) > 1:
            mid = len(chunk.days) // 2
            left_days = chunk.days[:mid]
            right_days = chunk.days[mid:]
            return [
                replace(
                    chunk,
                    days=left_days,
                    chunk_id=(
                        f"{chunk.chunk_id}_d{left_days[0]:02d}-{left_days[-1]:02d}"
                    ),
                ),
                replace(
                    chunk,
                    days=right_days,
                    chunk_id=(
                        f"{chunk.chunk_id}_d{right_days[0]:02d}-{right_days[-1]:02d}"
                    ),
                ),
            ]
        if len(chunk.hours) > 1:
            mid = len(chunk.hours) // 2
            left_hours = chunk.hours[:mid]
            right_hours = chunk.hours[mid:]

            def _h(hours: tuple[str, ...]) -> str:
                return f"{hours[0].replace(':', '')}-{hours[-1].replace(':', '')}"

            return [
                replace(
                    chunk,
                    hours=left_hours,
                    chunk_id=f"{chunk.chunk_id}_h{_h(left_hours)}",
                ),
                replace(
                    chunk,
                    hours=right_hours,
                    chunk_id=f"{chunk.chunk_id}_h{_h(right_hours)}",
                ),
            ]
        if len(chunk.variables) > 1:
            mid = len(chunk.variables) // 2
            return [
                replace(
                    chunk,
                    variables=chunk.variables[:mid],
                    chunk_id=f"{chunk.chunk_id}_v1of2",
                ),
                replace(
                    chunk,
                    variables=chunk.variables[mid:],
                    chunk_id=f"{chunk.chunk_id}_v2of2",
                ),
            ]
        return None

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
                # "Cost limits exceeded" / "Your request is too large" is
                # NOT a transient failure — retrying the identical
                # request will fail every single time. Surface a typed
                # error so ``_download_chunk`` can split adaptively
                # instead of burning the four configured retries.
                if _is_cds_too_large(e):
                    raise CDSRequestTooLargeError(str(e)) from e
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
