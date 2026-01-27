# ERA5-ETL

Pipeline profissional para download, processamento e análise de dados ERA5/ERA5-Land do Copernicus Climate Data Store (CDS).

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Características

- **Download automático** de dados ERA5/ERA5-Land via CDS API
- **Processamento eficiente** de arquivos NetCDF com xarray
- **Conversão para Parquet** com particionamento otimizado
- **Integração com DuckDB** para análises SQL
- **Interface CLI moderna** com Typer e Rich
- **Pipeline configurável** usando Pydantic
- **Suporte a múltiplas variáveis** meteorológicas
- **Processamento em paralelo** (opcional)

## Instalação

### Requisitos

- Python 3.11 ou superior
- Conta no [Copernicus Climate Data Store](https://cds.climate.copernicus.eu)
- Credenciais CDS API configuradas

### Instalar via pip

```bash
pip install era5-etl
```

### Instalar do código fonte

```bash
git clone https://github.com/seu-usuario/era5-etl.git
cd era5-etl
pip install -e .
```

### Configurar credenciais CDS API

1. Criar conta em https://cds.climate.copernicus.eu
2. Obter API key em https://cds.climate.copernicus.eu/api-how-to
3. Criar arquivo `~/.cdsapirc`:

```
url: https://cds.climate.copernicus.eu/api/v2
key: {seu-uid}:{sua-api-key}
```

## Uso Rápido

### Pipeline Completo

Execute o pipeline completo com um único comando:

```bash
era5 run \
  --data-dir ./data \
  --dataset era5-land \
  --start-date 2020-01-01 \
  --end-date 2020-12-31 \
  --var 2m_temperature \
  --var total_precipitation \
  --db ./data/era5.duckdb
```

Isso irá:
1. Fazer download dos dados do CDS
2. Processar arquivos NetCDF
3. Converter para Parquet particionado
4. Carregar no DuckDB

### Comandos Individuais

#### 1. Download de Dados

```bash
era5 download \
  --dataset era5-land \
  --start-date 2023-01-01 \
  --end-date 2023-01-31 \
  --var 2m_temperature \
  --var 2m_dewpoint_temperature \
  --var total_precipitation
```

#### 2. Processar NetCDF

```bash
era5 process ./data/netcdf ./data/processed
```

#### 3. Converter para Parquet

```bash
era5 convert ./data/processed ./data/parquet --compression snappy
```

#### 4. Consultar Dados (SQL)

```bash
era5 query "SELECT * FROM era5land_202301 LIMIT 10" --db ./data/era5.duckdb
```

#### 5. Exportar Dados

```bash
era5 export ./data/parquet/era5land_202301 output.csv
```

#### 6. Informações do Banco

```bash
era5 info --db ./data/era5.duckdb
```

## Uso Programático

### Exemplo Básico

```python
from pathlib import Path
from era5_etl import ERA5Pipeline, PipelineConfig
from era5_etl.config import DownloadConfig, TransformConfig, StorageConfig, DatabaseConfig

# Configurar pipeline
config = PipelineConfig(
    download=DownloadConfig(
        output_dir=Path("./data/netcdf"),
        dataset="era5-land",
        variables=["2m_temperature", "total_precipitation"],
        start_date="2023-01-01",
        end_date="2023-01-31",
    ),
    transform=TransformConfig(
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

# Executar pipeline
pipeline = ERA5Pipeline(config)
result = pipeline.run()

print(f"Estágios completados: {result.completed_stages}")
print(f"Arquivos processados: {result.get_metadata('processed_count')}")
```

### Consultas SQL no DuckDB

```python
from pathlib import Path
from era5_etl.storage.duckdb_manager import DuckDBManager
from era5_etl.config import DatabaseConfig

config = DatabaseConfig(db_path=Path("./data/era5.duckdb"), read_only=True)

with DuckDBManager(config) as db:
    # Consulta simples
    df = db.query("""
        SELECT
            DATE_TRUNC('day', time) as date,
            AVG(temp_2m) as avg_temp,
            SUM(total_precipitation) as total_precip
        FROM era5land_202301
        GROUP BY date
        ORDER BY date
    """)

    print(df)
```

### Processar NetCDF Manualmente

```python
from pathlib import Path
from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter
from era5_etl.config import TransformConfig

config = TransformConfig(
    input_dir=Path("./data/netcdf"),
    output_dir=Path("./data/processed"),
    convert_kelvin_to_celsius=True,
    calculate_wind_speed=True,
    resample_frequency="1D",  # Resample diário
)

converter = NetCDFToParquetConverter(config)

# Processar um arquivo
output = converter.process_file(Path("./data/netcdf/era5land_202301.nc"))
print(f"Arquivo processado: {output}")

# Processar diretório completo
stats = converter.process_directory()
print(f"Processados: {stats['processed']}, Falhas: {stats['failed']}")
```

## Variáveis Disponíveis

### ERA5-Land

As principais variáveis disponíveis no ERA5-Land incluem:

- `2m_temperature` - Temperatura a 2m
- `2m_dewpoint_temperature` - Temperatura do ponto de orvalho a 2m
- `10m_u_component_of_wind` - Componente U do vento a 10m
- `10m_v_component_of_wind` - Componente V do vento a 10m
- `surface_pressure` - Pressão à superfície
- `total_precipitation` - Precipitação total
- `skin_temperature` - Temperatura da superfície
- `soil_temperature_level_1` - Temperatura do solo (nível 1)
- `volumetric_soil_water_layer_1` - Umidade do solo (camada 1)

Para lista completa, consulte: https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-land

### ERA5 (Single Levels)

- Todas as variáveis do ERA5-Land
- Variáveis de radiação
- Fluxos de energia
- E muitas outras...

## Configuração Avançada

### Arquivo de Configuração Python

Crie um arquivo `config.py`:

```python
from pathlib import Path
from era5_etl.config import PipelineConfig, DownloadConfig, TransformConfig, StorageConfig, DatabaseConfig
from era5_etl.constants import BRAZIL_BBOX

config = PipelineConfig(
    download=DownloadConfig(
        output_dir=Path("./data/raw"),
        dataset="era5-land",
        variables=[
            "2m_temperature",
            "total_precipitation",
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
        ],
        start_date="2020-01-01",
        end_date="2020-12-31",
        area=BRAZIL_BBOX,  # Área do Brasil
        hours=["00:00", "06:00", "12:00", "18:00"],  # 4 horários por dia
    ),
    transform=TransformConfig(
        input_dir=Path("./data/raw"),
        output_dir=Path("./data/processed"),
        convert_kelvin_to_celsius=True,
        calculate_wind_speed=True,
        resample_frequency="1D",  # Média diária
        max_workers=4,  # Processamento paralelo
    ),
    storage=StorageConfig(
        parquet_dir=Path("./data/parquet"),
        partition_cols=["year", "month"],
        compression="snappy",
        row_group_size=100_000,
    ),
    database=DatabaseConfig(
        db_path=Path("./data/brazil_climate.duckdb"),
        threads=4,
    ),
)
```

E use:

```python
from config import config
from era5_etl import ERA5Pipeline

pipeline = ERA5Pipeline(config)
pipeline.run()
```

## Estrutura de Dados

### Diretórios

```
data/
├── netcdf/          # Arquivos NetCDF baixados do CDS
├── processed/       # CSVs processados
├── parquet/         # Parquet particionado por ano/mês
│   ├── era5land_202001/
│   │   ├── year=2020/
│   │   │   └── month=1/
│   │   │       └── *.parquet
│   └── ...
└── era5.duckdb     # Banco DuckDB
```

### Formato Parquet

Os dados são armazenados em formato Parquet com:
- **Particionamento** por ano e mês
- **Compressão** Snappy (padrão)
- **Colunas otimizadas** para queries analíticas
- **Compatível** com Polars, Pandas, DuckDB, Arrow

## Testes

Execute os testes com pytest:

```bash
# Instalar dependências de desenvolvimento
pip install -e ".[dev]"

# Executar testes
pytest

# Com coverage
pytest --cov=era5_etl --cov-report=html

# Testes específicos
pytest tests/test_config.py
pytest tests/test_core.py -v
```

## Desenvolvimento

### Setup

```bash
git clone https://github.com/seu-usuario/era5-etl.git
cd era5-etl
pip install -e ".[dev]"
```

### Code Quality

```bash
# Formatar código
ruff format .

# Lint
ruff check .

# Type checking
mypy src/era5_etl
```

## Arquitetura

ERA5-ETL usa design patterns profissionais:

- **Template Method**: Pipeline abstrato com stages customizáveis
- **Chain of Responsibility**: Encadeamento de stages
- **Context Object**: Compartilhamento de estado entre stages
- **Dependency Injection**: Configurações via Pydantic

### Componentes Principais

```
era5_etl/
├── core/              # Pipeline base e contexto
│   ├── pipeline.py    # Template Method pattern
│   ├── stage.py       # Stage abstrato
│   └── context.py     # Contexto compartilhado
├── download/          # Download do CDS
│   └── cds_downloader.py
├── transform/         # Processamento NetCDF
│   └── netcdf_to_parquet.py
├── storage/           # Armazenamento
│   ├── parquet_manager.py
│   └── duckdb_manager.py
├── pipeline/          # Pipeline ERA5
│   └── era5_pipeline.py
└── cli.py            # Interface CLI
```

## Troubleshooting

### Erro: "CDS API credentials not found"

Configure o arquivo `~/.cdsapirc` com suas credenciais.

### Erro: "No space left on device"

Dados ERA5 podem ser grandes. Certifique-se de ter espaço suficiente em disco.

### Timeout durante download

Aumente o timeout:

```python
config = DownloadConfig(
    timeout=7200,  # 2 horas
    ...
)
```

### Memória insuficiente durante processamento

Use processamento incremental ou reduza `max_workers`:

```python
config = TransformConfig(
    max_workers=1,  # Processar sequencialmente
    ...
)
```

## Contribuindo

Contribuições são bem-vindas! Por favor:

1. Fork o repositório
2. Crie uma branch para sua feature (`git checkout -b feature/nova-feature`)
3. Commit suas mudanças (`git commit -am 'Add nova feature'`)
4. Push para a branch (`git push origin feature/nova-feature`)
5. Abra um Pull Request

## Licença

Apache License 2.0 - veja [LICENSE](LICENSE) para detalhes.

## Citação

Se você usar ERA5-ETL em sua pesquisa, por favor cite:

```bibtex
@software{era5_etl,
  title = {ERA5-ETL: Pipeline profissional para dados ERA5},
  author = {Developer},
  year = {2024},
  url = {https://github.com/seu-usuario/era5-etl}
}
```

## Recursos

- [Copernicus CDS](https://cds.climate.copernicus.eu)
- [ERA5 Documentation](https://confluence.ecmwf.int/display/CKB/ERA5)
- [ERA5-Land Documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land)
- [CDS API Documentation](https://cds.climate.copernicus.eu/api-how-to)

## Suporte

- Email: dev@example.com
- Issues: https://github.com/seu-usuario/era5-etl/issues
- Discussions: https://github.com/seu-usuario/era5-etl/discussions
