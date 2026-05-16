# Inventory Controls Overhaul + Query Favorites Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invert the inventory variable filter to start all-checked, replace the point-display controls with a visibility checkbox + opacity slider + color picker, add a 24-hour filter, and fix the `/query` "Favoritas" filter showing empty.

**Architecture:** Backend gains a read-path `hours` filter on `CoverageIndex.query_grid_points` exposed via a repeatable `hour` query param on `GET /api/inventory/grid-points`. The React `/inventory` page reworks its filter-bar state (all-checked variables, all-checked hours, localStorage-persisted point style) and `InventoryMap` swaps the colormap encoding for a user-chosen color + opacity. `/query`'s `RightSidebar` stops overloading the ★ glyph so the favorite flag and the filter agree.

**Tech Stack:** Python 3.12 / FastAPI / DuckDB / Polars (backend); React + TanStack Router/Query + deck.gl + Vite/Bun (frontend). Backend tested with pytest + FastAPI `TestClient`; frontend verified via `bun run lint` (tsc) + `bun run build` + manual smoke (no React test harness in-repo).

Spec: `docs/superpowers/specs/2026-05-16-inventory-controls-and-query-favorites-design.md`

---

## File Structure

- `src/era5_etl/storage/coverage.py` — add `hours` param to `query_grid_points` (M3 backend)
- `src/era5_etl/web/routes/inventory.py` — add repeatable `hour` query param + 0–23 validation (M3 backend)
- `tests/test_coverage_index.py` — unit test for the hours filter
- `tests/test_inventory_routes.py` — route test for the `hour` param
- `web-ui/src/lib/api.ts` — thread `hour[]` into `inventory.gridPoints` (M3 frontend)
- `web-ui/src/pages/Inventory.tsx` — variables all-checked (M1), hours filter (M3), point-style controls (M2)
- `web-ui/src/components/inventory/InventoryMap.tsx` — color/opacity/visibility, drop colormap (M2)
- `web-ui/src/components/query/RightSidebar.tsx` — favorites display/filter fix (M4)

---

### Task 1: Backend — `query_grid_points` hours filter

**Files:**
- Modify: `src/era5_etl/storage/coverage.py:297-339`
- Test: `tests/test_coverage_index.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_coverage_index.py` (after the existing
`query_grid_points` tests, near line 330):

```python
def test_query_grid_points_hours_filter(tmp_path: Path) -> None:
    """`hours` keeps a cell only if a row's mask contains ALL selected hours."""
    df_full = _grid_df(
        lats=[-22.5], lons=[-43.5], hours=list(range(24)), date_str="2024-01-01"
    )
    df_partial = _grid_df(
        lats=[-23.0], lons=[-43.5], hours=[0, 6], date_str="2024-01-01"
    )

    with CoverageIndex("era5-land", tmp_path) as cov:
        cov.upsert_from_dataframe(df_full)
        cov.upsert_from_dataframe(df_partial)

        # All 24 selected -> only the fully-covered cell qualifies.
        g_all = cov.query_grid_points(hours=list(range(24)))
        assert g_all.height == 1
        assert g_all.row(0, named=True)["latitude"] == -22.5

        # {0, 6} present in BOTH cells.
        g_sub = cov.query_grid_points(hours=[0, 6])
        assert g_sub.height == 2

        # {0, 6, 12}: partial cell lacks hour 12 -> excluded.
        g_mix = cov.query_grid_points(hours=[0, 6, 12])
        assert g_mix.height == 1
        assert g_mix.row(0, named=True)["latitude"] == -22.5

        # None / empty -> unchanged behavior (both cells).
        assert cov.query_grid_points(hours=None).height == 2
        assert cov.query_grid_points(hours=[]).height == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_coverage_index.py::test_query_grid_points_hours_filter -v`
Expected: FAIL — `TypeError: query_grid_points() got an unexpected keyword argument 'hours'`

- [ ] **Step 3: Add the `hours` parameter and filter clause**

