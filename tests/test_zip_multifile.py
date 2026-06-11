"""Multi-file CDS ZIP handling: no silent variable loss + merge reunification.

ERA5-LAND mixes instantaneous and accumulated variables, which the CDS cannot
pack into a single NetCDF hypercube ("Structural differences in grib fields").
It therefore returns a ZIP holding several NetCDFs — one per cfgrib stepType
group. Ground truth captured by ``scripts/diagnose_era5land_zip.py``: a request
for all 50 ERA5-LAND variables returned **3** files (8 / 36 / 6 vars), every one
time-varying. The old downloader kept only the first (~8 soil vars) and deleted
the rest, silently dropping most of the requested variables.

These tests lock in the fix:
  1. ``_process_downloaded_file`` keeps **every** NetCDF from the ZIP.
  2. The convert+merge stage reunifies the disjoint groups into single wide
     rows per (lat, lon, date, hour) — the column-union path in
     ``parquet_manager._merge_by_key``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import polars as pl
import xarray as xr

from era5_etl.config import DownloadConfig, StorageConfig, TransformConfig


def _make_nc(path: Path, data_vars: dict[str, float]) -> None:
    """Write a tiny ERA5-LAND-shaped NetCDF (valid_time × 2 lat × 2 lon).

    ``data_vars`` maps a NetCDF short name to a constant fill value, so every
    file shares the same grid/time coords but carries a disjoint variable set —
    exactly the stepType-group split the real CDS produces.
    """
    n_t, n_lat, n_lon = 24, 2, 2
    ds = xr.Dataset(
        {
            name: (
                ["valid_time", "latitude", "longitude"],
                np.full((n_t, n_lat, n_lon), value, dtype="float64"),
            )
            for name, value in data_vars.items()
        },
        coords={
            "valid_time": np.arange(
                "2024-01-15", "2024-01-16", dtype="datetime64[h]"
            ).astype("datetime64[ns]"),
            "latitude": np.array([-22.0, -22.1], dtype="float64"),
            "longitude": np.array([-47.0, -47.1], dtype="float64"),
        },
    )
    ds.to_netcdf(path)


def _make_zip(zip_path: Path, members: dict[str, dict[str, float]]) -> None:
    """Build the named NetCDF members and bundle them into ``zip_path``."""
    build = zip_path.parent / "_build"
    build.mkdir(exist_ok=True)
    paths = []
    for fname, data_vars in members.items():
        p = build / fname
        _make_nc(p, data_vars)
        paths.append(p)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    for p in paths:
        p.unlink()
    build.rmdir()


@patch("era5_etl.download.cds_downloader.cdsapi.Client")
def test_process_downloaded_file_keeps_all_nc_files(
    mock_client_cls: MagicMock, tmp_path: Path
) -> None:
    mock_client_cls.return_value = MagicMock()
    out = tmp_path / "era5-land"
    out.mkdir()
    config = DownloadConfig(output_dir=out, dataset="era5-land")

    from era5_etl.download.cds_downloader import CDSDownloader

    with patch.object(CDSDownloader, "_validate_credentials"):
        dl = CDSDownloader(config)

    # A 3-member ZIP mirroring the real CDS response (8 / 2 / 1 vars).
    temp_file = out / ".tmp_chunk.download"
    _make_zip(
        temp_file,
        {
            "data_0.nc": {"stl1": 290.0, "swvl1": 0.3},
            "data_1.nc": {"t2m": 295.0, "tp": 0.001},
            "data_2.nc": {"sde": 0.0},
        },
    )
    temp_dir = out / ".tmp_extract_chunk"
    output_file = out / "era5land_20240115.nc"

    written = dl._process_downloaded_file(temp_file, temp_dir, output_file)

    # All three groups kept — nothing discarded.
    assert len(written) == 3
    assert output_file.exists()  # primary keeps the canonical sentinel name
    on_disk = sorted(out.glob("*.nc"))
    assert len(on_disk) == 3
    assert len({p.name for p in on_disk}) == 3  # distinct names
    assert all(p.name.startswith("era5land_20240115") for p in on_disk)

    # Temp artifacts cleaned up.
    assert not temp_file.exists()
    assert not temp_dir.exists()

    # Every requested variable survives across the kept files.
    union: set[str] = set()
    for p in on_disk:
        with xr.open_dataset(p) as ds:
            union |= {str(v) for v in ds.data_vars}
    assert {"stl1", "swvl1", "t2m", "tp", "sde"} <= union


def test_multifile_chunk_merges_to_full_schema(tmp_path: Path) -> None:
    from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter

    # Two groups, same grid+time, disjoint variables (instant t2m vs accum tp).
    input_dir = tmp_path / "_tmp_netcdf" / "era5-land"
    input_dir.mkdir(parents=True)
    _make_nc(input_dir / "era5land_20240115.nc", {"t2m": 295.0})
    _make_nc(input_dir / "era5land_20240115__01-accum.nc", {"tp": 0.002})

    out_dir = tmp_path / "climate_data_store_db" / "era5-land"
    converter = NetCDFToParquetConverter(
        transform_config=TransformConfig(calculate_wind_speed=False),
        storage_config=StorageConfig(
            database_dir=tmp_path,
            parquet_compression="zstd",
            partition_cols=["date"],
        ),
        output_dir=out_dir,
        dataset="era5-land",
    )

    # max_workers=1 forces the deterministic sequential merge path.
    stats = converter.convert_directory(input_dir, max_workers=1)
    assert stats["converted"] == 2
    assert stats["failed"] == 0

    files = sorted((out_dir / "date=2024-01-15").glob("*.parquet"))
    assert files, "expected a date=2024-01-15 partition"
    df = pl.read_parquet(files)

    # Both variables present, reunified into single wide rows.
    assert "temperature_2m" in df.columns
    assert "total_precipitation" in df.columns
    # 2x2 grid x 24 hours = 96 keys, NOT doubled (no per-file row duplication).
    assert df.height == 96
    # Every row carries BOTH values (column-union, not null-filled duplicates).
    assert df["temperature_2m"].null_count() == 0
    assert df["total_precipitation"].null_count() == 0
