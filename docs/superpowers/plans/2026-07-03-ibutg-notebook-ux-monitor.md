# Monitor Optuna ao vivo + UX de notebooks (rodada 3) — Plano (registro)

> Executado inline (TDD). Design em `../specs/2026-07-03-ibutg-notebook-ux-monitor-design.md`.

**Goal:** M01 gráfico Plotly do monitor Optuna atualizando in-place; M02 corrigir
o travamento da MLflow UI durante a busca; M03 botão "Clean All Outputs"; M04
células de código sem scrollbar vertical; M05 remover coluna redundante da
tabela da célula #12.

## Tasks

### Task 1 — Kernel: display_id / update_display (M01), TDD
- [x] 2 testes em `tests/test_notebook_kernel.py` (display com/sem `display_id`).
- [x] `src/era5_etl/notebooks/kernel_runner.py`: `_display(value, display_id=None)`
  anexa `display_id` à mensagem; `display(*objs, display_id=None)` e nova
  `update_display(obj, display_id)` injetadas no namespace do kernel. Verde.

### Task 2 — Template (M01/M02/M05)
- [x] `tests/test_notebook_templates.py`: 26 células (inalterado); remove token
  `MONITOR_MLFLOW_LIVE`, adiciona `update_display(`, `optuna-monitor-`,
  `N_JOBS = max(`, `pd.DataFrame({"coluna": training_cols})`; asserções negativas
  `MONITOR_MLFLOW_LIVE`/`_MONITOR_RUN_ID` ausentes.
- [x] Gerador scratchpad `build_ibutg_template.py`: callback do Optuna vira gráfico
  ao vivo (curva do melhor + valor por trial, status/recomendação no título e
  anotação) via `update_display(fig, display_id=f"optuna-monitor-{method}")`;
  shim `try: update_display / except NameError: from IPython.display import
  update_display` (portável ao .ipynb); removido o run "monitor" MLflow e as
  escritas por-trial; `N_JOBS = max(1, os.cpu_count()-1)`; tabela da célula #12
  passa a `pd.DataFrame({"coluna": training_cols})`. Regenerado (26 células,
  sintaxe OK). Verde.

### Task 3 — Backend: mlflow ui multithread (M02)
- [x] `src/era5_etl/web/routes/mlflow_ui.py`: `_server_concurrency_args()` →
  `--waitress-opts --threads=8` (Windows) / `--workers 4` (POSIX), passado ao
  `_spawn`. Teste `test_server_concurrency_args_are_multithreaded`. Verde.

### Task 4 — Frontend (M01/M03/M04)
- [x] `web-ui/src/lib/api.ts`: `CellOutput.display` ganha `display_id?`.
- [x] `web-ui/src/pages/NotebookEditor.tsx`: `Map<display_id → índice>` no
  `executeCell` (substitui o output in-place); botão "Clean All Outputs"
  (`Eraser`) que zera outputs/indicadores e persiste via PUT `save`.
- [x] `web-ui/src/components/notebooks/CellEditor.tsx`: altura do Monaco dirigida
  por `getContentHeight()` (`onDidContentSizeChange`), sem cap de 20 linhas →
  sem scrollbar interna.
- [x] i18n `en.ts`/`pt.ts`: `cleanOutputs`/`cleanOutputsTitle`.
- [x] `bun run build` (tsc + vite) → assets em `src/era5_etl/web/static/`.

### Task 5 — Regressão + finalização
- [x] `py -3.12 -m pytest` → 666 passed, 1 skipped.
- [ ] Commits + finishing-a-development-branch.

## Verificação end-to-end (manual)
1. `era5 ui` → notebook do template "XGBoost - Target IBUTG".
2. M04: abrir a célula grande do Optuna → editor mostra tudo, sem rolagem interna.
3. M01: rodar a célula da busca (ex.: `N_TRIALS=8`) → UM gráfico do monitor que
   se atualiza a cada trial (curva + status no título); não empilha.
4. M02: com a busca rodando, abrir a MLflow UI → carrega/exibe (não trava);
   `N_JOBS` deixa 1 núcleo livre; sem run "monitor" na lista Model runs.
5. M03: "Clean All Outputs" → todas as saídas somem; recarregar mantém limpo.
6. M05: célula #12 → segunda tabela tem só índice nativo + `coluna`.
