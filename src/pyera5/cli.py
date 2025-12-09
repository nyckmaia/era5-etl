"""Command-line interface for PyERA5."""

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from pyera5 import __version__
from pyera5.config import (
    DatabaseConfig,
    DownloadConfig,
    PipelineConfig,
    ProcessingConfig,
    StorageConfig,
)
from pyera5.pipeline.era5_pipeline import ERA5Pipeline
from pyera5.storage.data_exporter import DataExporter
from pyera5.storage.duckdb_manager import DuckDBManager

# Create CLI app
app = typer.Typer(
    name="pyera5",
    help="Pipeline profissional para dados ERA5/ERA5-Land do Copernicus CDS",
    add_completion=False,
)

# Rich console for output
console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with Rich handler.

    Args:
        verbose: Enable verbose (DEBUG) logging
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"PyERA5 version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
    version: bool = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """PyERA5 - Pipeline profissional para dados ERA5/ERA5-Land."""
    setup_logging(verbose)


@app.command()
def run(
    data_dir: Path = typer.Option(
        Path("./data"),
        "--data-dir",
        "-d",
        help="Base directory for data storage",
    ),
    dataset: str = typer.Option(
        "era5-land",
        "--dataset",
        help="Dataset to download (era5 or era5-land)",
    ),
    start_date: str = typer.Option(
        "2020-01-01",
        "--start-date",
        help="Start date (YYYY-MM-DD)",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="End date (YYYY-MM-DD, default: today)",
    ),
    variables: Optional[list[str]] = typer.Option(
        None,
        "--var",
        help="Variables to download (can be specified multiple times)",
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help="DuckDB database path (default: in-memory)",
    ),
) -> None:
    """Execute the complete ERA5 data pipeline.

    Downloads data from CDS, processes NetCDF files, converts to Parquet,
    and loads into DuckDB for analysis.
    """
    console.print("\n[bold blue]PyERA5 Pipeline[/bold blue]\n")

    # Set default variables if not provided
    if variables is None:
        variables = [
            "2m_temperature",
            "2m_dewpoint_temperature",
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            "surface_pressure",
            "total_precipitation",
        ]

    # Build configuration
    config = PipelineConfig(
        download=DownloadConfig(
            output_dir=data_dir / "netcdf",
            dataset=dataset,
            variables=variables,
            start_date=start_date,
            end_date=end_date,
        ),
        processing=ProcessingConfig(
            input_dir=data_dir / "netcdf",
            output_dir=data_dir / "processed",
        ),
        storage=StorageConfig(
            parquet_dir=data_dir / "parquet",
        ),
        database=DatabaseConfig(
            db_path=db_path or data_dir / "era5.duckdb",
        ),
    )

    # Run pipeline
    try:
        pipeline = ERA5Pipeline(config)
        context = pipeline.run()

        # Display results
        console.print("\n[bold green]Pipeline completed successfully![/bold green]\n")

        table = Table(title="Pipeline Summary")
        table.add_column("Stage", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details", style="yellow")

        for stage in context.completed_stages:
            table.add_row(stage, "✓ Completed", "")

        # Add metadata
        if context.get_metadata("download_count"):
            table.add_row(
                "Downloads",
                "",
                f"{context.get_metadata('download_count')} files",
            )
        if context.get_metadata("processed_count"):
            table.add_row(
                "Processed",
                "",
                f"{context.get_metadata('processed_count')} files",
            )
        if context.get_metadata("parquet_count"):
            table.add_row(
                "Parquet",
                "",
                f"{context.get_metadata('parquet_count')} files",
            )
        if context.get_metadata("tables_loaded"):
            table.add_row(
                "DuckDB",
                "",
                f"{context.get_metadata('tables_loaded')} tables",
            )

        console.print(table)

        if db_path:
            console.print(f"\n[blue]Database:[/blue] {db_path}")

    except Exception as e:
        console.print(f"\n[bold red]Pipeline failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def download(
    data_dir: Path = typer.Option(
        Path("./data"),
        "--data-dir",
        "-d",
        help="Base directory for data storage",
    ),
    dataset: str = typer.Option(
        "era5-land",
        "--dataset",
        help="Dataset to download (era5 or era5-land)",
    ),
    start_date: str = typer.Option(
        "2020-01-01",
        "--start-date",
        help="Start date (YYYY-MM-DD)",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="End date (YYYY-MM-DD, default: today)",
    ),
    variables: Optional[list[str]] = typer.Option(
        None,
        "--var",
        help="Variables to download",
    ),
    override: bool = typer.Option(
        False,
        "--override",
        help="Override existing files",
    ),
) -> None:
    """Download ERA5/ERA5-Land data from Copernicus CDS.

    Requires valid CDS API credentials in ~/.cdsapirc
    """
    from pyera5.download.cds_downloader import CDSDownloader

    console.print("\n[bold blue]Downloading ERA5 data[/bold blue]\n")

    if variables is None:
        variables = [
            "2m_temperature",
            "2m_dewpoint_temperature",
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            "surface_pressure",
            "total_precipitation",
        ]

    config = DownloadConfig(
        output_dir=data_dir / "netcdf",
        dataset=dataset,
        variables=variables,
        start_date=start_date,
        end_date=end_date,
        override=override,
    )

    try:
        downloader = CDSDownloader(config)
        files = downloader.download()
        console.print(f"\n[green]Downloaded {len(files)} files successfully![/green]")
    except Exception as e:
        console.print(f"\n[bold red]Download failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def process(
    input_dir: Path = typer.Argument(
        ...,
        help="Directory with NetCDF files",
    ),
    output_dir: Path = typer.Argument(
        ...,
        help="Directory for processed CSV files",
    ),
    override: bool = typer.Option(
        False,
        "--override",
        help="Override existing files",
    ),
) -> None:
    """Process NetCDF files to CSV format.

    Converts ERA5 NetCDF files to tabular CSV format with:
    - Temperature conversion (Kelvin to Celsius)
    - Wind speed calculation
    - Temporal resampling (optional)
    """
    from pyera5.transform.netcdf_processor import NetCDFProcessor

    console.print("\n[bold blue]Processing NetCDF files[/bold blue]\n")

    config = ProcessingConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        override=override,
    )

    try:
        processor = NetCDFProcessor(config)
        stats = processor.process_directory()

        console.print("\n[green]Processing complete![/green]")
        console.print(f"  Processed: {stats['processed']}")
        console.print(f"  Skipped: {stats['skipped']}")
        console.print(f"  Failed: {stats['failed']}")
    except Exception as e:
        console.print(f"\n[bold red]Processing failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def convert(
    input_dir: Path = typer.Argument(
        ...,
        help="Directory with CSV files",
    ),
    output_dir: Path = typer.Argument(
        ...,
        help="Directory for Parquet files",
    ),
    compression: str = typer.Option(
        "snappy",
        "--compression",
        help="Compression codec (snappy, gzip, brotli, zstd)",
    ),
) -> None:
    """Convert CSV files to Parquet format.

    Creates partitioned Parquet files optimized for analytical queries.
    """
    from pyera5.storage.parquet_writer import ParquetWriter

    console.print("\n[bold blue]Converting to Parquet[/bold blue]\n")

    config = StorageConfig(
        parquet_dir=output_dir,
        compression=compression,
    )

    try:
        writer = ParquetWriter(config)
        csv_files = list(input_dir.glob("*.csv"))

        if not csv_files:
            console.print(f"[yellow]No CSV files found in {input_dir}[/yellow]")
            return

        converted = 0
        for csv_file in csv_files:
            try:
                writer.write_csv_to_parquet(csv_file)
                converted += 1
            except Exception as e:
                console.print(f"[red]Failed to convert {csv_file.name}: {e}[/red]")

        console.print(f"\n[green]Converted {converted}/{len(csv_files)} files![/green]")
    except Exception as e:
        console.print(f"\n[bold red]Conversion failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def query(
    sql: str = typer.Argument(
        ...,
        help="SQL query to execute",
    ),
    db_path: Path = typer.Option(
        Path("./data/era5.duckdb"),
        "--db",
        help="DuckDB database path",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file (CSV format)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-n",
        help="Limit results (display only)",
    ),
) -> None:
    """Execute SQL query on ERA5 data.

    Query the DuckDB database with SQL and optionally export results.

    Example:
        pyera5 query "SELECT * FROM era5land_202001" --limit 10
    """
    console.print("\n[bold blue]Executing query[/bold blue]\n")

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        sys.exit(1)

    try:
        config = DatabaseConfig(db_path=db_path, read_only=True)

        with DuckDBManager(config) as db:
            result = db.query(sql)

            # Display results
            if len(result) > 0:
                console.print(f"[green]Query returned {len(result):,} rows[/green]\n")

                # Show limited results
                display_df = result.head(limit)
                console.print(display_df)

                if len(result) > limit:
                    console.print(f"\n[yellow]... and {len(result) - limit} more rows[/yellow]")

                # Export if requested
                if output:
                    exporter = DataExporter()
                    exporter.export_to_csv(result, output)
                    console.print(f"\n[green]Exported to {output}[/green]")
            else:
                console.print("[yellow]Query returned no rows[/yellow]")

    except Exception as e:
        console.print(f"\n[bold red]Query failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def info(
    db_path: Path = typer.Option(
        Path("./data/era5.duckdb"),
        "--db",
        help="DuckDB database path",
    ),
) -> None:
    """Show information about the ERA5 database.

    Lists all tables and their schemas.
    """
    console.print("\n[bold blue]Database Information[/bold blue]\n")

    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        sys.exit(1)

    try:
        config = DatabaseConfig(db_path=db_path, read_only=True)

        with DuckDBManager(config) as db:
            # Get list of tables
            tables = db.query("SHOW TABLES")

            if len(tables) > 0:
                console.print(f"[green]Found {len(tables)} table(s):[/green]\n")

                for table_name in tables["name"]:
                    console.print(f"[cyan]{table_name}[/cyan]")

                    # Get table schema
                    schema = db.query(f"DESCRIBE {table_name}")

                    table = Table(title=f"Schema: {table_name}")
                    table.add_column("Column", style="yellow")
                    table.add_column("Type", style="green")

                    for row in schema.iter_rows(named=True):
                        table.add_row(row["column_name"], row["column_type"])

                    console.print(table)
                    console.print()
            else:
                console.print("[yellow]No tables found in database[/yellow]")

    except Exception as e:
        console.print(f"\n[bold red]Info failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def export(
    parquet_dir: Path = typer.Argument(
        ...,
        help="Directory with Parquet files",
    ),
    output_file: Path = typer.Argument(
        ...,
        help="Output CSV file",
    ),
) -> None:
    """Export Parquet data to CSV format.

    Reads all Parquet files from a directory and exports to a single CSV.
    """
    console.print("\n[bold blue]Exporting to CSV[/bold blue]\n")

    try:
        exporter = DataExporter()
        exporter.export_parquet_to_csv(parquet_dir, output_file)
        console.print(f"\n[green]Exported to {output_file}[/green]")
    except Exception as e:
        console.print(f"\n[bold red]Export failed:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
