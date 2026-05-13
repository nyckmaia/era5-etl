"""Web UI server for ERA5-ETL.

The FastAPI app is constructed via :func:`era5_etl.web.server.create_app`. The
React/Vite SPA lives in ``web-ui/`` at the repository root and is bundled into
``era5_etl/web/static/`` at package build time.
"""
