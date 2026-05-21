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
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-800">
          {t("pageSettings.title")}
        </h1>
        <p className="mt-1 text-ink-500">{t("pageSettings.subtitle")}</p>
      </header>

      <DataDirectorySection />
      <QueryTimeoutSection />
      <CredentialsSection />
      <PrecisionSection />
      <DangerZoneSection />
    </div>
  );
}

function DangerZoneSection() {
  const { t } = useTranslation();
  const { data: datasets } = useQuery({
    queryKey: ["datasets"],
    queryFn: api.datasets,
  });

  return (
    <section className="card space-y-5 border-rose-200 bg-rose-50/40 p-6">
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
        <div>
          <h2 className="text-lg font-medium text-rose-900">
            {t("pageSettings.danger.title")}
          </h2>
          <p className="mt-1 text-sm text-rose-700">
            {t("pageSettings.danger.body")}
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
  const { t } = useTranslation();
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
          t("pageSettings.danger.deleteSuccess", {
            name: dataset.name.toUpperCase(),
            size: formatBytes(res.freed_bytes),
          }),
        );
      } else {
        toast.info(
          t("pageSettings.danger.deleteEmpty", {
            name: dataset.name.toUpperCase(),
          }),
        );
      }
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
      ? `${formatBytes(stats.total_size_bytes)} · ${stats.parquet_files} ${t(
          "common.files",
        )}`
      : "—";

  return (
    <div className="rounded-xl border border-rose-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-medium text-ink-900">
            {dataset.name.toUpperCase()}
          </div>
          <div className="text-xs text-ink-500">
            {t("pageSettings.danger.onDisk", { size: sizeLabel })}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="input w-56 text-sm"
            placeholder={t("pageSettings.danger.confirmPlaceholder", {
              name: dataset.name,
            })}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            aria-label={t("pageSettings.danger.ariaLabel", {
              name: dataset.name,
            })}
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
            {t("pageSettings.danger.deleteButton")}
          </button>
        </div>
      </div>
    </div>
  );
}

