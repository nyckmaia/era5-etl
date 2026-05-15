"""Command-line interface for ERA5-ETL.

Commands:
    pipeline    Download + convert end-to-end (era5, era5-land, or both).
    download    Download only.
    convert     NetCDF -> Parquet only.
    update      Detect missing chunks in the manifest and fetch only those.
    status      Show per-dataset storage stats (replaces the old `info`).
    query       Run a SQL query against the dataset's DuckDB view.
    variables   List variables available for a dataset.
    ibge        Generate IBGE municipality lookup parquet.
    ui          Launch the local FastAPI + React web UI (Phase 4+).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from era5_etl.__version__ import __version__
from era5_etl.config import PipelineConfig
from era5_etl.datasets import DatasetRegistry

app = typer.Typer(
    name="era5-etl",
    help="Professional ETL pipeline for ERA5/ERA5-Land climate data from Copernicus CDS.",
    add_completion=False,
)
console = Console()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    install_cdsapi_log_filter()


_ARCO_LOG_NEEDLES = (
    "Analysis Ready Cloud Optimized",
    "reanalysis-era5-land-timeseries",
    "reanalysis-era5-single-levels-timeseries",
)


def _arco_notice_filter(record: logging.LogRecord) -> bool:
    """Drop cdsapi log records that advertise the ARCO/Zarr time-series endpoint.

    The notice is irrelevant for area-bbox downloads (which is what this
    project does) and clutters every run. The README documents the ARCO
    endpoint for users who want to fetch single-point time-series.
    """
    return not any(needle in record.getMessage() for needle in _ARCO_LOG_NEEDLES)


def install_cdsapi_log_filter() -> None:
    """Attach the ARCO-notice filter to the ``cdsapi`` logger once."""
    cdsapi_logger = logging.getLogger("cdsapi")
    for existing in cdsapi_logger.filters:
        if getattr(existing, "_era5_etl_arco", False):
            return
    flt = logging.Filter()
    flt.filter = _arco_notice_filter  # type: ignore[method-assign]
    flt._era5_etl_arco = True  # type: ignore[attr-defined]
    cdsapi_logger.addFilter(flt)


def version_callback(value: bool) -> None:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_area(
    pais: str = "Brasil",
    municipio: str | None = None,
    uf: str | None = None,
    regiao_imediata: str | None = None,
    regiao_intermediaria: str | None = None,
) -> list[float]:
    """Resolve a bbox from country + IBGE region options.

    Resolution order: the most-specific flag wins. Order of specificity
    (smallest area first) is: ``municipio`` > ``regiao_imediata`` >
    ``regiao_intermediaria`` > ``uf`` > ``pais``.

    ``municipio`` may be combined with ``uf`` to disambiguate homonyms; any
    other pair of region flags raises ``typer.BadParameter``. A non-Brazilian
    ``pais`` combined with any sub-region flag also raises (IBGE loaders only
    cover Brazil).

    Always returns a ``[N, W, S, E]`` list.
    """
    from era5_etl.utils.ibge_regions import RegionType, lookup_region_bbox

    sub_flags = {
        "--municipio": municipio,
        "--regiao-imediata": regiao_imediata,
        "--regiao-intermediaria": regiao_intermediaria,
        "--uf": uf,
    }
    active = [name for name, value in sub_flags.items() if value]
    # municipio + uf is a permitted combo (uf disambiguates municipio).
    if set(active) - {"--municipio", "--uf"} and len(active) > 1:
        raise typer.BadParameter(
            "Use at most one sub-region flag at a time "
            f"(got: {', '.join(active)}). "
            "Only --municipio + --uf may be combined (to disambiguate municipalities)."
        )
    if active and pais.lower() != "brasil":
        raise typer.BadParameter(
            f"Sub-region flags ({', '.join(active)}) are only supported for "
            f"--pais Brasil; got --pais {pais!r}."
        )

    if municipio:
        area = lookup_region_bbox(RegionType.MUNICIPIO, municipio, uf=uf)
        _print_area("municipality", municipio, area)
        return area
    if regiao_imediata:
        area = lookup_region_bbox(RegionType.RG_IMEDIATA, regiao_imediata)
        _print_area("immediate region", regiao_imediata, area)
        return area
    if regiao_intermediaria:
        area = lookup_region_bbox(RegionType.RG_INTERMEDIARIA, regiao_intermediaria)
        _print_area("intermediate region", regiao_intermediaria, area)
        return area
    if uf:
        area = lookup_region_bbox(RegionType.UF, uf)
        _print_area("UF", uf, area)
        return area

    try:
        area = lookup_region_bbox(RegionType.PAIS, pais)
    except (ValueError, FileNotFoundError) as exc:
        raise typer.BadParameter(
            f"Country '{pais}' is not supported yet. Add a row to the bundled "
            f"pais.csv to enable it. Underlying error: {exc}"
        ) from exc
    _print_area("country", pais, area)
    return area


def _print_area(kind: str, name: str, area: list[float]) -> None:
    console.print(
        f"[cyan]Area from {kind} '{name}': "
        f"N={area[0]}, W={area[1]}, S={area[2]}, E={area[3]}[/cyan]"
    )


def _expand_datasets(name: str) -> list[str]:
    """``"all"`` -> all registered datasets; otherwise validate and return a single name."""
    if name == "all":
        return list(DatasetRegistry.names())
    if name not in DatasetRegistry.names():
        raise typer.BadParameter(
            f"Unknown dataset '{name}'. Available: {', '.join(DatasetRegistry.names())} or 'all'."
        )
    return [name]


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


@app.command()
def pipeline(
    data_dir: Path = typer.Option(
        Path("./data"),
        "--data-dir",
        "-d",
        help="Base directory for data storage (parent of climate_data_store_db/)",
    ),
    dataset: str = typer.Option(
        "era5-land",
        "--dataset",
        help="Dataset (era5, era5-land, or 'all' to run both sequentially)",
    ),
    start_date: str = typer.Option("2020-01-01", "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    variables: list[str] | None = typer.Option(None, "--var", help="Variables to download"),
    compression: str = typer.Option("zstd", "--compression", help="Parquet compression"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    workers: int | None = typer.Option(
        None, "--workers", "-w", help="Parallel workers for conversion"
    ),
    pais: str = typer.Option(
        "Brasil",
        "--pais",
        help="Country (default: Brasil). Without sub-region flags, resolves to the country bbox.",
    ),
    municipio: str | None = typer.Option(None, "--municipio", help="Municipality name (IBGE)"),
    uf: str | None = typer.Option(None, "--uf", help="State (UF) abbreviation"),
    regiao_imediata: str | None = typer.Option(
        None, "--regiao-imediata", help="Immediate region name (IBGE)"
    ),
    regiao_intermediaria: str | None = typer.Option(
        None, "--regiao-intermediaria", help="Intermediate region name (IBGE)"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Plan the requests and print the size estimate without contacting CDS",
    ),
) -> None:
    """Execute the complete ERA5 data pipeline (download + convert)."""
    area = _resolve_area(pais, municipio, uf, regiao_imediata, regiao_intermediaria)
    datasets = _expand_datasets(dataset)

    for ds_name in datasets:
        console.print(f"\n[bold blue]ERA5-ETL pipeline -- {ds_name}[/bold blue]\n")
        config = PipelineConfig.create(
            base_dir=data_dir,
            dataset=ds_name,
            start_date=start_date,
            end_date=end_date,
            variables=variables,
            override=override,
            compression=compression,  # type: ignore[arg-type]
            area=area,
        )
        config.transform.max_workers = workers

        if dry_run:
            _print_plan(config)
            continue

        try:
            from era5_etl.pipeline.era5_pipeline import ERA5Pipeline

            era5_pipeline = ERA5Pipeline(config)
            context = era5_pipeline.run()
            _print_summary(context, ds_name)
        except Exception as exc:
            console.print(f"\n[bold red]Pipeline failed for {ds_name}:[/bold red] {exc}")
            sys.exit(1)


def _print_plan(
    config: PipelineConfig,
    *,
    apply_diff: bool = False,
    data_dir: Path | None = None,
) -> None:
    from era5_etl.download.request_planner import plan_requests, plan_with_diff
    from era5_etl.download.size_estimator import estimate_request_size

    if apply_diff and data_dir is not None:
        chunks = plan_with_diff(config.download, data_dir)
    else:
        chunks = plan_requests(config.download)
    total_mb = 0.0
    for c in chunks:
        est = estimate_request_size(
            num_variables=len(c.variables),
            num_hours=len(c.hours),
            num_days=len(c.days),
            area=list(c.area),
            dataset=c.dataset,
            max_bytes=config.download.max_request_bytes,
        )
        total_mb += est.estimated_mb

    table = Table(title=f"Plan -- {config.dataset_name}")
    table.add_column("#")
    table.add_column("chunk_id", style="cyan")
    table.add_column("year-month")
    table.add_column("days")
    table.add_column("variables")
    table.add_column("area (N,W,S,E)")
    for i, c in enumerate(chunks, 1):
        days_repr = f"{c.days[0]:02d}-{c.days[-1]:02d}" if c.days else "-"
        table.add_row(
            str(i),
            c.chunk_id,
            f"{c.year}-{c.month:02d}",
            days_repr,
            ", ".join(c.variables),
            f"{c.area[0]:.2f},{c.area[1]:.2f},{c.area[2]:.2f},{c.area[3]:.2f}",
        )
    console.print(table)
    console.print(f"[green]Total planned chunks: {len(chunks)}[/green]")
    console.print(f"[green]Estimated total uncompressed size: {total_mb:,.1f} MB[/green]")


def _print_summary(context, dataset: str) -> None:
    console.print(f"\n[bold green]Pipeline completed -- {dataset}[/bold green]\n")
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


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


def _auto_rebuild_coverage(data_dir: Path, dataset_name: str) -> None:
    """Trigger ``ensure_coverage_index`` once and surface a single info line.

    Called from ``download`` and ``update`` before the actual run starts, so
    the coverage index is in sync with on-disk parquet even when the user
    has been running pre-v0.6.0 versions or has manually removed
    ``_coverage.duckdb``.
    """
    from era5_etl.storage.coverage import ensure_coverage_index

    rebuilt = ensure_coverage_index(dataset_name, data_dir)
    if rebuilt:
        console.print(
            f"[cyan]Coverage index for {dataset_name} was missing; rebuilt from "
            f"existing parquet partitions.[/cyan]"
        )


@app.command()
def download(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset (era5 or era5-land)"),
    start_date: str = typer.Option("2020-01-01", "--start-date", help="Start date"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date"),
    variables: list[str] | None = typer.Option(None, "--var", help="Variables to download"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    pais: str = typer.Option(
        "Brasil",
        "--pais",
        help="Country (default: Brasil). Without sub-region flags, resolves to the country bbox.",
    ),
    municipio: str | None = typer.Option(None, "--municipio", help="Municipality name (IBGE)"),
    uf: str | None = typer.Option(None, "--uf", help="State (UF) abbreviation"),
    regiao_imediata: str | None = typer.Option(
        None, "--regiao-imediata", help="Immediate region name (IBGE)"
    ),
    regiao_intermediaria: str | None = typer.Option(
        None, "--regiao-intermediaria", help="Intermediate region name (IBGE)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, do not download"),
    apply_diff: bool = typer.Option(
        True,
        "--apply-diff/--no-apply-diff",
        help=(
            "Subtract cells already present in the coverage index before "
            "downloading (smart diff). Default: enabled (new in v0.6.0). "
            "Pass --no-apply-diff to restore pre-v0.6.0 behavior of always "
            "planning the full request."
        ),
    ),
) -> None:
    """Download ERA5/ERA5-Land data from Copernicus CDS."""
    area = _resolve_area(pais, municipio, uf, regiao_imediata, regiao_intermediaria)
    for ds_name in _expand_datasets(dataset):
        console.print(f"\n[bold blue]Downloading {ds_name}[/bold blue]\n")
        _auto_rebuild_coverage(data_dir, ds_name)
        config = PipelineConfig.create(
            base_dir=data_dir,
            dataset=ds_name,
            start_date=start_date,
            end_date=end_date,
            variables=variables,
            override=override,
            area=area,
        )

        if dry_run:
            _print_plan(config, apply_diff=apply_diff, data_dir=data_dir)
            continue

        try:
            from era5_etl.download.cds_downloader import CDSDownloader

            downloader = CDSDownloader(config.download)
            files = downloader.download(apply_diff=apply_diff, base_dir=data_dir)
            console.print(f"\n[green]Downloaded {len(files)} files for {ds_name}[/green]")
        except Exception as exc:
            console.print(f"\n[bold red]Download failed for {ds_name}:[/bold red] {exc}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


@app.command()
def convert(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset name"),
    compression: str = typer.Option("zstd", "--compression", help="Parquet compression"),
    override: bool = typer.Option(False, "--override", help="Override existing files"),
    workers: int | None = typer.Option(None, "--workers", "-w", help="Parallel workers"),
) -> None:
    """Convert NetCDF files to Parquet format."""
    from era5_etl.transform.netcdf_to_parquet import NetCDFToParquetConverter

    for ds_name in _expand_datasets(dataset):
        console.print(f"\n[bold blue]Converting -- {ds_name}[/bold blue]\n")
        config = PipelineConfig.create(
            base_dir=data_dir,
            dataset=ds_name,
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
            console.print(
                f"[green]Done -- {ds_name}: converted={stats['converted']}, "
                f"skipped={stats['skipped']}, failed={stats['failed']}[/green]"
            )
        except Exception as exc:
            console.print(f"\n[bold red]Conversion failed for {ds_name}:[/bold red] {exc}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# update (incremental)
# ---------------------------------------------------------------------------


@app.command()
def update(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option(
        "era5-land", "--dataset", help="Dataset (era5, era5-land, or 'all')"
    ),
    start_date: str = typer.Option("2020-01-01", "--start-date", help="Start date"),
    end_date: str | None = typer.Option(None, "--end-date", help="End date"),
    variables: list[str] | None = typer.Option(None, "--var", help="Variables"),
    pais: str = typer.Option(
        "Brasil",
        "--pais",
        help="Country (default: Brasil). Without sub-region flags, resolves to the country bbox.",
    ),
    municipio: str | None = typer.Option(None, "--municipio", help="Municipality name (IBGE)"),
    uf: str | None = typer.Option(None, "--uf", help="State (UF) abbreviation"),
    regiao_imediata: str | None = typer.Option(
        None, "--regiao-imediata", help="Immediate region name (IBGE)"
    ),
    regiao_intermediaria: str | None = typer.Option(
        None, "--regiao-intermediaria", help="Intermediate region name (IBGE)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Only list the chunks that would be downloaded"
    ),
) -> None:
    """Incrementally download chunks for grid cells not yet in the manifest.

    Computes the missing region per ``(variable, year, month)`` as the
    requested area minus already-covered rectangles, then plans chunks only
    for what's missing. Robust to area changes between runs (does not depend
    on chunk_id collisions). Use with cron to keep a dataset up to date.
    """
    from era5_etl.download.cds_downloader import CDSDownloader
    from era5_etl.download.request_planner import plan_incremental_requests
    from era5_etl.storage.manifest import Manifest

    area = _resolve_area(pais, municipio, uf, regiao_imediata, regiao_intermediaria)

    for ds_name in _expand_datasets(dataset):
        console.print(f"\n[bold blue]Update -- {ds_name}[/bold blue]\n")
        _auto_rebuild_coverage(data_dir, ds_name)
        config = PipelineConfig.create(
            base_dir=data_dir,
            dataset=ds_name,
            start_date=start_date,
            end_date=end_date,
            variables=variables,
            area=area,
        )
        manifest = Manifest(data_dir, ds_name)
        missing = plan_incremental_requests(config.download, manifest)

        console.print(
            f"Manifest records: {len(manifest)}; missing chunk(s) to download: {len(missing)}"
        )

        if dry_run or not missing:
            for c in missing:
                area_repr = f"{c.area[0]:.2f},{c.area[1]:.2f},{c.area[2]:.2f},{c.area[3]:.2f}"
                console.print(
                    f"  - [yellow]{c.chunk_id}[/yellow]  vars={list(c.variables)}  area=[{area_repr}]"
                )
            continue

        try:
            downloader = CDSDownloader(config.download, manifest=manifest)
            downloader.download_chunks(missing)
            console.print(f"[green]Downloaded {len(missing)} missing chunk(s).[/green]")
        except Exception as exc:
            console.print(f"\n[bold red]Update failed for {ds_name}:[/bold red] {exc}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option(
        "all", "--dataset", help="Dataset to report on (era5, era5-land, or 'all')"
    ),
) -> None:
    """Report per-dataset storage stats and manifest coverage."""
    from era5_etl.storage.manifest import Manifest
    from era5_etl.storage.parquet_manager import ParquetManager

    console.print(f"\n[bold blue]Storage status -- base={data_dir}[/bold blue]\n")

    for ds_name in _expand_datasets(dataset):
        console.print(f"[bold cyan]Dataset: {ds_name}[/bold cyan]")
        manager = ParquetManager(data_dir, ds_name)
        manifest = Manifest(data_dir, ds_name)

        stats = manager.get_storage_stats()
        size_mb = stats.total_size_bytes / (1024 * 1024)

        table = Table(box=None)
        table.add_column("metric", style="cyan")
        table.add_column("value", style="green")
        table.add_row("Parquet files", str(stats.total_files))
        table.add_row("Total size", f"{size_mb:,.2f} MB")
        table.add_row("Partitions (date=)", str(len(stats.partitions)))
        table.add_row("Manifest chunks", str(len(manifest)))
        if stats.partitions:
            first, last = stats.partitions[0], stats.partitions[-1]
            table.add_row("First partition", first)
            table.add_row("Last partition", last)
        table.add_row("Parquet directory", str(manager.parquet_dir))
        console.print(table)
        console.print()


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------


@app.command()
def dedup(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option(
        "all", "--dataset", help="Dataset to dedup (era5, era5-land, or 'all')"
    ),
    compression: str = typer.Option("zstd", "--compression", help="Parquet compression"),
) -> None:
    """Rewrite each partition with duplicate ``(lat, lon, hour_utc)`` rows collapsed.

    One-off migration for datasets created before merge-on-key writes landed.
    Idempotent: re-running after a clean dataset is a no-op.
    """
    from era5_etl.storage.parquet_manager import ParquetManager

    for ds_name in _expand_datasets(dataset):
        console.print(f"\n[bold blue]Dedup -- {ds_name}[/bold blue]")
        manager = ParquetManager(data_dir, ds_name)
        if not manager.exists():
            console.print(f"  [yellow]No Parquet data for {ds_name}, skipping.[/yellow]")
            continue
        stats = manager.dedup_existing_partitions(
            compression=compression,  # type: ignore[arg-type]
        )
        table = Table(box=None)
        table.add_column("metric", style="cyan")
        table.add_column("value", style="green")
        table.add_row("Partitions processed", str(stats["partitions_processed"]))
        table.add_row("Rows before", f"{stats['rows_before']:,}")
        table.add_row("Rows after", f"{stats['rows_after']:,}")
        table.add_row(
            "Duplicates removed",
            f"{stats['rows_before'] - stats['rows_after']:,}",
        )
        console.print(table)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL query to execute"),
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option("era5-land", "--dataset", help="Dataset name"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output CSV file"),
    limit: int = typer.Option(100, "--limit", "-n", help="Limit displayed results"),
) -> None:
    """Execute a SQL query against the dataset's Parquet view."""
    import duckdb

    from era5_etl.storage.parquet_manager import ParquetManager

    if dataset == "all":
        console.print("[red]--dataset all is not supported for query; pick one.[/red]")
        sys.exit(2)

    manager = ParquetManager(data_dir, dataset)
    if not manager.exists():
        console.print("[red]No Parquet data found. Run the pipeline first.[/red]")
        sys.exit(1)

    try:
        conn = duckdb.connect(":memory:")
        view_name = dataset.replace("-", "_") + "_view"
        manager.create_duckdb_view(conn, view_name)
        result = conn.execute(sql).pl()
        console.print(f"[green]Query returned {len(result):,} rows[/green]\n")
        console.print(result.head(limit))
        if len(result) > limit:
            console.print(f"\n[yellow]... and {len(result) - limit} more rows[/yellow]")
        if output:
            result.write_csv(output)
            console.print(f"\n[green]Exported to {output}[/green]")
        conn.close()
    except Exception as exc:
        console.print(f"\n[bold red]Query failed:[/bold red] {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# ibge / variables / ui
# ---------------------------------------------------------------------------


@app.command()
def ibge(
    output: Path = typer.Option(
        Path("./data/ibge_locais.parquet"),
        "--output",
        "-o",
        help="Output path for IBGE Parquet file",
    ),
) -> None:
    """Generate the IBGE municipalities Parquet from the bundled CSV."""
    from era5_etl.utils.ibge_loader import generate_ibge_parquet

    try:
        result_path = generate_ibge_parquet(output)
        console.print(f"[green]Generated: {result_path}[/green]")
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@app.command()
def variables(
    dataset: str | None = typer.Option(
        None, "--dataset", help="Filter by dataset (era5 or era5-land)"
    ),
) -> None:
    """List available ERA5 / ERA5-Land variables."""
    from era5_etl.utils.variables import list_variables

    df = list_variables(dataset)
    if len(df) == 0:
        console.print("[yellow]No variables found.[/yellow]")
        return

    table = Table(title=f"Variables{f' ({dataset})' if dataset else ' (all datasets)'}")
    table.add_column("API name", style="cyan", no_wrap=True)
    table.add_column("Full name", style="green")
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


@app.command()
def ui(
    data_dir: Path | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help=(
            "Base directory for data storage. If omitted, the path saved in "
            "the web UI Settings (persisted user config) is used; only if "
            "none was ever saved does it fall back to ./data."
        ),
    ),
    port: int = typer.Option(8788, "--port", help="HTTP port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser"),
) -> None:
    """Launch the local web UI (FastAPI + React)."""
    try:
        import uvicorn  # type: ignore[import-untyped]

        from era5_etl.web.server import create_app
    except ImportError as exc:
        console.print(f"[red]Web UI dependencies not installed: {exc}[/red]")
        console.print(
            "Install web extras: [cyan]pip install 'era5-etl[web]'[/cyan] or "
            "the full requirements."
        )
        sys.exit(1)

    if not no_browser:
        import threading
        import webbrowser

        def _open():
            import time as _t

            _t.sleep(1.0)
            webbrowser.open(f"http://127.0.0.1:{port}/")

        threading.Thread(target=_open, daemon=True).start()

    # Resolve the storage root. Precedence:
    #   1. explicit --data-dir on the CLI (also persisted so the UI agrees)
    #   2. the data_dir saved via the web UI Settings (persisted user config)
    #   3. ./data fallback (first run, nothing configured yet)
    from era5_etl.web.user_config import load_user_config, update_user_config

    if data_dir is not None:
        resolved_dir = Path(data_dir).expanduser().resolve()
        update_user_config(data_dir=str(resolved_dir))
        source = "--data-dir flag"
    else:
        cfg = load_user_config()
        if cfg.data_dir.strip():
            resolved_dir = Path(cfg.data_dir).expanduser().resolve()
            source = "web UI Settings"
        else:
            resolved_dir = Path("./data").expanduser().resolve()
            source = "./data fallback (no Settings saved yet)"

    app_instance = create_app(resolved_dir)
    console.print(f"[green]Starting ERA5-ETL UI on http://127.0.0.1:{port}/[/green]")
    console.print(
        f"[cyan]Storage root:[/cyan] {resolved_dir} "
        f"[dim](from {source}; climate_data_store_db/ + _tmp_netcdf/ live here)[/dim]"
    )
    uvicorn.run(app_instance, host="127.0.0.1", port=port, log_level="info")


