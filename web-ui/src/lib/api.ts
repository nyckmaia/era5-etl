// Typed fetch wrappers for the FastAPI backend at /api/*.

export interface DatasetVariable {
  api_name: string;
  short_name: string;
  friendly_name: string;
  full_name: string;
  description: string;
  unit: string;
  /** Wizard section ids this variable belongs to. Empty for datasets that
   *  use a flat variable list (ERA5-LAND today). */
  groups?: string[];
}

export interface VariableGroup {
  id: string;
  label: string;
  order: number;
}

export interface DatasetInfo {
  name: string;
  cds_dataset_id: string;
  grid_resolution_deg: number;
  default_variables: string[];
  variables: DatasetVariable[];
  // Non-CDS/non-grid sources (e.g. INMET stations) report source_kind
  // "inmet_zip" and is_gridded=false. Optional for backward compat with
  // any cached/older payload shape.
  source_kind?: string;
  is_gridded?: boolean;
  /** Wizard sections in display order. Empty list = flat layout. */
  variable_groups?: VariableGroup[];
  /** True iff the user has at least one parquet for this dataset.
   *  The bootstrap grid parquet under ``_grids/`` does NOT flip this. */
  has_data?: boolean;
}

export interface StorageStats {
  dataset: string;
  parquet_files: number;
  total_size_bytes: number;
  partitions: string[];
  manifest_chunks: number;
  parquet_dir: string;
}

export interface UserSettings {
  data_dir: string;
  default_dataset: string;
  /** Server-side timeout (seconds) for /api/query. 0 disables. */
  query_timeout_s: number;
}

export interface EstimateChunk {
  chunk_id: string;
  year: number;
  month: number;
  days: number[];
  variables: string[];
  area: [number, number, number, number];
  estimated_bytes: number;
  estimated_mb: number;
}

export interface EstimateResult {
  dataset: string;
  total_chunks: number;
  total_estimated_bytes: number;
  total_estimated_mb: number;
  chunks: EstimateChunk[];
}

export interface PathValidation {
  path: string;
  exists: boolean;
  is_dir: boolean;
  is_writable: boolean;
  is_empty: boolean | null;
}

export interface CredentialStatus {
  has_credentials: boolean;
  source: "env" | "file" | "none";
  url: string | null;
  file_path: string;
}

export interface CredentialTestResult {
  ok: boolean;
  message: string;
  latency_ms: number | null;
  status_code: number | null;
}

// --- Inventory (v0.6.0) ---------------------------------------------------

export interface GridPoint {
  lat: number;
  lon: number;
  days: number;
  vars: number;
}

export interface StationPoint {
  station_id: string;
  latitude: number | null;
  longitude: number | null;
  altitude: number | null;
  uf: string | null;
  regiao: string | null;
  nome: string | null;
  year_min: number | null;
  year_max: number | null;
  n_years: number;
  n_vars: number;
}

export interface StationInventory {
  dataset: string;
  n_stations: number;
  stations: StationPoint[];
}

export interface CellDetailVariable {
  name: string;
  hours: number[];
}

export interface CellDetailDate {
  date: string;
  variables: CellDetailVariable[];
}

export interface CellDetail {
  latitude: number;
  longitude: number;
  dates: CellDetailDate[];
}

export interface RegionGap {
  date: string;
  missing_pct: number;
}

export interface RegionSummary {
  n_points: number;
  date_range: [string, string] | null;
  vars_per_cell_avg: number;
  gaps: RegionGap[];
}

export interface DiffPreviewSampleRow {
  lat: number;
  lon: number;
  date: string;
  variable: string;
  missing_mask: number;
}

export interface DiffPreview {
  requested_cells: number;
  missing_cells: number;
  savings_pct: number;
  sample_missing: DiffPreviewSampleRow[];
  diff_skipped: boolean;
  skip_reason: string | null;
  estimated_download_bytes: number | null;
  estimated_disk_bytes: number | null;
  estimated_chunks: number | null;
  missing_download_bytes: number | null;
  missing_disk_bytes: number | null;
}

// --- Query schema & display precision (v0.6.x) ----------------------------

export interface QuerySchemaColumn {
  name: string;
  type: string;
}

export interface QuerySchema {
  view: string;
  columns: QuerySchemaColumn[];
}

