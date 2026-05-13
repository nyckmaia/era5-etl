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
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, type CredentialTestResult } from "@/lib/api";
import { cn } from "@/lib/format";

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
      <CredentialsSection />
    </div>
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