In `src/era5_etl/storage/coverage.py`, change the `query_grid_points`
signature (currently lines 297-302) to add `hours`:

```python
    def query_grid_points(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        variable: str | list[str] | None = None,
        hours: list[int] | None = None,
    ) -> pl.DataFrame:
```

Then, immediately **after** the existing variable-filter block (after
the `elif variable:` branch that ends at line 326, before the
`where = ...` line 327), insert:

```python
        if hours:
            mask = 0
            for h in hours:
                mask |= 1 << int(h)
            # Keep a coverage row only if its hours_mask contains every
            # selected hour: (hours_mask & mask) = mask. A grid point then
            # survives the GROUP BY if ANY of its rows qualifies.
            clauses.append("(hours_mask & ?) = ?")
            params.append(mask)
            params.append(mask)
```

Also update the docstring's "Optional filters:" list to add:

```python
        - ``hours``: list of hour integers (0-23). A cell is kept only if
          at least one of its rows has every selected hour set in
          ``hours_mask``. ``None`` / empty list = no hour filter.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_coverage_index.py::test_query_grid_points_hours_filter -v`
Expected: PASS

- [ ] **Step 5: Run the full coverage suite for regressions**

Run: `py -3.12 -m pytest tests/test_coverage_index.py -q`
Expected: all pass (no regressions in the existing `query_grid_points` tests)

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/storage/coverage.py tests/test_coverage_index.py
git commit -m "feat(coverage): hours filter on query_grid_points

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Backend — `hour` query param on `/api/inventory/grid-points`

**Files:**
- Modify: `src/era5_etl/web/routes/inventory.py:89-119`
- Test: `tests/test_inventory_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inventory_routes.py` (after the existing
grid-points tests):

```python
def test_grid_points_hour_filter(client: TestClient, data_dir: Path):
    """Repeatable `hour` param applies the restrictive all-present rule."""
    df_partial = _coverage_df(
        lats=[-10.0], lons=[-50.0], hours=[0, 1, 2], dates=["2024-01-01"]
    )
    df_full = _coverage_df(
        lats=[-11.0], lons=[-50.0], hours=list(range(24)), dates=["2024-01-01"]
    )
    _populate(data_dir, "era5-land", df_partial)
    _populate(data_dir, "era5-land", df_full)

    # {0,1} present in both cells.
    r = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "format": "json", "hour": [0, 1]},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    # {0,5}: only the fully-covered cell has hour 5.
    r = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "format": "json", "hour": [0, 5]},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # Out-of-range hour -> 422.
    r = client.get(
        "/api/inventory/grid-points",
        params={"dataset": "era5-land", "hour": [24]},
    )
    assert r.status_code == 422, r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_inventory_routes.py::test_grid_points_hour_filter -v`
Expected: FAIL — both subset assertions return 2 (param ignored) / no 422

- [ ] **Step 3: Add the `hour` param, validation, and pass-through**

In `src/era5_etl/web/routes/inventory.py`, add a `hour` parameter to the
`grid_points` signature. Insert it after the `variable` Query param
(after line 99, before the `format` param at line 100):

```python
    hour: list[int] | None = Query(  # noqa: B008 - FastAPI Query default
        None,
        description="UTC hour(s) 0-23 to filter on. Repeat for multiple; "
        "a cell is kept only if a row has ALL selected hours. Omit for all.",
    ),
```

Then, inside the function body, right after
`df_to = _parse_iso_date(date_to, "date_to")` (line 108), add validation:

```python
    if hour is not None:
        for h in hour:
            if h < 0 or h > 23:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid hour: {h} (expected 0-23)",
                )
```

Finally, pass it through to the coverage query — change the
`cov.query_grid_points(...)` call (lines 117-119) to:

```python
        df = cov.query_grid_points(
            date_from=df_from,
            date_to=df_to,
            variable=variable or None,
            hours=hour or None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_inventory_routes.py::test_grid_points_hour_filter -v`
