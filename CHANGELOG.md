# Changelog

## [0.1.0] - 2024-12-09

### Implementação Completa do PyERA5

#### Adicionado
- **Interface CLI completa** (`cli.py`)
  - Comando `run`: Pipeline completo end-to-end
  - Comando `download`: Download de dados ERA5/ERA5-Land
  - Comando `process`: Processamento de NetCDF para CSV
  - Comando `convert`: Conversão de CSV para Parquet
  - Comando `query`: Consultas SQL no DuckDB
  - Comando `info`: Informações sobre o banco de dados
  - Comando `export`: Exportação para CSV
  - Rich output formatado no terminal
  - Logging configurável (verbose mode)

- **Estrutura de Testes** (`tests/`)
  - `test_config.py`: Testes para configurações (10 testes)
  - `test_core.py`: Testes para componentes core (11 testes)
  - `test_processor.py`: Testes para processamento NetCDF (7 testes)
  - `test_storage.py`: Testes para storage e DuckDB (10 testes)
  - `conftest.py`: Fixtures compartilhadas
  - **38 testes passando** ✅

- **Documentação Expandida**
  - README.md completo com:
    - Guia de instalação
    - Exemplos de uso
    - Documentação da API
    - Guia de desenvolvimento
    - Troubleshooting
  - Badges de status
  - Instruções de configuração CDS API

- **Exemplos de Configuração** (`examples/`)
  - `config_simple.py`: Configuração básica para iniciantes
  - `config_advanced.py`: Configuração avançada com todas as features
  - `query_examples.py`: 8 exemplos de consultas SQL
  - `README.md`: Documentação dos exemplos

#### Componentes Core (já existentes)
- ✅ `core/pipeline.py`: Pipeline base com Template Method pattern
- ✅ `core/stage.py`: Stages abstratos com Chain of Responsibility
- ✅ `core/context.py`: Context object para compartilhar estado
- ✅ `download/cds_downloader.py`: Download via CDS API
- ✅ `transform/netcdf_processor.py`: Processamento NetCDF com xarray
- ✅ `storage/parquet_writer.py`: Escrita de Parquet particionado
- ✅ `storage/duckdb_manager.py`: Gerenciamento DuckDB
- ✅ `storage/data_exporter.py`: Exportação de dados
- ✅ `pipeline/era5_pipeline.py`: Pipeline ERA5 completo
- ✅ `config.py`: Configurações com Pydantic
- ✅ `constants.py`: Constantes e mapeamentos
- ✅ `types.py`: Type aliases
- ✅ `exceptions.py`: Exceções customizadas

#### Melhorias
- Instalação funcionando com `pip install -e .`
- Comando CLI `pyera5` disponível globalmente
- Todos os testes passando (38/38)
- Documentação completa e profissional
- Exemplos práticos prontos para uso

#### Recursos Técnicos
- **Design Patterns**: Template Method, Chain of Responsibility, Context Object
- **Type Safety**: Type hints completos, validação Pydantic
- **Testing**: 38 testes com pytest, fixtures compartilhadas
- **CLI**: Typer com Rich para output formatado
- **Data Processing**: Polars, xarray, DuckDB
- **Code Quality**: Configuração ruff e mypy

### Status do Projeto

✅ **Totalmente funcional e pronto para uso!**

#### Testado
- ✅ Instalação via pip
- ✅ CLI funcionando
- ✅ Imports corretos
- ✅ 38 testes passando
- ✅ Exemplos executáveis

#### Para Produção
- [ ] Publicar no PyPI
- [ ] CI/CD com GitHub Actions
- [ ] Documentação online (ReadTheDocs)
- [ ] Mais exemplos de casos de uso
- [ ] Integração com outros formatos (GeoTIFF, Zarr)

### Como Usar

```bash
# Instalar
pip install -e .

# Executar pipeline completo
pyera5 run --data-dir ./data --dataset era5-land --start-date 2023-01-01 --end-date 2023-01-31

# Ver ajuda
pyera5 --help

# Executar testes
pytest tests/ -v
```

### Arquitetura

```
pyera5/
├── cli.py              # Interface CLI completa
├── core/               # Pipeline base
├── download/           # Download CDS
├── transform/          # Processamento NetCDF
├── storage/            # Storage (Parquet, DuckDB)
└── pipeline/           # Pipeline ERA5

tests/                  # 38 testes
examples/               # Exemplos práticos
```

### Dependências

- Python 3.11+
- polars, xarray, netCDF4
- duckdb, pyarrow
- pydantic, typer, rich
- cdsapi, cfgrib

### Autor

Developer <dev@example.com>

### Licença

Apache License 2.0
