# Melhorias 01–05 do template "XGBoost - Target IBUTG" — Plano (registro de execução)

> Executado inline na mesma sessão (superpowers:executing-plans). Este
> documento registra as tasks; o conteúdo integral das edições está no
> template gerado `src/era5_etl/_data/notebook_templates/xgboost_target_ibutg.json`
> e o design em `../specs/2026-07-03-ibutg-template-melhorias-design.md`.

**Goal:** aplicar as 5 melhorias aprovadas (TEST_FRACTION, defaults do
catálogo, tabela de colunas no preview, gráficos/métricas working-hours,
monitor de convergência do Optuna com curva ao vivo no MLflow).

## Tasks

### Task 1: testes primeiro (falhando)
- [x] `test_xgboost_target_ibutg_template`: `len(cells) == 26` + tokens novos
  (`mae_working_hours`, `r2_working_hours`, `fig_metrics_cmp`,
  `PERM_WH_REPEATS`, `TEST_FRACTION = 0.005`, `"wind_speed_10m": True`,
  `"wind_u_10m": False`, `MONITOR_EVERY`, `OPTUNA_STAGNATION_PATIENCE`,
  `MONITOR_MLFLOW_LIVE`).
- [x] Rodar `py -3.12 -m pytest tests/test_notebook_templates.py -k ibutg`
  → 1 FAILED (contagem/tokens), 2 PASSED.

### Task 2: estender o gerador e regenerar
- [x] Seção "MELHORIAS 01-05" no script scratchpad `build_ibutg_template.py`
  (edições ancoradas com assert; célula de config, catálogo, preview,
  callback do Optuna substituído pelo monitor + run MLflow "monitor",
  métricas WH no refit, 3 células novas de gráficos, log das figuras no
  MLflow). Índices pós-inserção: pred_wh=21, fig2_wh=23, metrics_cmp=24,
  mlflow=25; total 26.
- [x] Regenerar: `OK ... (26 cells)` sem falha de âncora.
- [x] `py -3.12 -m pytest tests/test_notebook_templates.py` → 19 passed.
- [x] Syntax-check (`ast.parse`) de todas as 24 células de código → OK.

### Task 3: docs + regressão + integração
- [x] Spec + este plano em docs/superpowers, commit.
- [ ] `py -3.12 -m pytest` completo.
- [ ] finishing-a-development-branch (merge conforme escolha do usuário).

## Verificação end-to-end (manual, com dados reais)
1. `era5 ui` → notebook novo do template → Run all (smoke: `N_TRIALS=3`,
   `MAX_WINDOWS=2`, `RUN_WINDOW_SWEEP=False`).
2. Conferir: split ~24h de teste (print da célula de config); preview com a
   tabela `indice × coluna`; painel do monitor a cada 25 trials no output da
   busca + run "monitor" na MLflow UI com `best_expanding`/`best_sliding`;
   gráficos WH após os equivalentes 24h; `fig_metrics_cmp` com 3 painéis;
   métricas `mae_working_hours`/`r2_working_hours` no run pai.
3. Modo threshold: definir `STOP_MODE="threshold"` com meta inatingível e
   observar o painel (status ESTAGNANDO/ESTAGNADO) e, com
   `OPTUNA_STAGNATION_STOP=True`, a parada automática.
