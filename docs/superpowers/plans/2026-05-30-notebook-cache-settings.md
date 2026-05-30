# Notebook Cache Management in /settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a *Notebook cache* section to `/settings` that lists the Parquet caches produced by `/notebooks`, grouped per notebook, showing per-file / per-notebook-subtotal / grand-total sizes, with delete at three levels (file, notebook, all).

**Architecture:** A new pure module `web/notebook_cache.py` does the filesystem scan + safe delete; four routes in `web/routes/settings.py` expose it; the notebook cache cell is changed to write under `_nb_cache/<notebook_id>/` so caches are attributable; a `NotebookCacheSection` React component renders/manages it.

**Tech Stack:** Python 3.12 (FastAPI, pathlib, pytest + `TestClient`), React/TanStack Query + TypeScript SPA, Vite, i18next. Run Python with `py -3.12`; build SPA with `npm run build`.

**Branch:** `feat/notebook-cache-load-logging` (already checked out; do NOT create a new branch).

**Environment note:** This session's terminal sometimes delivers command output on a ~1-turn delay. If a command shows no output, run `echo done` and re-read rather than assuming failure or re-running destructive commands.

---

## File Structure

- **Create** `src/era5_etl/web/notebook_cache.py` — scan + delete logic (pure, unit-testable).
- **Modify** `src/era5_etl/web/models/__init__.py` — 4 Pydantic response models + `__all__`.
- **Modify** `src/era5_etl/web/routes/settings.py` — 4 endpoints.
- **Modify** `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json` — cache cell writes under `_nb_cache/<notebook_id>/`.
- **Create** `tests/test_notebook_cache.py` — module unit tests + route smoke tests.
- **Modify** `web-ui/src/lib/api.ts` — `api.nbCache.*` + types.
- **Modify** `web-ui/src/pages/Settings.tsx` — `NotebookCacheSection`.
- **Modify** `web-ui/src/i18n/locales/pt.ts` and `en.ts` — labels.
- **Migrate (data, not repo)** the saved XGBoost notebook to the new cache cell.

---

## Task 1: Backend cache module (`web/notebook_cache.py`)

**Files:**
- Create: `src/era5_etl/web/notebook_cache.py`
- Test: `tests/test_notebook_cache.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_notebook_cache.py`:

