"""INMET portal downloader tests (HTTP fully mocked -- no network)."""

from __future__ import annotations

import io
import zipfile

import pytest

from era5_etl.config import DownloadConfig
from era5_etl.download.inmet_portal import (
    InmetPortalDownloader,
    manifest_chunk_id,
    years_from_dates,
)
from era5_etl.exceptions import DownloadError
from era5_etl.storage.manifest import Manifest

_PORTAL_HTML = """
<html><body>
  <a href="https://portal.inmet.gov.br/uploads/dadoshistoricos/2000.zip">2000</a>
  <a href="https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip">2026</a>
  <a href="/some/other/file.pdf">not a zip</a>
</body></html>
"""


def _zip_bytes(csv_name: str = "INMET_CO_DF_A001_BRASILIA_07-05-2000_A_31-12-2000.CSV"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, "REGIAO:;CO\nDATA;HORA;\n2000-01-01;00:00;\n")
        zf.writestr("readme.txt", "ignore me")
    return buf.getvalue()


class _Resp:
    def __init__(self, *, text="", content=b""):
        self.text = text
        self.content = content

    def raise_for_status(self):
        return None


class _FakeClient:
    """Serves the portal HTML for the portal URL and a ZIP for *.zip URLs."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        if url.endswith(".zip"):
            return _Resp(content=_zip_bytes())
        return _Resp(text=_PORTAL_HTML)

    def close(self):
        pass


def _cfg(tmp_path, start="2000-01-01", end="2000-12-31"):
    return DownloadConfig(
        output_dir=tmp_path / "raw",
        dataset="inmet",
        start_date=start,
        end_date=end,
        variables=[],
    )


def test_years_from_dates():
    assert years_from_dates("2000-01-01", "2002-06-30") == [2000, 2001, 2002]
    assert years_from_dates("2026-01-01", "2026-04-30") == [2026]


def test_download_extracts_csvs(tmp_path):
    client = _FakeClient()
    dl = InmetPortalDownloader(_cfg(tmp_path), client=client)
    dirs = dl.download()

    assert len(dirs) == 1
    year_dir = dirs[0]
    assert year_dir.name == "2000"
    csvs = list(year_dir.glob("*.CSV"))
    assert len(csvs) == 1
    # Non-CSV members are not extracted.
    assert not list(year_dir.glob("*.txt"))


def test_manifest_skip_on_second_run(tmp_path):
    manifest = Manifest(tmp_path / "base", "inmet")
    client = _FakeClient()
    dl = InmetPortalDownloader(_cfg(tmp_path), manifest=manifest, client=client)
    dl.download()
    assert manifest.has(manifest_chunk_id(2000))
    zip_calls_first = [c for c in client.calls if c.endswith(".zip")]
    assert len(zip_calls_first) == 1

    # Second run: year is in the manifest AND on disk -> no new ZIP fetch.
    client2 = _FakeClient()
    dl2 = InmetPortalDownloader(_cfg(tmp_path), manifest=manifest, client=client2)
    out = dl2.download()
    assert len(out) == 1
    assert [c for c in client2.calls if c.endswith(".zip")] == []


def test_missing_year_is_skipped_not_fatal(tmp_path):
    client = _FakeClient()
    dl = InmetPortalDownloader(
        _cfg(tmp_path, "1999-01-01", "1999-12-31"), client=client
    )
    out = dl.download()
    assert out == []


def test_emits_events(tmp_path):
    events = []
    client = _FakeClient()
    dl = InmetPortalDownloader(
        _cfg(tmp_path), on_event=events.append, client=client
    )
    dl.download()
    statuses = {e["status"] for e in events}
    assert "downloading" in statuses
    assert "completed" in statuses


def _seed_min_grid(base, dataset):
    from era5_etl.storage.paths import resolve_dataset_dir

    d = resolve_dataset_dir(base, dataset) / "date=2024-01-01"
    d.mkdir(parents=True, exist_ok=True)
    import polars as pl

    pl.DataFrame({"latitude": [0.0], "longitude": [0.0], "hour_utc": [0]}).write_parquet(
        d / f"{dataset}_2024-01-01_part-001.parquet"
    )


def test_prerequisite_blocks_inmet_without_grids(tmp_path):
    dl = InmetPortalDownloader(_cfg(tmp_path), client=_FakeClient())
    with pytest.raises(DownloadError, match="ERA5 and ERA5-LAND"):
        dl.download(base_dir=tmp_path)


def test_prerequisite_passes_with_minimal_grids(tmp_path):
    _seed_min_grid(tmp_path, "era5")
    _seed_min_grid(tmp_path, "era5-land")
    client = _FakeClient()
    dl = InmetPortalDownloader(_cfg(tmp_path), client=client)
    dirs = dl.download(base_dir=tmp_path)
    assert len(dirs) == 1
    assert dirs[0].name == "2000"


def test_prerequisite_skipped_when_base_dir_unresolvable(tmp_path):
    # output_dir not under _tmp_netcdf and no base_dir -> can't locate the
    # storage root -> precondition is skipped (legitimate direct use).
    client = _FakeClient()
    dl = InmetPortalDownloader(_cfg(tmp_path), client=client)
    dirs = dl.download()
    assert len(dirs) == 1


def test_explicit_years_subset_is_honoured(tmp_path):
    """config.years (non-contiguous) wins over the date range."""
    _seed_min_grid(tmp_path, "era5")
    _seed_min_grid(tmp_path, "era5-land")

    class _MultiYearClient(_FakeClient):
        def get(self, url: str):
            self.calls.append(url)
            if url.endswith(".zip"):
                return _Resp(content=_zip_bytes())
            return _Resp(
                text=(
                    '<a href="https://x/2000.zip">2000</a>'
                    '<a href="https://x/2001.zip">2001</a>'
                    '<a href="https://x/2002.zip">2002</a>'
                )
            )

    cfg = _cfg(tmp_path, "2000-01-01", "2002-12-31")
    cfg.years = [2000, 2002]  # skip 2001 on purpose
    client = _MultiYearClient()
    dirs = InmetPortalDownloader(cfg, client=client).download(base_dir=tmp_path)
    got = sorted(p.name for p in dirs)
    assert got == ["2000", "2002"]
    assert not (tmp_path / "raw" / "2001").exists()


def test_no_zip_links_raises(tmp_path):
    class _EmptyClient(_FakeClient):
        def get(self, url: str):
            self.calls.append(url)
            return _Resp(text="<html><body>no links</body></html>")

    dl = InmetPortalDownloader(_cfg(tmp_path), client=_EmptyClient())
    with pytest.raises(DownloadError):
        dl.download()
