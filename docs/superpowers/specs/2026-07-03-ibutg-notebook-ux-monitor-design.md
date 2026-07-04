# Design: monitor Optuna ao vivo + UX de notebooks (rodada 3)

Data: 2026-07-03. Aprovado em brainstorm. Abrange template `xgboost_target_ibutg`,
o kernel de notebooks, o backend da MLflow UI e o frontend React.

## M01 — Monitor de convergência como gráfico Plotly ao vivo (in-place)
Descoberta da exploração: o kernel transmite `display()`/`warn()` na hora, mas
`print(..., flush=True)` fica bufferizado até o fim da célula (o painel de texto
da rodada 2 não fazia streaming de verdade). E o protocolo só sabe ANEXAR outputs.

Solução (escolha do usuário): estender o protocolo do kernel com identidade de
display, retrocompatível.
- **Kernel** (`src/era5_etl/notebooks/kernel_runner.py`): `_display(value,
  display_id=None)` inclui `"display_id"` na mensagem `display` quando presente;
  `display(*objs, display_id=None)` e nova `update_display(obj, display_id)`
  injetadas no namespace. Sem `display_id` → comportamento atual (anexa).
- **Frontend** (`web-ui/src/pages/NotebookEditor.tsx`): no handler de streaming,
  um `Map<display_id → índice>`; se o id já foi visto, SUBSTITUI o output naquele
  índice em vez de anexar. `CellOutput` (`api.ts`) ganha `display_id?` opcional.
  Render por índice de array já reaproveita o componente → `NotebookPlotly`
  redesenha.
- **Template** (célula do Optuna): o callback constrói/atualiza UM gráfico por
  método via `update_display(fig, display_id=f"optuna-monitor-{method}")` a cada
  trial (cadência `MONITOR_EVERY`, default 1). O gráfico mostra a curva do melhor
  valor + valor por trial, e o STATUS (melhor vs meta, trials sem melhora, taxa,
  projeção até a meta, CONVERGINDO/ESTAGNANDO/ESTAGNADO) no título + anotação.
  Substitui o painel de texto e a sparkline ASCII da rodada 2. Auto-stop por
  estagnação permanece.

## M02 — MLflow UI travando durante a execução (correção mínima)
Diagnóstico: a UI trava por **starvation de CPU** (`N_JOBS=-1` satura todos os
núcleos; `mlflow ui` roda em processo único sem threads), agravada pelas escritas
MLflow por-trial do monitor ao vivo da rodada 2 sobre o file store que a UI relê.
Não é bug de thread do MLflow.
- Template célula de hardware: `N_JOBS = max(1, (os.cpu_count() or 2) - 1)` (deixa
  1 núcleo livre; flui p/ `XGB_BASE_PARAMS` e `permutation_importance`).
- `web/routes/mlflow_ui.py`: subir `mlflow ui` com threads — `--waitress-opts
  "--threads=8"` no Windows, `--workers 4` no POSIX (`sys.platform`).
- Remover as escritas MLflow por-trial do monitor ao vivo (o run "monitor" e
  `MONITOR_MLFLOW_LIVE`) — o M01 passa a dar o monitoramento ao vivo no próprio
  notebook. Mantém file store e runs existentes; sem migração.

## M03 — Botão "Clean All Outputs"
`NotebookEditor.tsx`, no toolbar ao lado de "Run all", ícone `Eraser`. Zera
`outputs` de todas as células no estado local (espelha o clear por-célula já
existente) + limpa `runStatus`/`elapsed`, e persiste via o PUT `save` existente
(recarregar mantém limpo). Sem endpoint novo, sem confirmação (reversível ao
re-rodar). i18n en/pt (`notebooks.editor.cleanOutputs`/`...Title`).

## M04 — Células de código sem scrollbar vertical
`web-ui/src/components/notebooks/CellEditor.tsx` (Monaco): troca a altura fixa
capada em 20 linhas por altura dirigida pelo conteúdo real
(`editor.getContentHeight()` via `onDidContentSizeChange`), respeitando quebra de
linha. Consequência desejada: células longas exibem tudo, sem rolagem interna.

## M05 — Tabela da célula #12
Troca `pd.DataFrame({"indice": range(len(training_cols)), "coluna": training_cols})`
por `pd.DataFrame({"coluna": training_cols})` — o índice nativo do DataFrame já dá
a posição, eliminando a coluna `indice` redundante.

## Entrega / testes
- Kernel: 2 testes em `tests/test_notebook_kernel.py` (display com/sem display_id).
- Template: `test_xgboost_target_ibutg_template` — 26 células (inalterado), remove o
  token `MONITOR_MLFLOW_LIVE`, adiciona `update_display(`, `N_JOBS = max(`,
  `pd.DataFrame({"coluna": training_cols})`.
- Frontend: validado pelo build TypeScript (`bun run build`) + verificação manual.
- SPA é gitignorada → rebuild obrigatório (`node_modules` já presente; `bun run
  build`). Backend/kernel/template cobertos por pytest.