```python
"""Tests for the notebook-cache scan/delete helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from era5_etl.web import notebook_cache as nc


def _make_cache(tmp_path: Path) -> Path:
    root = tmp_path / "_nb_cache"
    # Named notebook subdir with two files.
    (root / "nbA").mkdir(parents=True)
    (root / "nbA" / "f1.parquet").write_bytes(b"x" * 100)
    (root / "nbA" / "f2.parquet").write_bytes(b"y" * 50)
    # _unknown subdir (always orphan).
    (root / "_unknown").mkdir()
    (root / "_unknown" / "f3.parquet").write_bytes(b"z" * 10)
    # Loose root file (old flat layout -> "_root" orphan group).
    (root / "old.parquet").write_bytes(b"w" * 5)
    return root


def test_scan_groups_and_totals(tmp_path):
    _make_cache(tmp_path)
    out = nc.scan(tmp_path, {"nbA": "Notebook A"})
    groups = {g["notebook_id"]: g for g in out["groups"]}
    assert out["total_bytes"] == 165
    assert groups["nbA"]["subtotal_bytes"] == 150
    assert groups["nbA"]["notebook_name"] == "Notebook A"
    assert groups["nbA"]["is_orphan"] is False
    assert {f["name"] for f in groups["nbA"]["files"]} == {"f1.parquet", "f2.parquet"}
    assert groups["_unknown"]["is_orphan"] is True
    assert groups["_root"]["is_orphan"] is True
    assert groups["_root"]["subtotal_bytes"] == 5
    # groups sorted by subtotal desc
    assert [g["notebook_id"] for g in out["groups"]][0] == "nbA"


def test_scan_missing_dir(tmp_path):
    out = nc.scan(tmp_path, {})
    assert out == {"groups": [], "total_bytes": 0}


def test_delete_file(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_file(tmp_path, "nbA/f1.parquet")
    assert freed == 100
    assert not (tmp_path / "_nb_cache" / "nbA" / "f1.parquet").exists()


def test_delete_file_rejects_traversal(tmp_path):
    _make_cache(tmp_path)
    with pytest.raises(ValueError):
        nc.delete_file(tmp_path, "../secret.txt")
    with pytest.raises(ValueError):
        nc.delete_file(tmp_path, "nbA/../../escape.txt")


def test_delete_notebook(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_notebook(tmp_path, "nbA")
    assert freed == 150
    assert not (tmp_path / "_nb_cache" / "nbA").exists()


def test_delete_notebook_root_only_removes_loose_files(tmp_path):
    _make_cache(tmp_path)
    freed = nc.delete_notebook(tmp_path, "_root")
    assert freed == 5
    assert not (tmp_path / "_nb_cache" / "old.parquet").exists()
    # subdirs untouched
    assert (tmp_path / "_nb_cache" / "nbA").exists()


def test_delete_notebook_rejects_traversal(tmp_path):
    _make_cache(tmp_path)
    with pytest.raises(ValueError):
        nc.delete_notebook(tmp_path, "../x")


def test_clear_all(tmp_path):
    _make_cache(tmp_path)
    freed = nc.clear_all(tmp_path)
    assert freed == 165
    assert not (tmp_path / "_nb_cache").exists()


def test_delete_missing_returns_zero(tmp_path):
    (tmp_path / "_nb_cache").mkdir()
    assert nc.delete_file(tmp_path, "nbA/nope.parquet") == 0
    assert nc.delete_notebook(tmp_path, "ghost") == 0
    assert nc.clear_all(tmp_path) == 0  # empty dir -> 0 bytes freed (dir removed)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -3.12 -m pytest tests/test_notebook_cache.py -q`
Expected: FAIL / collection error — `ModuleNotFoundError: era5_etl.web.notebook_cache`.

- [ ] **Step 3: Write the module**

Create `src/era5_etl/web/notebook_cache.py`:

```python
"""Scan and delete the on-disk Parquet caches produced by /notebooks runs.

Layout (written by the notebook cache cell ``load_inmet_with_cache``)::

    <data_dir>/_nb_cache/<notebook_id>/<file>.parquet

Each immediate subdirectory is one notebook's cache. Loose ``*.parquet`` files
directly under ``_nb_cache/`` come from the older flat layout and are grouped
under the synthetic id ``"_root"``. A group is an *orphan* when its id does not
match a known notebook (the ``_unknown`` and ``_root`` ids are always orphans).

Pure functions over a ``data_dir``; no FastAPI / app-state coupling so they
unit-test directly. All deletes are best-effort and path-safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CACHE_DIRNAME = "_nb_cache"
ROOT_GROUP_ID = "_root"


def cache_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / CACHE_DIRNAME


def _file_entry(path: Path, rel_path: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "name": path.name,
        "rel_path": rel_path,
        "size_bytes": int(st.st_size),
        "modified_ts": int(st.st_mtime),
    }


def scan(data_dir: str | Path, notebook_names: dict[str, str]) -> dict[str, Any]:
    """Return cache groups + grand total. See module docstring for shape."""
    root = cache_root(data_dir)
    if not root.is_dir():
        return {"groups": [], "total_bytes": 0}

    groups: list[dict[str, Any]] = []
    total = 0

    # Subdirectory groups (one per notebook id).
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        files = [
            _file_entry(f, f"{sub.name}/{f.name}")
            for f in sorted(sub.glob("*.parquet"))
            if f.is_file()
        ]
        if not files:
            continue
        files.sort(key=lambda e: e["size_bytes"], reverse=True)
        subtotal = sum(e["size_bytes"] for e in files)
        total += subtotal
        groups.append(
            {
                "notebook_id": sub.name,
                "notebook_name": notebook_names.get(sub.name),
                "is_orphan": sub.name not in notebook_names,
                "subtotal_bytes": subtotal,
                "files": files,
            }
        )

    # Loose root files from the old flat layout.
    root_files = [
        _file_entry(f, f.name)
        for f in sorted(root.glob("*.parquet"))
        if f.is_file()
    ]
    if root_files:
        root_files.sort(key=lambda e: e["size_bytes"], reverse=True)
        subtotal = sum(e["size_bytes"] for e in root_files)
        total += subtotal
        groups.append(
            {
                "notebook_id": ROOT_GROUP_ID,
                "notebook_name": None,
                "is_orphan": True,
                "subtotal_bytes": subtotal,
                "files": root_files,
            }
        )

    groups.sort(key=lambda g: g["subtotal_bytes"], reverse=True)
    return {"groups": groups, "total_bytes": total}


def _safe_under_root(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and ensure it stays inside ``root``; else ValueError."""
    root_resolved = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"Path escapes cache root: {candidate}")
    return resolved


def delete_file(data_dir: str | Path, rel_path: str) -> int:
    """Delete one cache file given its scan ``rel_path``. Returns freed bytes."""
    root = cache_root(data_dir)
    target = _safe_under_root(root, root / rel_path)
    if target == root.resolve() or not target.is_file():
        return 0
    size = int(target.stat().st_size)
    target.unlink()
    return size


def delete_notebook(data_dir: str | Path, notebook_id: str) -> int:
    """Delete a whole group. For ``_root`` only loose files are removed."""
    if "/" in notebook_id or "\\" in notebook_id or notebook_id in ("", ".", ".."):
        raise ValueError(f"Invalid notebook id: {notebook_id!r}")
    root = cache_root(data_dir)
    if not root.is_dir():
        return 0
    freed = 0
    if notebook_id == ROOT_GROUP_ID:
        for f in root.glob("*.parquet"):
            if f.is_file():
                freed += int(f.stat().st_size)
                f.unlink()
        return freed
    sub = _safe_under_root(root, root / notebook_id)
    if not sub.is_dir():
        return 0
    for f in sub.rglob("*"):
        if f.is_file():
            freed += int(f.stat().st_size)
    import shutil

    shutil.rmtree(sub)
    return freed


def clear_all(data_dir: str | Path) -> int:
    """Remove the entire ``_nb_cache/`` tree. Returns freed bytes."""
    root = cache_root(data_dir)
    if not root.is_dir():
        return 0
    freed = sum(
        int(f.stat().st_size) for f in root.rglob("*") if f.is_file()
    )
    import shutil

    shutil.rmtree(root)
    return freed


__all__ = [
    "CACHE_DIRNAME",
    "ROOT_GROUP_ID",
    "cache_root",
    "scan",
    "delete_file",
    "delete_notebook",
    "clear_all",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -3.12 -m pytest tests/test_notebook_cache.py -q`
Expected: all tests PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/web/notebook_cache.py tests/test_notebook_cache.py
git commit -m "feat(web): notebook cache scan/delete helper module"
```

---

## Task 2: Response models

**Files:**
- Modify: `src/era5_etl/web/models/__init__.py`

- [ ] **Step 1: Add the models**

In `src/era5_etl/web/models/__init__.py`, after the `NotebookKernelStatusOut` class (the block of `Notebook*` models), add:

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

- [ ] **Step 2: Register them in `__all__`**

In the `__all__` list of the same file, add these four entries (keep alphabetical grouping near the other `Notebook*`/`Cache*` names):

```python
    "CacheDeleteOut",
    "NotebookCacheFileOut",
    "NotebookCacheGroupOut",
    "NotebookCacheOut",
