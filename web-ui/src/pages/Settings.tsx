import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  Folder,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  api,
  type CredentialTestResult,
  type DatasetInfo,
  type PrecisionConfig,
  type PrecisionMethod,
} from "@/lib/api";
import { cn, formatBytes } from "@/lib/format";

// Mirror src/era5_etl/storage/paths.py:STORAGE_ROOT_DIRNAME.
const STORAGE_ROOT_DIRNAME = "climate_data_store_db";

/** Append the storage-root subfolder to a path the user just picked. */
function withStorageRoot(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  if (!trimmed) return trimmed;
  const sep = trimmed.includes("\\") && !trimmed.includes("/") ? "\\" : "/";
  if (trimmed.toLowerCase().endsWith(`${sep}${STORAGE_ROOT_DIRNAME}`)) {
    return trimmed;
  }
  if (trimmed.toLowerCase().endsWith(STORAGE_ROOT_DIRNAME)) {
    return trimmed;
  }
  return `${trimmed}${sep}${STORAGE_ROOT_DIRNAME}`;
}

export function SettingsPage() {
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">Settings</h1>
        <p className="mt-1 text-ink-500">
          Configure where ERA5-ETL stores data and how it talks to the
          Copernicus CDS.
        </p>
      </header>

      <DataDirectorySection />
      <QueryTimeoutSection />
      <CredentialsSection />
      <PrecisionSection />
      <DangerZoneSection />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Danger zone — wipe a dataset's on-disk data
// ---------------------------------------------------------------------------

function DangerZoneSection() {
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  return (
    <section className="card space-y-5 border-rose-200 bg-rose-50/40 p-6">
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
        <div>
          <h2 className="text-lg font-medium text-rose-900">Zona de perigo</h2>
          <p className="mt-1 text-sm text-rose-700">
            Apagar os dados de um sistema remove{" "}
            <strong>permanentemente</strong> todo o conteúdo da sua pasta
            (partições Parquet, manifesto, índice de cobertura e os arquivos
            DuckDB) e os NetCDF temporários. <strong>Não há como desfazer</strong>{" "}
            — os dados terão que ser baixados novamente da CDS.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        {(datasets ?? []).map((d) => (
          <DeleteDatasetRow key={d.name} dataset={d} />
        ))}
      </div>
    </section>
  );
}

function DeleteDatasetRow({ dataset }: { dataset: DatasetInfo }) {
  const qc = useQueryClient();
  const [confirmText, setConfirmText] = useState("");
  const { data: stats } = useQuery({
    queryKey: ["stats", dataset.name],
    queryFn: () => api.stats(dataset.name),
  });

  const del = useMutation({
    mutationFn: () => api.deleteDatasetData(dataset.name),
    onSuccess: (res) => {
      setConfirmText("");
      if (res.deleted) {
        toast.success(
          `Dados de ${dataset.name.toUpperCase()} apagados — ${formatBytes(
            res.freed_bytes,
          )} liberados.`,
        );
      } else {
        toast.info(`Nenhum dado em disco para ${dataset.name.toUpperCase()}.`);
      }
      // The dataset's storage is gone: refresh everything derived from it.
      qc.invalidateQueries({ queryKey: ["stats", dataset.name] });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["inventory-grid-points"] });
      qc.invalidateQueries({ queryKey: ["inventory-date-range"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const armed = confirmText.trim() === dataset.name;
  const sizeLabel =
    stats != null
      ? `${formatBytes(stats.total_size_bytes)} · ${stats.parquet_files} arquivo(s)`
      : "—";

  return (
    <div className="rounded-xl border border-rose-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-medium text-ink-900">
            {dataset.name.toUpperCase()}
          </div>
          <div className="text-xs text-ink-500">Em disco: {sizeLabel}</div>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input w-56 text-sm"
            placeholder={`Digite "${dataset.name}" para confirmar`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            aria-label={`Confirmar exclusão de ${dataset.name}`}
          />
          <button
            type="button"
            disabled={!armed || del.isPending}
            onClick={() => del.mutate()}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition",
              armed && !del.isPending
                ? "bg-rose-600 text-white hover:bg-rose-700"
                : "cursor-not-allowed bg-ink-100 text-ink-400",
            )}
          >
            {del.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Apagar definitivamente
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Display precision
// ---------------------------------------------------------------------------

function PrecisionSection() {
  const qc = useQueryClient();
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });
  const [dataset, setDataset] = useState<string>("era5-land");

  const { data: config, isLoading } = useQuery({
    queryKey: ["precision", dataset],
    queryFn: () => api.precision.get(dataset),
  });
  const { data: schema } = useQuery({
    queryKey: ["query-schema", dataset],
    queryFn: () => api.querySchema(dataset),
  });

  const [draft, setDraft] = useState<PrecisionConfig | null>(null);

  useEffect(() => {
    if (config) setDraft(config);
  }, [config]);

  const save = useMutation({
    mutationFn: (body: PrecisionConfig) => api.precision.save(body),
    onSuccess: (saved) => {
      setDraft(saved);
      qc.invalidateQueries({ queryKey: ["precision", dataset] });
    },
  });

  const datasetNames = datasets?.map((d) => d.name) ?? ["era5", "era5-land"];
  const columns = schema?.columns ?? [];

  const updateColumn = (
    col: string,
    patch: Partial<{ decimals: number; method: PrecisionMethod }>,
  ) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const cols = { ...prev.columns };
      const existing = cols[col] ?? {
        decimals: prev.default_decimals,
        method: prev.default_method,
      };
      cols[col] = { ...existing, ...patch };
      return { ...prev, columns: cols };
    });
  };

  const clearColumn = (col: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const cols = { ...prev.columns };
      delete cols[col];
      return { ...prev, columns: cols };
    });
  };

  return (
    <section className="card space-y-5 p-6">
      <div>
        <h2 className="text-lg font-medium text-ink-900">Precisão de exibição</h2>
        <p className="mt-1 text-sm text-ink-500">
          Define quantas casas decimais (e o método) são usadas ao exibir
          colunas <code>float</code> nos resultados de consulta. Apenas
          afeta a visualização — os dados em Parquet não são alterados.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs uppercase tracking-wide text-ink-500">
          Dataset
        </label>
        <div className="flex gap-2">
          {datasetNames.map((name) => (
            <button
              key={name}
              onClick={() => setDataset(name)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-medium",
                dataset === name
                  ? "bg-ocean-600 text-white"
                  : "bg-ink-100 text-ink-500 hover:bg-ink-200",
              )}
            >
              {name}
            </button>
          ))}
        </div>
      </div>

      {isLoading || !draft ? (
        <div className="h-32 animate-pulse rounded-lg bg-ink-100" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs uppercase tracking-wide text-ink-500">
                Casas decimais (padrão)
              </label>
              <input
                type="number"
                min={0}
                max={12}
                value={draft.default_decimals}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v))
                    setDraft({
                      ...draft,
                      default_decimals: Math.min(12, Math.max(0, v)),
                    });
                }}
                className="input mt-1 w-32"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wide text-ink-500">
                Método (padrão)
              </label>
              <select
                value={draft.default_method}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    default_method: e.target.value as PrecisionMethod,
                  })
                }
                className="input mt-1 w-40"
              >
                <option value="round">round</option>
                <option value="truncate">truncate</option>
              </select>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-ink-100">
            <table className="w-full text-xs">
              <thead className="bg-ink-50">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Coluna</th>
                  <th className="px-3 py-2 text-left font-medium">Tipo</th>
                  <th className="px-3 py-2 text-left font-medium">Casas decimais</th>
                  <th className="px-3 py-2 text-left font-medium">Método</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((c) => {
                  const isFloat = c.type === "float";
                  const override = draft.columns[c.name];
                  return (
                    <tr key={c.name} className="border-t border-ink-100">
                      <td className="px-3 py-1.5 font-mono">{c.name}</td>
                      <td className="px-3 py-1.5 text-ink-500">{c.type}</td>
                      {isFloat ? (
                        <>
                          <td className="px-3 py-1.5">
                            <input
                              type="number"
                              min={0}
                              max={12}
                              placeholder="usa o padrão"
                              value={override ? override.decimals : ""}
                              onChange={(e) => {
                                if (e.target.value === "") {
                                  clearColumn(c.name);
                                  return;
                                }
                                const v = Number(e.target.value);
                                if (Number.isFinite(v))
                                  updateColumn(c.name, {
                                    decimals: Math.min(12, Math.max(0, v)),
                                  });
                              }}
                              className="input w-28 text-xs"
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <select
                              value={override ? override.method : ""}
                              onChange={(e) => {
                                if (e.target.value === "") {
                                  clearColumn(c.name);
                                  return;
                                }
                                updateColumn(c.name, {
                                  method: e.target.value as PrecisionMethod,
                                });
                              }}
                              className="input w-32 text-xs"
                            >
                              <option value="">usa o padrão</option>
                              <option value="round">round</option>
                              <option value="truncate">truncate</option>
                            </select>
                          </td>
                        </>
                      ) : (
                        <td
                          className="px-3 py-1.5 text-ink-300"
                          colSpan={2}
                          title="Arredondamento só se aplica a colunas float"
                        >
                          —
                        </td>
                      )}
                    </tr>
                  );
                })}
                {columns.length === 0 && (
                  <tr>
                    <td
                      className="px-3 py-4 text-center text-ink-400"
                      colSpan={4}
                    >
                      Sem colunas ainda (nenhum Parquet para este dataset).
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-end gap-3">
            {save.isSuccess && !save.isPending && (
              <Badge
                tone="success"
                icon={<CheckCircle2 className="h-4 w-4" />}
              >
                Precisão salva.
              </Badge>
            )}
            <button
              className="btn-primary"
              onClick={() => draft && save.mutate(draft)}
              disabled={save.isPending}
            >
              {save.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Salvar precisão
            </button>
          </div>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Data directory
// ---------------------------------------------------------------------------

function DataDirectorySection() {
  const qc = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });
  const [dataDir, setDataDir] = useState("");

  useEffect(() => {
    if (settings?.data_dir) {
      // Always show the appended form, even if the backend stored the parent.
      setDataDir(withStorageRoot(settings.data_dir));
    }
  }, [settings]);

  const pickDir = useMutation({
    mutationFn: () => api.pickDirectory(),
    onSuccess: (data) => setDataDir(withStorageRoot(data.path)),
  });
  const save = useMutation({
    mutationFn: () => api.saveSettings({ data_dir: dataDir }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  if (isLoading) {
    return <div className="card h-48 animate-pulse bg-ink-100" />;
  }

  return (
    <section className="card space-y-5 p-6">
      <div>
        <h2 className="text-lg font-medium text-ink-900">Data directory</h2>
        <p className="mt-1 text-sm text-ink-500">
          The path below points to the storage root --
          <code className="mx-1 rounded bg-ink-100 px-1 font-mono text-[11px]">
            {STORAGE_ROOT_DIRNAME}/
          </code>
          -- where all Parquet partitions, DuckDB files and the manifest live.
          When you click <strong>Pick</strong>, ERA5-ETL appends this subfolder
          to your choice so the path you save is the actual data root.
        </p>
      </div>

      <div>
        <label className="text-xs uppercase tracking-wide text-ink-500">
          Storage root path
        </label>
        <div className="mt-1 flex gap-2">
          <input
            className="input font-mono"
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            placeholder={`/path/to/data/${STORAGE_ROOT_DIRNAME}`}
          />
          <button
            className="btn-outline whitespace-nowrap"
            onClick={() => pickDir.mutate()}
            disabled={pickDir.isPending}
          >
            {pickDir.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Folder className="h-4 w-4" />
            )}
            Pick
          </button>
        </div>
        <p className="mt-2 text-[11px] text-ink-400">
          Tip: pick the folder where you want your data; ERA5-ETL adds{" "}
          <code className="font-mono">/{STORAGE_ROOT_DIRNAME}</code>{" "}
          automatically so the structure is explicit.
        </p>
      </div>

      <div className="flex justify-end">
        <button
          className="btn-primary"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save settings
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Query timeout
// ---------------------------------------------------------------------------

function QueryTimeoutSection() {
  const qc = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });
  const [value, setValue] = useState<number>(10);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings && !dirty) setValue(settings.query_timeout_s ?? 10);
  }, [settings, dirty]);

  const save = useMutation({
    mutationFn: () => api.saveSettings({ query_timeout_s: value }),
    onSuccess: () => {
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Tempo limite salvo");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (isLoading) return <div className="card h-32 animate-pulse bg-ink-100" />;

  const invalid = !Number.isFinite(value) || value < 0 || value > 3600;

  return (
    <section className="card space-y-4 p-6">
      <div>
        <h2 className="text-lg font-medium text-ink-900">Tempo limite da query</h2>
        <p className="mt-1 text-sm text-ink-500">
          Encerra automaticamente uma consulta da tela{" "}
          <code className="rounded bg-ink-100 px-1 font-mono text-[11px]">/query</code>{" "}
          que demore mais que o limite abaixo. O usuário também pode cancelar a
          qualquer momento clicando em <strong>Cancelar</strong> ao lado do botão
          Run query. Use <strong>0</strong> para desativar o timer (sem limite).
        </p>
      </div>

      <div className="flex items-end gap-3">
        <label className="flex-1 max-w-xs">
          <span className="text-xs uppercase tracking-wide text-ink-500">
            Segundos
          </span>
          <input
            type="number"
            min={0}
            max={3600}
            step={1}
            className={cn(
              "input mt-1 font-mono",
              invalid && "border-rose-400 focus:ring-rose-300",
            )}
            value={Number.isFinite(value) ? value : ""}
            onChange={(e) => {
              setDirty(true);
              const n = Number(e.target.value);
              setValue(Number.isFinite(n) ? Math.floor(n) : 0);
            }}
          />
        </label>
        <button
          className="btn-primary"
          onClick={() => save.mutate()}
          disabled={save.isPending || invalid || !dirty}
        >
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Salvar
        </button>
      </div>
      {invalid ? (
        <p className="text-[11px] text-rose-500">
          Use um inteiro entre 0 e 3600 (0 = sem limite).
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// CDS credentials
// ---------------------------------------------------------------------------

function CredentialsSection() {
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentialStatus,
  });
  const [url, setUrl] = useState("https://cds.climate.copernicus.eu/api");
  const [key, setKey] = useState("");
  const [testResult, setTestResult] = useState<CredentialTestResult | null>(null);

  useEffect(() => {
    if (status?.url) setUrl(status.url);
  }, [status]);

  const save = useMutation({
    mutationFn: () => api.saveCredentials({ url, key }),
    onSuccess: () => {
      setKey("");
      setTestResult(null);
      qc.invalidateQueries({ queryKey: ["credentials"] });
    },
  });

  const test = useMutation({
    mutationFn: api.testCredentials,
    onSuccess: (r) => setTestResult(r),
  });

  return (
    <section className="card space-y-5 p-6">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
          <KeyRound className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-medium text-ink-900">CDS credentials</h2>
          <p className="mt-1 text-sm text-ink-500">
            ERA5 data is served by the Copernicus Climate Data Store. Your
            Personal Access Token is saved to{" "}
            <code className="rounded bg-ink-100 px-1 font-mono text-[11px]">
              {status?.file_path ?? "~/.cdsapirc"}
            </code>{" "}
            on this machine -- not sent anywhere else.
          </p>
        </div>
      </div>

      {!isLoading && status && (
        <CredentialStatusBadge status={status} />
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <ol className="space-y-3 text-sm text-ink-600">
          <Step n={1}>
            Sign in to{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/">
              cds.climate.copernicus.eu
            </ExtLink>
            .
          </Step>
          <Step n={2}>
            Accept the terms once on each dataset page (ERA5, ERA5-Land).
          </Step>
          <Step n={3}>
            Open your{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/profile">
              profile
            </ExtLink>{" "}
            and copy the <strong>Personal Access Token</strong>.
          </Step>
          <Step n={4}>Paste it on the right and click Save.</Step>
        </ol>

        <div className="space-y-3">
          <div>
            <label className="block text-xs uppercase tracking-wide text-ink-500">
              API URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="input mt-1 font-mono"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wide text-ink-500">
              Personal Access Token
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                status?.has_credentials ? "(already saved -- paste to replace)" : ""
              }
              autoComplete="off"
              spellCheck={false}
              className="input mt-1 font-mono"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              className="btn-primary"
              onClick={() => save.mutate()}
              disabled={!key.trim() || save.isPending}
            >
              {save.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save credentials
            </button>
            <button
              className="btn-outline"
              onClick={() => test.mutate()}
              disabled={!status?.has_credentials || test.isPending}
            >
              {test.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Test
            </button>
          </div>

          {testResult && (
            <Badge
              tone={testResult.ok ? "success" : "error"}
              icon={
                testResult.ok ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <AlertCircle className="h-4 w-4" />
                )
              }
            >
              {testResult.message}
              {testResult.latency_ms != null && testResult.ok &&
                ` (${testResult.latency_ms} ms)`}
            </Badge>
          )}
        </div>
      </div>
    </section>
  );
}

function CredentialStatusBadge({
  status,
}: {
  status: { has_credentials: boolean; source: string; url: string | null };
}) {
  if (!status.has_credentials) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        No CDS credentials found yet. Downloads will fail until you save your
        token below.
      </Badge>
    );
  }
  if (status.source === "env") {
    return (
      <Badge tone="info" icon={<CheckCircle2 className="h-4 w-4" />}>
        Using credentials from environment variables. Saving here writes
        ~/.cdsapirc but the env vars still take precedence.
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
      Credentials present at {status.url}. Use <em>Test</em> to verify
      connectivity, or paste a new key to replace.
    </Badge>
  );
}

// ---------------------------------------------------------------------------

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ocean-100 text-[11px] font-semibold text-ocean-700">
        {n}
      </span>
      <span>{children}</span>
    </li>
  );
}

function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-0.5 text-ocean-700 hover:underline"
    >
      {children}
      <ExternalLink className="h-3 w-3" />
    </a>
  );
}

function Badge({
  tone,
  icon,
  children,
}: {
  tone: "success" | "error" | "info";
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const colors = {
    success: "bg-emerald-50 text-emerald-800 border-emerald-200",
    error: "bg-rose-50 text-rose-800 border-rose-200",
    info: "bg-ocean-50 text-ocean-800 border-ocean-200",
  }[tone];
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
        colors,
      )}
    >
      <span className="mt-0.5">{icon}</span>
      <span>{children}</span>
    </div>
  );
}
