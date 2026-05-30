# Notebook Data Cache + Load-Source Logging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a transparent on-disk Parquet cache to the `/notebooks` XGBoost example, auto-log the load source/duration into *Model runs*, fix `n_test` rendering, and optimize cell #4's query with bilinear features.

**Architecture:** All runtime logic lives **inside notebook cells** (template JSON + a migration of the already-saved notebook) so the user can read and edit it — no new backend Python module. Only the *Model runs* renderer (`ModelRunsPanel.tsx`) and two i18n files change in the SPA.

**Tech Stack:** Python 3.12 notebook kernel (pandas, pyarrow/Parquet, DuckDB), React/TanStack SPA (TypeScript), Vite, i18next. Build via `npm run build`; tests via `py -3.12 -m pytest`.

**Testability note:** Notebook-cell code runs in a per-notebook subprocess against real ERA5/INMET parquet that the test environment does not have, so cell bodies cannot be unit-tested by import. The verifiable gates here are: template **JSON validity**, the existing **kernel smoke tests** (`tests/test_notebook_kernel.py`), **`tsc --noEmit`**, **`npm run build`**, and an **idempotent migration** of the saved notebook with a `.bak` backup. Frontend logic that *can* be isolated (the metric-formatting/column-split) is covered by reasoning + tsc; there is no jest harness in this repo (confirmed: only `pytest`), so we do not invent one.

**Cell numbering (1-based, as the user refers to them):**
- #4 = template cell index **3** = `def inmet_with_era5_land(...)` helper
- #6 = template cell index **5** = `def log_model_run(...)` helper
- #7 = template cell index **6** = the Load cell (`df = inmet_with_era5_land(...)`)
- #9 = template cell index **8** = feature engineering (`feature_cols`, `.describe()`)

---

## File Structure

- **Modify** `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`
  - cell #4 (idx 3): optimized SQL + bilinear columns
  - cell #6 (idx 5): `log_model_run` reads `__last_load_info__`
  - NEW cell after #4 (idx 4): inline `bilinear_weights` + cache note? → No; cache helper goes with the Load section. Bilinear lives in the #4 helper. (No new cell added; we edit existing cells in place.)
  - cell #7 (idx 6): define `load_inmet_with_cache(...)` and call it
  - cell #9 (idx 8): add bilinear feature(s) to `feature_cols`
- **Modify** `web-ui/src/components/notebooks/ModelRunsPanel.tsx` — Load / Load time columns; integer-safe metric formatting
- **Modify** `web-ui/src/i18n/locales/pt.ts` and `en.ts` — column labels
- **Create (temp, not committed)** a one-off migration run that updates `%APPDATA%/era5-etl/notebooks/<id>.json` (executed inline via `py -3.12 - <<PY`, with `.bak` backup; no script file left in the repo)

---

## Task 1: Optimize cell #4 (`inmet_with_era5_land`) — date + bbox pre-filter, keep corners, add bilinear

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` (cell index 3)

- [ ] **Step 1: Replace cell #4 (index 3) `source` with the optimized helper (bilinear computed in a CTE)**

Set the JSON `source` of cell index 3 to exactly this Python text:

```python
# --- Helper: load INMET joined with the 4 surrounding ERA5-LAND cells ---
# Defined here (not hidden inside the app) so you can read and edit the join.
#
# Performance: era5_land is bounded by date AND a lat/lon bounding box BEFORE
# the corner join (tile-sorted parquet + row-group pruning). Float32 coords
# never compare exactly equal, so each corner is matched with abs(diff) < 1e-4
# (never `=`). Use column `station_id` (not `station`).
#
# Returns the 4 raw corner temperatures (…_tl/_tr/_bl/_br) AND a bilinearly
# interpolated temperature (era5_land_temp_bilinear): a weighted average of the
# 4 corners by the station's position inside the cell.
import pandas as pd  # noqa: F401


