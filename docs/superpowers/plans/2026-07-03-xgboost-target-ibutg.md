# Template de notebook "XGBoost - Target IBUTG" — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Novo template de notebook `xgboost_target_ibutg` ("XGBoost - Target IBUTG") que prevê o IBUTG (WBGT) derivado das observações INMET, usando features ERA5-LAND interpoladas bilinearmente no ponto da estação + derivadas Tn/Tg/IBUTG dos dois sistemas, com RMSE adicional restrito ao horário de trabalho.

**Architecture:** Cópia programática do template `xgboost_optuna_windows.json` (22 células) com edições cirúrgicas + 1 célula nova de derivação inserida entre o load e a validação (23 células). Todas as fórmulas meteorológicas ficam **inline na célula do notebook, vetorizadas com pandas** (decisão do usuário — visíveis para análise). Nenhuma mudança em código Python do pacote nem no web-ui (o nome do template vem da API).

**Tech Stack:** JSON de template (`src/era5_etl/_data/notebook_templates/`), pandas/numpy (células), pytest. Geração via script descartável no scratchpad (padrão já usado no repo — cf. commit b9289d7).

## Contexto (por que esta mudança)

Task 0 do `TODO.md`: o usuário quer prever o índice de estresse térmico IBUTG (Índice de Bulbo Úmido Termômetro de Globo / WBGT) da estação INMET. As fórmulas de referência estão em `~/dev/pyinmet/src/pyinmet/utils/meteorology.py`:

- `vel1_5 = vel10 * (1.5/10)**0.21` (lei de potência)
- `tn = 0.57175*d2m + 0.19447*t2m − 0.26523*vel1_5 − 0.05134*UR + 10.44966`
- `tg = 1.374385*t2m + 0.083627*UR − 1.021632*vel1_5`
- `ibutg = 0.7*tn + 0.2*tg + 0.1*t2m`

(entradas em °C, m/s, %; **sem os `round()` do pyinmet** — precisão cheia para treino; NaN propaga como o None-propagation original.)

**Decisões aprovadas pelo usuário no brainstorm:**
1. RMSE de horário de trabalho: filtro **direto em `hour_utc`**, intervalo **semiaberto** `[WORKING_HOUR_START, WORKING_HOUR_STOP)` = 7..18 (12 horas). Sem conversão de fuso.
2. Variáveis INMET/derivadas-INMET ligadas nos toggles entram como **features com lags e cutoff próprio** `INMET_CUTOFF_HOURS = 24` (INMET publica de hora em hora → ao prever D+1, D+0 está disponível; sem vazamento). ERA5-LAND mantém `ERA5_LAND_CUTOFF_HOURS = 168`.
3. Fórmulas **inline no JSON do template**, vetorizadas com pandas, claras para análise (não em módulo Python).
4. Defaults: derivadas ERA5-LAND ligadas (`era5_land_tn/tg/ibutg = True`); features INMET e derivadas INMET desligadas (baseline só-ERA5-LAND); alvo `inmet_ibutg` **sempre** calculado.

**Fatos do repo que o plano usa (verificados):**
- ERA5-LAND parquet: `temperature_2m`/`dewpoint_2m` em **Kelvin** (sem conversão na escrita), `wind_u_10m`/`wind_v_10m` m/s; **não existe umidade relativa** → derivar via Magnus (August-Roche-Magnus, 17.625/243.04).
- INMET parquet: `temp_ar` (°C), `temp_orvalho` (°C), `umidade_relativa` (%), `vento_velocidade` (m/s) — unidades já corretas.
- Template base: `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` — id = stem do arquivo; auto-descoberto por `list_templates()` (`src/era5_etl/notebooks/templates.py`); célula 4 já faz a interpolação bilinear inline (pesos wx/wy a partir das colunas de canto `era5_land_lat_top/lat_bottom/lon_left/lon_right` carregadas em cada linha INMET) — **não** usar colunas `dist_*` (não existem no parquet; docs estão desatualizados).
- Seleção de features (célula 13) parseia nomes com `c.rsplit("_lag_", 1)` — genérico; só o modo `"fixed"` itera a lista de bases (`for v in ACTIVE_VARS:` → passa a ser `FEATURE_BASES`).
- Front-end lista templates via `GET /api/notebooks/templates` (nome vem da API) — **zero mudança no web-ui**.
- JSON: UTF-8 sem BOM, `indent=2`, `ensure_ascii=False` (acentos crus no markdown; células de código do repo evitam acentos).

## Global Constraints

