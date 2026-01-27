# Exemplos de Configuração do ERA5-ETL

Este diretório contém exemplos práticos de configuração e uso do ERA5-ETL.

## Arquivos Disponíveis

### 1. `config_simple.py`

Exemplo básico de configuração para iniciantes.

**Características:**
- Configuração mínima necessária
- Download de 2 variáveis (temperatura e precipitação)
- Período de 1 mês
- Processamento padrão

**Uso:**
```bash
python examples/config_simple.py
```

### 2. `config_advanced.py`

Exemplo avançado com todas as funcionalidades.

**Características:**
- Área geográfica customizada (Brasil)
- 9 variáveis meteorológicas
- Período de 4 anos (2020-2023)
- Processamento paralelo
- Resampling temporal para médias diárias
- Particionamento customizado

**Uso:**
```bash
python examples/config_advanced.py
```

### 3. `query_examples.py`

Exemplos de consultas SQL no DuckDB.

**Demonstra:**
- Consultas simples
- Agregações temporais (médias diárias)
- Agregações espaciais (por região)
- Séries temporais
- Análise de precipitação
- Análise de vento
- Exportação para CSV
- Joins entre tabelas

**Uso:**
```bash
python examples/query_examples.py
```

## Pré-requisitos

Antes de executar os exemplos, certifique-se de:

1. **Instalar o ERA5-ETL:**
   ```bash
   pip install -e .
   ```

2. **Configurar credenciais CDS API:**

   Criar arquivo `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api/v2
   key: {seu-uid}:{sua-api-key}
   ```

3. **Ter espaço em disco suficiente:**
   - Dados NetCDF podem ocupar vários GB
   - Recomenda-se 10+ GB livres

## Modificando os Exemplos

### Alterar Período de Download

```python
download=DownloadConfig(
    start_date="2023-01-01",  # Data inicial
    end_date="2023-12-31",    # Data final
    ...
)
```

### Alterar Variáveis

```python
download=DownloadConfig(
    variables=[
        "2m_temperature",
        "total_precipitation",
        # Adicione mais variáveis aqui
    ],
    ...
)
```

### Alterar Área Geográfica

```python
from era5_etl.constants import BRAZIL_BBOX, GLOBAL_BBOX

download=DownloadConfig(
    area=BRAZIL_BBOX,  # Brasil
    # ou
    area=GLOBAL_BBOX,  # Global
    # ou
    area=[10, -50, -10, -30],  # Customizado: [N, W, S, E]
    ...
)
```

### Processar Apenas Download

Se você só quer fazer download dos dados:

```python
from era5_etl.download.cds_downloader import CDSDownloader
from era5_etl.config import DownloadConfig

config = DownloadConfig(
    output_dir=Path("./data/netcdf"),
    dataset="era5-land",
    variables=["2m_temperature"],
    start_date="2023-01-01",
    end_date="2023-01-31",
)

downloader = CDSDownloader(config)
files = downloader.download()
print(f"Baixados {len(files)} arquivos")
```

### Processar Apenas NetCDF

Se você já tem os arquivos NetCDF e quer apenas processá-los:

```python
from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter
from era5_etl.config import TransformConfig

config = TransformConfig(
    input_dir=Path("./data/netcdf"),
    output_dir=Path("./data/processed"),
    convert_kelvin_to_celsius=True,
    calculate_wind_speed=True,
)

converter = NetCDFToParquetConverter(config)
stats = converter.process_directory()
print(f"Processados: {stats['processed']}")
```

## Troubleshooting

### Erro: "CDS API credentials not found"

Configure o arquivo `~/.cdsapirc` com suas credenciais do CDS.

### Erro: "Timeout during download"

Aumente o timeout na configuração:

```python
download=DownloadConfig(
    timeout=7200,  # 2 horas
    ...
)
```

### Erro: "Memory error"

Reduza o número de workers:

```python
transform=TransformConfig(
    max_workers=1,  # Processar sequencialmente
    ...
)
```

## Recursos Adicionais

- [Documentação completa](../README.md)
- [Lista de variáveis ERA5-Land](https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-land)
- [CDS API Documentation](https://cds.climate.copernicus.eu/api-how-to)

## Suporte

Em caso de dúvidas ou problemas:

- Abra uma issue: https://github.com/seu-usuario/era5-etl/issues
- Consulte a documentação: https://github.com/seu-usuario/era5-etl
