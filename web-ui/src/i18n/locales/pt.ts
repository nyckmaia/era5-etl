// Portuguese is the canonical language: en.ts mirrors this shape and
// every key here MUST exist there. Keys are grouped by feature/page so
// you can find/edit a label by looking at the section name first.

export const pt = {
  common: {
    back: "Voltar",
    next: "Próximo",
    cancel: "Cancelar",
    confirm: "Confirmar",
    save: "Salvar",
    delete: "Excluir",
    edit: "Editar",
    close: "Fechar",
    loading: "Carregando…",
    error: "Erro",
    warning: "Aviso",
    success: "Sucesso",
    yes: "Sim",
    no: "Não",
    all: "Tudo",
    none: "Nenhum",
    clear: "Limpar",
    apply: "Aplicar",
    open: "Abrir",
    selectAll: "Selecionar tudo",
    deselectAll: "Desmarcar tudo",
    starting: "Iniciando…",
    running: "Em execução",
    completed: "Concluído",
    failed: "Falhou",
    waiting: "Aguardando…",
    units: "unidades",
    files: "arquivos",
    rows: "linhas",
    columns: "colunas",
    seconds: "segundos",
    download: "Baixar",
    upload: "Enviar",
    refresh: "Atualizar",
  },

  language: {
    portuguese: "Português",
    english: "Inglês",
    switchTo: "Trocar para {{language}}",
  },

  layout: {
    brand: "ERA5-ETL",
    tagline: "Dados climáticos",
    nav: {
      dashboard: "Painel",
      inventory: "Inventário",
      download: "Download",
      query: "Consulta",
      timeseries: "Séries temporais",
      notebooks: "Notebooks",
      settings: "Configurações",
    },
    expandMenu: "Expandir menu",
    collapseMenu: "Recolher menu",
    footer: "ERA5 / ERA5-LAND · Copernicus CDS",
  },

  dashboard: {
    title: "Painel",
    subtitle:
      "Dois sistemas climáticos independentes, cada um com suas variáveis e partições Parquet próprias. Ambos baixam em NetCDF4 e convertem para Parquet.",
    descriptions: {
      era5:
        "Reanálise atmosférica em grade single-level 0,25°. Temperatura, vento, pressão, radiação, nuvens.",
      "era5-land":
        "Reanálise da superfície terrestre em grade 0,1°. Temperatura, umidade do solo, neve, precipitação.",
      inmet:
        "Estações meteorológicas do INMET (Brasil). Uma série por estação/ano; comparável ao ERA5/ERA5-LAND via era5_inmet.",
    },
    fallbackDescription: "Fonte de dados.",
  },

  datasetCard: {
    parquetFiles: "arquivos Parquet",
    totalSize: "Tamanho total",
    partitions: "Partições",
    manifestChunks: "Chunks no manifesto",
    deleteData: "Apagar dados",
    deleteConfirm:
      "Tem certeza que quer apagar TODOS os dados de {{dataset}}? Esta ação não pode ser desfeita.",
    noData: "Sem dados ainda. Use o Download para baixar.",
  },

  wizard: {
    title: "Wizard de Download",
    subtitle:
      "Configure uma requisição ao CDS. Variáveis e resolução da grade são independentes por sistema.",
    steps: {
      dataset: "Sistema",
      variables: "Variáveis",
      area: "Área",
      period: "Período",
      smartDiff: "Smart Diff",
      confirm: "Confirmar",
    },
    chooseDataset: "Escolher sistema",
    resolution: "Resolução",
    variablesAvailable: "{{count}} variáveis disponíveis",

    variables: {
      title: "Selecionar variáveis",
      counter: "({{selected}}/{{total}})",
      defaultPreset: "Pré-seleção padrão",
      all: "Todas",
      clear: "Limpar",
      filter: "Filtrar por nome, código ou descrição…",
      sectionCounter: "({{selected}}/{{total}})",
      selectAll: "Selecionar tudo",
      deselectAll: "Desmarcar tudo",
      allVariables: "Todas as variáveis",
      nothingMatches:
        'Nada corresponde a "{{query}}". Limpe o filtro ou tente outro termo.',
    },

    area: {
      title: "Área geográfica",
      brazilRegions: "Brasil — recortar ao polígono",
      brazilWhole: "Brasil inteiro",
      allUfs: "Todas as UFs",
      noClip: "Sem recorte",
      brazilClipNote:
        "Recorte ao polígono do Brasil. Apenas pontos de grade cujo centro está dentro do território são mantidos; os demais serão descartados antes do Parquet.",
      ufsClipNote:
        "{{count}} UF(s) selecionada(s) — bbox ajustado para a união, e pontos fora do polígono serão descartados antes do Parquet.",
      noClipNote: "Sem recorte: o retângulo abaixo será baixado por inteiro.",
      north: "Norte",
      south: "Sul",
      east: "Leste",
      west: "Oeste",
      bboxOrder:
        "Ordem do bounding box: [Norte, Oeste, Sul, Leste] em graus decimais.",
      presets: {
        brazil: "Brasil",
        global: "Global",
        southAmerica: "América do Sul",
      },
    },

    period: {
      title: "Período e horas",
      startDate: "Data inicial",
      endDate: "Data final",
      hours: "Horas (UTC)",
      hoursAll: "Todas (24 horas)",
      hoursSynoptic: "Sinóticas (00, 06, 12, 18)",
      hours3h: "A cada 3 horas",
      hoursCustom: "Personalizado",
    },

    diff: {
      title: "Smart Diff (subtrair já baixado)",
      explanation:
        "O Smart Diff compara sua requisição com a coverage index e exclui as células já presentes no banco antes de despachar o download.",
      enabled: "Ativado (pula células já baixadas)",
      disabled: "Desativado (requisição completa)",
      compute: "Calcular Smart Diff",
      narrowSelection: "Refinar seleção",
      requestedCells: "Células requisitadas",
      missingCells: "Células faltando",
      savings: "Economia",
      sample: "Amostra do que falta",
      diffSkipped: "Diff pulado",
      estimatedDownload: "Tamanho estimado do download",
      estimatedDisk: "Tamanho estimado em disco",
    },

    confirm: {
      title: "Confirmar e iniciar",
      dataset: "Sistema",
      period: "Período",
      variables: "Variáveis",
      hours: "Horas",
      area: "Área",
      polygonClip: "Recorte por polígono",
      polygonNoClip: "Sem recorte (bbox bruto)",
      polygonBrazil: "Brasil (polígono, estrito)",
      polygonUfs: "UF(s): {{ufs}} (polígono estrito)",
      smartDiff: "Smart Diff",
      estimateSize: "Estimar tamanho",
      startDownload: "Iniciar download",
      planSummary: "Resumo do plano",
      chunks: "{{count}} chunk(s) · {{size}} estimados (uncompressed)",
      runId: "Run iniciado:",
      variablesSelected: "{{count}} selecionada(s)",
      hoursSelected: "{{count}} de 24",
    },
  },

  inmet: {
    title: "Download INMET",
    subtitle:
      "Estações meteorológicas do INMET. Um ZIP por ano (todas as estações) — sem variáveis, área ou Smart Diff.",
    autoBootstrap: {
      title: "Configuração automática",
      body: "Antes do INMET, o sistema baixa uma amostra mínima do ERA5 e do ERA5-LAND (1 variável · 1 hora · 1 dia · Brasil inteiro) se ainda não houver dado em disco — necessária para as views de comparação {{view}}.",
      noAction: "Sem ação sua.",
    },
    years: {
      title: "1. Anos disponíveis no portal",
      loading: "Consultando o portal INMET…",
      error:
        "Não foi possível listar os anos do portal INMET (fora do ar ou layout mudou). Tente novamente mais tarde.",
      selectAll: "Marcar todos",
      deselectAll: "Desmarcar todos",
    },
    status: {
      lagNoticeTitle: "Atraso de publicação do INMET",
      lagNoticeBody:
        "O INMET publica os dados de dezembro de cada ano com cerca de 3 meses de atraso. O ano corrente está sempre em curso; anos recentes podem precisar de atualização por volta de março/abril.",
      legendLabel: "Status do ano:",
      complete: "Completo",
      partial: "Possivelmente incompleto",
      stale: "Desatualizado",
      current: "Em curso (ano corrente)",
      tooltip: {
        lastRecord: "Último registro: {{date}}",
        stationsComplete:
          "{{n}}/{{total}} estações chegaram a 31/dez",
        downloadedAt: "Baixado: {{when}}",
        neverDownloaded: "Não está no banco local",
      },
      updateAllStale: "Atualizar {{count}} ano(s) desatualizado(s)",
      updateCurrent: "Atualizar o ano corrente",
      updateRunning: "Atualização em curso…",
      partialDialog: {
        title: "O ano {{year}} está parcialmente completo",
        body:
          "{{missing}} de {{total}} estações não chegaram a 31 de dezembro. Podem ter sido desativadas, ou o ZIP pode estar desatualizado. Como deseja proceder?",
        update: "Atualizar (re-baixar)",
        dismiss: "Ignorar (provavelmente estações desativadas)",
        cancel: "Cancelar",
      },
    },
    run: {
      title: "2. Executar",
      selectAtLeastOne: "Selecione ao menos um ano.",
      yearsSelected: "{{count}} ano(s) selecionado(s).",
      button: "Baixar + processar INMET",
      buttonUpdate: "Atualizar + reprocessar anos selecionados",
      failure: "Falha ao iniciar: {{message}}",
      runStarted: "Run iniciado:",
      nextSteps: "Próximos passos",
      seeInventory: "Ver as estações no Inventário",
      seeInventoryHint: "(mapa de pontos por estação)",
      compareNote:
        "Comparar com a reanálise via a view {{view}} — INMET alinhado ao ERA5/ERA5-LAND nos 4 vizinhos de grade, mesma data e hora.",
    },
  },

  runProgress: {
    finished: "Pipeline finalizado",
    failed: "Pipeline falhou",
    running: "Pipeline em execução",
    completedTitle: "Pipeline concluído com sucesso",
    completedSubtitle:
      "{{done}} {{unit}}(s) baixado(s) e convertido(s) para Parquet. Os dados já estão consultáveis.",
    startingCDS: "Iniciando — enviando requisição ao CDS…",
    startingINMET: "Iniciando — consultando o portal INMET…",
    chunkOf: "Chunk {{i}} de {{n}}",
    yearOf: "Ano {{i}} de {{n}}",
    converting: "Convertendo {{done}}/{{total}}",
    progressOf: "{{done}} de {{total}} {{unit}}(s)",
    bars: {
      currentRequest: "Requisição CDS atual (NetCDF individual)",
      groupDownload: "Download (grupo de chunks)",
      yearsDownload: "Download (anos)",
      conversionNetcdf: "Conversão NetCDF → Parquet",
      conversionCsv: "Conversão CSV → Parquet",
    },
    barSub: {
      submitting: "Enviando requisição ao CDS",
      queued: "Na fila do CDS (aguardando aceitação)",
      runningCDS: "Aceita — CDS processando",
      downloadingNetcdf: "Baixando NetCDF",
      downloadingYear: "Baixando ZIP do ano (portal INMET)",
      yearExtracted: "Ano extraído",
      completed: "Concluído",
      waitingFirstRequest: "Aguardando primeira requisição…",
      waitingDownloads: "Aguardando downloads…",
      waitingYearDownloads: "Aguardando o download dos anos…",
    },
    finalizing: {
      title: "Finalizando — aguarde",
      explanation:
        "Conversão concluída. Estamos atualizando os índices e preparando as views — não feche a janela.",
    },
    listHeader: {
      chunks: "Chunks",
      years: "Anos",
    },
    waitingFirstYear: "Aguardando o primeiro ano…",
    waitingFirstChunk: "Aguardando o primeiro chunk…",
    recentEvents: "Eventos recentes",
    goToQuery: "Ir para Query",
    timer: {
      elapsed: "Tempo decorrido",
      total: "Tempo total",
    },
    units: {
      chunk: "chunk",
      year: "ano",
    },
    phaseLabels: {
      "bootstrap-era5": "Bootstrap ERA5",
      "bootstrap-era5-land": "Bootstrap ERA5-LAND",
      inmet: "INMET",
      era5: "ERA5",
      "era5-land": "ERA5-LAND",
    },
    phaseStep: "Etapa {{i}}/{{n}}",
  },

  query: {
    title: "Consulta SQL",
    runQuery: "Executar consulta",
    cancelQuery: "Cancelar",
    formatSql: "Formatar SQL",
    saveAs: "Salvar como…",
    export: "Exportar",
    exportCsv: "CSV",
    exportParquet: "Parquet",
    showRows: "{{count}} linhas",
    truncated: "(truncado em {{limit}})",
    builder: {
      open: "Construtor de VIEW",
      title: "Construir VIEW visualmente",
    },
    schema: {
      title: "Schema",
      sistema: "Sistema",
      myViews: "Minhas views e macros",
      newView: "Nova VIEW personalizada",
      loadingViews: "Carregando views… {{settled}}/{{total}}",
      allViewsLoaded: "Todas as {{total}} views carregadas",
      partialLoaded: "{{ok}}/{{total}} views carregadas",
      noData: "sem dados",
      schemaError: "erro",
      removed: '"{{name}}" removido',
      builtinBadge: "sistema",
      builtinHint: "Objeto interno — fornecido pelo sistema, somente leitura.",
      builtinOpenSql: "Abrir o SQL desta macro do sistema em uma nova aba",
      createFromSystem: "+ criar a partir das views do sistema",
      collapseSchema: "Recolher",
      showSchema: "Mostrar schema",
      warnBadge: {
        label: "WARN",
        hoverMissing: "Falta(m): {{names}} — clique para detalhes",
        hoverGeneric: "Erro ao registrar a VIEW — clique para detalhes",
        ariaLabel: "Aviso: VIEW com referências faltando",
      },
      warnPopover: {
        title: "VIEW indisponível",
        bodyWithList:
          "A VIEW {{name}} referencia os seguintes itens, que não estão no banco:",
        bodyWithoutList: "A VIEW {{name}} referencia itens que não estão no banco.",
        action: "Baixe o(s) dataset(s) faltante(s) em Download para habilitar esta VIEW.",
      },
    },
    insert: 'Inserir "{{name}}"',
    queryHistory: "Histórico de queries",
    saveDialog: {
      title: "Salvar VIEW / MACRO",
      name: "Nome",
      kind: "Tipo",
      view: "VIEW",
      macro: "MACRO",
      saveButton: "Salvar",
      sqlLabel: "SQL",
    },
  },

  inventory: {
    title: "Inventário",
    subtitle:
      "Onde estão os dados baixados — selecione o sistema, o período e variáveis para mapear cobertura.",
    dataset: "Sistema",
    dateRange: "Período",
    variables: "Variáveis",
    hours: "Horas",
    legend: "Legenda",
    cellsTotal: "{{count}} células",
    stationsTotal: "{{count}} estações",
    noDataForFilter: "Nenhum dado para os filtros atuais.",
    clickCell: "Clique numa célula para detalhes.",
    cellDetail: {
      title: "Detalhe da célula",
      coords: "Coordenadas",
      dates: "Datas com dado",
      hoursAvailable: "Horas disponíveis",
    },
    stations: {
      title: "Estações",
      empty: "Nenhuma estação carregada ainda.",
    },
  },

  timeseries: {
    title: "Séries temporais",
    subtitle:
      "Compare variáveis ao longo do tempo. Misture sistemas (ERA5, ERA5-LAND, INMET) na mesma série.",
    addSeries: "Adicionar série",
    removeSeries: "Remover",
    dateRange: "Período",
    bucket: "Agregação",
    buckets: {
      raw: "Bruto",
      hour: "Hora",
      day: "Dia",
      month: "Mês",
    },
    maxPoints: "Máx. de pontos",
    series: {
      view: "View",
      yColumn: "Coluna Y",
      agg: "Agregação",
      location: "Localização",
      axis: "Eixo",
    },
    aggs: {
      avg: "Média",
      min: "Mín.",
      max: "Máx.",
      sum: "Soma",
    },
    location: {
      point: "Ponto",
      region: "Região",
      kind: "Tipo",
      lat: "Lat",
      lon: "Lon",
      station: "Estação",
      uf: "UF",
    },
    run: "Gerar gráfico",
    downsampled: "(reduzido)",
    coarsenedNotice:
      "Algumas séries foram reagregadas para caber no limite de pontos.",
    noSeries: "Adicione ao menos uma série para começar.",
  },

  settings: {
    title: "Configurações",
    dataDir: {
      title: "Diretório de dados",
      current: "Caminho atual",
      change: "Trocar",
      pickFolder: "Escolher pasta…",
      validate: "Validar",
      exists: "Existe",
      writable: "Gravável",
      empty: "Vazio",
      pickedFolder: "Pasta escolhida: {{path}}",
    },
    defaultDataset: {
      title: "Sistema padrão",
    },
    queryTimeout: {
      title: "Timeout de consulta (segundos)",
      help: "0 desliga o timeout.",
    },
    credentials: {
      title: "Credenciais do Copernicus CDS",
      url: "URL",
      key: "Chave",
      save: "Salvar credenciais",
      test: "Testar conexão",
      status: {
        none: "Sem credenciais configuradas.",
        env: "Lendo de variável de ambiente.",
        file: "Lidas de {{path}}.",
      },
      testOk: "OK ({{latency}} ms)",
      testFail: "Falhou: {{message}}",
    },
    precision: {
      title: "Precisão por coluna",
      decimals: "Casas decimais",
      method: "Método",
      round: "Arredondar",
      truncate: "Truncar",
    },
    saved: "Salvo",
  },

  onboarding: {
    title: "Configuração inicial",
    subtitle:
      "Duas coisas antes de baixar dados climáticos: onde armazená-los e como conversar com o Copernicus CDS.",
    steps: {
      welcome: "Boas-vindas",
      dataDir: "Diretório de dados",
      credentials: "Credenciais CDS",
      done: "Pronto",
    },
    welcome: {
      title: "Bem-vindo ao ERA5-ETL",
      body: "Dois passos rápidos te deixam pronto: escolha uma pasta para armazenar os dados climáticos baixados e cole sua chave da API do Copernicus CDS. Ambos podem ser alterados depois nas Configurações.",
      begin: "Começar configuração",
    },
    dataDir: {
      title: "Onde os dados baixados devem ficar?",
      body: "Escolha uma pasta raiz com vários GB livres. O ERA5-ETL não grava arquivos diretamente nela — cria duas subpastas gerenciadas descritas abaixo.",
      pathLabel: "Caminho da pasta",
      pickButton: "Escolher…",
      validating: "Validando…",
      saveContinue: "Salvar e continuar",
      saving: "Salvando…",
    },
    layoutPreview: {
      title: "O que será criado nessa pasta",
      body: "A pasta escolhida continua sendo sua raiz. O ERA5-ETL adiciona duas subpastas gerenciadas dentro dela; a raiz nunca é preenchida com arquivos diretamente.",
      placeholder: "<sua pasta>",
      managedCommentRoot: "← tudo que a ferramenta gerencia fica aqui",
      managedCommentData: "← Parquet + DuckDB + manifest (persistente)",
      managedCommentTmp: "← NetCDF temporário (apagado após conversão)",
      explanation:
        "Partições Parquet, o arquivo DuckDB e o manifesto por dataset ficam todos sob {{root}}/. A pasta {{tmp}}/ agora vive dentro dela e é removida automaticamente após uma conversão NetCDF → Parquet bem-sucedida.",
    },
    validation: {
      missing: "O caminho não existe. Escolha uma pasta existente ou crie antes.",
      notADir: "O caminho aponta para um arquivo, não um diretório.",
      notWritable: "Sem permissão de escrita nessa pasta. Verifique as permissões.",
      ok: "Pasta existe e é gravável.",
      okHasFiles: " (já contém arquivos — sem problema)",
    },
    credentials: {
      title: "Conectar ao Copernicus CDS",
      body: "Os dados ERA5 são servidos pelo Copernicus Climate Data Store. É preciso uma conta gratuita e um Personal Access Token. O token é salvo em {{path}} nesta máquina.",
      steps: {
        signIn: "Crie ou entre numa conta Copernicus em",
        accept:
          "Abra cada página de dataset (ERA5, ERA5-Land) e aceite os termos uma vez.",
        copyToken: "Visite seu",
        copyTokenSuffix: "e copie o",
        paste: "Cole na direita e clique em Salvar.",
      },
      apiUrl: "URL da API",
      token: "Personal Access Token",
      tokenPlaceholderReplace: "(já salvo — cole para substituir)",
      saveButton: "Salvar credenciais",
      saving: "Salvando…",
      testButton: "Testar",
      continue: "Continuar",
      presentNote:
        "Credenciais presentes ({{source}}). {{action}}",
      sourceEnv:
        "Carregadas de variáveis de ambiente.",
      sourceFile: "Clique em Testar para verificar se a chave é aceita.",
    },
    done: {
      title: "Configuração concluída",
      body: "Agora você pode explorar datasets, planejar um download e consultar Parquet.",
      openDashboard: "Abrir o painel",
    },
  },

  pageSettings: {
    title: "Configurações",
    subtitle:
      "Configure onde o ERA5-ETL armazena dados e como conversa com o Copernicus CDS.",
    dataDir: {
      title: "Diretório de dados",
      body: "O caminho abaixo aponta para a raiz de armazenamento — {{root}}/ — onde ficam todas as partições Parquet, arquivos DuckDB e o manifesto. Ao clicar em Escolher, o ERA5-ETL adiciona essa subpasta à sua escolha para que o caminho salvo seja a raiz real dos dados.",
      pathLabel: "Caminho da raiz de armazenamento",
      placeholder: "/caminho/para/dados/{{root}}",
      pick: "Escolher",
      tip: "Dica: escolha a pasta onde quer os dados; o ERA5-ETL adiciona /{{root}} automaticamente.",
      saveButton: "Salvar configurações",
    },
    queryTimeout: {
      title: "Tempo limite da consulta",
      body: "Encerra automaticamente uma consulta na tela /query que demore mais que o limite abaixo. O usuário também pode cancelar clicando em Cancelar ao lado do botão Run query. Use 0 para desativar o timer (sem limite).",
      seconds: "Segundos",
      saveButton: "Salvar",
      saved: "Tempo limite salvo",
      invalid: "Use um inteiro entre 0 e 3600 (0 = sem limite).",
    },
    credentials: {
      title: "Credenciais CDS",
      body: "Os dados ERA5 são servidos pelo Copernicus Climate Data Store. Seu Personal Access Token é salvo em {{path}} nesta máquina — não é enviado para outro lugar.",
      noCreds:
        "Nenhuma credencial CDS encontrada ainda. Downloads falharão até salvar seu token abaixo.",
      sourceEnv:
        "Usando credenciais de variáveis de ambiente. Salvar aqui escreve ~/.cdsapirc mas as variáveis continuam tendo precedência.",
      present:
        "Credenciais presentes em {{url}}. Use Testar para verificar conectividade ou cole uma nova chave para substituir.",
    },
    precision: {
      title: "Precisão de exibição",
      body: "Define quantas casas decimais (e o método) são usadas ao exibir colunas float nos resultados de consulta. Apenas afeta a visualização — os dados em Parquet não são alterados.",
      datasetLabel: "Dataset",
      defaultDecimals: "Casas decimais (padrão)",
      defaultMethod: "Método (padrão)",
      tableHeader: {
        column: "Coluna",
        type: "Tipo",
        decimals: "Casas decimais",
        method: "Método",
      },
      usesDefault: "usa o padrão",
      noColumns: "Sem colunas ainda (nenhum Parquet para este dataset).",
      saveButton: "Salvar precisão",
      saved: "Precisão salva.",
      floatOnly: "Arredondamento só se aplica a colunas float",
    },
    nbCache: {
      title: "Cache de notebooks",
      body: "Arquivos Parquet gerados pelos notebooks em /notebooks, agrupados por notebook.",
      total: "Total: {{size}}",
      clearAll: "Limpar tudo",
      clearAllConfirm: "Apagar TODO o cache de notebooks? Esta ação não pode ser desfeita.",
      deleteNotebook: "Limpar cache deste notebook",
      deleteNotebookConfirm: "Apagar todo o cache de \"{{name}}\"?",
      deleteFile: "Apagar este arquivo",
      orphans: "Órfãos / desconhecido",
      empty: "Nenhum cache de notebook ainda.",
      freed: "Liberados {{size}}.",
    },
    danger: {
      title: "Zona de perigo",
      body: "Apagar os dados de um sistema remove permanentemente todo o conteúdo da sua pasta (partições Parquet, manifesto, índice de cobertura e os arquivos DuckDB) e os NetCDF temporários. Não há como desfazer — os dados terão que ser baixados novamente da CDS.",
      onDisk: "Em disco: {{size}}",
      confirmPlaceholder: "Digite \"{{name}}\" para confirmar",
      ariaLabel: "Confirmar exclusão de {{name}}",
      deleteButton: "Apagar definitivamente",
      deleteSuccess: "Dados de {{name}} apagados — {{size}} liberados.",
      deleteEmpty: "Nenhum dado em disco para {{name}}.",
    },
  },

  pageInventory: {
    title: "Inventário",
    subtitle:
      "Onde estão os dados baixados — selecione o sistema, o período e variáveis para mapear cobertura.",
    selectDataset: "Sistema",
    selectDateRange: "Período",
    variables: "Variáveis",
    hours: "Horas",
    refresh: "Atualizar",
    legend: "Legenda",
    cellsCount: "{{count}} célula(s)",
    stationsCount: "{{count}} estação(ões)",
    emptyFilter:
      "Nenhum dado para os filtros atuais. Ajuste as variáveis, horas ou período acima.",
    emptyDataset: "Sem dados baixados ainda. Use o Download para começar.",
    cellDetail: {
      title: "Detalhe da célula",
      coords: "Coordenadas",
      dates: "Datas com dado",
      hours: "Horas disponíveis",
      close: "Fechar",
    },
    stations: {
      title: "Estações INMET",
      filter: "Filtrar por nome, ID ou UF…",
      yearsActive: "{{min}} → {{max}} ({{count}} ano(s))",
    },
  },

  pageTimeseries: {
    title: "Séries temporais",
    subtitle:
      "Compare variáveis ao longo do tempo. Misture sistemas (ERA5, ERA5-LAND, INMET) na mesma série.",
    addSeries: "Adicionar série",
    runChart: "Gerar gráfico",
    dateRange: "Período",
    startDate: "Data inicial",
    endDate: "Data final",
    bucket: "Agregação",
    maxPoints: "Máx. pontos",
    seriesEditor: {
      view: "View",
      yColumn: "Coluna Y",
      agg: "Agregação",
      location: "Localização",
      axis: "Eixo",
      name: "Nome (opcional)",
      remove: "Remover",
    },
    locationKinds: { point: "Ponto", region: "Região" },
    aggs: { avg: "Média", min: "Mín.", max: "Máx.", sum: "Soma" },
    buckets: { raw: "Bruto", hour: "Hora", day: "Dia", month: "Mês" },
    locationFields: {
      lat: "Latitude",
      lon: "Longitude",
      south: "Sul",
      north: "Norte",
      west: "Oeste",
      east: "Leste",
      station: "Estação",
      uf: "UF",
    },
    pickOnMap: "Escolher no mapa",
    noSeriesYet: "Adicione ao menos uma série para começar.",
    downsampledNote:
      "Algumas séries foram reagregadas para caber no limite de pontos.",
    failed: "Falha ao gerar o gráfico.",
  },

  diffPage: {
    title: "Smart Diff",
    description:
      "Comparamos sua requisição com o que já está no banco para baixar apenas os pontos/datas/horas/variáveis faltando.",
    computing: "Calculando o que já está no banco...",
    retry: "Tentar novamente",
    tooLargeTitle: "Requisição grande demais para o diff célula-a-célula",
    tooLargeBody:
      "Sua seleção expande para {{cells}} células. O diff fino esgotaria a memória; foi pulado. O download será planejado em {{chunks}} chunks sequenciais independentes.",
    downloadTotal: "Download TOTAL",
    diskTotal: "Em disco TOTAL (≈)",
    chunksLabel: "Chunks sequenciais",
    sumNotice: "Os tamanhos acima são o total somado de todos os chunks.",
    cellSplit: "Em média ≈ {{size}} de download por chunk.",
    chooseContinue:
      "Você pode prosseguir (clique em Próximo) e o download rodará nesses chunks sequenciais, ou voltar e escolher um período/área menor.",
    adjustArea: "Ajustar área",
    adjustPeriod: "Ajustar período",
    inDB: "Já no banco",
    missing: "Faltando",
    totalRequested: "Total requisitado",
    cellsUnit: "células",
    computeDiff: "Calcular diff",
    willBeDownloaded: "Será baixado (≈)",
    onDisk: "Em disco (≈)",
    onlyMissingNote: "apenas o que falta · transferência CDS",
    parquetAfter: "parquet após conversão",
    fullRequestInfo:
      "Requisição completa: {{dl}} de download · {{disk}} em disco (caso opte por baixar tudo).",
    downloadMode: "Modo de download",
    downloadMissing: "Baixar apenas o que falta (recomendado)",
    downloadMissingNote: "Economiza ~{{pct}}% das requisições ao CDS.",
    downloadAll: "Baixar tudo (sobrescrever)",
    downloadAllNote: "Re-baixa também os dados já presentes.",
    nothingMissing:
      "Nada faltando — todos os pontos/datas/horas/variáveis já estão no banco.",
  },

  notebooks: {
    title: "Notebooks",
    subtitle:
      "Células estilo Jupyter já conectadas ao DuckDB do sistema (com suas views/macros). Use Python + pandas + Plotly, ou rode SQL direto.",
    new: "Novo notebook",
    loading: "Carregando notebooks…",
    emptyHint: "Sem notebooks ainda. Crie um em branco ou parta de um template.",
    card: {
      cells: "{{count}} célula(s)",
      delete: "Apagar notebook",
      deleteConfirm: "Apagar \"{{name}}\"? Esta ação não pode ser desfeita.",
    },
    picker: {
      title: "Escolha um ponto de partida",
      body: "Templates já trazem código pronto que você pode editar.",
      blankName: "Notebook em branco",
      blankDescription: "Uma única célula Python vazia. Os imports são seus.",
      cancel: "Cancelar",
    },
    editor: {
      loading: "Carregando notebook…",
      notFound: "Notebook não encontrado. Pode ter sido apagado em outra aba.",
      save: "Salvar",
      runCell: "Executar",
      runCellTitle: "Executar célula (Ctrl/Cmd+Enter)",
      addBelow: "Adicionar célula abaixo",
      removeCell: "Apagar célula",
      addCell: "Adicionar célula",
      runAll: "Rodar tudo",
      runAllTitle: "Executar todas as células em ordem",
      runAllRunning: "Rodando tudo…",
      runStatusDone: "Executada",
      runStatusPending: "Ainda não executada",
      runStatusRunning: "Executando…",
    },
    kernel: {
      idle: "Kernel: pronto",
      busy: "Kernel: executando…",
      dead: "Kernel: parado",
      restart: "Reiniciar",
      restartTitle: "Mata e re-inicia o kernel (limpa todas as variáveis)",
      stop: "Parar",
      stopTitle: "Desligar o kernel",
    },
    runs: {
      section: "Histórico de modelos",
      title: "Runs de modelo ({{count}})",
      empty:
        "Nenhum run logado ainda. Chame log_model_run(params, metrics, duration_s).",
      metricLabel: "Métrica:",
      xAxis: "Run #",
      col: {
        when: "Quando",
        model: "Modelo",
        duration: "Duração",
        loadSource: "Carregamento",
        loadTime: "Tempo de carga",
        notes: "Notas",
      },
    },
  },
};

// Recursive shape: same tree as ``pt`` but every leaf is a plain string,
// so other locales (``en.ts``) can supply different translations without
// TypeScript complaining that each value is a literal type.
export type Dictionary = {
  [K in keyof typeof pt]: typeof pt[K] extends Record<string, unknown>
    ? DictionaryBranch<typeof pt[K]>
    : string;
};
type DictionaryBranch<T> = {
  [K in keyof T]: T[K] extends Record<string, unknown>
    ? DictionaryBranch<T[K]>
    : string;
};
