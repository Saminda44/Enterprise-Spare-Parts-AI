"""Command line entry point. A scheduler calls the same commands a planner does."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.settings import get_settings
from src.stages import load_stages

load_stages()

app = typer.Typer(add_completion=False, help="Yamaha spare-parts planning pipeline.")

#: filename -> sheets to convert. None means the first sheet; "*" means every sheet
#: (Sales_Summery carries one per year plus the classification tables).
SOURCE_WORKBOOKS: dict[str, str | None] = {
    "orders.xlsx": None,
    "sales.xlsx": None,
    "MCSI.xlsx": None,
    "current_stock.xlsx": None,
    "On_Orders.xlsx": None,
    "PN_Yamaha.xlsx": None,
    "dealers.xlsx": None,
    "Sales_Summery.xlsx": "*",
}


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
        path = settings.raw_dir / name
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
    typer.echo(run_report.render())
    typer.echo(f"report: {report_path}")
    raise typer.Exit(0 if run_report.ok else 1)


if __name__ == "__main__":
    app()