def inmet_with_era5_land(station_id, start, end):
    sql = """
    WITH inmet_rows AS (
        SELECT *
        FROM inmet
        WHERE station_id = ?
          AND date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    ),
    el AS (
        SELECT el.*
        FROM era5_land el, (SELECT * FROM inmet_rows LIMIT 1) s
        WHERE el.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
          AND el.latitude  BETWEEN s.era5_land_lat_bottom - 1e-4
                               AND s.era5_land_lat_top    + 1e-4
          AND el.longitude BETWEEN s.era5_land_lon_left   - 1e-4
                               AND s.era5_land_lon_right  + 1e-4
    ),
    joined AS (
        SELECT
            i.*,
            tl.temperature_2m AS era5_land_temp_tl,
            tr.temperature_2m AS era5_land_temp_tr,
            bl.temperature_2m AS era5_land_temp_bl,
            br.temperature_2m AS era5_land_temp_br,
            (i.longitude - i.era5_land_lon_left)
                / NULLIF(i.era5_land_lon_right - i.era5_land_lon_left, 0) AS wx,
            (i.era5_land_lat_top - i.latitude)
                / NULLIF(i.era5_land_lat_top - i.era5_land_lat_bottom, 0) AS wy
        FROM inmet_rows i
        LEFT JOIN el tl
            ON tl.date = i.date AND tl.hour_utc = i.hour_utc
           AND abs(tl.latitude  - i.era5_land_lat_top)    < 1e-4
           AND abs(tl.longitude - i.era5_land_lon_left)   < 1e-4
        LEFT JOIN el tr
            ON tr.date = i.date AND tr.hour_utc = i.hour_utc
           AND abs(tr.latitude  - i.era5_land_lat_top)    < 1e-4
           AND abs(tr.longitude - i.era5_land_lon_right)  < 1e-4
        LEFT JOIN el bl
            ON bl.date = i.date AND bl.hour_utc = i.hour_utc
           AND abs(bl.latitude  - i.era5_land_lat_bottom) < 1e-4
           AND abs(bl.longitude - i.era5_land_lon_left)   < 1e-4
        LEFT JOIN el br
            ON br.date = i.date AND br.hour_utc = i.hour_utc
           AND abs(br.latitude  - i.era5_land_lat_bottom) < 1e-4
           AND abs(br.longitude - i.era5_land_lon_right)  < 1e-4
    )
    SELECT
        * EXCLUDE (wx, wy),
        era5_land_temp_tl * (1.0 - wx) * (1.0 - wy)
        + era5_land_temp_tr * wx * (1.0 - wy)
        + era5_land_temp_bl * (1.0 - wx) * wy
        + era5_land_temp_br * wx * wy AS era5_land_temp_bilinear
    FROM joined
    ORDER BY date, hour_utc
    """
    return con.execute(sql, [station_id, start, end, start, end]).df()


print("inmet_with_era5_land() defined — date+bbox pre-filtered, with bilinear.")
```

- [ ] **Step 2: Validate the template JSON parses**

Run:
```bash
py -3.12 -c "import json; json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); print('JSON OK')"
```
Expected: `JSON OK`

- [ ] **Step 3: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): optimize inmet_with_era5_land (date+bbox pre-filter, bilinear)"
```

---

## Task 2: Cell #7 — `load_inmet_with_cache` (Parquet cache + freshness) and use it

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` (cell index 6)

- [ ] **Step 1: Replace cell #7 (index 6) `source` with the cache wrapper + call**

```python
# --- Load (cached): INMET joined with the 4 surrounding ERA5-LAND cells ---
# load_inmet_with_cache() wraps inmet_with_era5_land() with a transparent
# on-disk Parquet cache under <data_dir>/_nb_cache/. Re-running with the SAME
# (station, start, end) reads the cached parquet instead of re-querying DuckDB.
# The cache is invalidated automatically when any source parquet (this
# station's INMET file, or any era5-land file) is newer than the cache file,
# so a fresh download is never served stale. Edit freely — it's plain Python.
import os
import glob
import time

