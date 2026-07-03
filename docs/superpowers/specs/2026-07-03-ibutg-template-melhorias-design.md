# Design: melhorias 01–05 no template "XGBoost - Target IBUTG"

Data: 2026-07-03 (segunda rodada, aprovada em brainstorm). Template alvo:
`src/era5_etl/_data/notebook_templates/xgboost_target_ibutg.json` (23 → 26 células).

## Melhoria 01 — TEST_FRACTION
`TEST_FRACTION = 0.005` por padrão (~últimas 24h num período de ~6 meses),
alinhado ao framing "prever as próximas 24h de D+1" do TODO.

## Melhoria 02 — defaults do catálogo ERA5-LAND (célula #5)
Ligadas por padrão: `temperature_2m`, `dewpoint_2m`, `wind_speed_10m`,
`skin_temperature`. Todo o resto `False` (inclusive `wind_u_10m`,
`wind_v_10m` e `surface_net_solar_radiation`, antes True). Sem impacto na
derivação do IBUTG: u10/v10 continuam sempre carregadas via
`_ERA5_LAND_WBGT_INPUTS` — apenas deixam de ser features.

## Melhoria 03 — preview com tabela de colunas (célula #12)
Além do `.head()`, a célula exibe uma tabela `indice × coluna` com todas as
colunas de treino (`training_cols`).

## Melhoria 04 — gráficos working-hours + comparativo de métricas
- Nova célula após a #21: `fig_pred_wh` — previsões+resíduos
  (`plot_predictions`) filtrado a `hour_utc ∈ [7,19)` (guarda p/ vazio).
- Nova célula após a #22: `fig2_wh` — **importância por permutação medida só
  nas WH** (a importância por gain é global ao modelo e não muda com o
  filtro): embaralha cada feature `PERM_WH_REPEATS=5` vezes, mede o aumento
  do RMSE nas linhas WH via `predict_aligned`; top-25. Aviso de ruído com
  teste pequeno.
- Nova célula: `fig_metrics_cmp` — 3 painéis (RMSE/MAE/R²), 2 barras cada
  (teste 24h × WH).
- Refit passa a calcular `mae_working_hours` e `r2_working_hours` (R² com
  guarda ≥2 amostras); entram no dict `metrics` → MLflow. As 3 figuras novas
  são logadas no MLflow com guardas.

## Melhoria 05 — monitor de convergência do Optuna (modo threshold)
Escolha do usuário: painel didático + curva ao vivo no MLflow.
- `_make_progress_callback` vira monitor: a cada `MONITOR_EVERY=25` trials
  imprime painel em streaming — melhor vs meta, trials sem melhora
  (min_delta), taxa de melhora na janela `MONITOR_RATE_WINDOW=50`, projeção
  de trials até a meta, sparkline ASCII e STATUS com recomendação
  (CONVERGINDO / ESTAGNANDO / ESTAGNADO → parar/ampliar espaço).
- Auto-stop opcional: `OPTUNA_STAGNATION_STOP=False`,
  `OPTUNA_STAGNATION_PATIENCE=200`, `OPTUNA_STAGNATION_MIN_DELTA=0.001`
  (via `study.stop()`).
- `MONITOR_MLFLOW_LIVE=True`: run MLflow "monitor <estação> <período>"
  (tag `monitor=true`) criado via `MlflowClient.create_run` ANTES das buscas
  (não vira run ativo — sem conflito com o run pai da célula final); o
  callback loga `best_<método>`/`trial_<método>` com step = nº do trial;
  `set_terminated` ao fim da célula. Efeito colateral aceito pelo usuário:
  o run aparece na lista Model runs. Não roda em modo REPEAT.

## Implementação
Mesmo gerador (script scratchpad `build_ibutg_template.py`, edições
ancoradas com assert sobre o template base) — seção "MELHORIAS 01-05"
adicionada e JSON regenerado. Testes: contagem 23→26 + tokens novos.
Zero mudança em código Python do pacote e no web-ui.