```

- [ ] **Step 3: Verify import**

Run: `py -3.12 -c "from era5_etl.web.models import NotebookCacheOut, CacheDeleteOut, NotebookCacheGroupOut, NotebookCacheFileOut; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/era5_etl/web/models/__init__.py
git commit -m "feat(web): response models for notebook cache management"
```

---

## Task 3: Settings routes

**Files:**
- Modify: `src/era5_etl/web/routes/settings.py`
- Test: `tests/test_notebook_cache.py` (append route tests)

- [ ] **Step 1: Add route tests**

Append to `tests/test_notebook_cache.py`:

```python
# --- route smoke tests -------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from era5_etl.web.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import era5_etl.web.notebook_store as ns

    monkeypatch.setattr(ns, "_config_dir", lambda: tmp_path / "cfg")
    app = create_app(tmp_path / "data")
    # cache lives under app.state.data_dir; create some files there
    data_dir = tmp_path / "data"
    root = data_dir / "_nb_cache" / "nbX"
    root.mkdir(parents=True)
    (root / "a.parquet").write_bytes(b"x" * 200)
    with TestClient(app) as c:
        yield c, data_dir


def test_route_list_and_delete_file(client):
    c, data_dir = client
    r = c.get("/api/settings/nb-cache")
    assert r.status_code == 200
    body = r.json()
    assert body["total_bytes"] == 200
    assert body["groups"][0]["notebook_id"] == "nbX"
    rel = body["groups"][0]["files"][0]["rel_path"]
    d = c.request("DELETE", f"/api/settings/nb-cache/file", params={"path": rel})
    assert d.status_code == 200
    assert d.json() == {"deleted": True, "freed_bytes": 200}


def test_route_delete_file_traversal_400(client):
    c, _ = client
    d = c.request("DELETE", "/api/settings/nb-cache/file", params={"path": "../x"})
    assert d.status_code == 400


def test_route_delete_notebook_and_clear(client):
    c, data_dir = client
    d = c.request("DELETE", "/api/settings/nb-cache/notebook/nbX")
    assert d.status_code == 200 and d.json()["freed_bytes"] == 200
    # clear-all on now-empty tree
    d2 = c.request("DELETE", "/api/settings/nb-cache")
    assert d2.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `py -3.12 -m pytest tests/test_notebook_cache.py -q`
Expected: the new route tests FAIL with 404 (routes not defined yet).

- [ ] **Step 3: Add the routes**

In `src/era5_etl/web/routes/settings.py`, update the model import block to include the new models:

```python
from era5_etl.web.models import (
    CacheDeleteOut,
    DatasetPrecisionIn,
    DatasetPrecisionOut,
    NotebookCacheOut,
    PathValidationOut,
    UserConfigIn,
    UserConfigOut,
)
```

Add these imports near the top (after the existing `from era5_etl.web... import`):

```python
from era5_etl.web import notebook_cache, notebook_store
```

Then append these routes at the end of the file:

```python
@router.get("/nb-cache", response_model=NotebookCacheOut)
def list_nb_cache(request: Request) -> NotebookCacheOut:
    """List notebook Parquet caches grouped per notebook, with sizes."""
    data_dir = request.app.state.data_dir
    names = {n["id"]: n["name"] for n in notebook_store.list_notebooks()}
    return NotebookCacheOut(**notebook_cache.scan(data_dir, names))


@router.delete("/nb-cache/file", response_model=CacheDeleteOut)
def delete_nb_cache_file(path: str, request: Request) -> CacheDeleteOut:
    """Delete one cache file by its scan ``rel_path``."""
    data_dir = request.app.state.data_dir
    try:
        freed = notebook_cache.delete_file(data_dir, path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CacheDeleteOut(deleted=freed > 0, freed_bytes=freed)


@router.delete("/nb-cache/notebook/{notebook_id}", response_model=CacheDeleteOut)
def delete_nb_cache_notebook(notebook_id: str, request: Request) -> CacheDeleteOut:
    """Delete all cache files for one notebook id (or the ``_root`` orphans)."""
    data_dir = request.app.state.data_dir
    try:
        freed = notebook_cache.delete_notebook(data_dir, notebook_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CacheDeleteOut(deleted=freed > 0, freed_bytes=freed)


@router.delete("/nb-cache", response_model=CacheDeleteOut)
def clear_nb_cache(request: Request) -> CacheDeleteOut:
    """Delete the entire notebook cache tree."""
    data_dir = request.app.state.data_dir
    try:
        freed = notebook_cache.clear_all(data_dir)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CacheDeleteOut(deleted=freed > 0, freed_bytes=freed)
```

