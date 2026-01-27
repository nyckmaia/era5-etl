"""IBGE region lookup for geographic bounding boxes.

Provides lookup of geographic coordinates (bounding boxes) for Brazilian
geographic regions defined by IBGE (Instituto Brasileiro de Geografia e
Estatistica). Supports: municipalities (municipio), immediate regions
(regiao imediata), intermediate regions (regiao intermediaria), states (UF),
and country (pais).
"""

import logging
from enum import Enum
from functools import lru_cache
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


class RegionType(str, Enum):
    """Types of IBGE geographic regions."""

    MUNICIPIO = "municipio"
    RG_IMEDIATA = "rg_imediata"
    RG_INTERMEDIARIA = "rg_intermediaria"
    UF = "uf"
    PAIS = "pais"


# Maps RegionType to (csv_filename, name_column)
_REGION_CONFIG: dict[RegionType, tuple[str, str]] = {
    RegionType.MUNICIPIO: ("municipio.csv", "municipio"),
    RegionType.RG_IMEDIATA: ("rg_imediata.csv", "rg_imediata"),
    RegionType.RG_INTERMEDIARIA: ("rg_intermediaria.csv", "rg_intermediaria"),
    RegionType.UF: ("uf.csv", "uf"),
    RegionType.PAIS: ("pais.csv", "pais"),
}


def _get_ibge_data_dir() -> Path:
    """Get path to the IBGE data directory."""
    try:
        from importlib.resources import files

        data_path = files("era5_etl._data.ibge")
        path = Path(str(data_path))
        if path.exists():
            return path
    except (ImportError, TypeError, AttributeError):
        pass

    # Fallback: relative to this file
    package_dir = Path(__file__).parent.parent
    return package_dir / "_data" / "ibge"


@lru_cache(maxsize=8)
def load_region_data(region_type: RegionType) -> pl.DataFrame:
    """Load region data from the bundled CSV file.

    Args:
        region_type: The type of region to load.

    Returns:
        Polars DataFrame with region data.

    Raises:
        FileNotFoundError: If the CSV file is not found.
    """
    csv_filename, _ = _REGION_CONFIG[region_type]
    data_dir = _get_ibge_data_dir()
    csv_path = data_dir / csv_filename

    if not csv_path.exists():
        raise FileNotFoundError(
            f"IBGE region data not found: {csv_path}\n"
            f"Please place {csv_filename} in {data_dir}"
        )

    df = pl.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} rows from {csv_filename}")
    return df


def lookup_region_bbox(
    region_type: RegionType,
    name: str,
    uf: str | None = None,
) -> list[float]:
    """Look up the bounding box for a named region.

    Args:
        region_type: The type of region to search.
        name: The region name (case-insensitive match).
        uf: Optional UF filter (only for MUNICIPIO which has uf column).

    Returns:
        Bounding box as [North, West, South, East].

    Raises:
        ValueError: If the region name is not found.
        FileNotFoundError: If the CSV file is not found.
    """
    df = load_region_data(region_type)
    _, name_col = _REGION_CONFIG[region_type]

    # Case-insensitive match
    mask = pl.col(name_col).str.to_lowercase() == name.lower()

    # Apply UF filter if provided and column exists
    if uf and "uf" in df.columns:
        mask = mask & (pl.col("uf").str.to_uppercase() == uf.upper())

    matches = df.filter(mask)

    if len(matches) == 0:
        available = df[name_col].unique().sort().to_list()
        raise ValueError(
            f"Region '{name}' not found in {region_type.value}. "
            f"Available: {', '.join(str(v) for v in available[:10])}"
            f"{'...' if len(available) > 10 else ''}"
        )

    if len(matches) > 1 and region_type == RegionType.MUNICIPIO and uf is None:
        ufs = matches["uf"].to_list()
        raise ValueError(
            f"Multiple municipalities named '{name}' found in UFs: {ufs}. "
            f"Please specify a UF to disambiguate."
        )

    row = matches.row(0, named=True)
    return [row["north"], row["west"], row["south"], row["east"]]


def list_regions(region_type: RegionType) -> pl.DataFrame:
    """List all available regions of a given type.

    Args:
        region_type: The type of region to list.

    Returns:
        DataFrame with all region data.
    """
    return load_region_data(region_type)
