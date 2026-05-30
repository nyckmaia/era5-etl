# Design — Notebook cache management in /settings

**Date:** 2026-05-30
**Branch:** `feat/notebook-cache-load-logging` (continues the notebook-cache feature)
**Scope:** A new *Notebook cache* section on the `/settings` page that lists the
Parquet caches produced by `/notebooks` runs, grouped per notebook, showing
per-file / per-notebook subtotal / grand-total sizes, with delete at three
levels (one file, one notebook's caches, everything). Requires a small change
to where the notebook cache cell writes files so caches are attributable to a
notebook.

## Problem

The notebook cache (added earlier on this branch) writes Parquet files to a
single flat `<data_dir>/_nb_cache/` directory keyed only by
`(station, start, end)`. There is no UI to inspect or clear it, and the files
carry no notebook ownership, so they cannot be grouped or cleared per notebook.

## Goals

- Settings UI to **see** every notebook cache file with its size, plus a
  per-notebook **subtotal** and a **grand total**.
- **Delete** at three levels: a single file, all of one notebook's caches, and
  everything at once.
- Caches **grouped per notebook**, with a fallback group for orphans (caches of
  deleted notebooks and pre-existing flat-layout files).

## Non-goals

- No automatic eviction / TTL / size cap. Deletion is user-initiated only.
- No change to the cache *semantics* (freshness check, `__last_load_info__`,
  query version) beyond the directory layout.
- No cross-notebook cache sharing (explicitly traded away — see Decisions).

## Decisions (from brainstorming)

| Topic | Decision |
|-------|----------|
| Cache layout | Per-notebook subdir: `<data_dir>/_nb_cache/<notebook_id>/<file>.parquet`, using `ERA5_NB_ID`. Empty id → `_nb_cache/_unknown/`. |
| Delete levels | File + notebook + clear-all. |
| Orphans | Show an "Orphans / unknown" group (caches with no matching notebook, plus old flat-layout files at the `_nb_cache/` root). |

Trade-off accepted: two notebooks with identical parameters keep separate copies
(no sharing) in exchange for per-notebook isolation and cleanup.

## Architecture

```
Notebook cell (template + migration)   writes -> <data_dir>/_nb_cache/<notebook_id>/*.parquet
web/notebook_cache.py  (NEW)           scan + delete logic (pure, unit-testable)
web/routes/settings.py                 4 endpoints (list + 3 deletes)
web/models/__init__.py                 response models
web-ui/src/lib/api.ts                  api.nbCache.{list,deleteFile,deleteNotebook,clearAll}
web-ui/src/pages/Settings.tsx          NotebookCacheSection component
web-ui/src/i18n/locales/{pt,en}.ts     labels
```

## Component 1 — Cache layout change (prerequisite)

In the cache cell `load_inmet_with_cache`, `_nb_cache_dir()` becomes:

```python
def _nb_cache_dir():
    base = os.environ.get("ERA5_NB_DATA_DIR", ".")
    nb_id = os.environ.get("ERA5_NB_ID") or "_unknown"
    d = os.path.join(base, "_nb_cache", nb_id)
    os.makedirs(d, exist_ok=True)
    return d
```

`ERA5_NB_ID` is already injected into every kernel
(`kernel_manager.py` sets it). No `_CACHE_QUERY_VERSION` bump is needed: the
path changed, so any files written by the previous flat layout simply become
orphans surfaced under the "Orphans" group. Applies to both the template JSON
and the migration of the saved notebook.

## Component 2 — Backend (`web/notebook_cache.py` + routes)

New module `web/notebook_cache.py`:

- `CACHE_DIRNAME = "_nb_cache"`.
- `cache_root(data_dir) -> Path` = `data_dir / _nb_cache`.
- `scan(data_dir, notebook_names: dict[str,str]) -> dict` returns:
  ```python
  {
    "groups": [
      {
        "notebook_id": str,          # subdir name, or "_root" for loose files
        "notebook_name": str | None, # from notebook_names, else None
        "is_orphan": bool,           # True if no matching notebook
        "subtotal_bytes": int,
        "files": [
          {"name": str, "rel_path": str, "size_bytes": int, "modified_ts": int}
        ],
      }
    ],
    "total_bytes": int,
  }
  ```
  - Each immediate subdirectory of `_nb_cache/` is a group keyed by its name.
  - `*.parquet` files directly under `_nb_cache/` (old flat layout) form a
    synthetic group `notebook_id="_root"`, `is_orphan=True`.
  - `is_orphan = notebook_id not in notebook_names` (the `_unknown`/`_root`
    groups are always orphans).
  - `rel_path` is POSIX-style relative to `_nb_cache/` (e.g.
    `<id>/inmet_era5land__A001__...__v2.parquet` or
    `inmet_era5land__...parquet` for root files).
  - Groups sorted by `subtotal_bytes` desc; files within a group by
    `size_bytes` desc.
- `delete_file(data_dir, rel_path) -> int` (returns freed bytes). **Path-safety:**
  resolve `(_nb_cache / rel_path)` and assert it is inside `_nb_cache/` via
  `Path.resolve()` + `is_relative_to`; reject otherwise (`ValueError`). Only
  deletes regular files.
- `delete_notebook(data_dir, notebook_id) -> int`: validate `notebook_id`
  contains no path separators / `..`; remove the subdir (or, for `"_root"`,
  remove only the loose `*.parquet` files at the root, not subdirs). Returns
  freed bytes.
- `clear_all(data_dir) -> int`: remove the entire `_nb_cache/` tree; return
  freed bytes.

Routes in `web/routes/settings.py` (data_dir from `request.app.state.data_dir`):

- `GET /api/settings/nb-cache` → `NotebookCacheOut`. Builds `notebook_names`
  from `notebook_store.list_notebooks()` (`{id: name}`).
- `DELETE /api/settings/nb-cache/file?path=<rel_path>` → `{deleted, freed_bytes}`.
  `ValueError` from path-safety → HTTP 400.
- `DELETE /api/settings/nb-cache/notebook/{notebook_id}` → `{deleted, freed_bytes}`.
- `DELETE /api/settings/nb-cache` → `{deleted, freed_bytes}` (clear all).

All wrap I/O errors as HTTP 500 with detail; never crash the app. Deleting a
missing target returns `{deleted: false, freed_bytes: 0}`.

### Models (`web/models/__init__.py`)

```python
class NotebookCacheFileOut(BaseModel):
    name: str
    rel_path: str
    size_bytes: int
    modified_ts: int

class NotebookCacheGroupOut(BaseModel):
    notebook_id: str
    notebook_name: str | None
    is_orphan: bool
    subtotal_bytes: int
    files: list[NotebookCacheFileOut]

class NotebookCacheOut(BaseModel):
    groups: list[NotebookCacheGroupOut]
    total_bytes: int

class CacheDeleteOut(BaseModel):
    deleted: bool
    freed_bytes: int
```

## Component 3 — Frontend (`NotebookCacheSection` in Settings.tsx)

`api.ts` additions:

```ts
nbCache: {
  list: () => request<NotebookCache>("/api/settings/nb-cache"),
  deleteFile: (relPath: string) =>
    request<CacheDelete>(`/api/settings/nb-cache/file?path=${encodeURIComponent(relPath)}`, { method: "DELETE" }),
  deleteNotebook: (id: string) =>
    request<CacheDelete>(`/api/settings/nb-cache/notebook/${encodeURIComponent(id)}`, { method: "DELETE" }),
  clearAll: () =>
    request<CacheDelete>("/api/settings/nb-cache", { method: "DELETE" }),
}
```

with TS types `NotebookCache`, `NotebookCacheGroup`, `NotebookCacheFile`,
`CacheDelete`.

`NotebookCacheSection` (placed above `DangerZoneSection`):

- Query `["nb-cache"]` → `api.nbCache.list`.
- Header: title + grand total via `formatBytes(total_bytes)`; a **Clear all**
  button (guarded by a `confirm()`), disabled when there are no groups.
- One card per group, sorted by subtotal desc:
  - title = `notebook_name` or, when `is_orphan`, the i18n "Orphans / unknown"
    label (append the raw id for `_unknown`/`_root`);
  - `formatBytes(subtotal_bytes)` beside the title;
  - a trash button deleting the whole group (`deleteNotebook(notebook_id)`).
  - file rows: name, `formatBytes(size_bytes)`, `new Date(modified_ts*1000).toLocaleString()`,
    and a per-file trash button (`deleteFile(rel_path)`).
- Empty state: "No notebook cache yet."
- Each mutation invalidates `["nb-cache"]` and toasts freed space (mirrors
  `DeleteDatasetRow`).

Sizes are shown at all three requested levels: **per file**, **per-notebook
subtotal**, **grand total**.

## Error handling

- Backend path-safety rejects traversal (`..`, absolute, escaping `_nb_cache/`)
  with HTTP 400; nonexistent targets return `deleted:false`.
- Missing `_nb_cache/` dir → `scan` returns empty groups, `total_bytes:0`.
- Frontend mutations show an error toast on failure; the list refetches.

## Testing / verification

- `tests/test_notebook_cache.py` (new): build a fake `_nb_cache/` tree (a named
  notebook subdir, an `_unknown` subdir, a loose root file); assert `scan`
  grouping/subtotals/total and orphan flags; assert `delete_file`,
  `delete_notebook`, `clear_all` free the right bytes; assert path-traversal
  `rel_path` raises `ValueError`.
- Route smoke tests via FastAPI `TestClient` (list + each delete), pointing
  `app.state.data_dir` at a tmp dir.
- `npx tsc --noEmit`; `npm run build`.
- Idempotent migration of the saved XGBoost notebook to the new cache-cell
  body (per-notebook subdir), with `.bak` backup.

## Appendix — file naming recap

Cache filename is unchanged:
`inmet_era5land__<station>__<start>__<end>__v<N>.parquet`; only its parent
directory gains the `<notebook_id>/` level.
