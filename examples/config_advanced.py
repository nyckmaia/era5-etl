"""Exemplo avançado de configuração do ERA5-ETL.

Este exemplo mostra configurações avançadas incluindo:
- Área geográfica customizada (Brasil)
- Múltiplas variáveis meteorológicas
- Processamento paralelo
- Particionamento customizado
- Resampling temporal
"""

from pathlib import Path

from era5_etl.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    TransformConfig,
    StorageConfig,
)
from era5_etl.constants import BRAZIL_BBOX

# Configuração avançada para dados climáticos do Brasil
config = PipelineConfig(
    download=DownloadConfig(
        output_dir=Path("./data/brazil/netcdf"),
        dataset="era5-land",
        variables=[
            # Temperatura
            "2m_temperature",
            "2m_dewpoint_temperature",
            "skin_temperature",
            # Vento
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            # Precipitação e pressão
            "total_precipitation",
            "surface_pressure",
            # Solo
            "soil_temperature_level_1",
            "volumetric_soil_water_layer_1",
        ],
        start_date="2020-01-01",
        end_date="2023-12-31",
        area=BRAZIL_BBOX,  # Área do Brasil
        hours=[
            "00:00",
            "06:00",
            "12:00",
            "18:00",
        ],  # 4 horários por dia
        override=False,  # Não sobrescrever arquivos existentes
        timeout=7200,  # 2 horas de timeout
    ),
    transform=TransformConfig(
        input_dir=Path("./data/brazil/netcdf"),
        output_dir=Path("./data/brazil/processed"),
        convert_kelvin_to_celsius=True,
        calculate_wind_speed=True,
        resample_frequency="1D",  # Média diária
        override=False,
        max_workers=4,  # Processamento paralelo com 4 workers
    ),
    storage=StorageConfig(
        parquet_dir=Path("./data/brazil/parquet"),
        partition_cols=["year", "month"],  # Particionar por ano e mês
        compression="snappy",  # Compressão rápida
        row_group_size=100_000,  # 100k linhas por grupo
    ),
    database=DatabaseConfig(
        db_path=Path("./data/brazil/brazil_climate.duckdb"),
        read_only=False,
        threads=4,  # 4 threads para DuckDB
    ),
)


# Uso:
if __name__ == "__main__":
    from era5_etl import ERA5Pipeline

    print("Iniciando pipeline avançado para dados climáticos do Brasil...")
    print(f"Período: 2020-01-01 até 2023-12-31")
    print(f"Variáveis: {len(config.download.variables)}")
    print(f"Área: Brasil (BBOX: {BRAZIL_BBOX})")

    pipeline = ERA5Pipeline(config)
    result = pipeline.run()

    print("\n" + "=" * 60)
    print("Pipeline concluído com sucesso!")
    print("=" * 60)
    print(f"\nResumo:")
    print(f"  Estágios completados: {len(result.completed_stages)}")
    print(f"  Arquivos baixados: {result.get_metadata('download_count', 0)}")
    print(f"  Arquivos processados: {result.get_metadata('processed_count', 0)}")
    print(f"  Arquivos Parquet: {result.get_metadata('parquet_count', 0)}")
    print(f"  Tabelas no DuckDB: {result.get_metadata('tables_loaded', 0)}")
    print(f"\nBanco de dados: {config.database.db_path}")
