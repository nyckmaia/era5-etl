# Design: hot loop residente no device + Optuna pruning (templates IBUTG e Windows)

Data: 2026-07-08
Escopo: templates `xgboost_target_ibutg` (27 células) e `xgboost_optuna_windows`
(22 células); módulos `notebooks/device_data.py` (novo), `optuna_cache.py`,
`helpers_module.py`.

## Problema

O hot loop dos templates (trial Optuna × janela de backtest × seed) re-fatiava o
DataFrame pandas e refazia `pandas → numpy → cupy` (`to_device_frame`) em CADA
fit — milhares de conversões/uploads por busca. Cada `predict` do wrapper
sklearn ainda devolvia numpy (sync GPU→CPU escondida) e as métricas rodavam em
sklearn no host.

## Fatos medidos (RTX 3080, xgboost 3.2.0 CUDA, cupy 13.6.0, optuna 4.9.0)

| Medição | Resultado |
|---|---|
| Caminho atual vs residente+QDM cacheada (4,4k linhas × 44 feats) | empate ~1,74 s/fit — movimentação de dados ≈ 50 ms (~3%) |
| Dominante no tempo de fit | rounds de boosting (~5 ms/round na GPU, latência de kernel) |
| GPU vs CPU nessa escala | GPU 1,78 s vs CPU 2,79 s/fit (GPU vence; "cuda sempre" mantido) |
| Fits concorrentes em 1 GPU | 2 threads +10%, 3 threads piora (paralelismo descartado) |
| 300k linhas | upload 26 ms + QDM 50 ms por janela — residência paga proporcionalmente à base |
| sklearn `predict(cupy)` | devolve numpy (sync por predição, confirmado) |
| Aliases sklearn no `xgb.train` | `n_jobs`/`random_state`/`eval_metric` passam sem warning (verificado com `-W error::UserWarning`) |

Conclusão: residência é higiene arquitetural + prontidão para escala; o maior
acelerador de wall-clock na escala default é **não pagar janelas de trials
ruins** → pruning por janela.

## Decisões

1. **Camada de dados só CuPy, unificada** (sem cuDF — RAPIDS não existe em
   Windows nativo; detecção por capacidade: cupy funcional → GPU, senão numpy;
   mesmo código em Windows e Ubuntu 24).
2. **Device: cuda sempre que funcional** (comportamento anterior, validado).
3. **Sem paralelismo de trials/seeds** (medição: não escala em 1 GPU).
4. **Pruning por janela ligado por default** (`USE_OPTUNA_PRUNING=True`).

## Arquitetura

### `notebooks/device_data.py` (novo, testado — templates só orquestram)

- `DeviceDataset.from_frame(frame, feature_cols, target_col, *, device,
  cupy_ok)`: upload ÚNICO de X float32 C-contíguo (n, f) + y; cupy sse
  `device=="cuda" and cupy_ok`; valida índice monotônico; `.xp` dá o módulo de
  arrays correspondente.
- `window_bounds(index, window)`: `searchsorted(side="left")` ≡ máscara
  booleana half-open `(>= start) & (< end)` em índice ordenado com gaps
  (pós-dropna).
- `es_split(n, frac) = n - max(1, int(n*frac))` — espelha o split iloc.
- `WindowMatrixCache(dataset, *, es_val_fraction, use_early_stopping,
  max_bin=256, min_train_rows=50)`: memoiza por bounds
  (`Timestamp.value` × 4) UMA `QuantileDMatrix` (train) + QDM `ref=` (val)
  por janela, reutilizada por todos os trials × seeds (`max_bin` não é
  tunado → quantização vale a busca toda). Skip (None) sse `n_train < 50 or
  n_test == 0`; janela de exatamente 50 linhas treina SEM early stopping
  (assimetria `< 50` / `> 50` do template preservada). `clear()` libera VRAM
  após sweep/estudo de tamanho.

### Células (hot loop novo)

