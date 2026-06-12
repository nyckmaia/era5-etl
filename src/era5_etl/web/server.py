"""FastAPI app factory for the ERA5-ETL web UI.

Call ``create_app(data_dir)`` to obtain a configured app instance. The SPA
build (``static/index.html`` and assets) is mounted at the application root
with a catch-all fallback to ``index.html`` so client-side routes work.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from era5_etl.__version__ import __version__
from era5_etl.web.routes import (
    credentials as credentials_routes,
)
from era5_etl.web.routes import (
    datasets as datasets_routes,
)
from era5_etl.web.routes import (
    export as export_routes,
)
from era5_etl.web.routes import (
    inmet as inmet_routes,
)
from era5_etl.web.routes import (
    inventory as inventory_routes,
)
from era5_etl.web.routes import (
    mlflow_ui as mlflow_ui_routes,
)
from era5_etl.web.routes import (
    notebooks as notebooks_routes,
)
from era5_etl.web.routes import (
    pipeline as pipeline_routes,
)
from era5_etl.web.routes import (
    query as query_routes,
)
from era5_etl.web.routes import (
    query_store as query_store_routes,
)
from era5_etl.web.routes import (
    regions as regions_routes,
)
from era5_etl.web.routes import (
    settings as settings_routes,
)
from era5_etl.web.routes import (
    stats as stats_routes,
)
from era5_etl.web.routes import (
    timeseries as timeseries_routes,
)
from era5_etl.web.routes import (
    user_views as user_views_routes,
)
from era5_etl.web.routes import (
    variable_presets as variable_presets_routes,
)
from era5_etl.web.routes import (
    version as version_routes,
)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(data_dir: str | Path) -> FastAPI:
    """Build a FastAPI app rooted at ``data_dir``."""
    import os

    from era5_etl.cli import install_cdsapi_log_filter

    install_cdsapi_log_filter()

    # MLflow >= 3.x refuses to even OPEN a local file store (mlruns/) unless
    # this opt-in is set. The Model-runs panel reads it in-process, and the
    # notebook kernels / `mlflow ui` subprocess write to it (their env also
    # sets the flag explicitly, but the read path lives here).
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

    @asynccontextmanager
    async def _lifespan(app: FastAPI):  # noqa: ARG001
        yield
        mlflow_ui_routes.shutdown()

    app = FastAPI(
        title="ERA5-ETL",
        version=__version__,
        description="Local control panel for ERA5/ERA5-Land downloads.",
        lifespan=_lifespan,
    )
    app.state.data_dir = Path(data_dir).expanduser().resolve()

    # During local dev the SPA is served from vite (5173) and proxies /api.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    app.include_router(version_routes.router)
    app.include_router(datasets_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(credentials_routes.router)
    app.include_router(pipeline_routes.router)
    app.include_router(query_routes.router)
    app.include_router(query_store_routes.router)
    app.include_router(user_views_routes.router)
    app.include_router(variable_presets_routes.router)
    app.include_router(regions_routes.router)
    app.include_router(export_routes.router)
    app.include_router(inventory_routes.router)
    app.include_router(inmet_routes.router)
    app.include_router(mlflow_ui_routes.router)
    app.include_router(notebooks_routes.router)
    app.include_router(timeseries_routes.router)

    @app.exception_handler(404)
    async def _not_found(_request: Request, _exc):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    # Mount static SPA if it has been built; serve index.html as fallback.
    if STATIC_DIR.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(STATIC_DIR / "assets"), check_dir=False),
            name="assets",
        )

        @app.get("/{path:path}")
        async def _spa_fallback(path: str) -> FileResponse:
            index = STATIC_DIR / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return FileResponse(str(STATIC_DIR / "index.html"))

    return app