# ---------------------------------------------------------------------------
# coverage (per-dataset cell-level inventory index)
# ---------------------------------------------------------------------------


coverage_app = typer.Typer(
    name="coverage",
    help="Manage the per-dataset coverage index (_coverage.duckdb).",
    add_completion=False,
)
app.add_typer(coverage_app, name="coverage")


@coverage_app.command("rebuild")
def coverage_rebuild(
    data_dir: Path = typer.Option(Path("./data"), "--data-dir", "-d", help="Base data directory"),
    dataset: str = typer.Option(
        "all", "--dataset", help="Dataset to rebuild (era5, era5-land, or 'all')"
    ),
) -> None:
    """Rebuild the cell-level coverage index from the on-disk parquet files.

    The coverage index is derived state -- it lives in
    ``<base>/climate_data_store_db/<dataset>/_coverage.duckdb`` and tracks
    which (latitude, longitude, date, variable) cells have data, with a
    24-bit hours bitmap for hour-level precision.

    Idempotent: running twice produces the same end state. Use after a bulk
    backfill or whenever the index is suspected to be stale.
    """
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from era5_etl.storage.coverage import rebuild_from_parquet

    for ds_name in _expand_datasets(dataset):
        console.print(f"\n[bold blue]Rebuilding coverage index -- {ds_name}[/bold blue]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            stats = rebuild_from_parquet(ds_name, data_dir, progress=progress)

        table = Table(box=None)
        table.add_column("metric", style="cyan")
        table.add_column("value", style="green")
        table.add_row("Files processed", str(stats.get("files_processed", 0)))
        table.add_row("Total rows in index", f"{stats['total_rows']:,}")
        table.add_row("Distinct cells", f"{stats['n_cells']:,}")
        table.add_row("Distinct dates", f"{stats['n_dates']:,}")
        table.add_row("Distinct variables", str(stats["n_variables"]))
        table.add_row("DuckDB file size", f"{stats['db_size_bytes'] / (1024 * 1024):,.2f} MB")
        console.print(table)


# Hide unused datetime import (used only by web in some flows). Keeping it here is harmless,
# but ruff will complain if truly unused. We reference it lazily below.
_ = datetime


if __name__ == "__main__":
    app()