- [ ] **Step 4: Run to verify pass**

Run: `py -3.12 -m pytest tests/test_notebook_cache.py -q`
Expected: all PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add src/era5_etl/web/routes/settings.py tests/test_notebook_cache.py
git commit -m "feat(web): /api/settings/nb-cache list + delete endpoints"
```

---

## Task 4: Cache cell writes per-notebook subdir (template + migration)

**Files:**
- Modify: `src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json`

- [ ] **Step 1: Update `_nb_cache_dir()` in the cache cell**

Edit the cell whose source starts with `# --- Load` (index 6) in the template JSON: replace its `_nb_cache_dir` function body so it nests under the notebook id. Use a `py -3.12` snippet that loads the JSON, finds the cell, does a string replace of exactly:

```python
def _nb_cache_dir():
    base = os.environ.get("ERA5_NB_DATA_DIR", ".")
    d = os.path.join(base, "_nb_cache")
    os.makedirs(d, exist_ok=True)
    return d
```

with:

```python
def _nb_cache_dir():
    # Cache is namespaced by notebook id so /settings can group and clear it
    # per notebook. ERA5_NB_ID is injected by the kernel; empty -> "_unknown".
    base = os.environ.get("ERA5_NB_DATA_DIR", ".")
    nb_id = os.environ.get("ERA5_NB_ID") or "_unknown"
    d = os.path.join(base, "_nb_cache", nb_id)
    os.makedirs(d, exist_ok=True)
    return d
```

Then `json.dump(..., ensure_ascii=False, indent=2)`.

- [ ] **Step 2: Validate the template JSON parses + the new line is present**

Run:
```bash
py -3.12 -c "import json; d=json.load(open('src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json',encoding='utf-8')); s='\n'.join(c.get('source','') for c in d['cells']); assert 'os.environ.get(\"ERA5_NB_ID\")' in s, 'ERA5_NB_ID not found'; print('JSON OK + ERA5_NB_ID present')"
```
Expected: `JSON OK + ERA5_NB_ID present`

- [ ] **Step 3: Commit**

```bash
git add src/era5_etl/_data/notebook_templates/xgboost_temperature_forecast.json
git commit -m "feat(notebooks): namespace cache under _nb_cache/<notebook_id>/"
```

---

## Task 5: Frontend API client

**Files:**
- Modify: `web-ui/src/lib/api.ts`

- [ ] **Step 1: Add TS types**

In `web-ui/src/lib/api.ts`, add near the other interface declarations (e.g. just after the `interface CredentialTestResult { ... }` block, before `// --- Inventory`):

```ts
export interface NotebookCacheFile {
  name: string;
  rel_path: string;
  size_bytes: number;
  modified_ts: number;
}

export interface NotebookCacheGroup {
  notebook_id: string;
  notebook_name: string | null;
  is_orphan: boolean;
  subtotal_bytes: number;
  files: NotebookCacheFile[];
}

export interface NotebookCache {
  groups: NotebookCacheGroup[];
  total_bytes: number;
}

export interface CacheDelete {
  deleted: boolean;
  freed_bytes: number;
}
```

- [ ] **Step 2: Add the `nbCache` client**

In the `export const api = { ... }` object, immediately after the `precision: { ... },` block (which ends with `  },` right before `credentialStatus:`), insert:

```ts
  nbCache: {
    list: () => request<NotebookCache>("/api/settings/nb-cache"),
    deleteFile: (relPath: string) =>
      request<CacheDelete>(
        `/api/settings/nb-cache/file?path=${encodeURIComponent(relPath)}`,
        { method: "DELETE" },
      ),
    deleteNotebook: (id: string) =>
      request<CacheDelete>(
        `/api/settings/nb-cache/notebook/${encodeURIComponent(id)}`,
        { method: "DELETE" },
      ),
    clearAll: () =>
      request<CacheDelete>("/api/settings/nb-cache", { method: "DELETE" }),
  },
```