- `_fit_one(wm, hyper, seed)`: `xgb.train` nativo sobre a QDM cacheada
  (aliases sklearn passam direto; chaves `_`-prefixadas removidas;
  `objective` explícito; `eval_metric` só no ramo com ES — paridade),
  `inplace_predict(X_test, iteration_range=(0, best_iteration+1))` (devolve
  cupy na GPU) e métricas RMSE/MAE/R² **inline em `xp`** (float64, R² com
  espelho do `force_finite`; um `float()` por escalar = única sync).
- `_eval_windows(..., trial=None)`: com pruning, reporta a métrica de CADA
  janela (`step=w.index`, valor por janela — NÃO média corrente) e levanta
  `TrialPruned`.
- **Pruner = `WilcoxonPruner(p_threshold=0.1,
  n_startup_steps=PRUNER_WARMUP_WINDOWS)`** (NopPruner se desligado), com
  gate adicional de `PRUNER_STARTUP_TRIALS` trials COMPLETE antes do 1º
  `should_prune`. Por quê não MedianPruner: o E2E real mostrou 0 podas em
  25 trials — a semântica "best-so-far vs mediana no passo" quebra quando os
  passos têm dificuldade variável (a janela 0, mais fácil, deixa todo trial
  abaixo da mediana). O Wilcoxon compara PAREADO por janela contra o melhor
  trial: no cenário sintético equivalente, 20/30 podados vs 4/30 do Median,
  com `best` igual/melhor. Podar cedo é seguro: só cai quem já é
  estatisticamente pior que o melhor trial. Orçamento na retomada do cache
  conta COMPLETE+PRUNED (`remaining_trials(..., include_pruned=True)` —
  senão estudo com muita poda nunca fecha a conta); callback protegido
  contra `study.best_value` sem trial COMPLETE; resumo `[timing]` (fits
  totais, ms/fit médio, device).
- Fingerprint ganha `"train_pipeline": "device-resident-v2"` + knobs de poda:
  os valores do objetivo mudam por epsilon vs o wrapper sklearn → estudos dos
  dois caminhos nunca se misturam. Efeito colateral intencional: caches de
  features/CSV de sweep/estudo são recalculados uma vez.
- Refit final, seleção de features (permutation) e células one-shot
  permanecem no wrapper sklearn (rodam 1×; MLflow `log_model`,
  `feature_importances_` e permutação dependem dele); `to_device_frame` /
  `predict_aligned` continuam para esses usos.

### `optuna_cache.py`

`finished_trials(study)` (COMPLETE+PRUNED), `remaining_trials(...,
include_pruned=False)` (default preserva semântica antiga),
`open_cached_study(..., pruner=None)`.

### Bug corrigido de brinde

A célula 17 do template Windows chamava `plot_learning_curves(...)`, função
desenhada na spec 2026-06-28 mas nunca embarcada → `NameError` com
`RUN_WINDOW_SWEEP=True` (default). Implementada module-level em
`helpers_module.py` (painel por passo de slide + painel expanding), registrada
no `install_helpers` e testada estruturalmente.

## Expectativas honestas

- Na escala default (~4,3k linhas) o ganho da residência é ~3%/fit; o ganho
  real vem do pruning (menos fits) e da remoção das syncs por predição. Em
  bases maiores (100k+ linhas) a residência + QDM cacheada passam a pagar
  proporcionalmente.
- GPU util 80–100%/VRAM em GB NÃO acontecem com 4,3k linhas — o limite é
  latência de lançamento de kernel, não transferência.

## Compatibilidade

- Templates são copiados por valor: notebooks existentes NÃO mudam; criar um
  notebook novo a partir do template atualizado.
- Sem GPU/cupy: mesmo código roda no caminho numpy (testes cobrem o caminho
  CPU de ponta a ponta).
- Guard negativo do IBUTG (`"sliding" not in src.lower()`) preservado — API
  nova não contém a substring; comentários usam "deslizante".