export interface QueryHistoryEntry {
  id: string;
  sql: string;
  ts: number;
  rows: number;
  elapsed_ms: number;
  name: string | null;
  favorite: boolean;
}

export interface UfBbox {
  uf: string;
  north: number;
  west: number;
  south: number;
  east: number;
}

export interface TemplateItem {
  id: string;
  name: string;
  sql: string;
  category: string | null;
}

export type PrecisionMethod = "round" | "truncate";

export interface ColumnPrecision {
  decimals: number;
  method: PrecisionMethod;
}

export interface PrecisionConfig {
  dataset: string;
  default_decimals: number;
  default_method: PrecisionMethod;
  columns: Record<string, ColumnPrecision>;
}

export interface BuildSpec {
  name: string;
  join_type: "INNER" | "LEFT";
  sources: { view: string; alias: string; columns: string[] }[];
  joins: {
    left: string;
    right: string;
    approx: boolean;
    epsilon: number;
  }[];
}

export interface UserObject {
  id: string;
  name: string;
  kind: "view" | "macro";
  sql: string;
  /** Visual-builder snapshot — present iff the object was last saved via
   *  the builder. The modal re-hydrates from it on edit. */
  builder_spec: BuildSpec | null;
  ok: boolean;
  error: string | null;
  columns: { name: string; type: string }[];
  /** System-provided object (defined in code) — read-only, not editable. */
  builtin?: boolean;
}

export interface UserObjectBody {
  name: string;
  kind: string;
  sql: string;
  builder_spec?: BuildSpec | null;
}

