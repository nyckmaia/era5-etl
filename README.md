# ERA5-ETL

Pipeline para download, processamento e análise de dados climáticos —
**ERA5** e **ERA5-Land** do Copernicus Climate Data Store (CDS) e
**INMET** (estações meteorológicas do Brasil) — com CLI, API Python e
interface web local (mapa de inventário, wizard de download, SQL e
gráficos de séries temporais).

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-beta-orange.svg)](#)

## Visão geral

ERA5-ETL trata cada produto (`era5`, `era5-land`, `inmet`) como um
**dataset plug-in independente**. Cada `DatasetConfig` tem um
`SOURCE_KIND` (`cds_grid` ou `inmet_zip`) e `pipeline/source_handlers.py`
despacha o downloader/conversor/refresh corretos — sem `if dataset == …`
espalhado. Tudo é gravado em **Parquet** e exposto via DuckDB, CLI e uma
**SPA local** (FastAPI + React + Vite).

```
   CDS API (ERA5 / ERA5-LAND)            portal.inmet.gov.br (INMET)
        │                                         │
 ┌──────▼───────┐  área 2x2→dias→var       ┌───────▼──────────┐  1 ZIP/ano
 │request_planner│                          │InmetPortalDownloader│ (1 CSV/estação)
 └──────┬───────┘                          └───────┬──────────┘
 ┌──────▼───────┐  pula chunks prontos      ┌──────▼───────────┐ latin-1, ;/,
 │ CDSDownloader │  (manifest)              │ InmetToParquet…  │ 17 vars + metadados
 └──────┬───────┘                          └──────┬───────────┘
  NetCDF em _tmp_netcdf/<ds>/               CSVs em _tmp_netcdf/inmet/<ano>/
 ┌──────▼────────────────┐                  (1 CSV → 1 Parquet)
 │NetCDFToParquetConverter│                          │
 └──────┬────────────────┘                           │
        ▼                                             ▼
 climate_data_store_db/era5[-land]/        climate_data_store_db/inmet/
   date=YYYY-MM-DD/…part-001.parquet         station=<id>/<id>_<ano>.parquet
   _manifest.json · _coverage.duckdb         _manifest.json · _stations.duckdb
        └───────────────────┬─────────────────────────┘
                  ┌─────────▼─────────┐
                  │ CLI · Web UI      │  + VIEW era5_inmet
                  │ DuckDB · Python   │  (INMET × 4 vizinhos de grade)
                  └───────────────────┘
```

## Recursos

- **Datasets como plug-ins** — cada um em
  `src/era5_etl/datasets/<nome>/` com `variables.yaml` próprio, registrado
  via `@DatasetRegistry.register`. Adicionar um novo dataset não exige tocar
  na CLI, na UI nem no planner.
- **Fonte dirige o pipeline** — `DatasetConfig.SOURCE_KIND` (`cds_grid` |
  `inmet_zip`) + `pipeline/source_handlers.py` selecionam
  downloader/conversor/refresh. ERA5/ERA5-LAND vêm do CDS (NetCDF →
  Parquet particionado por `date=`, índice de cobertura
  `_coverage.duckdb`). INMET vem do portal (ZIP anual → 1 Parquet por
  estação/ano em `station=<id>/`, índice de estações `_stations.duckdb`).
- **INMET integrado** — `era5 pipeline --dataset inmet` baixa o ZIP anual
  do portal do INMET, normaliza o CSV (latin-1, `;`/`,`, formato que
  varia por ano), mapeia as 17 variáveis posicionalmente e grava o
  Parquet com `date`/`hour_utc`/`latitude`/`longitude` no mesmo padrão do
  ERA5. Cada Parquet carrega ainda os 4 vizinhos de grade ERA5/ERA5-LAND
  + distâncias para comparação espacial. Pré-requisito: ERA5 **e**
  ERA5-LAND precisam ter ao menos o mínimo baixado antes.
- **VIEW `era5_inmet`** — alinha cada observação INMET aos 4 pontos de
  grade vizinhos do ERA5/ERA5-LAND na mesma data/hora (CLI
  `era5 era5-inmet`; também usada pela tela de séries temporais).
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
  Router/Query. Páginas: **Dashboard**, **Inventory** (mapa
  multi-sistema sobreposto — cor/tamanho/opacidade/marcador por sistema,
  pontos de grade ERA5/ERA5-LAND e estações INMET), **Download wizard**
  (com fluxo dedicado para INMET), **Query** (SQL/DuckDB), **Time
  Series** (notebook de gráficos Plotly), **Settings**. Servida pelo
  `era5 ui` (FastAPI).
- **Time Series** — `/timeseries`: notebook de células de gráfico
  (Plotly). Por série: view + variável + ponto/região (selecionável no
  mapa) + eixo Y/Y2; X = timestamp (data+hora UTC). Conversão de unidade
  **só na visualização** (presets K↔°C/°F ou fórmula custom; dados
  originais intactos), estatísticas por série (mín/máx/média/desvio/
  variância/IQR) e linha de média opcional.
- **Filtros geográficos IBGE** — `--municipio`, `--uf`,
  `--regiao-imediata`, `--regiao-intermediaria` resolvem o `area` a partir
  do shapefile IBGE empacotado.
- **Dry-run em todo lugar** — `era5 pipeline --dry-run` e
  `era5 download --dry-run` imprimem o plano de chunks + estimativa de
  tamanho sem contactar o CDS.
- **`--dataset all`** — roda CLI commands sobre `era5` e `era5-land`
  sequencialmente.
- **CDS estritamente NetCDF4** — toda requisição ao CDS usa
  `data_format="netcdf"` (GRIB foi deliberadamente adiado). INMET vem
  como CSV dentro de ZIP — caminho de ingestão próprio, sem CDS.

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

`all` inclui `era5`, `era5-land` e `inmet`. Comandos CDS-específicos
(`update`/smart-diff) fazem **no-op** para `inmet` com mensagem clara.

### INMET (estações do Brasil)

INMET não é grade nem CDS: 1 ZIP por ano no portal, 1 CSV por estação.
O download exige que ERA5 **e** ERA5-LAND já tenham o mínimo em disco
(necessário para a comparação `era5_inmet` e as distâncias por estação).

```bash
# baixe primeiro o mínimo das grades
era5 pipeline --dataset era5      --start-date 2024-01-01 --end-date 2024-01-01 --var 2m_temperature
era5 pipeline --dataset era5-land --start-date 2024-01-01 --end-date 2024-01-01 --var 2m_temperature

# depois o INMET (o intervalo de datas é traduzido para anos)
era5 pipeline --dataset inmet --start-date 2000-01-01 --end-date 2026-12-31
```

### Comparação ERA5 × INMET

```bash
era5 era5-inmet --data-dir ./data \
  -q "SELECT station_id, date, hour_utc, temp_ar,
             era5_tl_temperature_2m, era5_land_tl_temperature_2m
      FROM era5_inmet WHERE station_id = 'A001'"
```

Cria/consulta a VIEW `era5_inmet` (INMET juntado aos 4 vizinhos de grade
do ERA5 e do ERA5-LAND, mesma data/hora). Sem `-q`, faz `SELECT *`.

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
retângulos faltantes sem contactar o CDS. `update` é CDS-only — para
`inmet` ele apenas avisa e não faz nada (reuso por ano é via manifesto).

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

Reporta, por dataset: número de arquivos Parquet, tamanho total,
partições (`date=` para grade, `station=` para INMET), primeira/última
partição, e quantos registros estão no manifesto.

### Consulta SQL

```bash
era5 query \
  "SELECT date, AVG(temperature_2m) FROM era5_land GROUP BY 1 ORDER BY 1" \
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
era5 convert   --dataset era5-land           # só conversão (NetCDF/CSV -> Parquet)
era5 download  --dataset inmet               # só download (ZIP do portal INMET)
era5 dedup     --dataset all                 # migração: dedupa parquets antigos
era5 era5-inmet -q "SELECT * FROM era5_inmet LIMIT 50"   # comparação ERA5×INMET
era5 ibge      -o ./data/ibge_locais.parquet # gera o Parquet IBGE
```

`era5 --help` ou `era5 <comando> --help` mostra todas as flags.

## Layout em disco

```
<data_dir>/
├── climate_data_store_db/
│   ├── era5/
│   │   ├── date=2024-01-01/era5_2024-01-01_part-001.parquet
│   │   ├── ...
│   │   ├── _manifest.json
│   │   ├── _coverage.duckdb            # índice de cobertura (grade)
│   │   └── era5.duckdb
│   ├── era5-land/
│   │   ├── date=YYYY-MM-DD/era5-land_YYYY-MM-DD_part-001.parquet
│   │   ├── _manifest.json · _coverage.duckdb · era5-land.duckdb
│   ├── inmet/
│   │   ├── station=A001/A001_2000.parquet   # 1 Parquet por estação/ano
│   │   ├── station=A001/A001_2001.parquet
│   │   ├── ...
│   │   ├── _manifest.json
│   │   ├── _stations.duckdb            # índice de estações (não grade)
│   │   └── inmet.duckdb
│   └── _tmp_netcdf/
│       ├── era5/<chunk_id>.nc          # NetCDF bruto (descartável)
│       └── inmet/<ano>/*.CSV           # CSVs extraídos (removidos pós-conversão)
```

- Nomes das pastas são **literais** — `era5-land` mantém o hífen (idem
  CDS / `variables.yaml`).
- O DuckDB fica colocado **dentro** do diretório do dataset, mantendo
  cada dataset autocontido.
- `_tmp_netcdf/` (dentro de `climate_data_store_db/`) é descartável;
  recriar o pipeline rebaixa do CDS / portal INMET. Os índices
  `_coverage.duckdb` / `_stations.duckdb` são estado derivado —
  reconstruídos a partir do Parquet.

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
    SELECT date, AVG(temperature_2m) AS avg_t2m
    FROM era5_land
    WHERE date BETWEEN '2024-01-01' AND '2024-01-31'
    GROUP BY 1 ORDER BY 1
""").pl()
```

## Web UI (`web-ui/`)

Stack:

- **Vite + React 18 + TypeScript** (strict)
- **Tailwind CSS** com tema inspirado em interfaces científicas
- **TanStack Query** (estado servidor) + **TanStack Router** (roteamento)
- **deck.gl + maplibre-gl** (mapas do inventário e do seletor de ponto)
- **Plotly** (`plotly.js-dist-min` + `react-plotly.js`, carregado lazy
  em chunk separado) para os gráficos de séries temporais
- **apache-arrow** (decodifica respostas grandes), **monaco** (editor
  SQL), **@dnd-kit** (reordenar abas), **sonner** (toasts),
  **lucide-react** (ícones)

Páginas:

| Rota          | Função                                                                       |
|---------------|------------------------------------------------------------------------------|
| `/dashboard`  | Cards por dataset com tamanho, partições, cobertura                          |
| `/inventory`  | Mapa multi-sistema sobreposto — pontos de grade ERA5/ERA5-LAND e estações INMET; cor/tamanho/opacidade/marcador por sistema |
| `/download`   | Wizard (dataset → vars → área → datas → estimativa → run + SSE); fluxo dedicado para INMET (anos do portal) |
| `/query`      | Editor SQL DuckDB com preview e export CSV/Parquet                           |
| `/timeseries` | Notebook de gráficos Plotly: séries multi-view, ponto/região via mapa, Y/Y2, conversão de unidade visual, estatísticas |
| `/settings`   | Config do `data_dir` persistido em `~/.config/era5-etl/config.toml`          |

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
│   ├── base.py                  # DatasetConfig (NAME, SOURCE_KIND, is_gridded)
│   ├── era5/ · era5_land/       # config.py + variables.yaml (cds_grid)
│   └── inmet/                   # config.py + variables.yaml (inmet_zip)
├── download/
│   ├── request_planner.py       # plan_requests() -> RequestChunk[]
│   ├── size_estimator.py        # estimate_request_size, split_area
│   ├── cds_downloader.py        # itera chunks + cdsapi
│   └── inmet_portal.py          # scrape do portal + ZIP anual + extração
├── transform/
│   ├── netcdf_to_parquet.py     # xarray -> polars -> Parquet (date=)
│   └── inmet_to_parquet.py      # CSV latin-1 -> Parquet (station=)
├── storage/
│   ├── paths.py                 # resolve_*_dir / resolve_*_path
│   ├── manifest.py              # ChunkRecord, Manifest
│   ├── parquet_manager.py       # escrita Parquet, view DuckDB
│   ├── coverage.py              # _coverage.duckdb (grade)
│   ├── stations.py              # _stations.duckdb (INMET)
│   └── comparison.py            # VIEW era5_inmet
├── pipeline/
│   ├── era5_pipeline.py         # Template Method (download → convert → refresh)
│   └── source_handlers.py       # SOURCE_KIND → (downloader, conversor, refresh)
├── web/
│   ├── server.py                # create_app(data_dir)
│   ├── routes/                  # version, datasets, stats, settings,
│   │                            # credentials, pipeline, query, query_store,
│   │                            # regions, export, inventory, inmet, timeseries
│   ├── timeseries_sql.py        # builder SELECT-only p/ séries temporais
│   ├── runtime.py               # jobs de pipeline em background + SSE
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
3. **Download CDS é sempre `netcdf`** (GRIB mudaria converter/estimador/
   manifesto). Fontes não-CDS (INMET) têm downloader/conversor próprios
   via `source_handlers`.
4. **Size budget vem do planner**. `request_planner` é o lugar onde se
   negocia tamanho; downstream confia.
5. **Manifesto é a fonte de verdade do "feito"**, não a presença do
   arquivo Parquet — re-runs com `--override` o reescrevem.

## Adicionando um novo dataset

1. Crie `src/era5_etl/datasets/<novo>/{__init__.py, config.py, variables.yaml}`.
2. Subclasse `DatasetConfig` e decore com `@DatasetRegistry.register`,
   setando `NAME`, `_variables_yaml_path` e — para uma fonte CDS de grade
   — `CDS_DATASET_ID`/`GRID_RESOLUTION_DEG`. Para uma fonte não-grade,
   defina `SOURCE_KIND` próprio (ex.: `inmet_zip`).
3. Importe a sub-package em `era5_etl.datasets.__init__:ensure_loaded`.
4. Se `SOURCE_KIND` for novo, registre o handler em
   `pipeline/source_handlers.py` (downloader, conversor, refresh stage).
5. Adicione uma asserção em `tests/test_datasets_registry.py`.

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

# Testes (424 testes; nenhum requer rede)
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

## Download de série pontual (ARCO/Zarr) — quando NÃO usar este projeto

> Esta seção é sobre o **endpoint ARCO do CDS** para baixar um ponto ao
> longo de muitos anos — não confundir com a tela `/timeseries` (que
> plota o que já está no Parquet local).

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

## INMET × ERA5/ERA5-LAND — unidades de medida

INMET é uma fonte **de estações** (não-grade): ZIP anual do portal, 1 CSV
por estação, gravado como `inmet/station=<código>/<código>_<ano>.parquet`.
As **unidades diferem** das do ERA5/ERA5-LAND e precisam ser harmonizadas
antes de qualquer comparação numérica:

| Grandeza | ERA5 / ERA5-LAND (nativo CDS) | INMET | Conversão / observação |
|---|---|---|---|
| Temperatura do ar (2 m) | **K** — `temperature_2m` | **°C** — `temp_ar` | `°C = K − 273.15`. O transform converte por padrão (`convert_kelvin_to_celsius=True`) → o Parquet ERA5 já sai em °C |
| Ponto de orvalho (2 m) | **K** — `dewpoint_2m` | **°C** — `temp_orvalho` | idem (K → °C) |
| Pressão atmosférica | **Pa** — `surface_pressure` (e `msl_pressure`, só ERA5 SL) | **hPa = mB** — `pressao_estacao`/`pressao_max`/`pressao_min` | `1 hPa = 1 mB = 100 Pa` → `Pa = mB × 100` |
| Precipitação | **m**, acumulada — `total_precipitation` | **mm**, total horário — `precipitacao_total` | `1 m = 1000 mm`; semântica difere: ERA5 é acumulado desde o passo anterior |
| Vento | componentes **U/V em m/s** — `wind_u_10m`/`wind_v_10m` | **velocidade m/s** + rajada + direção (°) — `vento_velocidade`/`vento_rajada_max`/`vento_direcao` | velocidade ERA5 `= √(u²+v²)`; o transform deriva `wind_speed` por padrão (`calculate_wind_speed=True`) |
| Umidade relativa | **%** — `relative_humidity` (só ERA5 SL) | **%** — `umidade_relativa`/`umidade_rel_max`/`umidade_rel_min` | mesma unidade |
| Radiação solar global | **J/m²**, acumulada — `solar_radiation` (ERA5 SL) | **kJ/m²** — `radiacao_global` | `1 kJ/m² = 1000 J/m²`; acumulação difere |
| Radiação térmica | **J/m²** — `thermal_radiation` (ERA5 SL) | — | INMET não mede |
| Cobertura de nuvens | **fração 0–1** — `cloud_cover` (ERA5 SL) | — | INMET não mede |
| Evaporação | **m** — `evaporation` (ERA5 SL) | — | INMET não mede |
| Temperatura de pele/solo | **K** — `skin_temperature`, `soil_temperature_level_1..4` | — | só ERA5-LAND tem perfil de solo |
| Umidade do solo | **m³/m³** — `volumetric_soil_water_layer_1..4` | — | só ERA5-LAND |
| Tempo | **hora UTC** — `hour_utc` | **hora UTC** — `hour_utc` | ambos UTC — **sem ajuste de fuso** |

> As "unidades nativas" são o que o CDS entrega. As flags em
> `TransformConfig` (`convert_kelvin_to_celsius`, `calculate_wind_speed`)
> mudam o que efetivamente vai para o Parquet ERA5 (por padrão: °C e
> `wind_speed` derivado). INMET é gravado nas unidades originais do portal.

### Vizinhos de grade por estação (sem snap a 1 ponto)

Cada Parquet do INMET carrega, por estação, a **célula de grade
envolvente** de cada produto e a distância (km, haversine) da estação aos
**4 vértices** dessa célula — em vez de arredondar para o ponto mais
próximo. Colunas: `era5_lat_top/lat_bottom/lon_left/lon_right` +
`dist_era5_top_left/top_right/bottom_left/bottom_right` (idem
`era5_land_*`). Isso permite interpolação espacial (IDW/bilinear) na hora
de comparar, em vez de assumir o ponto mais próximo. O Parquet é gravado
ordenado por `(date, hour_utc)` para pruning de row-group no DuckDB.

### VIEW `era5_inmet`

`era5 era5-inmet --data-dir ./data` cria e consulta a view `era5_inmet`,
que alinha cada observação de estação INMET com os **4 pontos de grade
vizinhos** do ERA5 e do ERA5-LAND na **mesma data e hora (UTC)**, em uma
única tabela achatada (`i.*` + colunas `era5_<tl|tr|bl|br>_<var>` /
`era5_land_<...>` + as 8 distâncias para ponderar). Grades sem Parquet em
disco são omitidas. Também disponível via API:
`era5_etl.storage.comparison.create_era5_inmet_view(conn, base_dir)`.

```bash
era5 era5-inmet -q "
  SELECT station_id, date, hour_utc,
         temp_ar AS inmet_t2m,
         era5_tl_temperature_2m, era5_tr_temperature_2m,
         era5_bl_temperature_2m, era5_br_temperature_2m,
         dist_era5_top_left, dist_era5_top_right,
         dist_era5_bottom_left, dist_era5_bottom_right
  FROM era5_inmet
  WHERE station_id = 'A001' AND date = DATE '2000-10-05'
"
```

### Tela de séries temporais (`/timeseries`)

Notebook de gráficos para analisar/correlacionar séries temporais entre
ERA5, ERA5-LAND, INMET e a view `era5_inmet`. Backend:
`POST /api/timeseries` (1 query capada por série; combina `date`+
`hour_utc` num timestamp UTC; bucket `raw|hour|day|month` com
auto-coarsen se exceder o limite de pontos) e `GET /api/timeseries/meta`
(views, colunas numéricas, tipo de localização, faixa de datas).

Por **célula de gráfico**: intervalo de datas (limitado à cobertura
real), bucket, máx. de pontos. Por **série**: view + variável +
agregação + eixo Y/Y2 + **ponto/região** (digitado ou clicado no mapa —
coordenadas são "snapadas" para a resolução da grade) + **conversão de
unidade só na visualização** (presets K↔°C/°F ou fórmula custom; os
dados no Parquet não mudam) + **linha de média** opcional. Cada série
mostra estatísticas (mín, máx, média, desvio-padrão, variância, IQR).
Adicionar/duplicar/remover/reordenar células; estado persiste em
`localStorage`.

> **Atenção à unidade:** ERA5/ERA5-LAND já são gravados em **°C** pelo
> pipeline (`convert_kelvin_to_celsius=True` por padrão — conversão feita
> na escrita do Parquet, não na tela). Logo, para comparar temperatura
> com o INMET (também °C) **não** aplique o preset K→°C. A conversão
> visual serve para unidades que realmente diferem (pressão Pa↔mB,
> precipitação m↔mm, radiação J/m²↔kJ/m²) ou se o Kelvin tiver sido
> mantido (`--no` da flag no uso programático).

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
