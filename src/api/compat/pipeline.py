"""Existing pipeline screen backed by the current registry and run reports."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from src.api.compat.filters import clear_cache
from src.api.deps import clear_cache as clear_planning_cache
from src.core.registry import REGISTRY
from src.core.settings import get_settings
from src.io.parquet import table_exists, table_path

router = APIRouter(tags=["pipeline"])

STAGE_ARTIFACTS = {
    "01_catalogue": ("facts", "catalogue_parts"),
    "02_part_master": ("facts", "part_master"),
    "03_orders": ("facts", "demand_history"),
    "04_sales": ("facts", "sales_kpis"),
    "05_order_analysis": ("facts", "supply_reliability"),
    "06_classification": ("facts", "sku_classification"),
    "07_model_selection": ("facts", "model_registry"),
    "08_forecast": ("facts", "forecast_protection"),
    "09_unit_sales": ("facts", "unit_sales"),
    "10_uio_cohorts": ("facts", "uio_age_matrix"),
    "11_targets": ("facts", "registration_forecast"),
    "12_stock": ("facts", "stock_position"),
    "13_policy": ("facts", "policy_params"),
    "14_monthly_order": ("marts", "mart_monthly_order"),
    "15_dashboard": ("marts", "mart_ui_overview"),
}


@router.get("/pipeline/stages")
def stages() -> dict[str, Any]:
    """List current registered stages using the existing screen's contract."""
    status = {}
    freshness = {}
    for name in REGISTRY.stages:
        key = "stage" + name
        source = STAGE_ARTIFACTS.get(name)
        exists = bool(source and table_exists(*source))
        status[key] = exists
        freshness[key] = (
            datetime.fromtimestamp(table_path(*source).stat().st_mtime, UTC).isoformat()
            if source and exists
            else None
        )
    return {
        "stages": [
            {"stage": name, "name": stage.description}
            for name, stage in sorted(REGISTRY.stages.items())
        ],
        "can_execute": False,
        "pipeline_status": status,
        "pipeline_freshness": freshness,
    }


@router.get("/pipeline/modules")
def modules() -> dict[str, Any]:
    """The new DAG has stages rather than the old intelligence modules."""
    return {"modules": []}


def _job(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    stages = report.get("stages", [])
    success = report.get("ok", False)
    return {
        "job_id": path.stem.removeprefix("run_"),
        "kind": "stage",
        "name": "Planning pipeline",
        "status": "SUCCESS" if success else "FAILED",
        "created_at": report.get("started_at", ""),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "logs": "\n".join(
            str(stage.get("stage", "")) + ": " + str(stage.get("status", "")) for stage in stages
        ),
        "error": None if success else "One or more stages failed; inspect the run report",
        "params": report.get("context", {}),
    }


@router.get("/pipeline/jobs")
def jobs(limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    """Read the current pipeline's persisted run history."""
    paths = sorted(
        get_settings().reports_dir.glob("run_*.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    return {"total": len(paths), "jobs": [_job(path) for path in paths[:limit]]}


@router.get("/pipeline/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    """Read one run report without permitting arbitrary paths."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise HTTPException(404, "unknown run")
    path = get_settings().reports_dir / ("run_" + job_id + ".json")
    if not path.is_file():
        raise HTTPException(404, "unknown run")
    return _job(path)


@router.post("/cache/clear")
def reset_cache() -> dict[str, bool]:
    """Refresh both API views of the published tables."""
    clear_cache()
    clear_planning_cache()
    return {"ok": True}


@router.post("/pipeline/stages/{stage}")
def run_stage(stage: str) -> None:
    """Do not translate legacy run buttons into unreviewed full-DAG executions."""
    raise HTTPException(
        409, "Use the current stage runner; this integration connects published outputs only"
    )


@router.get("/pipeline/refresh-status")
def refresh_status() -> dict[str, Any]:
    """The current or last source refresh — what changed, which stage is running."""
    from src.refresh import status  # noqa: PLC0415

    return status()


@router.post("/pipeline/refresh")
def refresh_now(
    rerun_all: bool = Query(False, description="Re-run every stage except the catalogue"),
) -> dict[str, Any]:
    """Re-ingest changed source workbooks and re-run the stages downstream of them.

    Runs in the background; poll ``/pipeline/refresh-status``. The catalogue step is
    never re-run here.
    """
    from src.refresh import refresh_in_background, status  # noqa: PLC0415

    started = refresh_in_background("manual", rerun_all=rerun_all)
    return {"started": started, **status()}
