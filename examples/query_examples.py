"""Exemplos de consultas SQL no DuckDB com dados ERA5.

Este script demonstra diferentes tipos de consultas que podem
ser realizadas nos dados processados pelo PyERA5.
"""

from pathlib import Path

from pyera5.config import DatabaseConfig
from pyera5.storage.data_exporter import DataExporter
from pyera5.storage.duckdb_manager import DuckDBManager

# Configurar acesso ao banco de dados
db_config = DatabaseConfig(
    db_path=Path("./data/era5.duckdb"),
    read_only=True,
)


def example_simple_query():
    """Consulta simples - primeiras 10 linhas."""
    print("\n" + "=" * 60)
    print("Exemplo 1: Consulta simples")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT *
            FROM era5land_202301
            LIMIT 10
        """)

        print(result)


def example_temporal_aggregation():
    """Agregação temporal - médias diárias."""
    print("\n" + "=" * 60)
    print("Exemplo 2: Médias diárias de temperatura")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                DATE_TRUNC('day', time) as date,
                AVG(temp_2m) as avg_temp,
                MIN(temp_2m) as min_temp,
                MAX(temp_2m) as max_temp,
                STDDEV(temp_2m) as std_temp
            FROM era5land_202301
            GROUP BY date
            ORDER BY date
        """)

        print(result)


def example_spatial_aggregation():
    """Agregação espacial - médias por região."""
    print("\n" + "=" * 60)
    print("Exemplo 3: Médias espaciais")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                ROUND(latitude, 0) as lat_region,
                ROUND(longitude, 0) as lon_region,
                AVG(temp_2m) as avg_temp,
                SUM(total_precipitation) as total_precip,
                COUNT(*) as num_points
            FROM era5land_202301
            GROUP BY lat_region, lon_region
            ORDER BY lat_region, lon_region
        """)

        print(result)


def example_time_series():
    """Série temporal - temperatura ao longo do tempo."""
    print("\n" + "=" * 60)
    print("Exemplo 4: Série temporal de temperatura")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                time,
                temp_2m,
                total_precipitation,
                wind_speed
            FROM era5land_202301
            WHERE latitude BETWEEN -23.6 AND -23.5
              AND longitude BETWEEN -46.7 AND -46.6
            ORDER BY time
        """)

        print(result.head(20))


def example_precipitation_analysis():
    """Análise de precipitação."""
    print("\n" + "=" * 60)
    print("Exemplo 5: Análise de precipitação")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                DATE_TRUNC('day', time) as date,
                SUM(total_precipitation) as daily_precip_mm,
                AVG(temp_2m) as avg_temp_c,
                AVG(dewpoint_temp_2m) as avg_dewpoint_c,
                COUNT(*) as num_measurements
            FROM era5land_202301
            GROUP BY date
            HAVING SUM(total_precipitation) > 0
            ORDER BY daily_precip_mm DESC
            LIMIT 10
        """)

        print("\nTop 10 dias com mais precipitação:")
        print(result)


def example_wind_analysis():
    """Análise de vento."""
    print("\n" + "=" * 60)
    print("Exemplo 6: Análise de vento")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                DATE_TRUNC('day', time) as date,
                AVG(wind_speed) as avg_wind_speed,
                MAX(wind_speed) as max_wind_speed,
                AVG(wind_u_10m) as avg_u_component,
                AVG(wind_v_10m) as avg_v_component
            FROM era5land_202301
            GROUP BY date
            ORDER BY max_wind_speed DESC
            LIMIT 10
        """)

        print("\nTop 10 dias com ventos mais fortes:")
        print(result)


def example_export_to_csv():
    """Exportar resultado de consulta para CSV."""
    print("\n" + "=" * 60)
    print("Exemplo 7: Exportar para CSV")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        result = db.query("""
            SELECT
                DATE_TRUNC('day', time) as date,
                AVG(temp_2m) as avg_temp,
                AVG(total_precipitation) as avg_precip
            FROM era5land_202301
            GROUP BY date
            ORDER BY date
        """)

        # Exportar para CSV
        exporter = DataExporter()
        output_file = Path("./monthly_summary.csv")
        exporter.export_to_csv(result, output_file)

        print(f"\nDados exportados para: {output_file}")
        print(f"Total de linhas: {len(result)}")


def example_join_tables():
    """Join de múltiplas tabelas (meses diferentes)."""
    print("\n" + "=" * 60)
    print("Exemplo 8: Join de múltiplos meses")
    print("=" * 60)

    with DuckDBManager(db_config) as db:
        # Este exemplo pressupõe que você tem dados de vários meses
        result = db.query("""
            SELECT
                EXTRACT(YEAR FROM time) as year,
                EXTRACT(MONTH FROM time) as month,
                AVG(temp_2m) as avg_temp,
                SUM(total_precipitation) as total_precip,
                COUNT(*) as num_records
            FROM era5land_202301
            GROUP BY year, month
            ORDER BY year, month
        """)

        print(result)


if __name__ == "__main__":
    print("Exemplos de consultas SQL para dados ERA5")
    print("=" * 60)

    try:
        example_simple_query()
        example_temporal_aggregation()
        example_spatial_aggregation()
        example_time_series()
        example_precipitation_analysis()
        example_wind_analysis()
        example_export_to_csv()
        example_join_tables()

        print("\n" + "=" * 60)
        print("Todos os exemplos executados com sucesso!")
        print("=" * 60)

    except Exception as e:
        print(f"\nErro ao executar exemplos: {e}")
        print("Certifique-se de que:")
        print("  1. O banco de dados existe em ./data/era5.duckdb")
        print("  2. Os dados foram processados corretamente")
        print("  3. As tabelas estão registradas no DuckDB")