Expected: PASS

- [ ] **Step 5: Run the full inventory route suite**

Run: `py -3.12 -m pytest tests/test_inventory_routes.py -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/era5_etl/web/routes/inventory.py tests/test_inventory_routes.py
git commit -m "feat(inventory-api): repeatable hour query param

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend API — thread `hour[]` into `inventory.gridPoints`

**Files:**
- Modify: `web-ui/src/lib/api.ts:353-368`

- [ ] **Step 1: Add the `hour` field to the params type and querystring**

In `web-ui/src/lib/api.ts`, replace the `gridPoints` method (lines
353-368) with:

```typescript
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
```

- [ ] **Step 2: Typecheck**

Run: `cd web-ui && bun run lint`
Expected: PASS (no type errors)

- [ ] **Step 3: Commit**

```bash
git add web-ui/src/lib/api.ts
git commit -m "feat(web-api): hour[] param on inventory.gridPoints

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Frontend M2 — InventoryMap color/opacity/visibility props

Do `InventoryMap` first so `Inventory.tsx` (Task 5/6) can pass the new
props and stop passing `colormap`/`totalVars` without a type error.

**Files:**
- Modify: `web-ui/src/components/inventory/InventoryMap.tsx`

- [ ] **Step 1: Replace the colormap props with color/opacity**

In `web-ui/src/components/inventory/InventoryMap.tsx`:

Replace the `InventoryMapProps` interface (lines 51-60) with:

```typescript
export interface InventoryMapProps {
  points: GridPoint[];
  selectionMode: SelectionMode;
  selection: [number, number][] | null; // polygon ring [lat, lon][]
  onSelectionChange: (poly: [number, number][] | null) => void;
  onCellClick: (lat: number, lon: number) => void;
  pointColor: string; // hex, e.g. "#2864c8"
  pointOpacity: number; // 0-100
  showPoints: boolean;
}
```

Replace `intensityColor` (lines 62-69) with a hex parser:

```typescript
function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = Number.parseInt(full || "2864c8", 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
```

Replace the destructuring (lines 72-81) with:

```typescript
  const {
    points,
    selectionMode,
    selection,
    onSelectionChange,
    onCellClick,
    pointColor,
    pointOpacity,
    showPoints,
  } = props;
```

Replace the `pointsLayer` `useMemo` (lines 87-117) `getFillColor` and
deps. The full replacement block:

```typescript
  const pointsLayer = useMemo(() => {
    const [r, g, b] = hexToRgb(pointColor);
    const alpha = Math.round((Math.max(0, Math.min(100, pointOpacity)) / 100) * 255);
    return new ScatterplotLayer<GridPoint>({
      id: "grid-points",
      data: points,
      visible: showPoints,
      pickable: true,
      radiusUnits: "meters",
      radiusMinPixels: 0.25,
      radiusMaxPixels: 9,
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => 1250 + Math.log10(Math.max(1, Number(d.days))) * 600,
      getFillColor: [r, g, b, alpha],
      getLineColor: [255, 255, 255, 220],
      lineWidthMinPixels: 1.5,
      stroked: true,
      updateTriggers: {
        getFillColor: [pointColor, pointOpacity],
      },
    });
  }, [points, pointColor, pointOpacity, showPoints]);
```

- [ ] **Step 2: Typecheck**

Run: `cd web-ui && bun run lint`
Expected: FAIL — `Inventory.tsx` still passes `colormap`/`totalVars`.
This is expected; Task 6 fixes the caller. Confirm the ONLY errors are
in `Inventory.tsx` referencing `colormap`/`totalVars`/`InventoryMap`
props (no errors inside `InventoryMap.tsx` itself).

- [ ] **Step 3: Do NOT commit yet**

This task leaves the build red by design; commit together with Task 6
(the caller fix) to keep every commit green. Proceed to Task 5.

---