- [ ] **Step 3: Typecheck**

Run: `cd web-ui && npx tsc --noEmit`
Expected: exit 0, no output.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/lib/api.ts
git commit -m "feat(ui): api client for notebook cache management"
```

---

## Task 6: i18n labels

**Files:**
- Modify: `web-ui/src/i18n/locales/pt.ts`
- Modify: `web-ui/src/i18n/locales/en.ts`

- [ ] **Step 1: Add the `nbCache` block to pt.ts**

In `web-ui/src/i18n/locales/pt.ts`, inside the `pageSettings: { ... }` object, add a new key block (place it right before the `danger: {` block). NOTE: pt.ts is the canonical shape — add here first:

```ts
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
      subtotal: "{{size}}",
    },
```

- [ ] **Step 2: Add the mirrored block to en.ts**

In `web-ui/src/i18n/locales/en.ts`, inside `pageSettings`, in the same position (before `danger:`):

```ts
    nbCache: {
      title: "Notebook cache",
      body: "Parquet files produced by notebooks in /notebooks, grouped per notebook.",
      total: "Total: {{size}}",
      clearAll: "Clear all",
      clearAllConfirm: "Delete ALL notebook cache? This cannot be undone.",
      deleteNotebook: "Clear this notebook's cache",
      deleteNotebookConfirm: "Delete all cache for \"{{name}}\"?",
      deleteFile: "Delete this file",
      orphans: "Orphans / unknown",
      empty: "No notebook cache yet.",
      freed: "Freed {{size}}.",
      subtotal: "{{size}}",
    },
```

- [ ] **Step 3: Typecheck (catches key-shape mismatch)**

Run: `cd web-ui && npx tsc --noEmit`
Expected: exit 0. (If `en.ts` is missing a key that pt.ts has, the `Dictionary` type errors here.)

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/i18n/locales/pt.ts web-ui/src/i18n/locales/en.ts
git commit -m "feat(ui): i18n labels for notebook cache settings"
```

---

## Task 7: `NotebookCacheSection` component

**Files:**
- Modify: `web-ui/src/pages/Settings.tsx`

- [ ] **Step 1: Import the icon and add the section to the page**

In `web-ui/src/pages/Settings.tsx`, ensure `Database` and `Trash2` are imported from `lucide-react` (Trash2 already is; add `Database`). Then in `SettingsPage`'s JSX, add `<NotebookCacheSection />` between `<PrecisionSection />` and `<DangerZoneSection />`:

```tsx
      <PrecisionSection />
      <NotebookCacheSection />
      <DangerZoneSection />
```

- [ ] **Step 2: Add the component**

Add this component to `web-ui/src/pages/Settings.tsx` (e.g. just above `function DangerZoneSection()`):

