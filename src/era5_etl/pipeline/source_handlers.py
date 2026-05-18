"""Source-kind dispatch for the pipeline.

A dataset's :attr:`DatasetConfig.SOURCE_KIND` selects how the generic
``DownloadStage`` / ``ConvertToParquetStage`` acquire and shape data, and
which post-convert refresh stage runs:

* ``cds_grid``  -> CDS NetCDF downloader + NetCDF->Parquet converter +
  grid coverage-index refresh (ERA5, ERA5-LAND).
* ``inmet_zip`` -> INMET portal ZIP downloader + CSV->Parquet converter +
  station-index refresh (INMET).

Keeping this table here (rather than as ``if dataset == ...`` chains
sprinkled through the pipeline, and rather than on ``DatasetConfig`` which
must stay free of pipeline/IO imports) means adding a future source is a
one-line registry entry. Downloader/converter classes are imported lazily
inside the factories so importing this module never drags in ``cdsapi`` /
``xarray`` for an INMET-only run, and vice-versa.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from era5_etl.datasets import DatasetRegistry

if TYPE_CHECKING:
    from era5_etl.config import DownloadConfig, StorageConfig, TransformConfig
    from era5_etl.storage.manifest import Manifest

# Refresh-stage identifiers. The actual Stage classes live in
# ``era5_pipeline`` (which owns the Stage base); mapping a string here
# instead of importing them keeps this module import-cycle free.
REFRESH_COVERAGE = "coverage"
REFRESH_STATIONS = "stations"


@dataclass(frozen=True)
class SourceHandler:
    """How one source kind is downloaded, converted, and indexed."""

    make_downloader: Callable[..., Any]
    make_converter: Callable[..., Any]
    refresh_kind: str


# -- CDS / NetCDF (ERA5, ERA5-LAND) ------------------------------------


def _cds_downloader(
    config: DownloadConfig,
    manifest: Manifest | None,
    on_event: Callable[[dict[str, Any]], None] | None,
) -> Any:
    from era5_etl.download.cds_downloader import CDSDownloader

    return CDSDownloader(config, manifest=manifest, on_event=on_event)


def _cds_converter(
    transform_config: TransformConfig,
    storage_config: StorageConfig,
    output_dir: Path,
    dataset: str | None,
) -> Any:
    from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter

    return NetCDFToParquetConverter(
        transform_config=transform_config,
        storage_config=storage_config,
        output_dir=output_dir,
        dataset=dataset,
    )


# -- INMET (station ZIPs) ----------------------------------------------


def _inmet_downloader(
    config: DownloadConfig,
    manifest: Manifest | None,
    on_event: Callable[[dict[str, Any]], None] | None,
) -> Any:
    from era5_etl.download.inmet_portal import InmetPortalDownloader

    return InmetPortalDownloader(config, manifest=manifest, on_event=on_event)


def _inmet_converter(
    transform_config: TransformConfig,
    storage_config: StorageConfig,
    output_dir: Path,
    dataset: str | None,
) -> Any:
    from era5_etl.transform.inmet_to_parquet import InmetToParquetConverter

    return InmetToParquetConverter(
        transform_config=transform_config,
        storage_config=storage_config,
        output_dir=output_dir,
        dataset=dataset,
    )


SOURCE_HANDLERS: dict[str, SourceHandler] = {
    "cds_grid": SourceHandler(_cds_downloader, _cds_converter, REFRESH_COVERAGE),
    "inmet_zip": SourceHandler(_inmet_downloader, _inmet_converter, REFRESH_STATIONS),
}


def get_handler(dataset_name: str) -> SourceHandler:
    """Return the :class:`SourceHandler` for a registered dataset."""
    cfg = DatasetRegistry.get(dataset_name)
    kind = getattr(cfg, "SOURCE_KIND", "cds_grid")
    try:
        return SOURCE_HANDLERS[kind]
    except KeyError as exc:
        raise KeyError(
            f"No source handler for SOURCE_KIND={kind!r} "
            f"(dataset {dataset_name!r}). Known: {sorted(SOURCE_HANDLERS)}"
        ) from exc


__all__ = [
    "REFRESH_COVERAGE",
    "REFRESH_STATIONS",
    "SOURCE_HANDLERS",
    "SourceHandler",
    "get_handler",
]