export interface UserObjectPreview {
  ok: boolean;
  error: string | null;
  columns: { name: string; type: string }[];
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

async function requestArrowOrJson<T>(url: string): Promise<T[]> {
  const r = await fetch(url, { headers: { Accept: "application/vnd.apache.arrow.stream, application/json" } });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  const ct = r.headers.get("content-type") ?? "";
  if (ct.includes("arrow")) {
    const { tableFromIPC } = await import("apache-arrow");
    const buf = new Uint8Array(await r.arrayBuffer());
    const table = tableFromIPC(buf);
    return table.toArray().map((row: { toJSON: () => unknown }) => row.toJSON()) as T[];
  }
  return (await r.json()) as T[];
}

// --- Time series -----------------------------------------------------

export interface TSViewMeta {
  view: string;
  location_kind: "grid" | "station";
  numeric_columns: { name: string; type: string }[];
  date_min: string | null;
  date_max: string | null;
  grid_resolution: number | null;
}
export interface TimeseriesMeta {
  views: TSViewMeta[];
}
export interface TSLocation {
  kind: "point" | "region";
  lat?: number | null;
  lon?: number | null;
  south?: number | null;
  north?: number | null;
  west?: number | null;
  east?: number | null;
  station_id?: string | null;
  uf?: string | null;
  station_ids?: string[] | null;
}
export interface TSSeriesConfig {
  view: string;
  y_column: string;
  agg: "avg" | "min" | "max" | "sum";
  location: TSLocation;
  axis: "y" | "y2";
  name?: string | null;
}
export interface TimeseriesRequest {
  date_from: string;
  date_to: string;
  bucket: "raw" | "hour" | "day" | "month";
  max_points: number;
  series: TSSeriesConfig[];
}
export interface TSSeriesResult {
  name: string;
  view: string;
  y_column: string;
  agg: string;
  axis: "y" | "y2";
  x: string[];
  y: (number | null)[];
  n_points: number;
  bucket_used: string;
  downsampled: boolean;
  location_label: string;
  error: string | null;
}
export interface TimeseriesResponse {
  series: TSSeriesResult[];
  bucket_requested: string;
  truncated: boolean;
}

export const api = {
  version: () => request<{ version: string }>("/api/version"),
  datasets: () => request<DatasetInfo[]>("/api/datasets"),
  dataset: (name: string) => request<DatasetInfo>(`/api/datasets/${encodeURIComponent(name)}`),
  stats: (name: string) => request<StorageStats>(`/api/stats/${encodeURIComponent(name)}`),
  deleteDatasetData: (name: string) =>
    request<{ dataset: string; deleted: boolean; freed_bytes: number }>(
      `/api/datasets/${encodeURIComponent(name)}/data`,
      { method: "DELETE" },
    ),
  settings: () => request<UserSettings>("/api/settings"),
  saveSettings: (body: Partial<UserSettings>) =>
    request<UserSettings>("/api/settings", { method: "POST", body: JSON.stringify(body) }),
  validatePath: (path: string) =>
    request<PathValidation>(
      `/api/settings/validate-path?path=${encodeURIComponent(path)}`,
    ),
  pickDirectory: () => request<PathValidation>("/api/settings/pick-directory", { method: "POST" }),
  estimate: (body: {
    dataset: string;
    variables: string[];
    start_date: string;
    end_date?: string | null;
    area: [number, number, number, number];
    hours: string[];
    max_request_bytes?: number;
    clip_regions?: string[] | null;
  }) => request<EstimateResult>("/api/pipeline/estimate", { method: "POST", body: JSON.stringify(body) }),
  startRun: (body: {
    dataset: string;
    variables: string[];
    start_date: string;
    end_date?: string | null;
    area: [number, number, number, number];
    hours: string[];
    clip_regions?: string[] | null;
  }) =>
    request<{ run_id: string; dataset: string; status: string }>(
      "/api/pipeline/run",
      { method: "POST", body: JSON.stringify(body) },
    ),
  query: (
    body: { dataset?: string; sql: string; limit?: number },
    signal?: AbortSignal,
  ) =>
    request<{
      columns: string[];
      column_types: string[];
      rows: (string | number | null)[][];
      row_count: number;
      truncated: boolean;
      total_rows: number;
      elapsed_ms: number;
    }>("/api/query", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  cancelQuery: () =>
    request<{ ok: boolean }>("/api/query/cancel", { method: "POST" }),
  querySchema: (dataset: string) =>
    request<QuerySchema>(
      `/api/query/schema?dataset=${encodeURIComponent(dataset)}`,
    ),
  exportQuery: async (fmt: "csv" | "parquet", sql: string) => {
    const r = await fetch(`/api/export/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql }),
    });
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try {
        const j = await r.json();
        if (j.detail) detail = String(j.detail);
      } catch {
        // ignore
      }
      throw new Error(detail);
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `query-export.${fmt}`;
    a.click();
    URL.revokeObjectURL(url);
  },
  regions: {
    uf: () => request<UfBbox[]>("/api/regions/uf"),
    clipAvailable: (dataset: string) =>
      request<{ regions: string[] }>(
        `/api/regions/clip-available?dataset=${encodeURIComponent(dataset)}`,
      ),
    ufCellCounts: (dataset: string) =>
      request<Record<string, number>>(
        `/api/regions/uf-cell-counts?dataset=${encodeURIComponent(dataset)}`,
      ),
  },
  queryTemplates: () => request<TemplateItem[]>("/api/query/templates"),
  userViews: {
    list: () => request<UserObject[]>("/api/user-views"),
    create: (b: UserObjectBody) =>
      request<UserObject>("/api/user-views", {
        method: "POST",
        body: JSON.stringify(b),
      }),
    update: (id: string, b: UserObjectBody) =>
      request<UserObject>(`/api/user-views/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify(b),
      }),
    del: (id: string) =>
      request<{ ok: boolean }>(
        `/api/user-views/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      ),
    preview: (b: { name: string; kind: string; sql: string }) =>
      request<UserObjectPreview>("/api/user-views/preview", {
        method: "POST",
        body: JSON.stringify(b),
      }),
    buildSql: (spec: BuildSpec) =>
      request<{ sql: string }>("/api/user-views/build-sql", {
        method: "POST",
        body: JSON.stringify(spec),
      }),
  },
  queryHistory: {
    list: (view: string) =>
      request<QueryHistoryEntry[]>(
        `/api/query/history/${encodeURIComponent(view)}`,
      ),
    append: (
      view: string,
      entry: { sql: string; rows?: number; elapsed_ms?: number },
    ) =>
      request<QueryHistoryEntry[]>(
        `/api/query/history/${encodeURIComponent(view)}`,
        { method: "POST", body: JSON.stringify(entry) },
      ),
    patch: (
      view: string,
      id: string,
      patch: { name?: string | null; favorite?: boolean },
    ) =>
      request<QueryHistoryEntry[]>(
        `/api/query/history/${encodeURIComponent(view)}/${encodeURIComponent(id)}`,
        { method: "PATCH", body: JSON.stringify(patch) },
      ),
    del: (view: string, id: string) =>
      request<QueryHistoryEntry[]>(
        `/api/query/history/${encodeURIComponent(view)}/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      ),
    clear: (view: string) =>
      request<QueryHistoryEntry[]>(
        `/api/query/history/${encodeURIComponent(view)}`,
        { method: "DELETE" },
      ),
  },
  precision: {
    get: (dataset: string) =>
      request<PrecisionConfig>(
        `/api/settings/precision?dataset=${encodeURIComponent(dataset)}`,
      ),
    save: (body: PrecisionConfig) =>
      request<PrecisionConfig>("/api/settings/precision", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },
  credentialStatus: () => request<CredentialStatus>("/api/credentials/status"),
  saveCredentials: (body: { url: string; key: string }) =>
    request<CredentialStatus>("/api/credentials", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  testCredentials: () =>
    request<CredentialTestResult>("/api/credentials/test", { method: "POST" }),

  inventory: {
    dateRange: (dataset: string) =>
      request<{ min: string | null; max: string | null }>(
        `/api/inventory/date-range?dataset=${encodeURIComponent(dataset)}`,
      ),
    gridPoints: (params: {
      dataset: string;
      date_from?: string;
      date_to?: string;
      variable?: string[];
      hour?: number[];
      format?: "json" | "arrow" | "auto";
    }) => {
      const q = new URLSearchParams({ dataset: params.dataset });
      if (params.date_from) q.set("date_from", params.date_from);
      if (params.date_to) q.set("date_to", params.date_to);
      if (params.variable) {
        for (const v of params.variable) q.append("variable", v);
      }
      if (params.hour) {
        for (const h of params.hour) q.append("hour", String(h));
      }
      if (params.format) q.set("format", params.format);
      return requestArrowOrJson<GridPoint>(`/api/inventory/grid-points?${q}`);
    },
    cellDetail: (params: { dataset: string; lat: number; lon: number }) => {
      const q = new URLSearchParams({
        dataset: params.dataset,
        lat: String(params.lat),
        lon: String(params.lon),
      });
      return request<CellDetail>(`/api/inventory/cell-detail?${q}`);
    },
    regionSummary: (body: { dataset: string; polygon: [number, number][] }) =>
      request<RegionSummary>("/api/inventory/region-summary", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    // Station sources (INMET): list stations as map points. The grid
    // endpoints above do not apply (no regular lat/lon grid).
    stations: (dataset: string) =>
      request<StationInventory>(
        `/api/inventory/stations?dataset=${encodeURIComponent(dataset)}`,
      ),
  },

  diffPreview: (body: {
    dataset: string;
    area: [number, number, number, number];
    date_from: string;
    date_to: string;
    hours: number[];
    variables: string[];
  }) =>
    request<DiffPreview>("/api/pipeline/diff-preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  startRunWithDiff: (body: {
    dataset: string;
    variables: string[];
    start_date: string;
    end_date?: string | null;
    area: [number, number, number, number];
    hours: string[];
    apply_diff: boolean;
    clip_regions?: string[] | null;
  }) =>
    request<{ run_id: string; dataset: string; status: string }>(
      "/api/pipeline/run",
      { method: "POST", body: JSON.stringify(body) },
    ),

  // INMET (station source) dedicated flow. The ERA5 wizard's
  // estimate/diff/area/variables don't apply: pick years + run.
  // The /api/pipeline/run orchestrator auto-bootstraps ERA5/ERA5-LAND
  // when they are missing — the SPA does NOT need to gate on a
  // prerequisite call any more.
  inmet: {
    years: () => request<{ years: number[] }>("/api/inmet/years"),
    yearStatus: () =>
      request<{
        items: Array<{
          year: number;
          status: "complete" | "partial" | "stale" | "current";
          n_stations: number;
          n_stations_complete: number;
          min_date_max: string | null;
          max_date_max: string | null;
          downloaded_at: string | null;
        }>;
        current_year: number;
        expected_publish_lag_days: number;
      }>("/api/inmet/year-status"),
    updateYears: (years: number[]) =>
      request<{ run_id: string; dataset: string; status: string }>(
        "/api/inmet/update-years",
        {
          method: "POST",
          body: JSON.stringify({ years }),
        },
      ),
    run: (years: number[]) =>
      request<{ run_id: string; dataset: string; status: string }>(
        "/api/pipeline/run",
        {
          method: "POST",
          body: JSON.stringify({
            dataset: "inmet",
            years,
            variables: [],
            start_date: `${Math.min(...years)}-01-01`,
            end_date: `${Math.max(...years)}-12-31`,
            area: [0, 0, 0, 0],
            hours: [],
            apply_diff: false,
          }),
        },
      ),
  },

  timeseries: {
    meta: () => request<TimeseriesMeta>("/api/timeseries/meta"),
    run: (body: TimeseriesRequest) =>
      request<TimeseriesResponse>("/api/timeseries", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },

  notebooks: {
    list: () => request<NotebookListItem[]>("/api/notebooks"),
    get: (id: string) => request<Notebook>(`/api/notebooks/${id}`),
    create: (body: { name?: string; template_id?: string | null }) =>
      request<Notebook>("/api/notebooks", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    save: (id: string, body: { name?: string; cells?: NotebookCell[] }) =>
      request<Notebook>(`/api/notebooks/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      request<{ deleted: boolean }>(`/api/notebooks/${id}`, {
        method: "DELETE",
      }),
    templates: () =>
      request<Array<{ id: string; name: string; description: string }>>(
        "/api/notebooks/templates",
      ),
    kernel: {
      status: (id: string) =>
        request<{ notebook_id: string; status: KernelStatus }>(
          `/api/notebooks/${id}/kernel/status`,
        ),
      restart: (id: string) =>
        request<{ notebook_id: string; status: KernelStatus }>(
          `/api/notebooks/${id}/kernel/restart`,
          { method: "POST" },
        ),
      stop: (id: string) =>
        request<{ notebook_id: string; status: KernelStatus }>(
          `/api/notebooks/${id}/kernel`,
          { method: "DELETE" },
        ),
    },
  },
};

// ---------------------------------------------------------------------------
// Notebook types
// ---------------------------------------------------------------------------

export type KernelStatus = "idle" | "busy" | "dead";

export type CellOutput =
  | { type: "stream"; name: "stdout" | "stderr"; text: string }
  | {
      type: "display";
      mime:
        | "application/vnd.dataframe+json"
        | "application/vnd.plotly.v1+json"
        | "text/plain";
      data: unknown;
    }
  | { type: "error"; ename: string; evalue: string; traceback: string[] };

export type NotebookCell = {
  id: string;
  type: "code" | "sql" | "markdown";
  source: string;
  outputs?: CellOutput[];
};

export type NotebookRun = {
  id: string;
  ts: number;
  model_name: string;
  params: Record<string, unknown>;
  metrics: Record<string, unknown>;
  duration_s: number;
  notes: string;
};

export type Notebook = {
  id: string;
  name: string;
  cells: NotebookCell[];
  runs: NotebookRun[];
  created_ts: number;
  updated_ts: number;
};

export type NotebookListItem = {
  id: string;
  name: string;
  updated_ts: number;
  created_ts: number;
  n_cells: number;
};

/**
 * Stream a cell execution via SSE. Returns a `cancel` function that closes
 * the EventSource on the client (the kernel keeps running until its current
 * cell finishes — there is no abort mid-cell on the server side yet).
 */
export function streamRunCell(
  notebookId: string,
  cellId: string,
  code: string,
  lang: "python" | "sql",
  onEvent: (ev: { type: string; data: unknown }) => void,
  onDone: () => void,
): () => void {
  // SSE clients only support GET. We POST first to start, but FastAPI's
  // EventSourceResponse on POST also works with EventSource via fetch +
  // ReadableStream. To keep it simple we use fetch streaming here.
  const controller = new AbortController();
  (async () => {
    try {
      const resp = await fetch(`/api/notebooks/${notebookId}/run-cell`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ cell_id: cellId, code, lang }),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        const text = await resp.text();
        onEvent({ type: "error", data: { ename: "HTTPError", evalue: text, traceback: [] } });
        onDone();
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "message";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const data = line.slice(5).trim();
            try {
              onEvent({ type: currentEvent, data: JSON.parse(data) });
            } catch {
              onEvent({ type: currentEvent, data });
            }
            if (currentEvent === "done") {
              onDone();
              return;
            }
          }
        }
      }
      onDone();
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onEvent({
          type: "error",
          data: { ename: "FetchError", evalue: (err as Error).message, traceback: [] },
        });
      }
      onDone();
    }
  })();
  return () => controller.abort();
}