```tsx
function NotebookCacheSection() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["nb-cache"],
    queryFn: api.nbCache.list,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["nb-cache"] });

  const clearAll = useMutation({
    mutationFn: () => api.nbCache.clearAll(),
    onSuccess: (r) => {
      toast.success(t("pageSettings.nbCache.freed", { size: formatBytes(r.freed_bytes) }));
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const delNotebook = useMutation({
    mutationFn: (id: string) => api.nbCache.deleteNotebook(id),
    onSuccess: (r) => {
      toast.success(t("pageSettings.nbCache.freed", { size: formatBytes(r.freed_bytes) }));
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const delFile = useMutation({
    mutationFn: (rel: string) => api.nbCache.deleteFile(rel),
    onSuccess: (r) => {
      toast.success(t("pageSettings.nbCache.freed", { size: formatBytes(r.freed_bytes) }));
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const groups = data?.groups ?? [];

  return (
    <section className="card space-y-5 p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-ocean-50 p-3 text-ocean-700">
            <Database className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-medium text-ink-900">
              {t("pageSettings.nbCache.title")}
            </h2>
            <p className="mt-1 text-sm text-ink-500">
              {t("pageSettings.nbCache.body")}
            </p>
            <p className="mt-1 text-xs font-medium text-ink-600">
              {t("pageSettings.nbCache.total", {
                size: formatBytes(data?.total_bytes ?? 0),
              })}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="btn-outline border-rose-300 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
          disabled={groups.length === 0 || clearAll.isPending}
          onClick={() => {
            if (confirm(t("pageSettings.nbCache.clearAllConfirm"))) clearAll.mutate();
          }}
        >
          {clearAll.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
          {t("pageSettings.nbCache.clearAll")}
        </button>
      </div>

      {isLoading ? (
        <div className="h-24 animate-pulse rounded-lg bg-ink-100" />
      ) : groups.length === 0 ? (
        <p className="text-sm text-ink-400">{t("pageSettings.nbCache.empty")}</p>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => {
            const title = g.is_orphan
              ? `${t("pageSettings.nbCache.orphans")} (${g.notebook_id})`
              : g.notebook_name ?? g.notebook_id;
            return (
              <div
                key={g.notebook_id}
                className="rounded-xl border border-ink-200 bg-white p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-ink-900">{title}</div>
                    <div className="text-xs text-ink-500">
                      {formatBytes(g.subtotal_bytes)} · {g.files.length}{" "}
                      {t("common.files")}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="rounded-md border border-ink-200 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50"
                    title={t("pageSettings.nbCache.deleteNotebook")}
                    disabled={delNotebook.isPending}
                    onClick={() => {
                      if (confirm(t("pageSettings.nbCache.deleteNotebookConfirm", { name: title })))
                        delNotebook.mutate(g.notebook_id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="mt-3 divide-y divide-ink-100 border-t border-ink-100">
                  {g.files.map((f) => (
                    <div
                      key={f.rel_path}
                      className="flex items-center justify-between gap-3 py-1.5 text-xs"
                    >
                      <span className="truncate font-mono text-ink-600">{f.name}</span>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="tabular-nums text-ink-500">
                          {formatBytes(f.size_bytes)}
                        </span>
                        <span className="text-ink-400">
                          {new Date(f.modified_ts * 1000).toLocaleString()}
                        </span>
                        <button
                          type="button"
                          className="text-rose-500 hover:text-rose-700"
                          title={t("pageSettings.nbCache.deleteFile")}
                          disabled={delFile.isPending}
                          onClick={() => delFile.mutate(f.rel_path)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web-ui && npx tsc --noEmit`
Expected: exit 0, no output.

- [ ] **Step 4: Build the SPA**

Run: `cd web-ui && NODE_OPTIONS="--use-system-ca" npm run build`
Expected: `✓ built in …s`, exit 0; regenerated `src/era5_etl/web/static/assets/*`.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/pages/Settings.tsx src/era5_etl/web/static
git commit -m "feat(ui): Notebook cache section in /settings (per-notebook sizes + delete)"
```

---

## Task 8: Migrate the saved XGBoost notebook to the new cache cell

**Files:**
- Modify (data, not repo): `%APPDATA%/era5-etl/notebooks/<id>.json` (idempotent, `.bak4` backup)

- [ ] **Step 1: Run the migration (replace the Load cell from the template)**

Run:
```bash
py -3.12 - <<'PY'
import json, glob, os, shutil
from importlib.resources import as_file, files
from era5_etl.web.user_config import _config_dir

res = files("era5_etl._data.notebook_templates").joinpath("xgboost_temperature_forecast.json")
with as_file(res) as f:
    tpl = json.load(open(f, encoding="utf-8"))
load_src = next(c["source"] for c in tpl["cells"] if c.get("source", "").startswith("# --- Load"))

nb = _config_dir() / "notebooks"
changed = 0
for path in sorted(glob.glob(str(nb / "*.json"))):
    d = json.load(open(path, encoding="utf-8"))
    cells = d.get("cells", [])
    if not any("load_inmet_with_cache(" in (c.get("source") or "") for c in cells):
        print(f" - {os.path.basename(path)}: no cache cell, skip"); continue
    shutil.copy2(path, path + ".bak4")
    hits = 0
    for c in cells:
        if (c.get("source") or "").startswith("# --- Load"):
            c["source"] = load_src
            c["outputs"] = []
            hits += 1
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    changed += 1
    print(f" - {os.path.basename(path)}: replaced {hits} Load cell(s); backup .bak4")
