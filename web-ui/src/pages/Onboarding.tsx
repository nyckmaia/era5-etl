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
import { useTranslation } from "react-i18next";

import { api, type CredentialTestResult, type PathValidation } from "@/lib/api";
import { cn } from "@/lib/format";

type StepKey = "welcome" | "data-dir" | "credentials" | "done";

const STEP_KEYS: { key: StepKey; labelKey: string }[] = [
  { key: "welcome", labelKey: "onboarding.steps.welcome" },
  { key: "data-dir", labelKey: "onboarding.steps.dataDir" },
  { key: "credentials", labelKey: "onboarding.steps.credentials" },
  { key: "done", labelKey: "onboarding.steps.done" },
];

export function Onboarding({ initialStep = "welcome" }: { initialStep?: StepKey }) {
  const { t } = useTranslation();
  const [step, setStep] = useState<StepKey>(initialStep);
  const stepIndex = STEP_KEYS.findIndex((s) => s.key === step);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-ink-900">
            {t("onboarding.title")}
          </h1>
          <p className="mt-1 text-sm text-ink-500">{t("onboarding.subtitle")}</p>
        </div>
      </div>

      <ol className="mb-8 flex items-center gap-2 text-xs">
        {STEP_KEYS.map((s, i) => (
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
              {t(s.labelKey)}
            </span>
            {i < STEP_KEYS.length - 1 && <span className="mx-1 h-px w-6 bg-ink-200" />}
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

function WelcomeStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
          <ShieldCheck className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-medium text-ink-900">
            {t("onboarding.welcome.title")}
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            {t("onboarding.welcome.body")}
          </p>
        </div>
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onNext}
          className="rounded-lg bg-ocean-600 px-4 py-2 text-sm font-medium text-white hover:bg-ocean-700"
        >
          {t("onboarding.welcome.begin")}
        </button>
      </div>
    </div>
  );
}

function DataDirStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation();
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
            {t("onboarding.dataDir.title")}
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            {t("onboarding.dataDir.body")}
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-xs font-medium uppercase tracking-wide text-ink-500">
          {t("onboarding.dataDir.pathLabel")}
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
            {t("onboarding.dataDir.pickButton")}
          </button>
        </div>

        {checking && (
          <div className="flex items-center gap-2 text-xs text-ink-400">
            <Loader2 className="h-3 w-3 animate-spin" />{" "}
            {t("onboarding.dataDir.validating")}
          </div>
        )}
        {validation && !checking && <ValidationBadge v={validation} />}
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
          {save.isPending
            ? t("onboarding.dataDir.saving")
            : t("onboarding.dataDir.saveContinue")}
        </button>
      </div>
    </div>
  );
}

const STORAGE_ROOT_DIRNAME = "climate_data_store_db";
const NETCDF_TMP_DIRNAME = "_tmp_netcdf";

function LayoutPreview({ rootPath }: { rootPath: string }) {
  const { t } = useTranslation();
  const trimmed = rootPath.replace(/[\\/]+$/, "");
  const sep = trimmed.includes("\\") && !trimmed.includes("/") ? "\\" : "/";
  return (
    <div className="rounded-lg border border-ocean-200 bg-ocean-50/50 px-4 py-3 text-xs">
      <div className="font-medium text-ocean-900">
        {t("onboarding.layoutPreview.title")}
      </div>
      <p className="mt-1 text-ink-600">{t("onboarding.layoutPreview.body")}</p>
      <pre className="mt-3 overflow-x-auto rounded-md bg-white p-3 font-mono text-[11px] leading-relaxed text-ink-700">
        <span className="text-ink-500">
          {trimmed || t("onboarding.layoutPreview.placeholder")}
        </span>
        {sep}
        {"\n"}
        <span className="text-ocean-700">
          └── {STORAGE_ROOT_DIRNAME}/
        </span>
        <span className="text-ink-400">
          {`           ${t("onboarding.layoutPreview.managedCommentRoot")}`}
        </span>
        {"\n"}
        <span className="text-ink-500">
          {"        ├── era5/\n"}
          {"        ├── era5-land/    "}
        </span>
        <span className="text-ink-400">
          {t("onboarding.layoutPreview.managedCommentData")}
        </span>
        {"\n"}
        <span className="text-ocean-700">
          {"        └── "}
          {NETCDF_TMP_DIRNAME}/
        </span>
        <span className="text-ink-400">
          {`      ${t("onboarding.layoutPreview.managedCommentTmp")}`}
        </span>
        {"\n"}
        <span className="text-ink-500">
          {"            ├── era5/\n"}
          {"            └── era5-land/"}
        </span>
      </pre>
      <p className="mt-2 text-ink-500">
        {t("onboarding.layoutPreview.explanation", {
          root: STORAGE_ROOT_DIRNAME,
          tmp: NETCDF_TMP_DIRNAME,
        })}
      </p>
    </div>
  );
}

function ValidationBadge({ v }: { v: PathValidation }) {
  const { t } = useTranslation();
  if (!v.exists) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        {t("onboarding.validation.missing")}
      </Badge>
    );
  }
  if (!v.is_dir) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        {t("onboarding.validation.notADir")}
      </Badge>
    );
  }
  if (!v.is_writable) {
    return (
      <Badge tone="error" icon={<AlertCircle className="h-4 w-4" />}>
        {t("onboarding.validation.notWritable")}
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
      {t("onboarding.validation.ok")}
      {v.is_empty === false && t("onboarding.validation.okHasFiles")}
    </Badge>
  );
}

function CredentialsStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation();
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
            {t("onboarding.credentials.title")}
          </h2>
          <p className="mt-1 text-sm text-ink-500">
            {t("onboarding.credentials.body", {
              path: status.data?.file_path ?? "~/.cdsapirc",
            })}
          </p>
        </div>
      </div>

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
            <label className="block text-xs font-medium uppercase tracking-wide text-ink-500">
              {t("onboarding.credentials.apiUrl")}
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
              {t("onboarding.credentials.token")}
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                alreadyOk
                  ? t("onboarding.credentials.tokenPlaceholderReplace")
                  : ""
              }
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
              {save.isPending
                ? t("onboarding.credentials.saving")
                : t("onboarding.credentials.saveButton")}
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
          {alreadyOk && !testResult && (
            <Badge tone="info" icon={<CheckCircle2 className="h-4 w-4" />}>
              {t("onboarding.credentials.presentNote", {
                source: status.data?.source ?? "",
                action:
                  status.data?.source === "env"
                    ? t("onboarding.credentials.sourceEnv")
                    : t("onboarding.credentials.sourceFile"),
              })}
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
          {t("onboarding.credentials.continue")}
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

function DoneStep() {
  const { t } = useTranslation();
  return (
    <div className="space-y-5 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
        <CheckCircle2 className="h-7 w-7" />
      </div>
      <div>
        <h2 className="text-lg font-medium text-ink-900">
          {t("onboarding.done.title")}
        </h2>
        <p className="mt-1 text-sm text-ink-500">{t("onboarding.done.body")}</p>
      </div>
      <div className="flex justify-center">
        <a
          href="/dashboard"
          className="rounded-lg bg-ocean-600 px-5 py-2 text-sm font-medium text-white hover:bg-ocean-700"
        >
          {t("onboarding.done.openDashboard")}
        </a>
      </div>
    </div>
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
