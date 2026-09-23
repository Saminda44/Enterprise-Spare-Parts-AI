"""Trigger and monitor pipeline runs.

A monthly run takes minutes, so it must not block an HTTP request: the endpoint returns
a job id immediately and the work continues in a background thread.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger
from src.api.deps import clear_cache
from src.api.schemas import RunAccepted, RunStatus
from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.settings import get_settings

router = APIRouter(prefix="/runs", tags=["runs"])

#: In-process job table. A multi-worker deployment needs a shared store instead.
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

#: The monthly cycle: stock position, policy, then the order proposal.
MONTHLY_TARGETS = ["14_monthly_order"]


def _execute(job_id: str, as_of: date, targets: list[str]) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    ctx = PlanningContext(
        as_of=as_of,
        lead_time_months=settings.lead_time_months,
        review_period_months=settings.review_period_months,
        plant=settings.plant,
        currency=settings.currency,
        config={"on_order_interpretation": settings.on_order_interpretation},
    )
    try:
        report = REGISTRY.run(
            ctx,
            targets=targets,
            settings_summary=settings.summary(),
            report_path=settings.reports_dir / f"run_{job_id}.json",
        )
        with _LOCK:
            _JOBS[job_id] = {
                "status": "succeeded" if report.ok else "failed",
                "report": report.to_dict(),
            }
        clear_cache()
    except Exception as exc:  # noqa: BLE001 — recorded against the job, not swallowed
        logger.exception("run {} failed", job_id)
        with _LOCK:
            _JOBS[job_id] = {
                "status": "failed",
                "report": {"error": f"{type(exc).__name__}: {exc}"},
            }


@router.post("/monthly", response_model=RunAccepted, status_code=202)
def trigger_monthly(
    background: BackgroundTasks,
    as_of: str | None = None,
) -> RunAccepted:
    """Run the monthly cycle. Returns a job id immediately."""
    try:
        cycle = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else date.today()
    except ValueError as exc:
        raise HTTPException(422, "as_of must be YYYY-MM-DD") from exc

    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {"status": "running", "report": None}
    background.add_task(_execute, job_id, cycle, MONTHLY_TARGETS)
    return RunAccepted(
        run_id=job_id,
        status="running",
        detail=f"monthly cycle for {cycle:%Y-%m} started; poll /runs/{job_id}",
    )


@router.get("/{run_id}", response_model=RunStatus)
def run_status(run_id: str) -> RunStatus:
    """Status and, once finished, the full run report."""
    with _LOCK:
        job = _JOBS.get(run_id)
    if job is None:
        settings = get_settings()
        path = settings.reports_dir / f"run_{run_id}.json"
        if path.exists():
            return RunStatus(
                run_id=run_id,
                status="succeeded",
                report=json.loads(path.read_text(encoding="utf-8")),
            )
        raise HTTPException(404, f"unknown run {run_id!r}")
    return RunStatus(run_id=run_id, status=job["status"], report=job["report"])
