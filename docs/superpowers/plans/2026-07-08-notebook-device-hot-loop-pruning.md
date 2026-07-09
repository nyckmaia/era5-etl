# Plano executado: hot loop residente no device + Optuna pruning

Data: 2026-07-08. Spec: `docs/superpowers/specs/2026-07-08-notebook-device-hot-loop-pruning-design.md`.
Ordem TDD (teste RED antes de cada implementação).

## Passos

1. **`notebooks/device_data.py`** (novo) + `tests/test_notebook_device_data.py`
   (30 testes): `DeviceDataset.from_frame` (float32/contíguo/monotônico),
   `window_bounds` ≡ máscara booleana em índice com gaps (expanding + janela
   deslizante + anchored), `es_split` ≡ matemática iloc, skip `<50`/teste
   vazio, memoização + `clear()`, janela de exatamente 50 linhas sem ES,
   caminho nativo CPU fim-a-fim (QDM + ES + `inplace_predict` + métricas
   inline ≡ sklearn a 1e-6).
2. **`optuna_cache.py`**: `finished_trials`, `remaining_trials(...,
   include_pruned=False)`, `open_cached_study(..., pruner=None)` (+3 testes).
3. **`helpers_module.py`**: `plot_learning_curves` module-level + registro no
   `install_helpers` (+3 testes) — corrige NameError latente da célula de
   curvas do template Windows.
4. **`xgboost_target_ibutg.json`** (células 1, 2, 14, 18): handle `xp`;
   knobs `USE_OPTUNA_PRUNING/PRUNER_WARMUP_WINDOWS/PRUNER_STARTUP_TRIALS`;
   hot loop nativo com `DeviceDataset`/`WindowMatrixCache`; fingerprint
   `train_pipeline=device-resident-v2` + poda; guard do callback; resumo
   `[timing]`; `_MATS.clear()` no estudo de tamanho. Edição via round-trip
   JSON (`ensure_ascii=False, indent=2` + newline final, byte-estável);
   `compile()` de cada célula como gate.
5. **`xgboost_optuna_windows.json`** (células 1, 2, 13, 16): mesmas edições;
   `_MATS.clear()` no fim do sweep. Célula de curvas passa a funcionar via
   passo 3 sem edição.
6. **`tests/test_notebook_templates.py`**: tokens novos em ambos os templates
   (device_data import, `WindowMatrixCache`, `inplace_predict(`,
   `USE_OPTUNA_PRUNING`, `PRUNER_WARMUP_WINDOWS`, `TrialPruned`,
   `train_pipeline`, `include_pruned=`); contagens 27/22 e guards negativos
   intactos.
7. **Packaging/docs**: extra `gpu = ["cupy-cuda12x>=13"]` no pyproject;
   `VERSION` 0.7.0 → 0.8.0; nota no CLAUDE.md; esta spec + plano.

## Verificação

- `py -3.12 -m pytest` completo (suite inteira verde).
- E2E com kernel real + dados reais: template novo com orçamento reduzido —
  paridade de RMSE (epsilon de GPU, sancionado pela spec 2026-06-28), sem
  warning "mismatched devices", `[timing]`/`[device]`/pruning visíveis,
  monitor ao vivo e MLflow funcionando.