### Task 5: Frontend M1 + M3 — variables all-checked + hours filter in Inventory

**Files:**
- Modify: `web-ui/src/pages/Inventory.tsx`

- [ ] **Step 1: Add hours constant, imports, and seeding state**

In `web-ui/src/pages/Inventory.tsx`:

Add the localStorage hook import after the existing imports (after
line 14 `import { cn, formatBytes } from "@/lib/format";`):

```typescript
import { useLocalStorage } from "@/hooks/useLocalStorage";

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const fmtHour = (h: number) => `${String(h).padStart(2, "0")}:00`;
```

Replace the filter state block (lines 23-36) with:

```typescript
  const [dataset, setDataset] = useState<string>("");
  const [variableFilter, setVariableFilter] = useState<string[]>([]);
  const [hourFilter, setHourFilter] = useState<number[]>(HOURS);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const userEditedDates = useRef(false);
  const seededVarsFor = useRef<string>("");
  const [varMenuOpen, setVarMenuOpen] = useState(false);
  const [hourMenuOpen, setHourMenuOpen] = useState(false);
  const varMenuRef = useRef<HTMLDivElement | null>(null);
  const hourMenuRef = useRef<HTMLDivElement | null>(null);
  const [pointColor, setPointColor] = useLocalStorage<string>(
    "inventory.pointColor",
    "#2864c8",
  );
  const [pointOpacity, setPointOpacity] = useLocalStorage<number>(
    "inventory.pointOpacity",
    85,
  );
  const [showPoints, setShowPoints] = useLocalStorage<boolean>(
    "inventory.showPoints",
    true,
  );
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("none");
  const [selection, setSelection] = useState<[number, number][] | null>(null);
  const [activeCell, setActiveCell] = useState<{ lat: number; lon: number } | null>(
    null,
  );
```

- [ ] **Step 2: Seed variables all-checked when the dataset's variables resolve**

Add this effect right after the `activeDataset` `useMemo` (after
line 48, before `const dateRangeQ = useQuery(`):

```typescript
  // M1: variables start ALL-checked ("checked = visible"). Seed once per
  // dataset, when its variable list is known.
  useEffect(() => {
    if (!activeDataset) return;
    if (seededVarsFor.current === activeDataset.name) return;
    seededVarsFor.current = activeDataset.name;
    setVariableFilter(activeDataset.variables.map((v) => v.api_name));
  }, [activeDataset]);
```

- [ ] **Step 3: Close the hours popover on outside click**

Directly after the existing variable-popover outside-click effect
(after line 76, the `}, [varMenuOpen]);` block), add:

```typescript
  useEffect(() => {
    if (!hourMenuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (hourMenuRef.current && !hourMenuRef.current.contains(e.target as Node)) {
        setHourMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [hourMenuOpen]);
```

- [ ] **Step 4: Re-seed filters on dataset change**

Replace `changeDataset` (lines 78-85) with:

```typescript
  function changeDataset(next: string) {
    setDataset(next);
    // New dataset → reset date/hour filters; variables re-seed via the
    // effect once the new dataset's variable list resolves.
    userEditedDates.current = false;
    seededVarsFor.current = "";
    setDateFrom("");
    setDateTo("");
    setVariableFilter([]);
    setHourFilter(HOURS);
  }
```

- [ ] **Step 5: Derive selection flags and rework the grid-points query**

Replace the `pointsQ` query and the two lines after it (lines 87-107)
with:

```typescript
  const allVarNames = useMemo(
    () => activeDataset?.variables.map((v) => v.api_name) ?? [],
    [activeDataset],
  );
  const varsAllSelected =
    allVarNames.length > 0 && variableFilter.length === allVarNames.length;
  const varsNoneSelected = variableFilter.length === 0;
  const hoursAllSelected = hourFilter.length === HOURS.length;
  const hoursNoneSelected = hourFilter.length === 0;
  const emptySelection = varsNoneSelected || hoursNoneSelected;

  const pointsQ = useQuery({
    queryKey: [
      "inventory-grid-points",
      dataset,
      dateFrom,
      dateTo,
      variableFilter,
      hourFilter,
    ],
    queryFn: () =>
      api.inventory.gridPoints({
        dataset,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        variable: varsAllSelected ? undefined : variableFilter,
        hour: hoursAllSelected ? undefined : hourFilter,
        format: "auto",
      }),
    enabled: Boolean(dataset) && !emptySelection,
  });

  const { data: stats } = useQuery({
    queryKey: ["stats", dataset],
    queryFn: () => api.stats(dataset),
    enabled: Boolean(dataset),
  });

  const points: GridPoint[] = emptySelection ? [] : pointsQ.data ?? [];
```

(Delete the now-removed `const totalVars = ...` line — `totalVars` is no
longer used anywhere.)

- [ ] **Step 6: Update the variables popover (label + toggle-all)**

Replace the variables `<Field label="Variáveis">…</Field>` block
(lines 163-220) with:

```tsx
        <Field label="Variáveis">
          <div className="relative" ref={varMenuRef}>
            <button
              type="button"
              onClick={() => setVarMenuOpen((o) => !o)}
              className="input flex min-w-[12rem] items-center justify-between gap-2 text-left"
            >
              <span className="truncate">
                {varsAllSelected
                  ? "Todas"
                  : varsNoneSelected
                    ? "Nenhuma"
                    : `${variableFilter.length} selecionada(s)`}
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" />
            </button>
            {varMenuOpen ? (
              <div className="absolute left-0 z-20 mt-1 max-h-72 w-72 overflow-y-auto rounded-xl border border-ink-200 bg-white p-2 shadow-elevated">
                <button
                  type="button"
                  onClick={() =>
                    setVariableFilter(varsAllSelected ? [] : allVarNames)
                  }
                  className="mb-1 w-full rounded-md px-2 py-1 text-left text-xs text-ocean-600 hover:bg-ink-50"
                >
                  {varsAllSelected ? "Desmarcar todas" : "Marcar todas"}
                </button>
                {activeDataset?.variables.map((v) => {
                  const checked = variableFilter.includes(v.api_name);
                  return (
                    <label
                      key={v.api_name}
                      className={cn(
                        "flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-ink-50",
                        checked && "bg-ocean-50/60",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={checked}
                        onChange={() =>
                          setVariableFilter((prev) =>
                            prev.includes(v.api_name)
                              ? prev.filter((x) => x !== v.api_name)
                              : [...prev, v.api_name],
                          )
                        }
                      />
                      <span className="flex-1">
                        <span className="block text-ink-800">{v.full_name}</span>
                        <span className="block text-[11px] text-ink-400">
                          {v.api_name}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : null}
          </div>
        </Field>
        <Field label="Horas">
          <div className="relative" ref={hourMenuRef}>
            <button
              type="button"
              onClick={() => setHourMenuOpen((o) => !o)}
              className="input flex min-w-[10rem] items-center justify-between gap-2 text-left"
            >
              <span className="truncate">
                {hoursAllSelected
                  ? "Todas"
                  : hoursNoneSelected
                    ? "Nenhuma"
                    : `${hourFilter.length} selecionada(s)`}
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" />
            </button>
            {hourMenuOpen ? (
              <div className="absolute left-0 z-20 mt-1 max-h-72 w-56 overflow-y-auto rounded-xl border border-ink-200 bg-white p-2 shadow-elevated">
                <button
                  type="button"
                  onClick={() =>
                    setHourFilter(hoursAllSelected ? [] : HOURS)
                  }
                  className="mb-1 w-full rounded-md px-2 py-1 text-left text-xs text-ocean-600 hover:bg-ink-50"
                >
                  {hoursAllSelected ? "Desmarcar todas" : "Marcar todas"}
                </button>
                {HOURS.map((h) => {
                  const checked = hourFilter.includes(h);
                  return (
                    <label
                      key={h}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-ink-50",
                        checked && "bg-ocean-50/60",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setHourFilter((prev) =>
                            prev.includes(h)
                              ? prev.filter((x) => x !== h)
                              : [...prev, h],
                          )
                        }
                      />
                      <span className="text-ink-800">{fmtHour(h)} UTC</span>
                    </label>
                  );
                })}
              </div>
            ) : null}
          </div>
        </Field>
```

