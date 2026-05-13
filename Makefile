.PHONY: help install dev ui-dev api-dev ui-build test lint typecheck clean

VENV := .venv
PY := py -3.12
UV := pip

help:
	@echo "Common targets:"
	@echo "  install      install Python deps (incl. dev) into the active interpreter"
	@echo "  dev          run UI (vite) and API (uvicorn) concurrently"
	@echo "  ui-dev       run Vite dev server only (port 5173)"
	@echo "  api-dev      run FastAPI/uvicorn only (port 8788)"
	@echo "  ui-build     build the SPA into src/era5_etl/web/static/"
	@echo "  test         run pytest"
	@echo "  lint         run ruff check"
	@echo "  typecheck    run mypy"
	@echo "  clean        remove build artifacts"

install:
	$(PY) -m pip install -e ".[dev]"

dev:
	@echo "Starting API + UI..."
	@start /b $(PY) -m uvicorn era5_etl.web.server:create_app --factory --reload --port 8788
	@cd web-ui && bun run dev

ui-dev:
	@cd web-ui && bun run dev

api-dev:
	$(PY) -m uvicorn era5_etl.web.server:create_app --factory --reload --port 8788

ui-build:
	@cd web-ui && bun install && bun run build

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests

typecheck:
	$(PY) -m mypy src/era5_etl

clean:
	@echo Cleaning build artifacts...
	@rm -rf build dist *.egg-info
	@rm -rf src/era5_etl/web/static
	@rm -rf web-ui/node_modules web-ui/dist
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
