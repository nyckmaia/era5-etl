import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  ExternalLink,
  FolderOpen,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, type CredentialTestResult, type PathValidation } from "@/lib/api";
import { cn } from "@/lib/format";

type StepKey = "welcome" | "data-dir" | "credentials" | "done";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "welcome", label: "Welcome" },
  { key: "data-dir", label: "Data directory" },
  { key: "credentials", label: "CDS credentials" },
  { key: "done", label: "Ready" },
];

export function Onboarding({ initialStep = "welcome" }: { initialStep?: StepKey }) {
  const [step, setStep] = useState<StepKey>(initialStep);
  const stepIndex = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink-900">First-time setup</h1>
          <p className="mt-1 text-sm text-ink-500">
            Two small things before downloading climate data: where to store it and
            how to talk to the Copernicus CDS.
          </p>
        </div>
      </div>

      <ol className="mb-8 flex items-center gap-2 text-xs">
        {STEPS.map((s, i) => (
          <li key={s.key} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-full border text-[11px] font-semibold",
                i < stepIndex
                  ? "border-ocean-600 bg-ocean-600 text-white"
                  : i === stepIndex
                    ? "border-ocean-600 text-ocean-700"
                    : "border-ink-200 text-ink-400",
              )}
            >
              {i < stepIndex ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
            </span>
            <span
              className={cn(
                i === stepIndex ? "font-medium text-ink-800" : "text-ink-400",
              )}
            >
              {s.label}
            </span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-ink-200" />}
          </li>
        ))}
      </ol>

      <div className="rounded-2xl border border-ink-100 bg-white p-8 shadow-sm">
        {step === "welcome" && <WelcomeStep onNext={() => setStep("data-dir")} />}
        {step === "data-dir" && (
          <DataDirStep onNext={() => setStep("credentials")} />
        )}
        {step === "credentials" && (
          <CredentialsStep onNext={() => setStep("done")} />
        )}
        {step === "done" && <DoneStep />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
          <ShieldCheck className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-medium text-ink-900">
            Welcome to ERA5-ETL
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            Two quick steps will get you ready: pick a folder to store downloaded
            climate data, then paste your Copernicus CDS API key. Both can be
            changed later from the Settings page.
          </p>
        </div>
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onNext}
          className="rounded-lg bg-ocean-600 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-700"
        >
          Begin setup
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function DataDirStep({ onNext }: { onNext: () => void }) {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [path, setPath] = useState("");
  const [validation, setValidation] = useState<PathValidation | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (settings.data?.data_dir && !path) setPath(settings.data.data_dir);
  }, [settings.data, path]);

  const validate = async (p: string) => {
    if (!p.trim()) {
      setValidation(null);
      return;
    }
    setChecking(true);
    try {
      const v = await api.validatePath(p);
      setValidation(v);
    } catch {
      setValidation(null);
    } finally {
      setChecking(false);
    }
  };

  const pick = useMutation({
    mutationFn: api.pickDirectory,
    onSuccess: (v) => {
      setPath(v.path);
      setValidation(v);
    },
  });

  const save = useMutation({
    mutationFn: () => api.saveSettings({ data_dir: path }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      onNext();
    },
  });

  const canSave =
    !!validation && validation.exists && validation.is_dir && validation.is_writable;

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
          <Database className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-medium text-ink-900">
            Where should downloaded data live?
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            Pick a root folder with several GB of headroom. ERA5-ETL{" "}
            <strong>will not write files directly inside it</strong> — it
            creates two managed subfolders described below.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-xs font-medium uppercase tracking-wide text-ink-500">
          Folder path
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onBlur={(e) => validate(e.target.value)}
            placeholder="/home/you/era5-data"
            className="flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-ocean-500 focus:outline-none focus:ring-1 focus:ring-ocean-500"
          />
          <button
            type="button"
            onClick={() => pick.mutate()}
            disabled={pick.isPending}
            className="flex items-center gap-2 rounded-lg border border-ink-200 px-3 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50 disabled:opacity-50"
          >
            {pick.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FolderOpen className="h-4 w-4" />
            )}
            Pick…
          </button>
        </div>

        {checking && (
          <div className="flex items-center gap-2 text-xs text-ink-400">
            <Loader2 className="h-3 w-3 animate-spin" /> Validating…
          </div>
        )}
        {validation && !checking && (
          <ValidationBadge v={validation} />
        )}
        {(validation?.path || path) && (
          <LayoutPreview rootPath={validation?.path || path} />
        )}
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={!canSave || save.isPending}
          className="rounded-lg bg-ocean-600 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-700 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save & continue"}
        </button>
      </div>
    </div>
  );
}

// Names mirror src/era5_etl/storage/paths.py (STORAGE_ROOT_DIRNAME, NETCDF_TMP_DIRNAME).
const STORAGE_ROOT_DIRNAME = "climate_data_store_db";
const NETCDF_TMP_DIRNAME = "_tmp_netcdf";