- [ ] **Step 7: Typecheck (expect only Task 6's pending errors)**

Run: `cd web-ui && bun run lint`
Expected: errors ONLY for the still-unported point controls / removed
`totalVars` / `InventoryMap` props in `Inventory.tsx`. No other errors.
Task 6 closes these.

- [ ] **Step 8: Do NOT commit yet — proceed to Task 6**

---

### Task 6: Frontend M2 — point-style controls + wire InventoryMap

**Files:**
- Modify: `web-ui/src/pages/Inventory.tsx`

- [ ] **Step 1: Replace the "Pontos" + "Cor" fields with the new controls**

In `web-ui/src/pages/Inventory.tsx`, replace the two fields — the
`<Field label="Pontos">…</Field>` block AND the `<Field label="Cor">…
</Field>` block (original lines 221-250) — with:

```tsx
        <Field label="Pontos">
          <label className="input flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={showPoints}
              onChange={(e) => setShowPoints(e.target.checked)}
            />
            <span className="text-sm text-ink-700">Mostrar</span>
          </label>
        </Field>
        <Field label="Opacidade">
          <div className="input flex items-center gap-2">
            <input
              type="range"
              min={0}
              max={100}
              value={pointOpacity}
              onChange={(e) => setPointOpacity(Number(e.target.value))}
              className="w-28 accent-ocean-600"
            />
            <span className="w-9 text-right text-xs tabular-nums text-ink-600">
              {pointOpacity}%
            </span>
          </div>
        </Field>
        <Field label="Cor">
          <input
            type="color"
            value={pointColor}
            onChange={(e) => setPointColor(e.target.value)}
            className="h-9 w-12 cursor-pointer rounded-lg border border-ink-200 bg-white p-1"
            aria-label="Cor dos pontos"
          />
        </Field>
```

- [ ] **Step 2: Reset the new filters in "Limpar filtros"**

Replace the "Limpar filtros" button block (original lines 251-263) with:

```tsx
        {(dateFrom ||
          dateTo ||
          !varsAllSelected ||
          !hoursAllSelected) && (
          <button
            onClick={() => {
              userEditedDates.current = true;
              setDateFrom("");
              setDateTo("");
              setVariableFilter(allVarNames);
              setHourFilter(HOURS);
            }}
            className="text-xs text-ocean-600 hover:underline"
          >
            Limpar filtros
          </button>
        )}
```

- [ ] **Step 3: Pass the new props to `InventoryMap`**

Replace the `<InventoryMap … />` element (original lines 268-280) with:

```tsx
          <InventoryMap
            points={points}
            selectionMode={selectionMode}
            selection={selection}
            onSelectionChange={setSelection}
            onCellClick={(lat, lon) => {
              setActiveCell({ lat, lon });
              setSelection(null);
            }}
            pointColor={pointColor}
            pointOpacity={pointOpacity}
            showPoints={showPoints}
          />
```

- [ ] **Step 4: Add an explicit empty-selection map message**

Replace the `{!pointsQ.isLoading && points.length === 0 ? (` overlay
block (original lines 298-310) with:

```tsx
          {emptySelection ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  Nenhuma variável ou hora selecionada.
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Marque ao menos uma variável e uma hora.
                </p>
              </div>
            </div>
          ) : !pointsQ.isLoading && points.length === 0 ? (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-2xl bg-white/95 p-6 text-center shadow-elevated ring-1 ring-ink-200">
                <MapPin className="mx-auto h-6 w-6 text-ink-400" />
                <p className="mt-2 text-sm font-medium text-ink-700">
                  Nenhum dado baixado para {dataset || "este dataset"}.
                </p>
                <p className="mt-1 text-xs text-ink-400">
                  Use a página Download para começar.
                </p>
              </div>
            </div>
          ) : null}
```

- [ ] **Step 5: Typecheck — must be clean now**

Run: `cd web-ui && bun run lint`
Expected: PASS — zero type errors (Tasks 4–6 are now mutually
consistent; `colormap`/`totalVars` fully removed).

- [ ] **Step 6: Manual smoke (build + serve)**

Run: `cd web-ui && bun run build`
Then start the API (`py -3.12 -m era5_etl ui` or the project's usual
command) and open `/inventory`. Verify:
- Variáveis button shows "Todas" on load; all checkboxes checked; map
  shows points as before.
- Unchecking some narrows points; unchecking all → "Nenhuma variável ou
  hora selecionada" overlay, no points.
- Horas shows "Todas", 24 entries `00:00 UTC … 23:00 UTC`, all checked.
- "Mostrar" checkbox hides/shows points; opacity slider changes point
  transparency live; color picker recolors points; all three persist
  across a page reload.

- [ ] **Step 7: Commit (Tasks 4–6 together — first green commit)**

```bash
git add web-ui/src/components/inventory/InventoryMap.tsx web-ui/src/pages/Inventory.tsx
git commit -m "feat(inventory): all-checked variables, hours filter, point style controls

M1 variables start all-checked (checked = visible). M2 replaces the
Pontos/Cor toggles with a visibility checkbox + opacity slider + color
picker (persisted). M3 adds a 24h UTC checkbox filter (restrictive
all-present semantics). Drops the intensity colormap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Frontend M4 — fix `/query` "Favoritas" filter

**Files:**
- Modify: `web-ui/src/components/query/RightSidebar.tsx:95-163`

- [ ] **Step 1: De-overload the ★ glyph and make the favorite button always visible**

In `web-ui/src/components/query/RightSidebar.tsx`, replace the entry
`map` body — the `entries.map((e) => ( … ))` block (lines 95-163) — with:

```tsx
          entries.map((e) => (
            <div
              key={e.id}
              className="group mb-1 rounded-lg border border-ink-100 p-2 text-[11px] hover:border-ink-200"
            >
              {e.name ? (
                <div className="mb-1 truncate text-[11px] font-medium text-ink-700">
                  {e.name}
                </div>
              ) : null}
              <pre className="mb-1 max-h-16 overflow-hidden whitespace-pre-wrap font-mono text-[10px] text-ink-600">
                {e.sql}
              </pre>
              <div className="flex items-center justify-between text-[10px] text-ink-400">
                <span>
                  {e.rows} rows · {e.elapsed_ms}ms
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    title={e.favorite ? "Desfavoritar" : "Favoritar"}
                    onClick={() =>
                      patch.mutate({
                        id: e.id,
                        patch: { favorite: !e.favorite },
                      })
                    }
                    className="rounded p-0.5 hover:bg-amber-100"
                  >
                    <Star
                      className={cn(
                        "h-3 w-3",
                        e.favorite
                          ? "fill-amber-500 text-amber-500"
                          : "text-ink-400",
                      )}
                    />
                  </button>
                  <div className="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                    <button
                      type="button"
                      title="Carregar"
                      onClick={() => onLoad(e.sql)}
                      className="rounded p-0.5 hover:bg-ocean-100 hover:text-ocean-700"
                    >
                      <Play className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      title="Renomear"
                      onClick={() => {
                        const name = window.prompt(
                          "Nome (vazio = remover):",
                          e.name ?? "",
                        );
                        if (name === null) return;
                        patch.mutate({
                          id: e.id,
                          patch: { name: name.trim() || null },
                        });
                      }}
                      className="rounded p-0.5 hover:bg-ink-100"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      title="Excluir"
                      onClick={() => del.mutate(e.id)}
                      className="rounded p-0.5 hover:bg-red-100 hover:text-red-600"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))
```

The favorite button now sits outside the `opacity-0 group-hover`
wrapper, so it is always visible; the ★ is filled only when
`e.favorite`. Named entries render the name as a plain label (no star).
The `!favOnly || e.favorite` filter (line 61) is unchanged and now
matches the visible state.

- [ ] **Step 2: Typecheck**

Run: `cd web-ui && bun run lint`
Expected: PASS

- [ ] **Step 3: Manual smoke**

Run: `cd web-ui && bun run build`, serve, open `/query` → Histórico tab.
With the existing store (`aaa`, `ccc` are named, not favorited):
- Both show as labeled rows WITHOUT a star.
- Click a row's star → it fills amber and persists (reload keeps it).
- Click "Favoritas" → only the starred entries show; named-only entries
  do NOT appear. Toggle off → all return.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/components/query/RightSidebar.tsx
git commit -m "fix(query): stop conflating renamed entries with favorites

The history row drew a star for any named entry while the Favoritas
filter keyed on the separate favorite flag, so the filter looked broken.
Name now renders as a plain label; the always-visible star reflects and
toggles the favorite flag the filter actually uses.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Full verification + final SPA build

**Files:** none (verification + build artifacts)

- [ ] **Step 1: Run the entire backend test suite**

Run: `py -3.12 -m pytest -q`
Expected: all pass (≈180 tests + the 2 new ones), no regressions.

- [ ] **Step 2: Frontend typecheck + production build**

Run: `cd web-ui && bun run lint && bun run build`
Expected: PASS, `vite build` emits a fresh bundle into the SPA output.

- [ ] **Step 3: Confirm the served SPA is regenerated**

Run: `git status --porcelain src/era5_etl/web/static`
Expected: shows modified/new `assets/index-*.js` (the rebuilt bundle the
`era5 ui` command serves). If the static assets are gitignored and show
nothing, that is also acceptable — the build still refreshed what
`era5 ui` serves locally; note which case applies.

- [ ] **Step 4: Commit the rebuilt SPA (only if tracked)**

```bash
git add -A src/era5_etl/web/static
git status --porcelain src/era5_etl/web/static
# If staged changes exist, commit; otherwise skip this step.
git commit -m "build: regenerate SPA bundle for inventory + favorites changes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Final smoke pass**

Serve the app, exercise `/inventory` (all four M1–M3 behaviors) and
`/query` Histórico (M4) end-to-end one more time against the running
server to confirm the built bundle reflects the changes.

---

## Self-Review

**Spec coverage:**
- M1 (variables all-checked) → Task 5 (seeding effect, query logic, label, clear).
- M2 (visibility/opacity/color, drop colormap) → Tasks 4 + 6.
- M3 (hours filter, restrictive semantics, backend param) → Tasks 1, 2, 3, 5.
- M4 (favorites de-conflation) → Task 7.
- Build/DoD (SPA rebuild) → Task 6 step 6, Task 8.
- Testing (backend unit + route tests; frontend lint/build/manual) → Tasks 1, 2, 8.
No spec requirement is left without a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step
contains the full replacement code and exact file/line anchors.

**Type consistency:** `pointColor: string`, `pointOpacity: number`,
`showPoints: boolean` are defined identically in `InventoryMap`
(Task 4), the `Inventory.tsx` state (Task 5 step 1) and the props passed
in Task 6 step 3. `api.inventory.gridPoints` gains `hour?: number[]`
(Task 3) and is called with `hour:` in Task 5 step 5. Backend
`query_grid_points(hours=...)` (Task 1) is called with `hours=hour or
None` from the route (Task 2). `hourFilter: number[]` / `HOURS`
consistent across Task 5/6. Commit ordering: Tasks 4–6 share one green
commit (Task 4/5 intentionally leave the build red mid-flight).