- Rodar testes com `py -3.12 -m pytest` (sem venv; ambiente do usuário).
- **Não** editar `src/era5_etl/__version__.py`, nem renomear `era5-land`, nem tocar no web-ui.
- Código de células **sem acentos** (padrão do repo: "Configuracao", "nao", "degC"); markdown pode ter acentos.
- O script gerador fica **no scratchpad** (`C:\Users\nyck\AppData\Local\Temp\claude\C--Users-nyck-dev-era5-etl\0fb11351-4d14-4e97-ab40-bae809f382b4\scratchpad\`), não no repo (precedente: commit b9289d9/b9289d7 removeu script temporário).
- Commits pequenos e frequentes; mensagens em inglês no padrão do repo (`feat(notebooks): ...`); rodapé `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. **Não fazer push** (SSL quebrado — memória do projeto; o usuário faz o push).

## Mapa de células do novo template (23 células)

| # novo | # base | mudança |
|---|---|---|
| 0 | 0 | markdown título — **substituída** |
| 1 | 1 | GPU/hardware — igual |
| 2 | 2 | configuração — **editada** (TARGET_VAR, INMET_CUTOFF_HOURS, WORKING_HOUR_*) |
| 3 | 3 | markdown helpers — igual |
| 4 | 4 | catálogo + join builder — **editada** (toggles, derived_vars, insumos forçados) |
| 5 | 5 | plot_predictions — igual |
| 6 | 6 | MLflow setup — **editada** (repeat config: novos params) |
| 7 | 7 | load com cache — **editada** (digest com uniões efetivas) |
| 8 | — | **NOVA**: colunas derivadas Tn/Tg/IBUTG + FEATURE_GROUPS |
| 9 | 8 | validação — **editada** (required_cols via FEATURE_GROUPS) |
| 10 | 9 | feature engineering — **substituída** (grupos com cutoff por origem) |
| 11–13 | 10–12 | preview / split / janelas — iguais |
| 14 | 13 | busca Optuna — **editada** (1 linha: `for v in FEATURE_BASES:`) |
| 15 | 14 | estatísticas backtest — igual |
| 16 | 15 | refit final + métricas — **editada** (rmse_working_hours) |
| 17–21 | 16–20 | sweep / plots — iguais |
| 22 | 21 | logging MLflow — **editada** (tags/params novos) |

---

### Task 1: Persistir o spec de design no repo

**Files:**
- Create: `docs/superpowers/specs/2026-07-03-xgboost-target-ibutg-design.md`

**Interfaces:** nenhuma (documentação).

- [ ] **Step 1: Escrever o spec**

Criar o arquivo com este conteúdo (resumo do design aprovado):

```markdown
# Design: template de notebook "XGBoost - Target IBUTG"

Data: 2026-07-03. Aprovado em brainstorm (Task 0 do TODO.md).

## Objetivo
Prever o IBUTG (WBGT) horário derivado das observações INMET, com features
ERA5-LAND interpoladas bilinearmente no ponto da estação e derivadas
meteorológicas dos dois sistemas.

## Decisões
- Novo template `xgboost_target_ibutg` (nome "XGBoost - Target IBUTG"),
  cópia adaptada do `xgboost_optuna_windows` (23 células; 1 nova).
- O SQL do join usa a MACRO builtin `bilinear_weights` (pedida no TODO;
  registrada na conexão do notebook via BUILTIN_OBJECTS) no lugar da
  expressão aritmética inline do template base — mesma matemática.
- Fórmulas do pyinmet (vel1_5, Tn, Tg, IBUTG) INLINE numa célula, vetorizadas
  com pandas, sem round() (decisão do usuário: visíveis para análise).
- ERA5-LAND: Kelvin→°C; vento = |(u,v)| bilinear; UR derivada via Magnus
  (August-Roche-Magnus 17.625/243.04, clip 100%) — ERA5-LAND não tem UR.
- INMET: temp_ar/temp_orvalho/umidade_relativa/vento_velocidade já em
  °C/%/m/s.
- Alvo: `inmet_ibutg` (sempre calculado). Toggles `era5_land_vars`,
  `inmet_vars` (semântica nova: True = carregar E virar feature) e
  `derived_vars` controlam as features. Insumos do IBUTG sempre carregados.
- Features com cutoff por origem: ERA5-LAND 168h (D−6); INMET 24h (D+0) —
  novo parâmetro INMET_CUTOFF_HOURS. Sem vazamento.
- Defaults: era5_land_tn/tg/ibutg ON; features INMET e derivadas INMET OFF.
- RMSE adicional `rmse_working_hours`: só horas de teste com hour_utc no
  intervalo SEMIABERTO [WORKING_HOUR_START, WORKING_HOUR_STOP) = [7, 19)
  (12 horas), sem conversão de fuso. Optuna continua otimizando o RMSE geral.
- MLflow: tag model_name="xgboost_target_ibutg"; novos params
  (inmet_cutoff_hours, working_hour_start/stop, inmet_vars_active,
  derived_vars_active); métricas novas fluem pelo dict `metrics`.
- Derivação roda APÓS o cache parquet do load (ligar/desligar derivadas não
  invalida o cache); digest do cache usa as uniões efetivas carregadas.
- Zero mudança em código Python do pacote e no web-ui.
```

- [ ] **Step 2: Commit**

```powershell
git add docs/superpowers/specs/2026-07-03-xgboost-target-ibutg-design.md
git commit -m @'
docs(specs): design for XGBoost - Target IBUTG notebook template

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Testes (falhando primeiro)

**Files:**
- Modify: `tests/test_notebook_templates.py` (acrescentar ao final)

**Interfaces:**
- Consumes: helper `_code_sources(template_id)` já existente no topo do arquivo (linhas 8–15); `load_template`/`list_templates` de `era5_etl.notebooks.templates`.
- Produces: 3 testes que o Task 3 fará passar: `test_xgboost_target_ibutg_template`, `test_ibutg_template_derivation_between_load_and_validation`, `test_ibutg_derivation_cell_formulas`.

- [ ] **Step 1: Escrever os testes**

Acrescentar ao final de `tests/test_notebook_templates.py`:

```python
# --- "XGBoost - Target IBUTG" template -------------------------------------


def test_xgboost_target_ibutg_template():
    from era5_etl.notebooks.templates import list_templates, load_template

    ids = {t["id"]: t for t in list_templates()}
    assert "xgboost_target_ibutg" in ids
    assert ids["xgboost_target_ibutg"]["name"] == "XGBoost - Target IBUTG"

    tpl = load_template("xgboost_target_ibutg")
    assert len(tpl["cells"]) == 23

    src = _code_sources("xgboost_target_ibutg")
    for token in (
        '"inmet_ibutg"',            # alvo derivado
        "WORKING_HOUR_START",
        "WORKING_HOUR_STOP",
        "INMET_CUTOFF_HOURS",
        "rmse_working_hours",
        "derived_vars",
        "FEATURE_GROUPS",
        "0.57175",                  # coeficiente Tn (pyinmet)
        "1.374385",                 # coeficiente Tg (pyinmet)
        "0.7 * tn + 0.2 * tg",      # IBUTG (pyinmet)
        "273.15",                   # Kelvin -> Celsius
        "17.625",                   # Magnus (umidade relativa ERA5-LAND)
        "mlflow.set_experiment",
        "from era5_etl.notebooks.backtest import",
        "REPEAT_RUN_ID",
        "bilinear_weights(",     # macro builtin exigida pelo TODO (Task 0)
    ):
        assert token in src, f"template must contain {token!r}"
    assert "log_model_run" not in src  # MLflow-only, como o template base


def test_ibutg_template_derivation_between_load_and_validation():
    """A celula de derivacao roda DEPOIS do load e ANTES da validacao
    (a validacao exige o alvo derivado inmet_ibutg nao-nulo)."""
    from era5_etl.notebooks.templates import load_template

    srcs = [c["source"] for c in load_template("xgboost_target_ibutg")["cells"]
            if c["type"] == "code"]
    i_load = next(i for i, s in enumerate(srcs) if "load_inmet_with_cache(" in s)
    i_der = next(i for i, s in enumerate(srcs) if "def calc_ibutg" in s)
    i_val = next(i for i, s in enumerate(srcs) if "VALIDACAO DE DADOS FALHOU" in s)
    assert i_load < i_der < i_val


def test_ibutg_derivation_cell_formulas():
    """Executa a celula de derivacao numa DataFrame sintetica e confere os
    valores contra a cadeia de formulas do pyinmet (sem arredondamento)."""
    import pandas as pd

    from era5_etl.notebooks.templates import load_template

    src = next(
        c["source"] for c in load_template("xgboost_target_ibutg")["cells"]
        if c["type"] == "code" and "def calc_ibutg" in c["source"]
    )
    df = pd.DataFrame({
        "era5_land_temperature_2m_bilinear": [303.15],  # 30 degC em Kelvin
        "era5_land_dewpoint_2m_bilinear": [293.15],     # 20 degC em Kelvin
        "era5_land_wind_u_10m_bilinear": [3.0],
        "era5_land_wind_v_10m_bilinear": [0.0],
        "temp_ar": [30.0],
        "temp_orvalho": [20.0],
        "umidade_relativa": [55.0],
        "vento_velocidade": [3.0],
    })
    ns = {
        "df": df,
        "era5_land_vars": {"temperature_2m": True},
        "inmet_vars": {"temp_ar": False},
        "derived_vars": {"era5_land_ibutg": True, "inmet_tn": False},
        "ERA5_LAND_CUTOFF_HOURS": 168,
        "INMET_CUTOFF_HOURS": 24,
    }
    exec(src, ns)  # fonte controlada: e o nosso proprio template
    out = ns["df"]

    # Referencia: formulas pyinmet sem round().
    vel15 = 3.0 * (1.5 / 10.0) ** 0.21
    tn = 0.57175 * 20 + 0.19447 * 30 - 0.26523 * vel15 - 0.05134 * 55 + 10.44966
    tg = 1.374385 * 30 + 0.083627 * 55 - 1.021632 * vel15
    ibutg = 0.7 * tn + 0.2 * tg + 0.1 * 30

    assert abs(out["inmet_tn"].iloc[0] - tn) < 1e-9
    assert abs(out["inmet_tg"].iloc[0] - tg) < 1e-9
    assert abs(out["inmet_ibutg"].iloc[0] - ibutg) < 1e-9
    # ERA5-LAND: mesma entrada fisica; UR via Magnus ~55.08% -> IBUTG proximo.
    assert abs(out["era5_land_ibutg"].iloc[0] - ibutg) < 0.05

    # FEATURE_GROUPS montado com origem e cutoff certos.
    groups = {base: (srccol, cut) for srccol, base, cut in ns["FEATURE_GROUPS"]}
    assert groups["temperature_2m"] == ("era5_land_temperature_2m_bilinear", 168)
    assert groups["era5_land_ibutg"] == ("era5_land_ibutg", 168)
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -k ibutg -v`
Expected: 3 FAILED — `assert "xgboost_target_ibutg" in ids` (template ainda não existe) e `StopIteration`/`AssertionError` nos outros dois.

- [ ] **Step 3: Commit (testes vermelhos, junto com o Task 3)**

Não commitar ainda — o commit é conjunto com o template no Task 3 (o repo não deve ficar com a suíte quebrada em um commit isolado).

---

### Task 3: Gerar o template JSON

**Files:**
- Create: `src/era5_etl/_data/notebook_templates/xgboost_target_ibutg.json` (gerado)
- Create (scratchpad, fora do repo): `<scratchpad>\build_ibutg_template.py`

**Interfaces:**
- Consumes: `src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json` (base, 22 células — NÃO editar o base).
- Produces: template id `xgboost_target_ibutg`, name `XGBoost - Target IBUTG`, 23 células. Variáveis de namespace que células posteriores usam: `derived_vars`, `_ERA5_LAND_WBGT_INPUTS`, `_INMET_WBGT_INPUTS` (célula 4), `FEATURE_GROUPS`/`FEATURE_BASES` (célula 8), `rmse_working_hours` (célula 16).

- [ ] **Step 1: Escrever o script gerador no scratchpad**

`<scratchpad>\build_ibutg_template.py` — conteúdo completo:

```python
"""Gera xgboost_target_ibutg.json a partir de xgboost_optuna_windows.json.

Edicoes ancoradas com assert: se o template base mudou e uma ancora nao for
encontrada (ou for ambigua), o script FALHA em vez de gerar um template
silenciosamente errado.
"""
import json
from pathlib import Path

REPO = Path(r"C:\Users\nyck\dev\era5-etl")
BASE = REPO / "src/era5_etl/_data/notebook_templates/xgboost_optuna_windows.json"
OUT = REPO / "src/era5_etl/_data/notebook_templates/xgboost_target_ibutg.json"


def replace_once(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"ancora ambigua/ausente: {old[:70]!r}"
    return src.replace(old, new, 1)


def replace_line(src: str, anchor: str, new_line: str) -> str:
    lines = src.split("\n")
    hits = [i for i, l in enumerate(lines) if anchor in l]
    assert len(hits) == 1, f"ancora de linha ambigua/ausente: {anchor!r} -> {hits}"
    lines[hits[0]] = new_line
    return "\n".join(lines)


def insert_after_line(src: str, anchor: str, block: str) -> str:
    lines = src.split("\n")
    hits = [i for i, l in enumerate(lines) if anchor in l]
    assert len(hits) == 1, f"ancora de linha ambigua/ausente: {anchor!r} -> {hits}"
    return "\n".join(lines[: hits[0] + 1] + block.split("\n") + lines[hits[0] + 1 :])


def insert_before_line(src: str, anchor: str, block: str) -> str:
    lines = src.split("\n")
    hits = [i for i, l in enumerate(lines) if anchor in l]
    assert len(hits) == 1, f"ancora de linha ambigua/ausente: {anchor!r} -> {hits}"
    return "\n".join(lines[: hits[0]] + block.split("\n") + lines[hits[0] :])


tpl = json.loads(BASE.read_text(encoding="utf-8"))
assert len(tpl["cells"]) == 22, len(tpl["cells"])

tpl["name"] = "XGBoost - Target IBUTG"
tpl["description"] = (
    "Tudo do 'XGBoost With Optuna and Windows', com alvo IBUTG (WBGT) do "
    "INMET: une INMET + ERA5-LAND por interpolacao bilinear no ponto da "
    "estacao, calcula Tn, Tg e IBUTG para os dois sistemas (formulas do "
    "pyinmet, visiveis no notebook), toggles de features com cutoff por "
    "origem (ERA5-LAND 168h, INMET 24h) e RMSE adicional restrito ao "
    "horario de trabalho (hour_utc em [7, 19))."
)

C = tpl["cells"]

# ------------------------------------------------------------------ cell 0
C[0]["source"] = """# XGBoost + Optuna — Target IBUTG (WBGT)

Este template estende o **"XGBoost With Optuna and Windows"** trocando o alvo
para o **IBUTG** (Índice de Bulbo Úmido Termômetro de Globo / WBGT) calculado
a partir das observações INMET:

1. Carrega observações INMET unidas às 4 células ERA5-LAND vizinhas e
   **interpola cada variável ERA5-LAND para o ponto exato da estação**
   (bilinear, pesos wx/wy).
2. **Calcula colunas derivadas para os dois sistemas** (fórmulas do pyinmet,
   visíveis na célula "Colunas derivadas"): `era5_land_tn/tg/ibutg` e
   `inmet_tn/tg/ibutg`. Para o ERA5-LAND converte Kelvin→°C, obtém o vento de
   (u, v) e deriva a umidade relativa via Magnus (o ERA5-LAND não tem UR).
3. O **alvo é `inmet_ibutg`**. Os dicionários `era5_land_vars`, `inmet_vars` e
   `derived_vars` (célula de catálogo) controlam quais colunas viram features.
4. **Features com cutoff por origem**: ERA5-LAND defasado ≥168 h (D−6) e
   INMET defasado ≥24 h (D+0) — sem vazamento em nenhum grupo.
5. Backtesting (Expanding/Sliding) gerido pelo Optuna, refit do vencedor e
   avaliação no holdout — tudo como no template base, registrado no MLflow.
6. **RMSE adicional do horário de trabalho**: além do RMSE do teste inteiro,
   reporta `rmse_working_hours` usando só as horas `hour_utc` no intervalo
   semiaberto `[WORKING_HOUR_START, WORKING_HOUR_STOP)` (7→19, 12 horas).

> Edite `STATION_ID`, `DATE_START`, `DATE_END`, os toggles de variáveis e os
> parâmetros em MAIÚSCULAS na célula de configuração, e rode tudo.
"""

# ------------------------------------------------------------------ cell 2 (config)
s = C[2]["source"]
s = replace_line(
    s, '= "temp_ar"',
    'TARGET_VAR    = "inmet_ibutg"    # IBUTG (WBGT) derivado do INMET -- '
    'celula "Colunas derivadas"',
)
s = insert_after_line(
    s, "ERA5_LAND_CUTOFF_HOURS = 168",
    "\n"
    "# Cutoff (horas) das features de ORIGEM INMET (colunas observadas e\n"
    "# derivadas inmet_*). O INMET publica de hora em hora: ao prever D+1, os\n"
    "# dados ate D+0 ja existem -> defasagem minima de 24h, sem vazamento.\n"
    "INMET_CUTOFF_HOURS = 24",
)
s = insert_before_line(
    s, "# --- Repetir experimento (MLflow)",
    "# --- RMSE em horario de trabalho -------------------------------------\n"
    "# Alem do RMSE do teste inteiro, o notebook reporta rmse_working_hours,\n"
    "# calculado APENAS nas horas de trabalho: hour_utc no intervalo SEMIABERTO\n"
    "# [WORKING_HOUR_START, WORKING_HOUR_STOP) -> 7..18 = 12 horas por dia.\n"
    "# Filtro direto em hour_utc (sem conversao de fuso horario).\n"
    "WORKING_HOUR_START = 7\n"
    "WORKING_HOUR_STOP = 19\n",
)
C[2]["source"] = s

# ------------------------------------------------------------------ cell 4 (catalogo/join)
s = C[4]["source"]
s = replace_once(
    s,
    "# maior (e mais lenta) a busca. Colunas precisam existir na era5-land baixada.",
    "# maior (e mais lenta) a busca. Colunas precisam existir na era5-land baixada.\n"
    "# Os 4 insumos do IBUTG (_ERA5_LAND_WBGT_INPUTS, abaixo) sao SEMPRE\n"
    "# interpolados, mesmo com toggle False (False = so nao vira feature).",
)
s = replace_once(
    s,
    "# Variaveis do INMET lidas da VIEW inmet. True = incluir a coluna no DataFrame\n"
    "# unido (INMET + ERA5-LAND); False = nao ler. Por padrao so 'temp_ar' (o alvo)\n"
    "# e True. As colunas 'date'/'hour_utc' NAO entram aqui: sao sempre lidas para\n"
    "# fazer o JOIN com a era5-land (ver _INMET_KEY_COLS). Assim o DataFrame nao\n"
    "# carrega variaveis extras do INMET que o algoritmo nao usa.",
    "# Variaveis do INMET lidas da VIEW inmet. True = incluir a coluna E usa-la\n"
    "# como feature de treino defasada por INMET_CUTOFF_HOURS. Default: tudo\n"
    "# False (baseline so-ERA5-LAND). Os 4 insumos do IBUTG (_INMET_WBGT_INPUTS,\n"
    "# abaixo) sao SEMPRE carregados para derivar o alvo, mesmo com toggle\n"
    "# False -- o toggle so decide se a coluna tambem vira feature.",
)
s = replace_line(s, '"temp_ar": True,', '    "temp_ar": False,')
s = insert_before_line(
    s, "# Colunas estruturais do INMET sempre lidas",
    '# Colunas DERIVADAS (calculadas na celula "Colunas derivadas", apos o\n'
    "# load). True = vira feature de treino com lag, usando o cutoff do sistema\n"
    "# de origem (era5_land_* -> ERA5_LAND_CUTOFF_HOURS; inmet_* ->\n"
    "# INMET_CUTOFF_HOURS). O ALVO inmet_ibutg e SEMPRE calculado,\n"
    '# independente do toggle: ligar "inmet_ibutg" aqui significa usa-lo\n'
    "# TAMBEM como feature autorregressiva defasada.\n"
    "derived_vars = {\n"
    '    "era5_land_tn": True,\n'
    '    "era5_land_tg": True,\n'
    '    "era5_land_ibutg": True,\n'
    '    "inmet_tn": False,\n'
    '    "inmet_tg": False,\n'
    '    "inmet_ibutg": False,\n'
    "}\n"
    "\n"
    "# Insumos do calculo do IBUTG -- sempre carregados, independente dos toggles:\n"
    '_ERA5_LAND_WBGT_INPUTS = ["temperature_2m", "dewpoint_2m",\n'
    '                          "wind_u_10m", "wind_v_10m"]\n'
    '_INMET_WBGT_INPUTS = ["temp_ar", "temp_orvalho",\n'
    '                      "umidade_relativa", "vento_velocidade"]\n',
)
s = replace_once(
    s,
    "    active = [v for v, enabled in vars_dict.items() if enabled]\n"
    "    if not active:\n"
    '        raise ValueError("Nenhuma variavel selecionada em vars_dict.")',
    "    # uniao: toggles ligados + insumos do IBUTG (sempre interpolados)\n"
    "    active = sorted({v for v, enabled in vars_dict.items() if enabled}\n"
    "                    | set(_ERA5_LAND_WBGT_INPUTS))",
)
s = replace_once(
    s,
    "    active_inmet = [v for v, on in inmet_vars_dict.items() if on]",
    "    active_inmet = sorted({v for v, on in inmet_vars_dict.items() if on}\n"
    "                          | set(_INMET_WBGT_INPUTS))",
)
# TODO.md pede explicitamente a MACRO bilinear_weights (builtin registrada na
# conexao `con` do notebook via era5_etl.notebooks.connect -> BUILTIN_OBJECTS).
# Troca a expressao aritmetica inline do template base pela chamada da macro
# (mesma matematica; ver web/builtin_objects.py).
s = replace_once(
    s,
    '        bilinear_selects.append(f"""\\\n'
    "        era5_land_{var}_tl * (1.0 - wx) * (1.0 - wy)\n"
    "        + era5_land_{var}_tr * wx * (1.0 - wy)\n"
    "        + era5_land_{var}_bl * (1.0 - wx) * wy\n"
    '        + era5_land_{var}_br * wx * wy AS era5_land_{var}_bilinear""")',
    '        bilinear_selects.append(f"""\\\n'
    "        bilinear_weights(\n"
    "            wx, wy,\n"
    "            era5_land_{var}_tl, era5_land_{var}_tr,\n"
    "            era5_land_{var}_bl, era5_land_{var}_br\n"
    '        ) AS era5_land_{var}_bilinear""")',
)
C[4]["source"] = s

# ------------------------------------------------------------------ cell 6 (mlflow setup / repeat)
s = C[6]["source"]
s = replace_once(
    s,
    '        "ERA5_LAND_CUTOFF_HOURS": int(p["era5_land_cutoff_hours"]),',
    '        "ERA5_LAND_CUTOFF_HOURS": int(p["era5_land_cutoff_hours"]),\n'
    '        "INMET_CUTOFF_HOURS": int(p.get("inmet_cutoff_hours", 24)),\n'
    '        "WORKING_HOUR_START": int(p.get("working_hour_start", 7)),\n'
    '        "WORKING_HOUR_STOP": int(p.get("working_hour_stop", 19)),',
)
s = replace_once(
    s,
    '    ERA5_LAND_CUTOFF_HOURS = REPEAT_CONFIG["ERA5_LAND_CUTOFF_HOURS"]',
    '    ERA5_LAND_CUTOFF_HOURS = REPEAT_CONFIG["ERA5_LAND_CUTOFF_HOURS"]\n'
    '    INMET_CUTOFF_HOURS = REPEAT_CONFIG["INMET_CUTOFF_HOURS"]\n'
    '    WORKING_HOUR_START = REPEAT_CONFIG["WORKING_HOUR_START"]\n'
    '    WORKING_HOUR_STOP = REPEAT_CONFIG["WORKING_HOUR_STOP"]',
)
C[6]["source"] = s

# ------------------------------------------------------------------ cell 7 (load/cache digest)
C[7]["source"] = replace_once(
    C[7]["source"],
    '    active = ",".join(sorted(v for v, on in vars_dict.items() if on))\n'
    '    active_inmet = ",".join(sorted(v for v, on in inmet_vars_dict.items() if on))',
    "    # inclui os insumos do IBUTG sempre carregados (uniao efetiva do load)\n"
    '    active = ",".join(sorted({v for v, on in vars_dict.items() if on}\n'
    "                             | set(_ERA5_LAND_WBGT_INPUTS)))\n"
    '    active_inmet = ",".join(sorted({v for v, on in inmet_vars_dict.items() if on}\n'
    "                                   | set(_INMET_WBGT_INPUTS)))",
)

# ------------------------------------------------------------------ NOVA cell 8 (derivacao)
DERIVED_SRC = '''# --- Colunas derivadas: Tn, Tg e IBUTG (ERA5-LAND e INMET) -----------
# Formulas do pyinmet (MeteorologicalFunctions), vetorizadas com pandas.
# Sem round(): precisao cheia para treino; NaN propaga naturalmente
# (equivalente ao None-propagation do pyinmet).
import numpy as np


def vel10_to_vel1_5(vel10):
    """Vento de 10 m para 1.5 m (lei de potencia, expoente 0.21)."""
    return vel10 * (1.5 / 10.0) ** 0.21


def relative_humidity_pct(t2m_c, d2m_c):
    """Umidade relativa (%) via Magnus (August-Roche-Magnus, 17.625/243.04).

    Necessaria so para o ERA5-LAND (nao tem UR); o INMET ja mede
    umidade_relativa. Limitada a 100% (a interpolacao pode gerar d2m > t2m).
    """
    es = np.exp((17.625 * t2m_c) / (243.04 + t2m_c))
    e = np.exp((17.625 * d2m_c) / (243.04 + d2m_c))
    return (100.0 * e / es).clip(upper=100.0)


def calc_tn(d2m_c, t2m_c, vel1_5, rh_pct):
    """Temperatura de bulbo umido natural Tn (degC)."""
    return (0.57175 * d2m_c + 0.19447 * t2m_c - 0.26523 * vel1_5
            - 0.05134 * rh_pct + 10.44966)


def calc_tg(t2m_c, rh_pct, vel1_5):
    """Temperatura de globo Tg (degC)."""
    return 1.374385 * t2m_c + 0.083627 * rh_pct - 1.021632 * vel1_5


def calc_ibutg(t2m_c, tn, tg):
    """IBUTG / WBGT (degC): 0.7*Tn + 0.2*Tg + 0.1*T."""
    return 0.7 * tn + 0.2 * tg + 0.1 * t2m_c


# ---------- ERA5-LAND interpolado no ponto da estacao ----------------
# O parquet guarda temperaturas em KELVIN -> converte para degC aqui.
# Vento: modulo do vetor (u, v) interpolado componente a componente.
_el_t2m = df["era5_land_temperature_2m_bilinear"] - 273.15
_el_d2m = df["era5_land_dewpoint_2m_bilinear"] - 273.15
_el_vel10 = np.sqrt(df["era5_land_wind_u_10m_bilinear"] ** 2
                    + df["era5_land_wind_v_10m_bilinear"] ** 2)
_el_rh = relative_humidity_pct(_el_t2m, _el_d2m)
_el_v15 = vel10_to_vel1_5(_el_vel10)
df["era5_land_tn"] = calc_tn(_el_d2m, _el_t2m, _el_v15, _el_rh)
df["era5_land_tg"] = calc_tg(_el_t2m, _el_rh, _el_v15)
df["era5_land_ibutg"] = calc_ibutg(_el_t2m, df["era5_land_tn"],
                                   df["era5_land_tg"])

# ---------- INMET observado (ja em degC / % / m/s) -------------------
_in_v15 = vel10_to_vel1_5(df["vento_velocidade"])
df["inmet_tn"] = calc_tn(df["temp_orvalho"], df["temp_ar"], _in_v15,
                         df["umidade_relativa"])
df["inmet_tg"] = calc_tg(df["temp_ar"], df["umidade_relativa"], _in_v15)
df["inmet_ibutg"] = calc_ibutg(df["temp_ar"], df["inmet_tn"], df["inmet_tg"])

# ---------- Grupos de features: (coluna_no_df, base, cutoff_horas) ----
# Toggle True nos dicionarios da celula de catalogo = vira feature de lag.
# Cada origem tem seu proprio cutoff: ERA5-LAND (D-6) vs INMET (D+0).
FEATURE_GROUPS = []
for _var, _on in era5_land_vars.items():
    if _on:
        FEATURE_GROUPS.append((f"era5_land_{_var}_bilinear", _var,
                               ERA5_LAND_CUTOFF_HOURS))
for _name, _on in derived_vars.items():
    if _on:
        _cut = (ERA5_LAND_CUTOFF_HOURS if _name.startswith("era5_land_")
                else INMET_CUTOFF_HOURS)
        FEATURE_GROUPS.append((_name, _name, _cut))
for _var, _on in inmet_vars.items():
    if _on:
        FEATURE_GROUPS.append((_var, f"inmet_{_var}", INMET_CUTOFF_HOURS))
FEATURE_BASES = [b for _, b, _ in FEATURE_GROUPS]

_derived_cols = ["era5_land_tn", "era5_land_tg", "era5_land_ibutg",
                 "inmet_tn", "inmet_tg", "inmet_ibutg"]
print(f"Derivadas calculadas: {', '.join(_derived_cols)}")
print(f"{len(FEATURE_GROUPS)} grupos de features "
      f"(cutoff ERA5-LAND={ERA5_LAND_CUTOFF_HOURS}h, "
      f"INMET={INMET_CUTOFF_HOURS}h)")
df[_derived_cols].describe().rename_axis("stat").reset_index()
'''
C.insert(8, {"type": "code", "source": DERIVED_SRC})

# ------------------------------------------------------------------ cell 9 (validacao; base 8)
s = C[9]["source"]
s = replace_once(
    s,
    "ACTIVE_VARS = [v for v, enabled in era5_land_vars.items() if enabled]\n"
    "\n"
    "era5_required_cols = []\n"
    "for var in ACTIVE_VARS:\n"
    '    era5_required_cols += [f"era5_land_{var}_bilinear"]\n'
    "\n"
    "required_cols = [TARGET_VAR] + era5_required_cols",
    "ACTIVE_VARS = [v for v, enabled in era5_land_vars.items() if enabled]\n"
    "\n"
    "# Colunas exigidas: alvo derivado + coluna de ORIGEM de cada grupo de\n"
    "# features (bilinears ERA5-LAND ativas, derivadas ligadas, colunas INMET\n"
    '# ligadas). FEATURE_GROUPS vem da celula "Colunas derivadas".\n'
    "required_cols = [TARGET_VAR] + sorted({src for src, _, _ in FEATURE_GROUPS})",
)
s = replace_once(
    s,
    'print(f"Validation passed ({len(ACTIVE_VARS)} active var(s): '
    "{', '.join(ACTIVE_VARS)})\")",
    'print(f"Validation passed ({len(FEATURE_BASES)} feature base(s): '
    "{', '.join(FEATURE_BASES)})\")",
)
C[9]["source"] = s

# ------------------------------------------------------------------ cell 10 (feature eng; base 9)
C[10]["source"] = '''# --- Feature engineering: cutoff-offset lags + cyclical calendar ----
import numpy as np
import pandas as pd


def build_design_matrix(frame, feature_groups, lag_hours=LAG_HOURS):
    """Return (design_df, lag_feature_cols, cyclical_cols).

    Cada grupo ``(src_col, base, cutoff)`` gera features ``{base}_lag_{L}h`` =
    ``src_col`` deslocada de ``cutoff + L`` horas. Grupos de ORIGEM ERA5-LAND
    usam ERA5_LAND_CUTOFF_HOURS (o alvo em D+1 so enxerga ERA5-LAND ate D-6);
    grupos de ORIGEM INMET usam INMET_CUTOFF_HOURS (D+1 so enxerga INMET ate
    D+0). Sem vazamento em nenhum grupo. O frame e reindexado para a grade
    horaria completa antes, entao um shift posicional equivale a um shift em
    horas mesmo com buracos. As features ciclicas de calendario vem do
    timestamp do ALVO (conhecido na hora da previsao, sem vazamento).
    """
    d = frame.copy()
    d["ts"] = pd.to_datetime(d["date"]) + pd.to_timedelta(d["hour_utc"].astype(int), unit="h")
    d = d.dropna(subset=["ts"]).drop_duplicates("ts").sort_values("ts").set_index("ts")
    full = pd.date_range(d.index.min(), d.index.max(), freq="h")
    d = d.reindex(full)

    hour = d.index.hour.to_numpy()
    doy = d.index.dayofyear.to_numpy()
    # Monta TODAS as colunas novas (ciclicas + lags) num dict e concatena de
    # uma vez. Inserir 150+ colunas uma a uma (d[col] = ...) fragmenta o
    # DataFrame e dispara o PerformanceWarning "DataFrame is highly
    # fragmented" do pandas; pd.concat(axis=1) evita isso e e mais rapido.
    new_cols = {
        "hora_sin": np.sin(2 * np.pi * hour / 24.0),
        "hora_cos": np.cos(2 * np.pi * hour / 24.0),
        "dia_ano_sin": np.sin(2 * np.pi * doy / 365.25),
        "dia_ano_cos": np.cos(2 * np.pi * doy / 365.25),
    }
    cyc_cols = ["hora_sin", "hora_cos", "dia_ano_sin", "dia_ano_cos"]

    lag_cols = []
    for src_col, base, cutoff in feature_groups:
        if src_col not in d.columns:
            continue
        for lag in lag_hours:
            col = f"{base}_lag_{lag}h"          # e.g. temperature_2m_lag_1h
            new_cols[col] = d[src_col].shift(cutoff + lag)
            lag_cols.append(col)
    d = pd.concat([d, pd.DataFrame(new_cols, index=d.index)], axis=1)
    return d, lag_cols, cyc_cols


design, LAG_FEATURE_COLS, CYCLICAL_COLS = build_design_matrix(df, FEATURE_GROUPS)
CANDIDATE_COLS = LAG_FEATURE_COLS + CYCLICAL_COLS
clean = design.dropna(subset=[TARGET_VAR] + CANDIDATE_COLS).copy()

print(f"{len(clean):,} usable rows after engineering: "
      f"{len(LAG_FEATURE_COLS)} lag features over {len(FEATURE_GROUPS)} grupo(s) "
      f"+ {len(CYCLICAL_COLS)} cyclical.")
print("Sample lag features:",
      [c for c in LAG_FEATURE_COLS if c.startswith('temperature_2m')][:4])
assert len(clean) > 50, "Not enough rows - widen DATE_START..DATE_END."
clean[["hora_sin", "hora_cos", "dia_ano_sin", "dia_ano_cos", TARGET_VAR]].describe().rename_axis("stat").reset_index()
'''

# ------------------------------------------------------------------ cell 14 (optuna; base 13)
C[14]["source"] = replace_once(
    C[14]["source"], "for v in ACTIVE_VARS:", "for v in FEATURE_BASES:"
)

# ------------------------------------------------------------------ cell 16 (refit final; base 15)
s = C[16]["source"]
s = insert_after_line(
    s, "r2 = float(r2_score(y_true, y_pred))",
    "\n"
    "# --- RMSE independente: somente horas de trabalho ---------------------\n"
    "# Intervalo SEMIABERTO [WORKING_HOUR_START, WORKING_HOUR_STOP) sobre a\n"
    "# hora UTC do indice do teste: 7..18 -> 12 horas por dia.\n"
    "_wh_hours = test.index.hour.to_numpy()\n"
    "_wh_mask = (_wh_hours >= WORKING_HOUR_START) & (_wh_hours < WORKING_HOUR_STOP)\n"
    "if _wh_mask.any():\n"
    "    rmse_working_hours = _rmse(y_true[_wh_mask], y_pred[_wh_mask])\n"
    "else:\n"
    "    rmse_working_hours = float(\"nan\")\n"
    "    print(\"AVISO: nenhuma linha do teste dentro do horario de trabalho \"\n"
    "          f\"[{WORKING_HOUR_START}, {WORKING_HOUR_STOP})h UTC.\")",
)
s = replace_once(
    s,
    '    "rmse": rmse, "mae": mae, "r2": r2,',
    '    "rmse": rmse, "mae": mae, "r2": r2,\n'
    '    "rmse_working_hours": rmse_working_hours,\n'
    '    "n_test_working_hours": int(_wh_mask.sum()),',
)
s = insert_after_line(
    s, "print(metrics)",
    "print(f\"RMSE horario de trabalho [{WORKING_HOUR_START},\"\n"
    "      f\"{WORKING_HOUR_STOP})h UTC: {rmse_working_hours:.4f} \"\n"
    "      f\"({int(_wh_mask.sum())} horas de teste)\")",
)
C[16]["source"] = s

# ------------------------------------------------------------------ cell 22 (mlflow log; base 21)
s = C[22]["source"]
s = replace_once(s, '"model_name": "xgboost_optuna_windows",',
                 '"model_name": "xgboost_target_ibutg",')
s = replace_once(
    s,
    'mlflow.set_tag("model_name", f"xgboost_optuna_windows_{_method}")',
    'mlflow.set_tag("model_name", f"xgboost_target_ibutg_{_method}")',
)
s = replace_once(
    s,
    '"notes": f"backtest expanding+sliding; station={STATION_ID}; D+1 from <=D-6",',
    '"notes": f"target IBUTG (INMET); backtest expanding+sliding; station={STATION_ID}",',
)
s = replace_once(
    s,
    '        "era5_land_cutoff_hours": ERA5_LAND_CUTOFF_HOURS,',
    '        "era5_land_cutoff_hours": ERA5_LAND_CUTOFF_HOURS,\n'
    '        "inmet_cutoff_hours": INMET_CUTOFF_HOURS,\n'
    '        "working_hour_start": WORKING_HOUR_START,\n'
    '        "working_hour_stop": WORKING_HOUR_STOP,',
)
s = replace_once(
    s,
    '        "era5_land_vars_active": ACTIVE_VARS,',
    '        "era5_land_vars_active": ACTIVE_VARS,\n'
    '        "inmet_vars_active": [v for v, on in inmet_vars.items() if on],\n'
    '        "derived_vars_active": [n for n, on in derived_vars.items() if on],',
)
C[22]["source"] = s

assert len(C) == 23, len(C)
with OUT.open("w", encoding="utf-8") as f:
    json.dump(tpl, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"OK: {OUT} ({len(C)} cells)")
```

**Nota sobre âncoras:** todas as âncoras acima vieram do conteúdo verbatim do template base inspecionado em 2026-07-03. O helper faz `assert` — se alguma âncora falhar (base mudou), inspecionar a célula com `python -c "import json;print(json.load(open(r'...base.json'))['cells'][N]['source'])"` e ajustar a âncora, **não** relaxar o assert. Exceção conhecida: a âncora do config `= "temp_ar"` e as âncoras da célula 2 vieram de um relatório de exploração (HTML-escapado); se `replace_line`/`insert_*` falhar nessa célula, conferir espaçamento real e corrigir a âncora.

- [ ] **Step 2: Rodar o script**

Run: `py -3.12 <scratchpad>\build_ibutg_template.py`
Expected: `OK: ...xgboost_target_ibutg.json (23 cells)` — sem AssertionError.

- [ ] **Step 3: Rodar os testes do Task 2**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -k ibutg -v`
Expected: 3 PASSED.

Se `test_ibutg_derivation_cell_formulas` falhar no `exec`, depurar rodando o source da célula 8 manualmente (o teste dá o traceback da linha exata da célula).

- [ ] **Step 4: Suíte inteira do arquivo**

Run: `py -3.12 -m pytest tests/test_notebook_templates.py -v`
Expected: todos PASSED (os testes antigos não referenciam o novo id; nenhum deles conta templates globalmente, mas se algum falhar por listar templates, ajustar o teste antigo — não o template).

- [ ] **Step 5: Commit**

```powershell
git add src/era5_etl/_data/notebook_templates/xgboost_target_ibutg.json tests/test_notebook_templates.py
git commit -m @'
feat(notebooks): add "XGBoost - Target IBUTG" template (WBGT target)

New template derived from xgboost_optuna_windows: joins INMET with
bilinear-interpolated ERA5-LAND at the station point, computes Tn/Tg/IBUTG
for both systems inline (pyinmet formulas, vectorized pandas; Magnus RH for
ERA5-LAND), targets inmet_ibutg, adds per-source feature cutoffs
(ERA5-LAND 168h, INMET 24h via INMET_CUTOFF_HOURS), derived_vars feature
toggles, and an independent working-hours RMSE over hour_utc in
[WORKING_HOUR_START, WORKING_HOUR_STOP) = [7, 19).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: Verificação de regressão + carga do template

**Files:** nenhum novo.

- [ ] **Step 1: Suíte completa**

Run: `py -3.12 -m pytest`
Expected: tudo verde (≈178 + 3 novos). Se algo não relacionado falhar, investigar antes de concluir (pode ser pré-existente — comparar com `git stash` se necessário).

- [ ] **Step 2: Smoke de carga do template via API pública**

Run:
```powershell
py -3.12 -c "from era5_etl.notebooks.templates import load_template, list_templates; t = load_template('xgboost_target_ibutg'); print(t['name'], len(t['cells'])); print([x['id'] for x in list_templates()])"
```
Expected: `XGBoost - Target IBUTG 23` e o id `xgboost_target_ibutg` na lista.

- [ ] **Step 3: Commit final de docs (se houve ajuste)**

Somente se algum arquivo de doc/plan foi ajustado durante a execução.

---

## Verificação end-to-end (com dados reais)

O teste de execução real é manual (usa dados baixados + GPU do usuário):

1. Subir o servidor web do projeto (`era5 ui`).
2. Página **Notebooks** → criar notebook a partir de **"XGBoost - Target IBUTG"** (o template aparece automaticamente — nome vem da API).
3. Para um smoke rápido, editar na célula de configuração: `N_TRIALS = 3`, `MAX_WINDOWS = 2`, `RUN_WINDOW_SWEEP = False` (estação `A726`, período default 2025-01-01..2025-06-30 — o usuário tem esses dados).
4. Run all. Conferir:
   - célula "Colunas derivadas" imprime as 6 derivadas + nº de grupos e mostra o `describe()` com valores plausíveis (IBUTG tipicamente 10–35 °C; `era5_land_ibutg` ≈ `inmet_ibutg` na mesma hora);
   - validação passa com alvo `inmet_ibutg`;
   - métricas finais incluem `rmse_working_hours` e `n_test_working_hours` (≈ metade do RMSE-geral em contagem: 12/24 das horas de teste);
   - run pai no painel **Model runs** com tag `model_name=xgboost_target_ibutg` e os novos params (`inmet_cutoff_hours`, `working_hour_start/stop`).
5. Teste de toggles: ligar `inmet_vars["temp_ar"] = True` e `derived_vars["inmet_ibutg"] = True`, rodar de novo → features `inmet_temp_ar_lag_*h` e `inmet_ibutg_lag_*h` aparecem nos candidatos (print da célula de features) e o cache de dados **não** é invalidado ao mudar só `derived_vars` (o load imprime "from cache").

## Fora de escopo (itens 1–3 do TODO.md)

Interpolação de NULLs do INMET (linear/polinomial/XGBoost), interpolação das outras 3 variáveis (d2m, u10, v10) e a VIEW com coluna IBUTG no banco são tarefas futuras separadas — este plano cobre apenas a Task 0. A célula de derivação deste template foi escrita para ser o ponto de partida das fórmulas nessas tarefas.

## Execução

Duas opções (escolher ao iniciar a execução):
1. **Subagent-Driven** (recomendado): superpowers:subagent-driven-development — um subagente novo por task, revisão entre tasks.
2. **Inline**: superpowers:executing-plans — execução em lote com checkpoints.

Passo extra da execução (fora do repo): copiar este plano para `docs/superpowers/plans/2026-07-03-xgboost-target-ibutg.md` no commit do Task 1, mantendo a convenção superpowers do repo.