function PrecisionSection() {
  const { t } = useTranslation();
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
        <h2 className="text-lg font-medium text-ink-900">
          {t("pageSettings.precision.title")}
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          {t("pageSettings.precision.body")}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs uppercase tracking-wide text-ink-500">
          {t("pageSettings.precision.datasetLabel")}
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
                {t("pageSettings.precision.defaultDecimals")}
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
                {t("pageSettings.precision.defaultMethod")}
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
                  <th className="px-3 py-2 text-left font-medium">
                    {t("pageSettings.precision.tableHeader.column")}
                  </th>
                  <th className="px-3 py-2 text-left font-medium">
                    {t("pageSettings.precision.tableHeader.type")}
                  </th>
                  <th className="px-3 py-2 text-left font-medium">
                    {t("pageSettings.precision.tableHeader.decimals")}
                  </th>
                  <th className="px-3 py-2 text-left font-medium">
                    {t("pageSettings.precision.tableHeader.method")}
                  </th>
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
                              placeholder={t(
                                "pageSettings.precision.usesDefault",
                              )}
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
                              <option value="">
                                {t("pageSettings.precision.usesDefault")}
                              </option>
                              <option value="round">round</option>
                              <option value="truncate">truncate</option>
                            </select>
                          </td>
                        </>
                      ) : (
                        <td
                          className="px-3 py-1.5 text-ink-300"
                          colSpan={2}
                          title={t("pageSettings.precision.floatOnly")}
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
                      {t("pageSettings.precision.noColumns")}
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
                {t("pageSettings.precision.saved")}
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
              {t("pageSettings.precision.saveButton")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function DataDirectorySection() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });
  const [dataDir, setDataDir] = useState("");

  useEffect(() => {
    if (settings?.data_dir) {
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
        <h2 className="text-lg font-medium text-ink-900">
          {t("pageSettings.dataDir.title")}
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          {t("pageSettings.dataDir.body", { root: STORAGE_ROOT_DIRNAME })}
        </p>
      </div>

      <div>
        <label className="text-xs uppercase tracking-wide text-ink-500">
          {t("pageSettings.dataDir.pathLabel")}
        </label>
        <div className="mt-1 flex gap-2">
          <input
            className="input font-mono"
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            placeholder={t("pageSettings.dataDir.placeholder", {
              root: STORAGE_ROOT_DIRNAME,
            })}
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
            {t("pageSettings.dataDir.pick")}
          </button>
        </div>
        <p className="mt-2 text-[11px] text-ink-400">
          {t("pageSettings.dataDir.tip", { root: STORAGE_ROOT_DIRNAME })}
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
          {t("pageSettings.dataDir.saveButton")}
        </button>
      </div>
    </section>
  );
}

function QueryTimeoutSection() {
  const { t } = useTranslation();
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
      toast.success(t("pageSettings.queryTimeout.saved"));
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (isLoading) return <div className="card h-32 animate-pulse bg-ink-100" />;

  const invalid = !Number.isFinite(value) || value < 0 || value > 3600;

  return (
    <section className="card space-y-4 p-6">
      <div>
        <h2 className="text-lg font-medium text-ink-900">
          {t("pageSettings.queryTimeout.title")}
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          {t("pageSettings.queryTimeout.body")}
        </p>
      </div>

      <div className="flex items-end gap-3">
        <label className="flex-1 max-w-xs">
          <span className="text-xs uppercase tracking-wide text-ink-500">
            {t("pageSettings.queryTimeout.seconds")}
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
          {t("pageSettings.queryTimeout.saveButton")}
        </button>
      </div>
      {invalid ? (
        <p className="text-[11px] text-rose-500">
          {t("pageSettings.queryTimeout.invalid")}
        </p>
      ) : null}
    </section>
  );
}

function CredentialsSection() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: status, isLoading } = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentialStatus,
  });
  const [url, setUrl] = useState("https://cds.climate.copernicus.eu/api");
  const [key, setKey] = useState("");
  const [testResult, setTestResult] = useState<CredentialTestResult | null>(
    null,
  );

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
          <h2 className="text-lg font-medium text-ink-900">
            {t("pageSettings.credentials.title")}
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            {t("pageSettings.credentials.body", {
              path: status?.file_path ?? "~/.cdsapirc",
            })}
          </p>
        </div>
      </div>

      {!isLoading && status && <CredentialStatusBadge status={status} />}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <ol className="space-y-3 text-sm text-ink-600">
          <Step n={1}>
            {t("onboarding.credentials.steps.signIn")}{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/">
              cds.climate.copernicus.eu
            </ExtLink>
            .
          </Step>
          <Step n={2}>{t("onboarding.credentials.steps.accept")}</Step>
          <Step n={3}>
            {t("onboarding.credentials.steps.copyToken")}{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/profile">
              profile
            </ExtLink>{" "}
            {t("onboarding.credentials.steps.copyTokenSuffix")}{" "}
            <strong>Personal Access Token</strong>.
          </Step>
          <Step n={4}>{t("onboarding.credentials.steps.paste")}</Step>
        </ol>

        <div className="space-y-3">
          <div>
            <label className="block text-xs uppercase tracking-wide text-ink-500">
              {t("onboarding.credentials.apiUrl")}
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
              {t("onboarding.credentials.token")}
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                status?.has_credentials
                  ? t("onboarding.credentials.tokenPlaceholderReplace")
                  : ""
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
              {t("onboarding.credentials.saveButton")}
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
              {t("onboarding.credentials.testButton")}
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
  const { t } = useTranslation();
  if (!status.has_credentials) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        {t("pageSettings.credentials.noCreds")}
      </Badge>
    );
  }
  if (status.source === "env") {
    return (
      <Badge tone="info" icon={<CheckCircle2 className="h-4 w-4" />}>
        {t("pageSettings.credentials.sourceEnv")}
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
      {t("pageSettings.credentials.present", { url: status.url ?? "" })}
    </Badge>
  );
}

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

function ExtLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
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
