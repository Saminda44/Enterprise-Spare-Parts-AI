"""Command line entry point. A scheduler calls the same commands a planner does."""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import typer

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.settings import get_settings
from src.refresh import SOURCE_WORKBOOKS, source_workbook_path
from src.stages import load_stages

load_stages()

app = typer.Typer(add_completion=False, help="Yamaha spare-parts planning pipeline.")


def _console_safe(value: str, encoding: str | None = None) -> str:
    """Keep reports printable in Windows consoles with legacy code pages."""
    codec = encoding or sys.stdout.encoding or "utf-8"
    return value.encode(codec, errors="backslashreplace").decode(codec)


def _context(as_of: str | None) -> PlanningContext:
    settings = get_settings()
    when = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else date.today()
    return PlanningContext(
        as_of=when,
        lead_time_months=settings.lead_time_months,
        review_period_months=settings.review_period_months,
        plant=settings.plant,
        currency=settings.currency,
        config={"on_order_interpretation": settings.on_order_interpretation},
    )


@app.command()
def stages() -> None:
    """List the registered stages and what each depends on."""
    if not REGISTRY.stages:
        typer.echo("no stages registered yet")
        raise typer.Exit()
    for name in REGISTRY.order():
        stage = REGISTRY.get(name)
        deps = ", ".join(stage.depends_on) or "-"
        typer.echo(f"{name:<28} depends_on: {deps:<40} {stage.description}")


@app.command()
def ingest(force: bool = typer.Option(False, help="Re-convert even if the hash matches.")) -> None:
    """Convert the source workbooks to parquet. Idempotent — unchanged files are skipped."""
    from src.io.excel import workbook_sheets, workbook_to_parquet

    settings = get_settings()
    settings.ensure_dirs()
    typer.echo(f"source dir: {settings.raw_dir}")
    failures = 0
    for name, sheets in SOURCE_WORKBOOKS.items():
        path = source_workbook_path(settings.raw_dir, name)
        if not path.exists():
            typer.echo(f"  {name:<24} MISSING")
            failures += 1
            continue
        targets: list[str | int] = list(workbook_sheets(path)) if sheets == "*" else [0]
        for sheet in targets:
            label = name if sheet == 0 else f"{name}[{sheet}]"
            try:
                result = workbook_to_parquet(path, sheet=sheet, force=force)
            except Exception as exc:  # noqa: BLE001 — reported, next file still runs
                typer.echo(f"  {label:<34} FAILED  {type(exc).__name__}: {exc}")
                failures += 1
                continue
            action = "converted" if result.converted else "unchanged"
            note = (
                f"  coerced to text: {', '.join(result.coerced_to_text)}"
                if result.coerced_to_text
                else ""
            )
            typer.echo(
                f"  {label:<34} {action:<10} {result.rows:>9,} rows x "
                f"{result.columns:>3} cols{note}"
            )
    if failures:
        typer.echo(f"{failures} source(s) failed or missing")
        raise typer.Exit(1)


@app.command()
def run(
    as_of: str = typer.Option(None, help="Cycle date, YYYY-MM-DD. Defaults to today."),
    only: list[str] = typer.Option(None, help="Run these stages and their dependencies."),
    skip: list[str] = typer.Option(
        None, help="Treat these stages as done and reuse their artifacts on disk."
    ),
    report: Path = typer.Option(None, help="Write the run report JSON here."),
) -> None:
    """Execute the pipeline in dependency order and print the run report."""
    settings = get_settings()
    settings.ensure_dirs()
    ctx = _context(as_of)
    report_path = report or (settings.reports_dir / f"run_{ctx.as_of:%Y%m%d}.json")
    run_report = REGISTRY.run(
        ctx,
        targets=only or None,
        skip=skip or None,
        settings_summary=settings.summary(),
        report_path=report_path,
    )
    typer.echo(_console_safe(run_report.render()))
    typer.echo(f"report: {report_path}")
    raise typer.Exit(0 if run_report.ok else 1)


@app.command("catalogue-load")
def catalogue_load(
    file: list[str] = typer.Option(
        None,
        "--file",
        help="Load only these, as <MC|OBM>/<model folder>/<file>.pdf. Default: every PDF.",
    ),
    force: bool = typer.Option(False, help="Reload even when the stored copy is current."),
    workers: int = typer.Option(4, help="PDFs read in parallel."),
) -> None:
    """Extract PDF catalogues and save them to PostgreSQL for the Catalogues page.

    Run once for the existing PDFs; run again (``--file``) when a catalogue is added.
    A stored copy whose PDF hash and reader version are unchanged is skipped.
    """
    from src.catalogue.store import load_catalogues, source_key
    from src.core.errors import CatalogueStoreError

    settings = get_settings()
    root = settings.raw_dir / "pdf_catalogues"
    pdfs = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    if file:
        wanted = {f.replace("\\", "/") for f in file}
        pdfs = [p for p in pdfs if source_key(p) in wanted]
        missing = wanted - {source_key(p) for p in pdfs}
        if missing:
            typer.echo(f"not found under {root}: {sorted(missing)}")
            raise typer.Exit(1)

    def report(event: dict[str, object]) -> None:
        kind, key = event["event"], event["source_file"]
        if kind == "loaded":
            typer.echo(f"  loaded    {key}: {event['rows']} rows")
        elif kind == "excluded":
            typer.echo(f"  excluded  {key}: {event['reason']}")
        elif kind == "failed":
            typer.echo(f"  FAILED    {key}: {event['error']}")

    try:
        summary = load_catalogues(
            pdfs, force=force, workers=workers, on_event=report, settings=settings
        )
    except CatalogueStoreError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(
        f"{summary['loaded']} loaded, {summary['skipped']} already current, "
        f"{summary['excluded']} excluded, {len(summary['failed'])} failed"
    )
    raise typer.Exit(1 if summary["failed"] else 0)


@app.command("pn-yamaha-load")
def pn_yamaha_load() -> None:
    """Load PN_Yamaha's Yamaha-brand ("YM") materials into PostgreSQL.

    Material, Latest SS, Material description and the ten Supersede columns. Run
    ``ingest`` first so the workbook is converted; re-run whenever PN_Yamaha changes.
    """
    from src.catalogue.store import connect, ensure_schema, load_pn_yamaha
    from src.core.errors import CatalogueStoreError, SourceDataError

    try:
        with connect(get_settings()) as conn:
            ensure_schema(conn)
            summary = load_pn_yamaha(conn)
    except (CatalogueStoreError, SourceDataError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(
        f"{summary['loaded']} of {summary['brand_rows']} Brand {summary['brand']} rows loaded "
        f"({summary['source_rows']} in PN_Yamaha); rejected: {summary['rejected']}"
    )


if __name__ == "__main__":
    app()
