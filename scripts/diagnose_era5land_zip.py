"""Ground-truth diagnostic: what does the CDS return for an all-variable ERA5-LAND request?

Downloads ALL ERA5-LAND variables for a single day over a tiny area, then unzips
the CDS response and inspects every NetCDF member: variables, dimensions, and
whether each file carries a time axis (time-varying) or not (static).

This answers two questions that drive the fix:
  1. How many NetCDF files does the ZIP actually contain, and which variables go
     into each? (The downloader was discarding all but the first.)
  2. Is any of those files time-less/static? (That would need special handling in
     the NetCDF->Parquet converter; a time-varying-only split "just works".)

Run it directly (needs ~/.cdsapirc credentials + network):

    py -3.12 scripts/diagnose_era5land_zip.py

It writes nothing permanent: everything lands in a temp dir that is printed and
left in place for manual inspection.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import cdsapi
import xarray as xr

from era5_etl.datasets import DatasetRegistry

# --- request parameters ---------------------------------------------------
CDS_DATASET_ID = "reanalysis-era5-land"
YEAR = "2024"
MONTH = "01"
DAY = "15"
HOURS = [f"{h:02d}:00" for h in range(24)]
# Tiny 1x1 degree box inside São Paulo state -> well under any cost limit.
AREA = [-22.0, -48.0, -23.0, -47.0]  # N, W, S, E


def all_era5land_variables() -> list[str]:
    cfg = DatasetRegistry.get("era5-land")  # .get() loads the registry lazily
    return [v.api_name for v in cfg.variables]


def build_request(variables: list[str]) -> dict[str, object]:
    # Mirrors CDSDownloader._build_cds_request_from_chunk.
    return {
        "product_type": "reanalysis",
        "data_format": "netcdf",
        "download_format": "unarchived",
        "variable": variables,
        "year": YEAR,
        "month": MONTH,
        "day": [DAY],
        "time": HOURS,
        "area": AREA,
    }


def inspect_netcdf(path: Path) -> None:
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"\n--- {path.name}  ({size_mb:.2f} MB) ---")
    try:
        ds = xr.open_dataset(path, engine="netcdf4")
    except Exception as exc:  # noqa: BLE001 - diagnostic, report and move on
        print(f"  !! could not open: {exc}")
        return
    with ds:
        time_name = next(
            (c for c in ("valid_time", "time") if c in ds.variables), None
        )
        n_time = int(ds.sizes[time_name]) if time_name in ds.sizes else None
        kind = (
            f"TIME-VARYING (coord={time_name}, len={n_time})"
            if time_name
            else "STATIC (no time dim)"
        )
        print(f"  kind:      {kind}")
        print(f"  dims:      {dict(ds.sizes)}")
        print(f"  coords:    {list(ds.coords)}")
        print(f"  data_vars: {list(ds.data_vars)}")
        for name, da in ds.data_vars.items():
            step = da.attrs.get("GRIB_stepType", da.attrs.get("stepType", "?"))
            print(f"    - {name:<10} dims={da.dims} stepType={step}")


def main() -> None:
    variables = all_era5land_variables()
    print(f"Requesting {len(variables)} ERA5-LAND variables for {YEAR}-{MONTH}-{DAY}")
    print(f"Area={AREA}  hours=0..23")

    work = Path(tempfile.mkdtemp(prefix="era5land_diag_"))
    zip_path = work / "response.download"
    print(f"\nWork dir: {work}")

    client = cdsapi.Client()
    client.retrieve(CDS_DATASET_ID, build_request(variables), str(zip_path))

    print(f"\nDownloaded {zip_path.stat().st_size / 1024 / 1024:.2f} MB to {zip_path.name}")
    print(f"Is ZIP? {zipfile.is_zipfile(zip_path)}")

    if zipfile.is_zipfile(zip_path):
        extract_dir = work / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.namelist()
            zf.extractall(extract_dir)
        print(f"\nZIP members ({len(members)}): {members}")
        nc_files = sorted(extract_dir.glob("*.nc"))
    else:
        nc_files = [zip_path]

    print(f"\n=== {len(nc_files)} NetCDF file(s) ===")
    for nc in nc_files:
        inspect_netcdf(nc)

    print(f"\nDone. Files left for inspection in: {work}")


if __name__ == "__main__":
    main()