# Bump if you change the inmet_with_era5_land() SQL, to invalidate old caches.
_CACHE_QUERY_VERSION = 2

# Records how the LAST load happened so log_model_run() can report it.
__last_load_info__ = {"source": "unknown", "duration_s": 0.0}


def _nb_cache_dir():
    base = os.environ.get("ERA5_NB_DATA_DIR", ".")
    d = os.path.join(base, "_nb_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _newest_source_mtime(station_id):
    # Newest mtime among this station's INMET parquet and all era5-land parquet.
    base = os.environ.get("ERA5_NB_DATA_DIR", ".")
    db = os.path.join(base, "climate_data_store_db")
    patterns = [
        os.path.join(db, "inmet", f"station={station_id}", "*.parquet"),
        os.path.join(db, "era5-land", "**", "*.parquet"),
    ]
    newest = 0.0
    for pat in patterns:
        for f in glob.glob(pat, recursive=True):
            try:
                newest = max(newest, os.path.getmtime(f))
            except OSError:
                pass
    return newest


def load_inmet_with_cache(station_id, start, end):
    global __last_load_info__
    fname = (
        f"inmet_era5land__{station_id}__{start}__{end}"
        f"__v{_CACHE_QUERY_VERSION}.parquet"
    )
    cache_path = os.path.join(_nb_cache_dir(), fname)

    fresh = False
    if os.path.exists(cache_path):
        try:
            fresh = os.path.getmtime(cache_path) > _newest_source_mtime(station_id)
        except OSError:
            fresh = False

    t0 = time.perf_counter()
    if fresh:
        try:
            df = pd.read_parquet(cache_path)
            __last_load_info__ = {
                "source": "csv cache",
                "duration_s": time.perf_counter() - t0,
            }
            print(f"Loaded {len(df):,} rows from cache: {fname}")
            return df
        except Exception as exc:  # corrupt/unreadable cache -> rebuild
            print(f"Cache unreadable ({exc}); rebuilding from DB.")

    df = inmet_with_era5_land(station_id, start, end)
    __last_load_info__ = {
        "source": "db query",
        "duration_s": time.perf_counter() - t0,
    }
    try:
        df.to_parquet(cache_path, index=False)
        print(f"Loaded {len(df):,} rows from DB; cached to {fname}")
    except Exception as exc:  # caching is best-effort, never fatal
        print(f"Loaded {len(df):,} rows from DB; cache write failed ({exc}).")
    return df


df = load_inmet_with_cache(STATION_ID, DATE_START, DATE_END)
print(f"load_source={__last_load_info__['source']}, "
      f"load_duration_s={__last_load_info__['duration_s']:.3f}")
df.head()
```

- [ ] **Step 2: Validate the template JSON parses**

Run:
```bash
py -3.12 -c "import json; json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); print('JSON OK')"
```
Expected: `JSON OK`

- [ ] **Step 3: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): add Parquet cache wrapper load_inmet_with_cache"
```

---

## Task 3: Cell #6 — `log_model_run` auto-records load source/duration

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` (cell index 5)

- [ ] **Step 1: Replace cell #6 (index 5) `source` so it reads `__last_load_info__`**

```python
# --- Helper: log this run to the notebook's "Model runs" panel -------
# Posts a JSON record back to the FastAPI server. The per-kernel callback URL
# and auth token are provided to the kernel as environment variables.
# It also auto-attaches how the data was loaded for this run (db query vs
# csv cache) and how long that load took, read from __last_load_info__ which
# load_inmet_with_cache() sets. Your call below does not need to change.
import os
import json
import urllib.request


def log_model_run(params, metrics, duration_s, notes="", model_name="xgboost"):
    runs_url = os.environ["ERA5_NB_RUNS_URL"]
    runs_token = os.environ["ERA5_NB_RUNS_TOKEN"]

    # Auto-attach data-load provenance for this run, if available.
    info = globals().get(
        "__last_load_info__", {"source": "unknown", "duration_s": 0.0}
    )
    metrics = dict(metrics)
    metrics.setdefault("load_source", info.get("source", "unknown"))
    metrics.setdefault("load_duration_s", float(info.get("duration_s", 0.0)))

    def _coerce(d):
        # Coerce numpy scalars etc. to plain JSON-serialisable values.
        out = {}
        for k, v in d.items():
            try:
                json.dumps(v)
                out[str(k)] = v
            except TypeError:
                out[str(k)] = v.item() if hasattr(v, "item") else repr(v)
        return out

    body = json.dumps({
        "params": _coerce(params),
        "metrics": _coerce(metrics),
        "duration_s": float(duration_s),
        "notes": str(notes),
        "model_name": str(model_name),
    }).encode("utf-8")
    req = urllib.request.Request(
        runs_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Notebook-Token": runs_token},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


print("log_model_run() defined (auto-logs load_source + load_duration_s).")
```

- [ ] **Step 2: Validate JSON parses**

Run:
```bash
py -3.12 -c "import json; json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); print('JSON OK')"
```
Expected: `JSON OK`

- [ ] **Step 3: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): log_model_run auto-records load source + duration"
```

---

## Task 4: Cell #9 — add bilinear feature to `feature_cols`

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` (cell index 8, feature engineering)

- [ ] **Step 1: Replace cell #9 (index 8) `source` to drop NA on + include the bilinear column**

```python
# --- Feature engineering -------------------------------------------
import pandas as pd

needed = [
    TARGET_VAR, "era5_land_temp_tl", "era5_land_temp_tr",
    "era5_land_temp_bl", "era5_land_temp_br", "era5_land_temp_bilinear",
]
df = df.dropna(subset=needed).copy()
df["date"] = pd.to_datetime(df["date"])
df["hour"] = df["hour_utc"].astype(int)
df["month"] = df["date"].dt.month
df["dayofyear"] = df["date"].dt.dayofyear

feature_cols = [
    "era5_land_temp_tl", "era5_land_temp_tr",
    "era5_land_temp_bl", "era5_land_temp_br",
    "era5_land_temp_bilinear",
    "hour", "month", "dayofyear", "altitude",
]
target_col = TARGET_VAR
# .describe() is indexed by the statistic name (count/mean/std/min/...).
# rename_axis("stat").reset_index() turns that index into a visible first
# column so the metric names show up in the rendered table.
df[feature_cols + [target_col]].describe().rename_axis("stat").reset_index()
```

- [ ] **Step 2: Validate JSON parses**

Run:
```bash
py -3.12 -c "import json; json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); print('JSON OK')"
```
Expected: `JSON OK`

- [ ] **Step 3: Update the Validate cell (#8, index 7) to also check the bilinear column**

Replace the `required_cols` list inside cell index 7 so the bilinear column is validated too. Change the list to:

```python
required_cols = [
    TARGET_VAR,
    "era5_land_temp_tl", "era5_land_temp_tr",
    "era5_land_temp_bl", "era5_land_temp_br",
    "era5_land_temp_bilinear",
]
```

(Leave the rest of cell index 7 unchanged.)

- [ ] **Step 4: Validate JSON parses**

Run:
```bash
py -3.12 -c "import json; json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); print('JSON OK')"
```
Expected: `JSON OK`

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): use bilinear temperature as an XGBoost feature"
```

---

## Task 5: Kernel smoke test still passes (template boots, helpers defined)

**Files:**
- Test: `tests/test_notebook_kernel.py` (existing; no change unless needed)

- [ ] **Step 1: Run the notebook test suites**

Run:
```bash
py -3.12 -m pytest tests/test_notebook_kernel.py tests/test_notebook_routes.py tests/test_notebook_store.py -q
```
Expected: `21 passed` (same count as before; these cover kernel boot/exec/state, not the template data path).

- [ ] **Step 2: If any test fails, STOP and fix the cause before continuing.**

No commit (verification-only task).

---

## Task 6: Model runs table — Load / Load time columns + integer-safe metrics

**Files:**
- Modify: `web-ui/src/components/notebooks/ModelRunsPanel.tsx`
- Modify: `web-ui/src/i18n/locales/pt.ts`
- Modify: `web-ui/src/i18n/locales/en.ts`

- [ ] **Step 1: Add i18n keys in `en.ts`** (inside `notebooks.runs.col`, after `duration`)

Find:
```ts
      col: {
        when: "When",
        model: "Model",
        duration: "Duration",
        notes: "Notes",
      },
```
Replace with:
```ts
      col: {
        when: "When",
        model: "Model",
        duration: "Duration",
        loadSource: "Load",
        loadTime: "Load time",
        notes: "Notes",
      },
```

- [ ] **Step 2: Add the matching keys in `pt.ts`** (same `notebooks.runs.col` block)

Find:
```ts
      col: {
        when: "Quando",
        model: "Modelo",
        duration: "Duração",
        notes: "Notas",
      },
```
Replace with:
```ts
      col: {
        when: "Quando",
        model: "Modelo",
        duration: "Duração",
        loadSource: "Carregamento",
        loadTime: "Tempo de carga",
        notes: "Notas",
      },
```

> NOTE: If the exact pt.ts strings differ, match the existing `when/model/duration/notes` lines verbatim and insert `loadSource`/`loadTime` before `notes`. Confirm with:
> `grep -n "col: {" -A6 web-ui/src/i18n/locales/pt.ts`

- [ ] **Step 3: In `ModelRunsPanel.tsx`, exclude the load keys from generic metric columns**

Find:
```ts
function metricKeys(runs: NotebookRun[]): string[] {
  const keys = new Set<string>();
  runs.forEach((r) => Object.keys(r.metrics ?? {}).forEach((k) => keys.add(k)));
  return Array.from(keys);
}
```
Replace with:
```ts
// Metrics rendered in their own dedicated columns, not the generic metric grid.
const LOAD_KEYS = new Set(["load_source", "load_duration_s"]);

function metricKeys(runs: NotebookRun[]): string[] {
  const keys = new Set<string>();
  runs.forEach((r) =>
    Object.keys(r.metrics ?? {}).forEach((k) => {
      if (!LOAD_KEYS.has(k)) keys.add(k);
    }),
  );
  return Array.from(keys);
}

// Format a metric value: integers without decimals, floats to 4 places.
function fmtMetric(v: unknown): string {
  if (typeof v !== "number") return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

// Read a run's load provenance with safe defaults for older runs.
function loadInfo(r: NotebookRun): { source: string; seconds: number | null } {
  const m = r.metrics ?? {};
  const src = typeof m.load_source === "string" ? m.load_source : "—";
  const sec =
    typeof m.load_duration_s === "number" ? m.load_duration_s : null;
  return { source: src, seconds: sec };
}
```

- [ ] **Step 4: Use `fmtMetric` in the metric cells**

Find:
```ts
                  {allKeys.map((k) => {
                    const v = r.metrics?.[k];
                    return (
                      <td key={k} className="px-2 py-1 text-right text-ink-600">
                        {typeof v === "number" ? v.toFixed(4) : "—"}
                      </td>
                    );
                  })}
```
Replace with:
```ts
                  {allKeys.map((k) => (
                    <td key={k} className="px-2 py-1 text-right text-ink-600">
                      {fmtMetric(r.metrics?.[k])}
                    </td>
                  ))}
```

- [ ] **Step 5: Add the two header cells (Load, Load time) after Duration**

Find:
```ts
              <th className="px-2 py-1 text-right font-medium text-ink-700">
                {t("notebooks.runs.col.duration")}
              </th>
              {allKeys.map((k) => (
```
Replace with:
```ts
              <th className="px-2 py-1 text-right font-medium text-ink-700">
                {t("notebooks.runs.col.duration")}
              </th>
              <th className="px-2 py-1 text-left font-medium text-ink-700">
                {t("notebooks.runs.col.loadSource")}
              </th>
              <th className="px-2 py-1 text-right font-medium text-ink-700">
                {t("notebooks.runs.col.loadTime")}
              </th>
              {allKeys.map((k) => (
```

- [ ] **Step 6: Add the two body cells (Load, Load time) after the Duration cell**

Find:
```ts
                  <td className="px-2 py-1 text-right text-ink-600">
                    {r.duration_s.toFixed(2)}s
                  </td>
                  {allKeys.map((k) => {
```
Replace with:
```ts
                  <td className="px-2 py-1 text-right text-ink-600">
                    {r.duration_s.toFixed(2)}s
                  </td>
                  <td className="px-2 py-1 text-ink-600">
                    {loadInfo(r).source}
                  </td>
                  <td className="px-2 py-1 text-right text-ink-600">
                    {loadInfo(r).seconds === null
                      ? "—"
                      : `${loadInfo(r).seconds!.toFixed(2)}s`}
                  </td>
                  {allKeys.map((k) => {
```

> NOTE: Step 4 already rewrote the `allKeys.map((k) => {…})` body block to the arrow-return form. Apply Step 6 to the line **preceding** that block (the Duration `<td>`). The `{allKeys.map((k) => {` anchor in Step 6 is the original text; if Step 4 was applied first, anchor on `{r.duration_s.toFixed(2)}s` + its closing `</td>` and insert the two new `<td>`s immediately after.

- [ ] **Step 7: Typecheck the SPA**

Run:
```bash
cd web-ui && npx tsc --noEmit
```
Expected: no output, exit 0.

- [ ] **Step 8: Build the SPA**

Run:
```bash
cd web-ui && NODE_OPTIONS="--use-system-ca" npm run build
```
Expected: `✓ built in …s`, exit 0; fresh `index-*.js`/`.css` under `src/era5_etl/web/static/assets/`.

- [ ] **Step 9: Commit**

```bash
git add web-ui/src/components/notebooks/ModelRunsPanel.tsx web-ui/src/i18n/locales/pt.ts web-ui/src/i18n/locales/en.ts src/era5_etl/web/static
git commit -m "feat(notebooks): Model runs Load/Load time columns; integer-safe metrics"
```

---

## Task 7: Migrate the already-saved XGBoost notebook to the new cells

**Files:**
- Modify (data, not repo): `%APPDATA%/era5-etl/notebooks/<id>.json` (idempotent, `.bak3` backup)

- [ ] **Step 1: Run the migration (replaces matching cells from the template by source-prefix)**

Run:
```bash
py -3.12 - <<'PY'
import json, glob, os, shutil
from importlib.resources import as_file, files
from era5_etl.web.user_config import _config_dir

res = files("era5_etl._data.notebook_templates").joinpath("xgboost_temperature_forecast.json")
with as_file(res) as f:
    tpl = json.load(open(f, encoding="utf-8"))

def tpl_src(prefix):
    for c in tpl["cells"]:
        if c.get("source", "").startswith(prefix):
            return c["source"]
    raise SystemExit(f"template cell not found: {prefix!r}")

# Map: source-prefix -> new source text (from the just-updated template).
REPLACEMENTS = {
    "# --- Helper: load INMET joined": tpl_src("# --- Helper: load INMET joined"),
    "# --- Helper: log this run":      tpl_src("# --- Helper: log this run"),
    "# --- Load":                      tpl_src("# --- Load"),
    "# --- Validate:":                 tpl_src("# --- Validate:"),
    "# --- Feature engineering":       tpl_src("# --- Feature engineering"),
}

nb = _config_dir() / "notebooks"
changed = 0
for path in sorted(glob.glob(str(nb / "*.json"))):
    d = json.load(open(path, encoding="utf-8"))
    cells = d.get("cells", [])
    name = d.get("name", "")
    uses = any("inmet_with_era5_land(" in (c.get("source") or "") for c in cells)
    if not (("xgboost" in name.lower()) or uses):
        print(f" - {os.path.basename(path)}: not XGBoost, skip"); continue
    shutil.copy2(path, path + ".bak3")
    hits = 0
    for c in cells:
        s = c.get("source") or ""
        for prefix, new_src in REPLACEMENTS.items():
            if s.startswith(prefix):
                c["source"] = new_src
                c["outputs"] = []          # stale outputs no longer match
                hits += 1
                break
    d["cells"] = cells
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    changed += 1
    print(f" - {os.path.basename(path)}: replaced {hits} cell(s); backup .bak3")
print("DONE. modified:", changed)
PY
```
Expected: `replaced 5 cell(s)` for the XGBoost notebook, `DONE. modified: 1`.

- [ ] **Step 2: Verify the saved notebook now has the cache + bilinear + load logging**

Run:
```bash
py -3.12 - <<'PY'
import json, glob, os
from era5_etl.web.user_config import _config_dir
nb = _config_dir() / "notebooks"
for p in sorted(glob.glob(str(nb / "*.json"))):
    if p.endswith(".bak") or p.endswith(".bak2") or p.endswith(".bak3"):
        continue
    d = json.load(open(p, encoding="utf-8")); cells = d.get("cells", [])
    j = "\n".join(c.get("source") or "" for c in cells)
    print(os.path.basename(p),
          "| cache:", "load_inmet_with_cache(" in j,
          "| bilinear:", "era5_land_temp_bilinear" in j,
          "| loadinfo:", "__last_load_info__" in j)
PY
```
Expected (for the XGBoost notebook): `cache: True | bilinear: True | loadinfo: True`.

No commit (this edits user data outside the repo).

---

## Task 8: Final verification sweep

- [ ] **Step 1: Template JSON valid**
```bash
py -3.12 -c "import json,glob; [json.load(open(f,encoding='utf-8')) for f in glob.glob('src/era5_etl/_data/notebook_templates/*.json')]; print('ALL TEMPLATES OK')"
```
Expected: `ALL TEMPLATES OK`

- [ ] **Step 2: Notebook tests green**
```bash
py -3.12 -m pytest tests/test_notebook_kernel.py tests/test_notebook_routes.py tests/test_notebook_store.py -q
```
Expected: `21 passed`

- [ ] **Step 3: SPA typecheck + build**
```bash
cd web-ui && npx tsc --noEmit && NODE_OPTIONS="--use-system-ca" npm run build
```
Expected: tsc exit 0; `✓ built in …s`.

- [ ] **Step 4: Confirm clean git state (only intended files changed)**
```bash
git status --short && git log --oneline -6
```
Expected: working tree clean (or only `static/` rebuild artifacts staged in Task 6's commit); commits for Tasks 1–4 and 6 present.

---

## Self-Review (filled in by plan author)

**Spec coverage:**
- Melhoria 01 (cache) → Task 2 ✓
- Melhoria 02 (log source+duration, show in table) → Task 3 (logging) + Task 6 (columns) ✓
- Melhoria 03 (`n_test` integer) → Task 6 Step 3/4 (`fmtMetric`) ✓
- Melhoria 04 (cell #4 correctness/perf + bilinear; parquet metadata report) → Task 1 + Task 4; the parquet-metadata answer is the spec Appendix (already delivered as a report, no code) ✓
- Saved-notebook migration → Task 7 ✓

**Placeholder scan:** None. Task 1 has a single authoritative cell body (the earlier skeleton draft was removed). Every code step contains complete, runnable content.

**Type/name consistency:** `__last_load_info__` (set in Task 2, read in Task 3) ✓; metric keys `load_source`/`load_duration_s` (written in Task 3, consumed in Task 6 via `LOAD_KEYS`/`loadInfo`) ✓; i18n keys `col.loadSource`/`col.loadTime` (added Task 6 Steps 1-2, used Steps 5) ✓; `era5_land_temp_bilinear` (produced Task 1, validated Task 4 Step 3, used Task 4 Step 1) ✓.

**Ambiguity:** Cell indices are pinned both by 1-based number and 0-based template index. Frontend find/replace anchors note the Step-4-then-Step-6 ordering interaction explicitly.
