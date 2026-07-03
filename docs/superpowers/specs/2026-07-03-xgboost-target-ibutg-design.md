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
