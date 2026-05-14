"""Single source of truth for on-disk paths.

Every other module that needs to know where to read/write data must call
through these helpers. This keeps the layout consistent across the CLI, the
web API, and the tests, and makes the layout easy to change later.

Layout (a user-configurable ``base_dir`` is the root)::

    <base_dir>/
    +-- climate_data_store_db/
    |   +-- era5/
    |   |   +-- date=YYYY-MM-DD/
    |   |   |   +-- part-N.parquet
    |   |   +-- _manifest.json
    |   |   +-- era5.duckdb
    |   +-- era5-land/
    |       +-- date=YYYY-MM-DD/
    |       +-- _manifest.json
    |       +-- era5-land.duckdb
    +-- _tmp_netcdf/
        +-- era5/
        +-- era5-land/
"""

from __future__ import annotations

from pathlib import Path

STORAGE_ROOT_DIRNAME = "climate_data_store_db"
NETCDF_TMP_DIRNAME = "_tmp_netcdf"
MANIFEST_FILENAME = "_manifest.json"


def resolve_base_dir(base_dir: str | Path) -> Path:
    """Resolve a user-provided ``base_dir`` to an absolute Path.

    The directory itself is not created here -- creation is the responsibility
    of the functions that actually need to write into it.
    """
    return Path(base_dir).expanduser().resolve()


def resolve_storage_root(base_dir: str | Path) -> Path:
    """Return ``<base_dir>/climate_data_store_db/``.

    If ``base_dir`` already ends in ``climate_data_store_db`` (case-insensitive),
    it is returned unchanged -- this lets callers pass either the parent or the
    storage root itself.
    """
    base = resolve_base_dir(base_dir)
    if base.name.lower() == STORAGE_ROOT_DIRNAME.lower():
        return base
    return base / STORAGE_ROOT_DIRNAME


def resolve_dataset_dir(base_dir: str | Path, dataset: str) -> Path:
    """Return the per-dataset Parquet directory.

    ``dataset`` is used literally (``"era5"`` or ``"era5-land"``). No silent
    canonicalisation, no fallback to legacy names.
    """
    _validate_dataset_name(dataset)
    return resolve_storage_root(base_dir) / dataset


def resolve_manifest_path(base_dir: str | Path, dataset: str) -> Path:
    """Return the path of a dataset's manifest file."""
    return resolve_dataset_dir(base_dir, dataset) / MANIFEST_FILENAME


def resolve_duckdb_path(base_dir: str | Path, dataset: str) -> Path:
    """Return the dataset's DuckDB file path.

    The DuckDB file lives next to the parquet partitions so a dataset is
    fully self-contained.
    """
    return resolve_dataset_dir(base_dir, dataset) / f"{dataset}.duckdb"


def base_dir_from_dataset_dir(parquet_dir: str | Path) -> Path:
    """Inverse of :func:`resolve_dataset_dir`.

    Given a path of the form ``<base>/climate_data_store_db/<dataset>/``,
    return ``<base>``. Asserts the second-to-last segment matches the
    canonical storage root name (``climate_data_store_db``); raises
    :class:`ValueError` otherwise. Used by write paths that need to update
    derived per-base artifacts (e.g., the coverage index) and only have a
    parquet directory in hand.
    """
    p = Path(parquet_dir).resolve()
    if p.parent.name.lower() != STORAGE_ROOT_DIRNAME.lower():
        raise ValueError(
            f"{parquet_dir!s} is not a per-dataset directory under "
            f"{STORAGE_ROOT_DIRNAME!r}; cannot recover base_dir."
        )
    return p.parent.parent


def resolve_netcdf_temp_dir(base_dir: str | Path, dataset: str) -> Path:
    """Return the per-dataset temporary NetCDF directory."""
    _validate_dataset_name(dataset)
    return resolve_base_dir(base_dir) / NETCDF_TMP_DIRNAME / dataset


def ensure_dataset_dirs(base_dir: str | Path, dataset: str) -> tuple[Path, Path]:
    """Create the per-dataset storage and NetCDF-temp directories if missing.

    Returns the pair ``(dataset_dir, netcdf_tmp_dir)``.
    """
    dataset_dir = resolve_dataset_dir(base_dir, dataset)
    tmp_dir = resolve_netcdf_temp_dir(base_dir, dataset)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return dataset_dir, tmp_dir


def _validate_dataset_name(dataset: str) -> None:
    if not dataset or "/" in dataset or "\\" in dataset or dataset.startswith("."):
        raise ValueError(f"Invalid dataset name: {dataset!r}")
