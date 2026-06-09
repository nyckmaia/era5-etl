"""Opt-in real-CDS integration test (never runs in CI).

Downloads ALL ERA5-LAND variables for a single day over a tiny area through the
real :class:`CDSDownloader` and asserts the post-fix behaviour: the multi-file
ZIP response is kept whole (more than one NetCDF group), and the union of
variables across the kept files covers far more than the single group the old
code retained. This is the repeatable form of ``scripts/diagnose_era5land_zip.py``.

Enable with::

    RUN_CDS_INTEGRATION=1 py -3.12 -m pytest tests/test_cds_integration.py -s

Requires CDS credentials in ``~/.cdsapirc``. On a machine behind a corporate TLS
proxy you may also need ``REQUESTS_CA_BUNDLE`` / ``SSL_CERT_FILE`` pointing at a
CA bundle that includes the proxy root CA (Python's bundled certs won't have it).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import xarray as xr

from era5_etl.config import DownloadConfig
from era5_etl.datasets import DatasetRegistry

_CDSRC = Path.home() / ".cdsapirc"

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_CDS_INTEGRATION") or not _CDSRC.exists(),
    reason=(
        "set RUN_CDS_INTEGRATION=1 and provide ~/.cdsapirc to run the real "
        "CDS download"
    ),
)


def test_all_era5land_vars_one_day_keeps_every_group(tmp_path: Path) -> None:
    from era5_etl.download.cds_downloader import CDSDownloader
    from era5_etl.download.request_planner import plan_requests

    variables = [v.api_name for v in DatasetRegistry.get("era5-land").variables]
    out = tmp_path / "era5-land"
    out.mkdir()
    config = DownloadConfig(
        output_dir=out,
        dataset="era5-land",
        variables=variables,
        start_date="2024-01-15",
        end_date="2024-01-15",
        area=[-22.0, -48.0, -23.0, -47.0],  # tiny 1x1 box, well under cost limits
        hours=[f"{h:02d}:00" for h in range(24)],
    )

    chunks = plan_requests(config)
    assert chunks, "planner produced no chunks"

    dl = CDSDownloader(config, manifest=None)
    dl._download_chunk(chunks[0])

    nc_files = sorted(out.glob("*.nc"))
    union: set[str] = set()
    print(f"\nKept {len(nc_files)} NetCDF file(s):")
    for p in nc_files:
        with xr.open_dataset(p) as ds:
            v = {str(name) for name in ds.data_vars}
            union |= v
            print(f"  {p.name} ({p.stat().st_size / 1024:.0f} KB): {len(v)} vars")
    print(f"Union across files: {len(union)} variables (requested {len(variables)})")

    # The old code kept only the first group (~8 soil vars); the fix keeps the
    # whole multi-file ZIP, so the union covers (nearly) every requested var.
    assert len(nc_files) >= 2
    assert len(union) >= 40
