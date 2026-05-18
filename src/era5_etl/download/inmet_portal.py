"""INMET historical-data portal downloader.

INMET publishes one ZIP per calendar year at
``https://portal.inmet.gov.br/dadoshistoricos``; each ZIP holds one CSV per
automatic station. This downloader scrapes the portal for the year links,
downloads the ZIPs for the requested year range, and extracts the CSVs into
``<output_dir>/<year>/``.

It deliberately mirrors :class:`CDSDownloader`'s public surface
(``__init__(config, manifest=, on_event=)`` and
``download(apply_diff=False, base_dir=None) -> list[Path]``) so the
pipeline's source-handler dispatch can use either interchangeably.
``apply_diff`` is accepted but ignored -- INMET has no cell-level smart
diff; per-year reuse is handled via the manifest instead.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from era5_etl.config import DownloadConfig
from era5_etl.exceptions import DownloadError
from era5_etl.storage.manifest import ChunkRecord, Manifest
from era5_etl.storage.paths import (
    base_dir_from_netcdf_dir,
    resolve_dataset_dir,
)

#: INMET station data is only useful next to the grids it is compared
#: against (the `era5_inmet` view + the per-station grid-neighbour
#: distances). Require at least the bare minimum of each grid on disk
#: before fetching INMET.
_REQUIRED_GRIDS = ("era5", "era5-land")

logger = logging.getLogger(__name__)

INMET_PORTAL_URL = "https://portal.inmet.gov.br/dadoshistoricos"
_DEFAULT_USER_AGENT = "era5-etl/inmet (+https://github.com/)"
_ZIP_YEAR_RE = re.compile(r"(\d{4})\.zip", re.IGNORECASE)


def manifest_chunk_id(year: int) -> str:
    """Manifest key for a downloaded INMET year (the unit of reuse)."""
    return f"inmet:{year}"


def years_from_dates(start_date: str, end_date: str | None) -> list[int]:
    """Translate a ``YYYY-MM-DD`` date range to the inclusive set of years.

    INMET's unit of acquisition is the calendar year, so a date range only
    selects which yearly ZIPs to fetch.
    """
    start_year = int(start_date[:4])
    end_year = int(end_date[:4]) if end_date else datetime.now(UTC).year
    if end_year < start_year:
        start_year, end_year = end_year, start_year
    return list(range(start_year, end_year + 1))


def scrape_available_years(
    *,
    portal_url: str = INMET_PORTAL_URL,
    timeout: int = 30,
    client: httpx.Client | None = None,
) -> list[int]:
    """Return the sorted list of years offered on the INMET portal.

    Standalone helper (no manifest/config) used by the web UI so the
    INMET wizard can let the user pick exactly which yearly ZIPs to
    fetch. Raises :class:`DownloadError` if the portal can't be reached
    or exposes no yearly ZIP links.
    """
    owns = client is None
    cli = client or httpx.Client(
        timeout=timeout,
        headers={"User-Agent": _DEFAULT_USER_AGENT},
        follow_redirects=True,
    )
    try:
        resp = cli.get(portal_url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise DownloadError(f"Failed to fetch INMET portal page: {e}") from e
    finally:
        if owns:
            cli.close()

    soup = BeautifulSoup(resp.text, "html.parser")
    years: set[int] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if not href.lower().endswith(".zip"):
            continue
        m = _ZIP_YEAR_RE.search(href)
        if m:
            years.add(int(m.group(1)))
    if not years:
        raise DownloadError(
            "No yearly ZIP links found on the INMET portal page"
        )
    return sorted(years)


def _grid_has_parquet(base_dir: str | Path, dataset: str) -> bool:
    d = resolve_dataset_dir(base_dir, dataset)
    return d.exists() and any(d.rglob("*.parquet"))


def ensure_grid_prerequisites(base_dir: str | Path) -> None:
    """Require minimal ERA5 **and** ERA5-LAND parquet before INMET.

    INMET is only ingested to be compared against the reanalysis grids
    (the ``era5_inmet`` view + per-station grid-neighbour distances). At
    least the bare minimum (1 variable × 1 day × 1 hour) of *each* grid
    must already be on disk. Raises :class:`DownloadError` listing what to
    download first.
    """
    missing = [d for d in _REQUIRED_GRIDS if not _grid_has_parquet(base_dir, d)]
    if not missing:
        return
    cmds = "\n".join(
        f"  era5 pipeline --dataset {d} --start-date 2024-01-01 "
        f"--end-date 2024-01-01 --var 2m_temperature"
        for d in missing
    )
    raise DownloadError(
        "INMET requires ERA5 and ERA5-LAND to have at least minimal data "
        f"downloaded first (needed for the era5_inmet comparison and the "
        f"per-station grid-neighbour distances). Missing: "
        f"{', '.join(missing)}.\nDownload the minimum first, e.g.:\n{cmds}"
    )


class InmetPortalDownloader:
    """Download + extract INMET yearly station ZIPs from the portal."""

    def __init__(
        self,
        config: DownloadConfig,
        manifest: Manifest | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        *,
        client: httpx.Client | None = None,
        portal_url: str = INMET_PORTAL_URL,
    ) -> None:
        self.config = config
        self.manifest = manifest
        self.on_event = on_event
        self.portal_url = portal_url
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=config.timeout,
            headers={"User-Agent": _DEFAULT_USER_AGENT},
            follow_redirects=True,
        )

    # ---- events ------------------------------------------------------

    def _emit(self, **payload: Any) -> None:
        if self.on_event is not None:
            try:
                self.on_event({"stage": "download", **payload})
            except Exception:  # noqa: BLE001 -- UI callback must never break ETL
                logger.debug("on_event callback raised", exc_info=True)

    # ---- public API --------------------------------------------------

    def download(
        self,
        apply_diff: bool = False,  # noqa: ARG002 -- parity with CDSDownloader
        base_dir: str | Path | None = None,  # noqa: ARG002
    ) -> list[Path]:
        """Download every requested year's ZIP and extract its CSVs.

        Returns the list of per-year output directories that now hold CSVs.
        Years already recorded in the manifest (and still present on disk)
        are skipped unless ``config.override`` is set.
        """
        # Enforce the ERA5/ERA5-LAND prerequisite (M01). Resolve the
        # storage root from the explicit base_dir, else from the temp
        # output dir's layout. If it can't be located (custom output_dir,
        # direct-API/unit use), skip rather than block a legitimate flow.
        effective_base = base_dir or base_dir_from_netcdf_dir(
            self.config.output_dir
        )
        if effective_base is not None:
            ensure_grid_prerequisites(effective_base)
        else:
            logger.warning(
                "INMET: could not locate the storage root; skipping the "
                "ERA5/ERA5-LAND prerequisite check."
            )

        output_root = Path(self.config.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        # Explicit year list (user picked a possibly non-contiguous subset
        # in the wizard) wins; otherwise derive a contiguous range from the
        # date span.
        if self.config.years:
            years = sorted({int(y) for y in self.config.years})
        else:
            years = years_from_dates(
                self.config.start_date, self.config.end_date
            )
        logger.info("INMET: %d year(s) requested: %s", len(years), years)

        try:
            available = self._scrape_available_files()
        except DownloadError:
            raise
        except Exception as e:  # noqa: BLE001
            raise DownloadError(f"Failed to scrape INMET portal: {e}") from e

        by_year = {f["year"]: f for f in available}
        out_dirs: list[Path] = []
        for year in years:
            chunk_id = manifest_chunk_id(year)
            year_dir = output_root / str(year)

            if (
                not self.config.override
                and self.manifest is not None
                and self.manifest.has(chunk_id)
                and year_dir.exists()
                and any(year_dir.glob("*.CSV"))
            ):
                logger.info("INMET: year %d already downloaded; skipping", year)
                self._emit(year=year, status="skipped")
                out_dirs.append(year_dir)
                continue

            info = by_year.get(year)
            if info is None:
                logger.warning("INMET: year %d not found on portal; skipping", year)
                self._emit(year=year, status="missing")
                continue

            try:
                self._emit(year=year, status="downloading")
                n_csv = self._download_and_extract(info, year_dir)
                self._record(chunk_id, year, n_csv)
                self._emit(year=year, status="completed", files=n_csv)
                out_dirs.append(year_dir)
            except Exception as e:  # noqa: BLE001 -- one bad year shouldn't abort the rest
                logger.error("INMET: failed year %d: %s", year, e)
                self._emit(year=year, status="failed", error=str(e))

        return out_dirs

    # ---- scraping ----------------------------------------------------

    def _scrape_available_files(self) -> list[dict[str, Any]]:
        logger.debug("Fetching INMET portal page: %s", self.portal_url)
        try:
            response = self.client.get(self.portal_url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DownloadError(f"Failed to fetch portal page: {e}") from e

        soup = BeautifulSoup(response.text, "html.parser")
        base_url = "/".join(self.portal_url.split("/")[:-1])
        files: list[dict[str, Any]] = []
        for link in soup.find_all("a", href=True):
            href = str(link["href"])
            if not href.lower().endswith(".zip"):
                continue
            m = _ZIP_YEAR_RE.search(href)
            if not m:
                continue
            year = int(m.group(1))
            url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
            files.append({"name": Path(href).name, "url": url, "year": year})
        if not files:
            raise DownloadError(
                "No yearly ZIP links found on the INMET portal page"
            )
        return files

    # ---- download/extract -------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _download_and_extract(self, info: dict[str, Any], year_dir: Path) -> int:
        """Download one yearly ZIP and extract its CSVs; return CSV count."""
        try:
            response = self.client.get(info["url"])
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise DownloadError(f"HTTP error downloading {info['name']}: {e}") from e

        year_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                csv_names = [n for n in zf.namelist() if n.upper().endswith(".CSV")]
                for name in csv_names:
                    # Flatten: drop any intermediate ZIP directories so files
                    # land directly under <output>/<year>/.
                    target = year_dir / Path(name).name
                    with zf.open(name) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except zipfile.BadZipFile as e:
            raise DownloadError(f"Invalid ZIP for {info['name']}: {e}") from e
        logger.info("INMET: extracted %d CSV(s) for %s", len(csv_names), info["name"])
        return len(csv_names)

    # ---- manifest ----------------------------------------------------

    def _record(self, chunk_id: str, year: int, n_csv: int) -> None:
        if self.manifest is None:
            return
        self.manifest.record(
            ChunkRecord(
                chunk_id=chunk_id,
                year=year,
                month=0,
                variables=[],
                area=[],
                size_bytes=0,
            )
        )
        self.manifest.save()

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        if getattr(self, "_owns_client", False):
            try:
                self.client.close()
            except Exception:
                pass