function LayoutPreview({ rootPath }: { rootPath: string }) {
  const trimmed = rootPath.replace(/[\\/]+$/, "");
  const sep = trimmed.includes("\\") && !trimmed.includes("/") ? "\\" : "/";
  return (
    <div className="rounded-lg border border-ocean-200 bg-ocean-50/50 px-4 py-3 text-xs">
      <div className="font-medium text-ocean-900">
        What gets created in this folder
      </div>
      <p className="mt-1 text-ink-600">
        The folder you picked stays your root.{" "}
        <strong>ERA5-ETL adds two managed subfolders inside it</strong>; the
        root itself is never filled with data files directly.
      </p>
      <pre className="mt-3 overflow-x-auto rounded-md bg-white p-3 font-mono text-[11px] leading-relaxed text-ink-700">
        <span className="text-ink-500">{trimmed || "<your folder>"}</span>
        {sep}
        {"\n"}
        <span className="text-ocean-700">
          └── {STORAGE_ROOT_DIRNAME}/
        </span>
        <span className="text-ink-400">
          {"           ← tudo que a ferramenta gerencia fica aqui"}
        </span>
        {"\n"}
        <span className="text-ink-500">
          {"        ├── era5/\n"}
          {"        ├── era5-land/    "}
        </span>
        <span className="text-ink-400">
          {"← Parquet + DuckDB + manifest (persistente)"}
        </span>
        {"\n"}
        <span className="text-ocean-700">
          {"        └── "}
          {NETCDF_TMP_DIRNAME}/
        </span>
        <span className="text-ink-400">
          {"      ← NetCDF temporário (apagado após conversão)"}
        </span>
        {"\n"}
        <span className="text-ink-500">
          {"            ├── era5/\n"}
          {"            └── era5-land/"}
        </span>
      </pre>
      <p className="mt-2 text-ink-500">
        Parquet partitions, the DuckDB file, and the per-dataset manifest
        all live under <code className="rounded bg-white px-1">{STORAGE_ROOT_DIRNAME}/</code>.
        The <code className="rounded bg-white px-1">{NETCDF_TMP_DIRNAME}/</code>{" "}
        folder now lives <em>inside</em> it and is removed automatically
        after a successful NetCDF → Parquet conversion.
      </p>
    </div>
  );
}

function ValidationBadge({ v }: { v: PathValidation }) {
  if (!v.exists) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        Path doesn't exist yet. Pick an existing folder or create it first.
      </Badge>
    );
  }
  if (!v.is_dir) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        That path points to a file, not a directory.
      </Badge>
    );
  }
  if (!v.is_writable) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        ERA5-ETL can't write to this folder. Check permissions.
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
      Folder exists and is writable.
      {v.is_empty === false && " (it already has files — that's fine)"}
    </Badge>
  );
}

// ---------------------------------------------------------------------------

function CredentialsStep({ onNext }: { onNext: () => void }) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["credentials"],
    queryFn: api.credentialStatus,
  });
  const [url, setUrl] = useState("https://cds.climate.copernicus.eu/api");
  const [key, setKey] = useState("");
  const [testResult, setTestResult] = useState<CredentialTestResult | null>(null);

  useEffect(() => {
    if (status.data?.url) setUrl(status.data.url);
  }, [status.data]);

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

  const alreadyOk = status.data?.has_credentials === true;

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
          <KeyRound className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-medium text-ink-900">
            Connect to the Copernicus CDS
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            ERA5 data is served by the Copernicus Climate Data Store. You'll
            need a free account and a Personal Access Token. The token is saved
            to <code className="rounded bg-ink-100 px-1 py-0.5 text-[11px]">
              {status.data?.file_path ?? "~/.cdsapirc"}
            </code> on this machine.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <ol className="space-y-3 text-sm text-ink-600">
          <Step n={1}>
            Create or sign in to a Copernicus account at{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/">
              cds.climate.copernicus.eu
            </ExtLink>
            .
          </Step>
          <Step n={2}>
            Open each dataset page (ERA5, ERA5-Land) and accept the terms
            once.
          </Step>
          <Step n={3}>
            Visit your{" "}
            <ExtLink href="https://cds.climate.copernicus.eu/profile">
              profile
            </ExtLink>{" "}
            and copy the <strong>Personal Access Token</strong>.
          </Step>
          <Step n={4}>Paste it on the right and click Save.</Step>
        </ol>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-ink-500">
              API URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-ocean-500 focus:outline-none focus:ring-1 focus:ring-ocean-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium uppercase tracking-wide text-ink-500">
              Personal Access Token
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={alreadyOk ? "(already saved — paste to replace)" : ""}
              autoComplete="off"
              spellCheck={false}
              className="mt-1 w-full rounded-lg border border-ink-200 px-3 py-2 font-mono text-sm focus:border-ocean-500 focus:outline-none focus:ring-1 focus:ring-ocean-500"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={!key.trim() || save.isPending}
              className="rounded-lg bg-ocean-600 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save credentials"}
            </button>
            <button
              type="button"
              onClick={() => test.mutate()}
              disabled={!alreadyOk || test.isPending}
              className="flex items-center gap-1 rounded-lg border border-ink-200 px-4 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50 disabled:opacity-50"
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
          {alreadyOk && !testResult && (
            <Badge tone="info" icon={<CheckCircle2 className="h-4 w-4" />}>
              Credentials present ({status.data?.source}).{" "}
              {status.data?.source === "env"
                ? "Loaded from environment variables."
                : "Click Test to verify the key is accepted."}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onNext}
          disabled={!alreadyOk}
          className="rounded-lg bg-ocean-600 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-700 disabled:opacity-50"
        >
          Continue
        </button>
      </div>
    </div>
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

// ---------------------------------------------------------------------------

function DoneStep() {
  return (
    <div className="space-y-5 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
        <CheckCircle2 className="h-7 w-7" />
      </div>
      <div>
        <h2 className="text-lg font-medium text-ink-900">Setup complete</h2>
        <p className="mt-1 text-sm text-ink-500">
          You can now browse datasets, plan a download, and query parquet data.
        </p>
      </div>
      <div className="flex justify-center">
        <a
          href="/dashboard"
          className="rounded-lg bg-ocean-600 px-5 py-2 text-sm font-medium text-white hover:bg-ocean-700"
        >
          Open the dashboard
        </a>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

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
