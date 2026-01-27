"""Command-line interface for ERA5-ETL."""

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from era5_etl.__version__ import __version__
from era5_etl.config import PipelineConfig

# Create CLI app
app = typer.Typer(
    name="era5-etl",
    help="Professional ETL pipeline for ERA5/ERA5-Land climate data from Copernicus CDS.",
    add_completion=False,
)

# Rich console for output
console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with Rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"ERA5-ETL version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    version: bool = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    """ERA5-ETL - Professional ETL pipeline for ERA5/ERA5-Land climate data."""
    setup_logging(verbose)


def _resolve_area(
    municipio: str | None = None,
    uf: str | None = None,
    regiao_imediata: str | None = None,
    regiao_intermediaria: str | None = None,
) -> list[float] | None:
    """Resolve geographic area from IBGE region options.

    Priority: municipio > regiao_imediata > regiao_intermediaria > uf (alone).

    Returns:
        Bounding box as [North, West, South, East], or None if no region specified.
    """
    if municipio:
        from era5_etl.utils.ibge_regions import RegionType, lookup_region_bbox

        area = lookup_region_bbox(RegionType.MUNICIPIO, municipio, uf=uf)
        console.print(
            f"[cyan]Area from municipality '{municipio}': "
            f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}[/cyan]"
        )
        return area
    elif regiao_imediata:
        from era5_etl.utils.ibge_regions import RegionType, lookup_region_bbox

        area = lookup_region_bbox(RegionType.RG_IMEDIATA, regiao_imediata)
        console.print(
            f"[cyan]Area from immediate region '{regiao_imediata}': "
            f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}[/cyan]"
        )
        return area
    elif regiao_intermediaria:
        from era5_etl.utils.ibge_regions import RegionType, lookup_region_bbox

        area = lookup_region_bbox(RegionType.RG_INTERMEDIARIA, regiao_intermediaria)
        console.print(
            f"[cyan]Area from intermediate region '{regiao_intermediaria}': "
            f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}[/cyan]"
        )
        return area
    elif uf and not municipio:
        from era5_etl.utils.ibge_regions import RegionType, lookup_region_bbox

        area = lookup_region_bbox(RegionType.UF, uf)
        console.print(
            f"[cyan]Area from UF '{uf}': "
            f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}[/cyan]"
        )
        return area

    return None


@app.command()
def pipeline(
    data_dir: Path = typer.Option(
        Path("./data"),
        "--data-dir",
        "-d",
        help="Base directory for data storage",
    ),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset (era5 or era5-land)"),
    start_date: str = typer.Option("2020-01-01", "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    variables: list[str] | None = typer.Option(None, "--var", help="Variables to download"),
    compression: str = typer.Option("zstd", "--compression", help="Parquet compression"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    workers: int | None = typer.Option(None, "--workers", "-w", help="Number of parallel workers for conversion"),
    municipio: str | None = typer.Option(None, "--municipio", help="Municipality name (IBGE)"),
    uf: str | None = typer.Option(None, "--uf", help="State (UF) abbreviation for disambiguation or download"),
    regiao_imediata: str | None = typer.Option(None, "--regiao-imediata", help="Immediate region name (IBGE)"),
    regiao_intermediaria: str | None = typer.Option(None, "--regiao-intermediaria", help="Intermediate region name (IBGE)"),
) -> None:
    """Execute the complete ERA5 data pipeline (download + convert to Parquet)."""
    from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

    console.print("\n[bold blue]ERA5-ETL Pipeline[/bold blue]\n")

    # Resolve geographic area from region options
    area = _resolve_area(
        municipio=municipio,
        uf=uf,
        regiao_imediata=regiao_imediata,
        regiao_intermediaria=regiao_intermediaria,
    )

    config = PipelineConfig.create(
        base_dir=data_dir,
        dataset=dataset,  # type: ignore[arg-type]
        start_date=start_date,
        end_date=end_date,
        variables=variables,
        override=override,
        compression=compression,  # type: ignore[arg-type]
        area=area,
    )
    config.transform.max_workers = workers

    try:
        era5_pipeline = ERA5Pipeline(config)
        context = era5_pipeline.run()

        console.print("\n[bold green]Pipeline completed successfully![/bold green]\n")

        table = Table(title="Pipeline Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        if context.get_metadata("download_count"):
            table.add_row("Files downloaded", str(context.get_metadata("download_count")))
        if context.get_metadata("converted_count"):
            table.add_row("Files converted", str(context.get_metadata("converted_count")))
        if context.get_metadata("view_name"):
            table.add_row("DuckDB VIEW", context.get_metadata("view_name"))
        if context.get_metadata("database_path"):
            table.add_row("Database", context.get_metadata("database_path"))

        console.print(table)

    except Exception as e:
        console.print(f"\n[bold red]Pipeline failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def download(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset (era5 or era5-land)"),
    start_date: str = typer.Option("2020-01-01", "--start-date", help="Start date"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date"),
    variables: list[str] | None = typer.Option(None, "--var", help="Variables to download"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    municipio: str | None = typer.Option(None, "--municipio", help="Municipality name (IBGE)"),
    uf: str | None = typer.Option(None, "--uf", help="State (UF) abbreviation for disambiguation or download"),
    regiao_imediata: str | None = typer.Option(None, "--regiao-imediata", help="Immediate region name (IBGE)"),
    regiao_intermediaria: str | None = typer.Option(None, "--regiao-intermediaria", help="Intermediate region name (IBGE)"),
) -> None:
    """Download ERA5/ERA5-Land data from Copernicus CDS."""
    from era5_etl.download.cds_downloader import CDSDownloader

    console.print("\n[bold blue]Downloading ERA5 data[/bold blue]\n")

    # Resolve geographic area from region options
    area = _resolve_area(
        municipio=municipio,
        uf=uf,
        regiao_imediata=regiao_imediata,
        regiao_intermediaria=regiao_intermediaria,
    )

    config = PipelineConfig.create(
        base_dir=data_dir,
        dataset=dataset,  # type: ignore[arg-type]
        start_date=start_date,
        end_date=end_date,
        variables=variables,
        override=override,
        area=area,
    )

    try:
        downloader = CDSDownloader(config.download)
        files = downloader.download()
        console.print(f"\n[green]Downloaded {len(files)} files successfully![/green]")
    except Exception as e:
        console.print(f"\n[bold red]Download failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def convert(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset name"),
    compression: str = typer.Option("zstd", "--compression", help="Parquet compression"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    workers: int | None = typer.Option(None, "--workers", "-w", help="Number of parallel workers"),
) -> None:
    """Convert NetCDF files to Parquet format."""
    from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter

    console.print("\n[bold blue]Converting NetCDF to Parquet[/bold blue]\n")

    config = PipelineConfig.create(
        base_dir=data_dir,
        dataset=dataset,  # type: ignore[arg-type]
        override=override,
        compression=compression,  # type: ignore[arg-type]
    )

    try:
        converter = NetCDFToParquetConverter(
            transform_config=config.transform,
            storage_config=config.storage,
            output_dir=config.get_parquet_dir(),
        )
        stats = converter.convert_directory(config.get_netcdf_dir(), max_workers=workers)

        console.print("\n[green]Conversion complete![/green]")
        console.print(f"  Converted: {stats['converted']}")
        console.print(f"  Skipped: {stats['skipped']}")
        console.print(f"  Failed: {stats['failed']}")
    except Exception as e:
        console.print(f"\n[bold red]Conversion failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL query to execute"),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output CSV file"),
    limit: int = typer.Option(100, "--limit", "-n", help="Limit displayed results"),
) -> None:
    """Execute SQL query on ERA5 Parquet data."""
    import duckdb

    from era5_etl.storage.parquet_manager import ParquetManager

    console.print("\n[bold blue]Executing query[/bold blue]\n")

    config = PipelineConfig.create(base_dir=data_dir, dataset=dataset)  # type: ignore[arg-type]
    manager = ParquetManager(config.storage.database_dir, config.dataset_name)

    if not manager.exists():
        console.print("[red]No Parquet data found. Run the pipeline first.[/red]")
        sys.exit(1)

    try:
        conn = duckdb.connect(":memory:")
        manager.create_duckdb_view(conn, "era5")

        result = conn.execute(sql).pl()
        console.print(f"[green]Query returned {len(result):,} rows[/green]\n")

        display_df = result.head(limit)
        console.print(display_df)

        if len(result) > limit:
            console.print(f"\n[yellow]... and {len(result) - limit} more rows[/yellow]")

        if output:
            result.write_csv(output)
            console.print(f"\n[green]Exported to {output}[/green]")

        conn.close()
    except Exception as e:
        console.print(f"\n[bold red]Query failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def info(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset name"),
) -> None:
    """Show information about ERA5 data storage."""
    from era5_etl.storage.parquet_manager import ParquetManager

    console.print("\n[bold blue]ERA5-ETL Data Information[/bold blue]\n")

    config = PipelineConfig.create(base_dir=data_dir, dataset=dataset)  # type: ignore[arg-type]
    manager = ParquetManager(config.storage.database_dir, config.dataset_name)

    if not manager.exists():
        console.print("[yellow]No Parquet data found.[/yellow]")
        return

    stats = manager.get_storage_stats()
    size_mb = stats.total_size_bytes / (1024 * 1024)

    table = Table(title=f"Storage: {dataset}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Parquet files", str(stats.total_files))
    table.add_row("Total size", f"{size_mb:.2f} MB")
    table.add_row("Partitions", str(len(stats.partitions)))
    table.add_row("Processed files", str(len(manager.get_processed_files())))
    console.print(table)


@app.command()
def ibge(
    output: Path = typer.Option(
        Path("./data/ibge_locais.parquet"),
        "--output",
        "-o",
        help="Output path for IBGE Parquet file",
    ),
) -> None:
    """Generate IBGE municipalities Parquet from bundled CSV."""
    from era5_etl.utils.ibge_loader import generate_ibge_parquet

    console.print("\n[bold blue]Generating IBGE Parquet[/bold blue]\n")

    try:
        result_path = generate_ibge_parquet(output)
        console.print(f"[green]Generated: {result_path}[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Failed:[/bold red] {e}")
        sys.exit(1)


@app.command()
def variables(
    dataset: str | None = typer.Option(
        None, "--dataset", help="Filter by dataset (era5 or era5-land)"
    ),
) -> None:
    """List available ERA5/ERA5-Land variables for download."""
    from era5_etl.utils.variables import list_variables

    console.print("\n[bold blue]Available ERA5 Variables[/bold blue]\n")

    df = list_variables(dataset)

    if len(df) == 0:
        console.print("[yellow]No variables found for the specified dataset.[/yellow]")
        return

    table = Table(title=f"Variables{f' ({dataset})' if dataset else ' (all datasets)'}")
    table.add_column("API Name", style="cyan", no_wrap=True)
    table.add_column("Full Name", style="green")
    table.add_column("Description")
    table.add_column("Unit", style="yellow", no_wrap=True)
    table.add_column("Datasets", style="magenta", no_wrap=True)

    for row in df.iter_rows(named=True):
        table.add_row(
            row["api_name"],
            row["full_name"],
            row["description"],
            row["unit"],
            row["datasets"],
        )

    console.print(table)
    console.print(f"\n[green]Total: {len(df)} variables[/green]")


if __name__ == "__main__":
    app()
