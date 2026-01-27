"""IBGE municipality location data loader.

Loads municipality reference data with geographic coordinates from the
bundled CSV file. Used for geographic JOINs between ERA5 climate data
and DataSUS health data in the clima-sus package.
"""

import logging
from functools import lru_cache
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


def get_ibge_data_path() -> Path:
    """Get path to the bundled IBGE locations CSV file.

    Returns:
        Path to the CSV file

    Raises:
        FileNotFoundError: If the data file is not found
    """
    try:
        from importlib.resources import files

        data_path = files("era5_etl._data.ibge").joinpath("ibge_locais.csv")
        path = Path(str(data_path))
        if path.exists():
            return path
    except (ImportError, TypeError, AttributeError):
        pass

    # Fallback: relative to this file
    package_dir = Path(__file__).parent.parent
    fallback_path = package_dir / "_data" / "ibge" / "ibge_locais.csv"

    if fallback_path.exists():
        return fallback_path

    raise FileNotFoundError(
        f"IBGE locations CSV not found. Expected at: {fallback_path}\n"
        "Please place ibge_locais.csv in src/era5_etl/_data/ibge/"
    )


@lru_cache(maxsize=1)
def load_ibge_locations() -> list[dict[str, object]]:
    """Load IBGE municipality location data from bundled CSV.

    The CSV file has columns:
    - latitude (FLOAT)
    - longitude (FLOAT)
    - codigo_municipio_7_digitos (INT)
    - codigo_municipio_6_digitos (INT)
    - municipio (VARCHAR)
    - rg_imediata (VARCHAR)
    - rg_intermediaria (VARCHAR)
    - uf (VARCHAR)

    Returns:
        List of dicts with municipality location data
    """
    import csv

    csv_path = get_ibge_data_path()
    logger.info(f"Loading IBGE locations from {csv_path}")

    locations: list[dict[str, object]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            locations.append({
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "codigo_municipio_7_digitos": int(row["codigo_municipio_7_digitos"]),
                "codigo_municipio_6_digitos": int(row["codigo_municipio_6_digitos"]),
                "municipio": row["municipio"],
                "rg_imediata": row["rg_imediata"],
                "rg_intermediaria": row["rg_intermediaria"],
                "uf": row["uf"],
            })

    logger.info(f"Loaded {len(locations)} municipality locations")
    return locations


def generate_ibge_parquet(output_path: Path) -> Path:
    """Generate Parquet file from the bundled IBGE locations CSV.

    Reads the bundled CSV file and exports it to Parquet format using DuckDB.

    Args:
        output_path: Path for output Parquet file

    Returns:
        Path to the generated Parquet file
    """
    csv_path = get_ibge_data_path()
    logger.info(f"Generating IBGE Parquet from {csv_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(":memory:")

    conn.execute(f"""
        COPY (
            SELECT
                CAST(latitude AS DOUBLE) AS latitude,
                CAST(longitude AS DOUBLE) AS longitude,
                CAST(codigo_municipio_7_digitos AS INTEGER) AS codigo_municipio_7_digitos,
                CAST(codigo_municipio_6_digitos AS INTEGER) AS codigo_municipio_6_digitos,
                municipio,
                rg_imediata,
                rg_intermediaria,
                uf
            FROM read_csv_auto('{csv_path}', header=true)
        )
        TO '{output_path}'
        (FORMAT PARQUET, COMPRESSION 'zstd')
    """)

    result = conn.execute(
        f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}', header=true)"
    ).fetchone()
    row_count = result[0] if result else 0
    conn.close()

    logger.info(f"Generated IBGE Parquet at {output_path} with {row_count} rows")
    return output_path
