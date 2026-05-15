# ERA5-ETL

Pipeline para download, processamento e análise de dados ERA5 e ERA5-Land do
Copernicus Climate Data Store (CDS), com CLI, API Python e interface web
local.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](#)

## Visão geral

ERA5-ETL trata cada produto ERA5-family (`era5`, `era5-land`) como um
**dataset plug-in independente**, faz download via CDS API quebrando
automaticamente requisições grandes em pedaços (`RequestChunk`s), grava em
**Parquet particionado por dia** (`date=YYYY-MM-DD/`), mantém um
**manifesto** com o que já foi baixado, e expõe os dados via DuckDB, CLI e
uma **SPA local** (FastAPI + React + Vite).

```
              CDS API
                 │
        ┌────────▼────────┐
        │ request_planner │  ─ quebra por área 2x2 → dias → variável
        └────────┬────────┘
                 │ RequestChunk[]
        ┌────────▼────────┐
        │  CDSDownloader  │  ─ consulta manifest, pula chunks prontos
        └────────┬────────┘
       NetCDF em _tmp_netcdf/<dataset>/
                 │
        ┌────────▼────────────────┐
        │ NetCDFToParquetConverter│
        └────────┬────────────────┘
                 │
   climate_data_store_db/<dataset>/
     date=YYYY-MM-DD/<dataset>_<YYYY-MM-DD>_part-001.parquet
     _manifest.json
     <dataset>.duckdb
                 │
        ┌────────▼────────┐
        │ CLI · Web UI    │
        │ DuckDB · Python │
        └─────────────────┘
```

## Recursos

- **Datasets como plug-ins** — cada um em
  `src/era5_etl/datasets/<nome>/` com `variables.yaml` próprio, registrado
  via `@DatasetRegistry.register`. Adicionar um novo dataset não exige tocar
  na CLI, na UI nem no planner.
- **Layout único de paths** — `storage/paths.py` é o ponto único de verdade:
  `climate_data_store_db/<dataset>/` para Parquet+manifest+DuckDB,
  `_tmp_netcdf/<dataset>/` para downloads brutos. Sem path-joining
  espalhado.
- **Request planner hierárquico** — `download/request_planner.py` divide
  requisições no cascata fixa **área 2x2 → blocos de dias → por variável**,
  cada chunk caindo dentro do `max_request_bytes`. Levanta
  `DownloadSizeError` em vez de mandar uma requisição que será rejeitada.
- **Manifesto por dataset** — `storage/manifest.py` mantém um JSON
  `(_manifest.json)` indexado por `chunk_id`. Tanto o download quanto o
  comando `era5 update` consultam o manifesto para pular trabalho já feito.
- **Web UI local** — Vite + React + TypeScript + Tailwind + TanStack
  Router/Query + Radix. Páginas: **Dashboard**, **Download wizard**,
  **SQL query**, **Settings**. Servida pelo `era5 ui` (FastAPI).
- **Filtros geográficos IBGE** — `--municipio`, `--uf`,
  `--regiao-imediata`, `--regiao-intermediaria` resolvem o `area` a partir
  do shapefile IBGE empacotado.
- **Dry-run em todo lugar** — `era5 pipeline --dry-run` e
  `era5 download --dry-run` imprimem o plano de chunks + estimativa de
  tamanho sem contactar o CDS.
- **`--dataset all`** — roda CLI commands sobre `era5` e `era5-land`
  sequencialmente.
- **Estritamente NetCDF4** — todas as requisições usam
  `data_format="netcdf"`; o converter é a única coisa que lê o arquivo
  bruto. Suporte a GRIB foi deliberadamente adiado.

## Instalação

### Pré-requisitos

- **Python 3.11+** (recomendado 3.12).
- Conta no [Copernicus CDS](https://cds.climate.copernicus.eu) com chave
  de API ativa.
- **Para a Web UI:** `bun` (recomendado) ou `pnpm`/`npm`. O hook de build
  do Hatch detecta automaticamente o runner disponível; sem nenhum, o
  bundle SPA é pulado e a UI fica indisponível no wheel
  (mas as APIs HTTP continuam funcionando).

### A partir do código fonte

```bash
git clone https://github.com/seu-usuario/era5-etl.git
cd era5-etl
pip install -e ".[dev]"
```

Em ambiente Windows com Python 3.12 isolado:

```powershell
py -3.12 -m pip install -e ".[dev]"
```

### Credenciais CDS

1. Crie um arquivo `~/.cdsapirc` (Linux/macOS) ou `%USERPROFILE%\.cdsapirc`
   (Windows):

```ini
url: https://cds.climate.copernicus.eu/api
key: <SEU-UID>:<SUA-API-KEY>
```

2. Aceite os termos do dataset que vai usar na página do produto
   (ex.: ERA5-Land) antes do primeiro download.

## Uso rápido (CLI)

O comando principal é `era5` (alias: `era5-etl`).

### Inspecionar variáveis disponíveis

```bash
era5 variables --dataset era5-land
```

### Pipeline completo (download + convert)

```bash
era5 pipeline \
  --data-dir ./data \
  --dataset era5-land \
  --start-date 2023-01-01 \
  --end-date 2023-01-31 \
  --var 2m_temperature \
  --var total_precipitation
```

Cobertura geográfica padrão: bounding box do Brasil. Use `--municipio`,
`--uf`, `--regiao-imediata` ou `--regiao-intermediaria` para recortar.

### Dry-run (planejar sem baixar)

```bash
era5 pipeline --dataset era5-land \
  --start-date 2024-01-01 --end-date 2024-12-31 --dry-run
```

Imprime a lista de `chunk_id`s, dias cobertos, área (N,W,S,E) e estimativa
total em MB.

### Rodar para todos os datasets

```bash
era5 pipeline --dataset all --start-date 2024-01-01 --end-date 2024-01-31
```

### Atualização incremental

`era5 update` calcula, por `(variável, ano-mês)`, o **diff de cobertura
em nível de célula** entre a área pedida e o que o manifesto registra como
já baixado, e só faz requisição CDS para os retângulos faltantes — pronto
para crontab:

```bash
era5 update --dataset era5-land --start-date 2020-01-01 --uf SP
```

A próxima execução com `--uf RJ` (cuja bbox se sobrepõe à de SP) baixa
**apenas a região disjunta**. Adicione `--dry-run` para listar os
retângulos faltantes sem contactar o CDS.

### País e regiões IBGE

`--pais` é a flag de primeiro nível para escopo geográfico (default
`Brasil`). Sem mais nenhuma flag, devolve a bbox do país:

```bash
era5 pipeline --pais Brasil --start-date 2024-01-01 --end-date 2024-01-31
```

Combinado com flags de subregião IBGE, restringe dentro do país:

```bash
era5 pipeline --pais Brasil --uf SP   # bbox de SP
era5 pipeline --pais Brasil --municipio Campinas --uf SP  # municipio + UF (desambigua)
```

As flags `--municipio`, `--regiao-imediata`, `--regiao-intermediaria`,
`--uf` são mutuamente exclusivas (exceto `--municipio + --uf`). Países
não suportados levantam erro — adicione uma linha em
`src/era5_etl/_data/ibge/pais.csv` para habilitar.

### Dedup de dados pré-existentes

Para datasets criados antes da v0.3.0 (que podia gravar arquivos
sobrepostos numa mesma partição):

```bash
era5 dedup --dataset all
```

Lê cada partição `date=YYYY-MM-DD/`, colapsa linhas duplicadas por
`(latitude, longitude, hour_utc)`, e regrava. Idempotente.

### Status

```bash
era5 status --dataset all
```

Reporta, por dataset: número de arquivos Parquet, tamanho total, número de
partições `date=`, primeira/última partição, e quantos chunks estão no
manifesto.

### Consulta SQL

```bash
era5 query \
  "SELECT date_trunc('day', valid_time) AS d, AVG(t2m) FROM era5_land GROUP BY 1 ORDER BY 1" \
  --dataset era5-land --limit 50
```

A view DuckDB (`<dataset>` (hífens viram `_`: `era5-land` → view `era5_land`)) é criada sob demanda apontando para o
diretório Parquet do dataset.

**Pruning automático em duas camadas:**

1. **Diretório Hive** — `WHERE date BETWEEN ...` poda partições antes
   de abrir qualquer arquivo (a coluna `date` está no nome da pasta).
2. **Row-group statistics** — `WHERE latitude BETWEEN ...` aproveita o
   sort interno `(latitude, longitude, hour_utc)` aplicado na escrita.
   Min/max de cada row-group ficam apertados → DuckDB pula
   row-groups inteiros que não intersectam o filtro espacial. **Não há
   necessidade de colunas Hive auxiliares** como `lat_bucket` ou
   `lon_bucket`; a query é natural sobre `latitude`/`longitude` reais.

Exemplo de query natural que aproveita as duas camadas:

```sql
SELECT *
FROM era5_land
WHERE date BETWEEN '2024-06-01' AND '2024-08-31'   -- partition pruning
  AND latitude  BETWEEN -25.0 AND -22.0            -- row-group pruning
  AND longitude BETWEEN -48.0 AND -45.0            -- row-group pruning
  AND hour_utc IN (12, 13, 14);                    -- row-group pruning
```

### Web UI

```bash
era5 ui --data-dir ./data --port 8788
```

Abre o navegador em `http://127.0.0.1:8788/`. A SPA é servida pelo FastAPI
a partir de `src/era5_etl/web/static/` (gerada no build).

### Comandos auxiliares

```bash
era5 convert  --dataset era5-land            # só conversão NetCDF -> Parquet
era5 download --dataset era5      --dry-run  # só plano de download
era5 dedup    --dataset all                  # migração: dedupa parquets antigos
era5 ibge     -o ./data/ibge_locais.parquet  # gera o Parquet IBGE
```

`era5 --help` ou `era5 <comando> --help` mostra todas as flags.

## Layout em disco

```
<data_dir>/
├── climate_data_store_db/
│   ├── era5/
│   │   ├── date=2024-01-01/era5_2024-01-01_part-001.parquet
│   │   ├── date=2024-01-02/era5_2024-01-02_part-001.parquet
│   │   ├── ...
│   │   ├── _manifest.json
│   │   └── era5.duckdb
│   └── era5-land/
│       ├── date=YYYY-MM-DD/era5-land_YYYY-MM-DD_part-001.parquet
│       ├── _manifest.json
│       └── era5-land.duckdb
└── _tmp_netcdf/
    ├── era5/<chunk_id>.nc
    └── era5-land/<chunk_id>.nc
```

- Nomes das pastas são **literais** — `era5-land` mantém o hífen (idem
  CDS / `variables.yaml`).
- O DuckDB fica colocado **dentro** do diretório do dataset, mantendo
  cada dataset autocontido.
- `_tmp_netcdf/` é descartável; recriar o pipeline regenera tudo a
  partir do CDS.

## Uso programático

```python
from pathlib import Path
from era5_etl.config import PipelineConfig
from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

config = PipelineConfig.create(
    base_dir=Path("./data"),
    dataset="era5-land",
    start_date="2024-01-01",
    end_date="2024-01-31",
    variables=["2m_temperature", "total_precipitation"],
)

context = ERA5Pipeline(config).run()
print(context.get_metadata("converted_count"))
```

`PipelineConfig.create()` é o único caminho sancionado para montar config:
ele resolve paths via `storage.paths`, puxa variáveis default do
`variables.yaml` do dataset, e amarra `download.output_dir`, `storage`,
`database.db_path` consistentemente.

### Consultando direto via DuckDB

```python
import duckdb
from era5_etl.storage.parquet_manager import ParquetManager

mgr = ParquetManager(base_dir=Path("./data"), dataset="era5-land")
conn = duckdb.connect(":memory:")
mgr.create_duckdb_view(conn, "era5_land")

df = conn.execute("""
    SELECT date_trunc('day', valid_time) AS day,
           AVG(t2m) AS avg_t2m
    FROM era5_land
    WHERE valid_time BETWEEN '2024-01-01' AND '2024-01-31'
    GROUP BY 1 ORDER BY 1
""").pl()
```

## Web UI (`web-ui/`)

Stack:

- **Vite + React 18 + TypeScript** (strict)
- **Tailwind CSS** com tema inspirado em interfaces científicas
- **TanStack Query** (estado servidor) + **TanStack Router** (roteamento)
- **Radix UI** (dialog, select, tabs, tooltip)
- **lucide-react** para ícones

Páginas:

| Rota             | Função                                                                       |
|------------------|------------------------------------------------------------------------------|
| `/`              | Dashboard — cards por dataset com tamanho, partições, cobertura              |
| `/download`      | Wizard de download (dataset → vars → área → datas → estimativa → run + SSE)  |
| `/query`         | Editor SQL com preview Polars e export CSV/Parquet                           |
| `/settings`      | Config do `data_dir` persistido em `~/.config/era5-etl/config.toml`          |

### Dev mode

Backend e frontend em paralelo:

```bash
# Terminal 1 — FastAPI em :8788
make api-dev
# (ou) py -3.12 -m uvicorn era5_etl.web.server:create_app --factory --reload --port 8788

# Terminal 2 — Vite em :5173 com proxy /api -> :8788
make ui-dev
# (ou) cd web-ui && bun run dev
```

### Build da SPA

```bash
make ui-build           # bun install && bun run build
# saída: src/era5_etl/web/static/
```

Quando o pacote Python é construído (`pip install .` / `hatch build`), o
hook `hatch_build.py` roda esse build automaticamente. Defina
`ERA5_ETL_SKIP_UI_BUILD=1` para pular (CI sem Node/Bun).

## Arquitetura

```
src/era5_etl/
├── cli.py                       # Typer + Rich; despacha para módulos
├── config.py                    # PipelineConfig.create(), DownloadConfig, ...
├── datasets/                    # plug-ins
│   ├── base.py                  # DatasetConfig abstrato
│   ├── era5/                    # config.py + variables.yaml
│   └── era5_land/               # config.py + variables.yaml
├── download/
│   ├── request_planner.py       # plan_requests() -> RequestChunk[]
│   ├── size_estimator.py        # estimate_request_size, split_area
│   └── cds_downloader.py        # itera chunks + cdsapi
├── transform/
│   └── netcdf_to_parquet.py     # xarray -> polars -> Parquet particionado
├── storage/
│   ├── paths.py                 # resolve_*_dir / resolve_*_path
│   ├── manifest.py              # ChunkRecord, Manifest
│   ├── parquet_manager.py       # escrita Parquet, view DuckDB
│   └── duckdb_manager.py
├── pipeline/
│   └── era5_pipeline.py         # Template Method (download → convert)
├── web/
│   ├── server.py                # create_app(data_dir)
│   ├── routes/                  # version, datasets, stats, settings,
│   │                            # pipeline (estimate/run/SSE), query, export
│   ├── runtime.py               # roda jobs de pipeline em background + SSE
│   ├── user_config.py           # ~/.config/era5-etl/config.toml
│   └── static/                  # SPA gerada (gitignored)
├── utils/
│   ├── variables.py             # list_variables() via registry
│   └── ibge_loader.py           # bbox por município/UF/região
└── _data/                       # IBGE CSV/shape empacotados
```

### Invariantes que importa preservar

1. **`DownloadConfig.dataset` é validado pelo registry**, não por
   `Literal`. Adicionar dataset = `@DatasetRegistry.register`.
2. **Toda decisão de path passa por `storage.paths`**. Nunca faça
   `base / "parquet" / dataset` na unha — chame `resolve_dataset_dir`.
3. **Todo download é `netcdf`**. Se for adicionar GRIB, isso muda também
   o converter, o estimador, e o manifesto.
4. **Size budget vem do planner**. `request_planner` é o lugar onde se
   negocia tamanho; downstream confia.
5. **Manifesto é a fonte de verdade do "feito"**, não a presença do
   arquivo Parquet — re-runs com `--override` o reescrevem.

## Adicionando um novo dataset

1. Crie `src/era5_etl/datasets/<novo>/{__init__.py, config.py, variables.yaml}`.
2. Subclasse `DatasetConfig` e decore com `@DatasetRegistry.register`,
   setando `NAME`, `CDS_DATASET_ID`, `GRID_RESOLUTION_DEG`, e o
   `_variables_yaml_path`.
3. Importe a sub-package em `era5_etl.datasets.__init__:ensure_loaded`.
4. Adicione uma asserção em `tests/test_datasets_registry.py`.

CLI, Web UI, planner e manifesto pegam o novo nome automaticamente.

## Versionamento

- **`VERSION`** é a fonte única de verdade.
- `hatch_build.py` materializa o conteúdo em
  `src/era5_etl/__version__.py` no build (não edite à mão).
- `web-ui/package.json` é atualizado manualmente para refletir releases
  maiores (sem impacto funcional, mas exposto no SPA).

## Desenvolvimento

```bash
# Setup
pip install -e ".[dev]"

# Testes (178 testes; nenhum requer rede)
make test          # ou: py -3.12 -m pytest

# Coverage HTML
py -3.12 -m pytest --cov-report=html

# Lint / type-check
make lint          # ruff check src tests
make typecheck     # mypy src/era5_etl

# Format
ruff format .

# Rodar API + UI em modo dev (paralelo)
make dev
```

Testes da Web UI usam o `TestClient` do FastAPI — sem rede.
Testes do request planner usam `max_request_bytes` artificialmente baixos
para forçar todos os tiers de split (a flag é setada após a construção
para passar do floor de 1 MiB do Pydantic).

## Time-series (ARCO/Zarr) — quando NÃO usar este projeto

O Copernicus mantém endpoints experimentais em formato
**Analysis Ready Cloud Optimized (ARCO / Zarr)** otimizados para
**single-point time-series** ao longo de períodos muito longos:

- `reanalysis-era5-land-timeseries`
- `reanalysis-era5-single-levels-timeseries`

São o caminho mais eficiente quando o caso de uso é:
> "extrair uma ou poucas variáveis em **um único ponto da grade** ao longo
> de **muitos anos**" (sem precisar do retângulo todo).

Para esse caso, vá direto via `cdsapi` — este projeto não cobre o
endpoint ARCO porque o pipeline é otimizado para downloads **por área**
com particionamento Parquet diário (formato e schema diferentes). O
`cdsapi` por default loga uma nota sobre o endpoint ARCO em todas as
requisições; o ERA5-ETL silencia essa mensagem
(`install_cdsapi_log_filter`) para reduzir ruído. Re-habilitar se
necessário: remover o filter do `logging.getLogger("cdsapi")`.

Exemplo mínimo (fora do escopo deste pacote):

```python
import cdsapi
c = cdsapi.Client()
c.retrieve(
    "reanalysis-era5-land-timeseries",
    {
        "variable": "2m_temperature",
        "location": {"latitude": -23.55, "longitude": -46.63},  # ponto único
        "date": ["2000-01-01/2024-12-31"],
        "data_format": "netcdf",
    },
    "sao_paulo_t2m.nc",
)
```

## Troubleshooting

### `Unknown dataset 'era5land'`

Use o nome canônico **com hífen**: `era5-land`. O hífen é literal em CDS
API, no diretório, e na YAML.

### `DownloadSizeError`

Aconteceu mesmo após o planner ter quebrado a requisição até o mínimo
(1 var × 1 dia × 1 ponto da grade). Aumente `max_request_bytes` ou reduza
o `area`/`hours`.

### `era5 ui` abre mas só vê JSON / `404`

A SPA não foi construída. Rode `make ui-build` ou faça `pip install .`
(que dispara o hook do Hatch). Garanta que `src/era5_etl/web/static/index.html`
exista.

### `bun: command not found` no build

Use `pnpm` ou `npm` — o hook detecta o primeiro disponível. Ou
`ERA5_ETL_SKIP_UI_BUILD=1 pip install .` para instalar sem a SPA (CLI e
API HTTP continuam funcionando).

### CDS retorna `Your request is queued`

Comportamento normal — pedidos grandes esperam fila do Copernicus. O
downloader faz long-poll com retry exponencial (`max_retries`,
`retry_delay`).

## Licença

Apache License 2.0 — veja [LICENSE](LICENSE).

## Recursos externos

- [Copernicus CDS](https://cds.climate.copernicus.eu)
- [ERA5 documentation](https://confluence.ecmwf.int/display/CKB/ERA5)
- [ERA5-Land documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land)
- [CDS API how-to](https://cds.climate.copernicus.eu/api-how-to)