print("DONE. modified:", changed)
PY
```
Expected: `replaced 1 Load cell(s)`, `DONE. modified: 1`.

- [ ] **Step 2: Verify the saved notebook has the per-notebook cache dir**

Run:
```bash
py -3.12 - <<'PY'
import json, glob, os
from era5_etl.web.user_config import _config_dir
nb = _config_dir() / "notebooks"
for p in sorted(glob.glob(str(nb / "*.json"))):
    if p.endswith((".bak", ".bak2", ".bak3", ".bak4")): continue
    d = json.load(open(p, encoding="utf-8"))
    j = "\n".join(c.get("source") or "" for c in d.get("cells", []))
    if "load_inmet_with_cache(" in j:
        print(os.path.basename(p), "| ERA5_NB_ID in cache cell:", 'os.environ.get("ERA5_NB_ID")' in j)
PY
```
Expected: `ERA5_NB_ID in cache cell: True`.

No commit (edits user data outside the repo).

---

## Task 9: Final verification sweep

- [ ] **Step 1: Backend tests green**
```bash
py -3.12 -m pytest tests/test_notebook_cache.py tests/test_notebook_kernel.py tests/test_notebook_routes.py tests/test_notebook_store.py -q
```
Expected: all pass (≥ 12 + 21 prior).

- [ ] **Step 2: Templates valid**
```bash
py -3.12 -c "import json,glob; [json.load(open(f,encoding='utf-8')) for f in glob.glob('src/era5_etl/_data/notebook_templates/*.json')]; print('ALL TEMPLATES OK')"
```
Expected: `ALL TEMPLATES OK`

- [ ] **Step 3: SPA typecheck + build**
```bash
cd web-ui && npx tsc --noEmit && NODE_OPTIONS="--use-system-ca" npm run build
```
Expected: tsc exit 0; `✓ built in …s`.

- [ ] **Step 4: Clean git state**
```bash
git status --short && git log --oneline -8
```
Expected: working tree clean; commits for Tasks 1–7 present.

---

## Self-Review (filled in by plan author)

**Spec coverage:**
- Cache layout change (`_nb_cache/<notebook_id>/`) → Task 4 (template) + Task 8 (saved notebook) ✓
- `web/notebook_cache.py` scan/delete with path-safety → Task 1 ✓
- Models → Task 2 ✓
- 4 routes (list + 3 deletes) → Task 3 ✓
- api.ts client → Task 5 ✓
- `NotebookCacheSection` with per-file/subtotal/total sizes + 3 delete levels → Task 7 ✓
- i18n → Task 6 ✓
- Orphans group (`_unknown` + `_root`) → Task 1 (`scan`) + Task 7 (rendering) ✓
- Tests (module + routes + traversal) → Tasks 1 & 3 ✓

**Placeholder scan:** None. Every code step has complete content.

**Type/name consistency:** `scan`/`delete_file`/`delete_notebook`/`clear_all` signatures match across module (T1), routes (T3), and the spec. Model names `NotebookCacheOut`/`NotebookCacheGroupOut`/`NotebookCacheFileOut`/`CacheDeleteOut` consistent across T2, T3 import, and api.ts types (`NotebookCache`/`NotebookCacheGroup`/`NotebookCacheFile`/`CacheDelete`). Route paths `/api/settings/nb-cache[...]` identical in T3 and T5. i18n keys under `pageSettings.nbCache.*` consistent T6↔T7. `ROOT_GROUP_ID="_root"` used in scan + delete_notebook + frontend orphan title.

**Ambiguity:** `delete_notebook("_root")` is explicitly scoped to loose root files only (not subdirs), tested in T1. `is_relative_to` requires Python ≥3.9 (project targets 3.11+) — fine.
