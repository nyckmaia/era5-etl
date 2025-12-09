"""Exemplo simples de configuração do PyERA5.

Este exemplo mostra uma configuração básica para download e
processamento de dados ERA5-Land.
"""

from pathlib import Path

from pyera5.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    ProcessingConfig,
    StorageConfig,
)

# Configuração básica para download de dados ERA5-Land
config = PipelineConfig(
    download=DownloadConfig(
        output_dir=Path("./data/netcdf"),
        dataset="era5-land",
        variables=[
            "2m_temperature",
            "total_precipitation",
        ],
        start_date="2023-01-01",
        end_date="2023-01-31",
    ),
    processing=ProcessingConfig(
        input_dir=Path("./data/netcdf"),
        output_dir=Path("./data/processed"),
    ),
    storage=StorageConfig(
        parquet_dir=Path("./data/parquet"),
    ),
    database=DatabaseConfig(
        db_path=Path("./data/era5.duckdb"),
    ),
)


# Uso:
if __name__ == "__main__":
    from pyera5 import ERA5Pipeline

    pipeline = ERA5Pipeline(config)
    result = pipeline.run()

    print(f"\nPipeline concluído!")
    print(f"Estágios completados: {result.completed_stages}")
    print(f"Arquivos baixados: {result.get_metadata('download_count')}")
    print(f"Arquivos processados: {result.get_metadata('processed_count')}")
