"""Allow running era5_etl as a module: python -m era5_etl."""

from era5_etl.cli import app

if __name__ == "__main__":
    app()
