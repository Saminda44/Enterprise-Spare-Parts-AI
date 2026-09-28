"""Refresh the analysis when a source workbook changes.

The dashboard serves published tables; they only change when the pipeline runs. Before
this module an edited ``orders.xlsx`` or ``MCSI.xlsx`` reached nothing until someone ran
``ingest`` and then the pipeline by hand. Now the API watches the source workbooks:

1. A workbook whose modification time changes, and then holds still for
   ``source_settle_seconds`` (Excel has finished saving), triggers a refresh.
2. The refresh re-converts only workbooks whose content hash changed (``ingest``'s own
   hash check), then re-runs only the stages downstream of them — ``orders.xlsx`` from
   step 03, ``MCSI.xlsx`` from step 09 — reusing every other stage's artifacts. The PDF
   catalogue step (~10 min) is never re-run here; catalogues have their own load.
3. The API's table caches are cleared, and PN_Yamaha is reloaded into the catalogue
   database if it changed.

One refresh runs at a time. Any workbook that fails to convert stops the refresh before
a single stage runs (fail closed), and the reason is reported.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.settings import get_settings

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

SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "Sales_Summery.xlsx": ("Sales Summery.xlsx",),
}


def source_workbook_path(raw_dir: Path, name: str) -> Path:
    """Find the supplied workbook without renaming a source file."""
    for candidate in (name, *SOURCE_ALIASES.get(name, ())):
        path = raw_dir / candidate
        if path.exists():
            return path
    return raw_dir / name


#: The stages that read each workbook; everything downstream of them goes stale when it
#: changes. Declared from each stage's ``read_source`` calls.
SOURCE_STAGES: dict[str, tuple[str, ...]] = {
    "orders.xlsx": ("03_orders",),
    "dealers.xlsx": ("03_orders", "04_sales"),
    "sales.xlsx": ("04_sales",),
    "MCSI.xlsx": ("09_unit_sales",),
    "current_stock.xlsx": ("12_stock",),
    "On_Orders.xlsx": ("12_stock",),
    "PN_Yamaha.xlsx": ("02_part_master",),
    "Sales_Summery.xlsx": ("02_part_master", "10_uio_cohorts"),
}

#: Never re-run by a source refresh: it reads the PDF catalogues, not a workbook, and
#: takes about ten minutes.
CATALOGUE_STAGE = "01_catalogue"

#: The order date the demand history is built on (step 03).
ORDER_DATE_COLUMN = "Document Date"

#: The stages whose outputs the dashboard serves; a run report that executed one of
#: them carries the cycle date the dashboard currently reflects.
_PUBLISHING_STAGES = {"13_policy", "14_monthly_order", "15_dashboard"}

_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {"state": "idle"}


def status() -> dict[str, Any]:
    """The current or last refresh, for the dashboard banner."""
    return dict(_STATUS)


def _set(**values: Any) -> None:
    _STATUS.update(values)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def cycle_date() -> date:
    """The as_of a refresh runs with.

    ``refresh_as_of`` when set; otherwise the as_of of the newest run report that
    executed a publishing stage, so a refresh keeps the dashboard on the same cycle;
    today when there is no report at all.
    """
    settings = get_settings()
    if settings.refresh_as_of:
        return datetime.strptime(settings.refresh_as_of, "%Y-%m-%d").date()
    reports = sorted(
        settings.reports_dir.glob("run_*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    fallback: date | None = None
    for path in reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            as_of = datetime.strptime(report["context"]["as_of"], "%Y-%m-%d").date()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        fallback = fallback or as_of
        executed = {
            s.get("stage")
            for s in report.get("stages", [])
            if "skipped by request" not in " ".join(s.get("warnings") or [])
        }
        if executed & _PUBLISHING_STAGES:
            return as_of
    return fallback or date.today()


def data_cycle_date() -> date | None:
    """The cycle date the order history itself implies, or None if it has no dates.

    The month after the last month with orders, when that month is complete (the data
    reaches its final day); the last month itself when it is not, so a half-finished
    month is never treated as closed. orders.xlsx to 2026-08-31 gives 2026-09-01.

    Business meaning: new months in the source files move the planning cycle forward,
    instead of being ignored by a forecast still dated at the old cycle.
    """
    import pandas as pd

    from src.io.excel import read_source

    try:
        frame = read_source("orders")
    except Exception:  # noqa: BLE001 - no usable order history: keep the last cycle
        return None
    if ORDER_DATE_COLUMN not in frame.columns:
        return None
    dates = pd.to_datetime(frame[ORDER_DATE_COLUMN], errors="coerce").dropna()
    if dates.empty:
        return None
    last = dates.max()
    month_start = last.to_period("M").to_timestamp()
    if last.normalize() == (month_start + pd.offsets.MonthEnd(0)).normalize():
        return (month_start + pd.offsets.MonthBegin(1)).date()
    return month_start.date()


def _ingest() -> tuple[list[str], list[str]]:
    """Re-convert changed workbooks. Returns (changed workbook names, failures)."""
    from src.io.excel import workbook_sheets, workbook_to_parquet

    settings = get_settings()
    changed: list[str] = []
    failed: list[str] = []
    for name, sheets in SOURCE_WORKBOOKS.items():
        path = source_workbook_path(settings.raw_dir, name)
        if not path.exists():
            failed.append(f"{name}: missing")
            continue
        try:
            targets: list[str | int] = list(workbook_sheets(path)) if sheets == "*" else [0]
        except Exception as exc:  # noqa: BLE001 - reported; the refresh stops
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        for sheet in targets:
            label = name if sheet == 0 else f"{name}[{sheet}]"
            try:
                result = workbook_to_parquet(path, sheet=sheet)
            except Exception as exc:  # noqa: BLE001 - reported; the refresh stops
                failed.append(f"{label}: {type(exc).__name__}: {exc}")
                continue
            if result.converted and name not in changed:
                changed.append(name)
    return changed, failed


def refresh(reason: str, *, rerun_all: bool = False) -> dict[str, Any]:
    """Bring the published analysis up to date with the source workbooks.

    Args:
        reason: why it ran, shown in the banner ("orders.xlsx changed", "manual").
        rerun_all: re-run every stage except the catalogue even if no workbook changed.

    Returns:
        The final status.

    Business meaning: the dashboard's numbers always come from the workbooks on disk,
    without anyone remembering to re-run the pipeline.
    """
    if not _LOCK.acquire(blocking=False):
        return status()
    try:
        if not REGISTRY.stages:
            from src.stages import load_stages

            load_stages()
        settings = get_settings()
        started = _now()
        _set(
            state="checking",
            reason=reason,
            started_at=started,
            stage=None,
            position=0,
            total=0,
            error=None,
        )
        changed, failed = _ingest()
        if failed:
            _set(
                state="failed",
                finished_at=_now(),
                changed=changed,
                error="source file(s) could not be read — nothing was re-run: " + "; ".join(failed),
            )
            logger.error(f"refresh stopped: {failed}")
            return status()
        # The cycle date: pinned by setting, else implied by the order history. When it
        # moves, every stage that reads as_of goes stale, so all but the catalogue re-run.
        published = cycle_date()
        implied = None if settings.refresh_as_of else data_cycle_date()
        as_of = implied or published
        cycle_moved = as_of != published
        if not changed and not rerun_all and not cycle_moved:
            _set(state=_STATUS.get("last_state", "idle"), checked_at=_now())
            return status()
        rerun_all = rerun_all or cycle_moved

        starts = sorted({s for name in changed for s in SOURCE_STAGES.get(name, ())})
        stale = (
            set(REGISTRY.stages) - {CATALOGUE_STAGE}
            if rerun_all
            else REGISTRY.downstream(starts) - {CATALOGUE_STAGE}
        )
        skip = sorted(set(REGISTRY.stages) - stale)
        _set(previous_as_of=published.isoformat(), cycle_moved=cycle_moved)
        ctx = PlanningContext(
            as_of=as_of,
            lead_time_months=settings.lead_time_months,
            review_period_months=settings.review_period_months,
            plant=settings.plant,
            currency=settings.currency,
            config={"on_order_interpretation": settings.on_order_interpretation},
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        report_path = settings.reports_dir / f"run_refresh_{stamp}.json"
        _set(state="running", changed=changed, stages=sorted(stale), as_of=as_of.isoformat())
        logger.info(f"refresh ({reason}): changed {changed}; running {sorted(stale)} as of {as_of}")

        def progress(name: str, position: int, total: int) -> None:
            _set(stage=name, position=position, total=total)

        settings.ensure_dirs()
        report = REGISTRY.run(
            ctx,
            skip=skip,
            settings_summary=settings.summary(),
            report_path=report_path,
            on_stage=progress,
        )
        notes: list[str] = []
        if "PN_Yamaha.xlsx" in changed:
            notes.append(_reload_pn_yamaha())
        _clear_api_caches()
        failed_stages = [r.stage for r in report.stages if r.status.value != "ok"]
        final = "done" if report.ok else "failed"
        _set(
            state=final,
            last_state=final,
            finished_at=_now(),
            stage=None,
            failed_stages=failed_stages,
            report=report_path.name,
            notes=notes,
            error=None if report.ok else f"stage(s) did not complete: {', '.join(failed_stages)}",
        )
        return status()
    except Exception as exc:  # noqa: BLE001 - reported to the banner, and logged
        logger.exception("refresh failed")
        _set(
            state="failed",
            last_state="failed",
            finished_at=_now(),
            error=f"{type(exc).__name__}: {exc}",
        )
        return status()
    finally:
        _LOCK.release()


def _reload_pn_yamaha() -> str:
    from src.catalogue.store import connect, ensure_schema, load_pn_yamaha
    from src.core.errors import CatalogueStoreError, SourceDataError

    try:
        with connect() as conn:
            ensure_schema(conn)
            summary = load_pn_yamaha(conn)
        return f"PN_Yamaha reloaded into the database ({summary['loaded']:,} materials)"
    except (CatalogueStoreError, SourceDataError) as exc:
        return f"PN_Yamaha not reloaded into the database: {exc}"


def _clear_api_caches() -> None:
    try:
        from src.api.deps import clear_cache

        clear_cache()
    except ImportError:  # running outside the API
        pass


def refresh_in_background(reason: str, *, rerun_all: bool = False) -> bool:
    """Start a refresh on a worker thread. False when one is already running."""
    if _LOCK.locked():
        return False
    threading.Thread(
        target=refresh,
        args=(reason,),
        kwargs={"rerun_all": rerun_all},
        daemon=True,
        name="source-refresh",
    ).start()
    return True


def _snapshot() -> dict[str, tuple[int, int]]:
    raw = get_settings().raw_dir
    snap: dict[str, tuple[int, int]] = {}
    for name in SOURCE_WORKBOOKS:
        path = source_workbook_path(raw, name)
        try:
            stat = path.stat()
            snap[name] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            snap[name] = (0, 0)
    return snap


def _watch(stop: threading.Event) -> None:
    settings = get_settings()
    refresh("startup check")
    last = _snapshot()
    pending_since: float | None = None
    moving: set[str] = set()
    while not stop.wait(settings.source_poll_seconds):
        current = _snapshot()
        if current != last:
            moving |= {n for n in current if current[n] != last.get(n)}
            last = current
            pending_since = time.monotonic()
            _set(waiting_for=sorted(moving))
            continue
        if (
            pending_since is not None
            and time.monotonic() - pending_since >= settings.source_settle_seconds
        ):
            names = sorted(moving)
            moving, pending_since = set(), None
            _set(waiting_for=[])
            refresh(f"{', '.join(names)} changed")


_WATCHER: threading.Thread | None = None
_STOP = threading.Event()


def start_watcher() -> None:
    """Start watching the source workbooks (once per process)."""
    global _WATCHER
    if _WATCHER is not None and _WATCHER.is_alive():
        return
    _STOP.clear()
    _WATCHER = threading.Thread(target=_watch, args=(_STOP,), daemon=True, name="source-watcher")
    _WATCHER.start()
    logger.info("watching source workbooks for changes")


def stop_watcher() -> None:
    _STOP.set()
