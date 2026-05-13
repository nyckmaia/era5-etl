# era5-etl web UI

Vite + React + TypeScript + Tailwind + TanStack frontend for ERA5-ETL.

## Develop

```bash
cd web-ui
bun install        # or: pnpm install
bun run dev        # vite on :5173, proxies /api to http://127.0.0.1:8788
```

In parallel, run the FastAPI backend:

```bash
era5 ui            # or: uvicorn era5_etl.web.server:create_app --factory --port 8788
```

## Build

```bash
bun run build      # outputs to ../src/era5_etl/web/static/
```

When the Python package is built (`pip install .` or `hatch build`), the
custom Hatch hook runs `bun run build` automatically and bundles the SPA
into the wheel under `era5_etl/web/static/`. Set the env var
`ERA5_ETL_SKIP_UI_BUILD=1` to skip the SPA build (CI, etc.).
