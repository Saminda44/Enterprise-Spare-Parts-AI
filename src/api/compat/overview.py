"""Overview KPIs and pipeline status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from src.api.compat.context import planning_context
from src.api.compat.filters import f, i, mart
from src.io.parquet import table_age_hours, table_exists

router = APIRouter(tags=["overview"])

#: The legacy dashboard's fourteen stage lights, mapped onto the tables the new pipeline
#: actually publishes. Two have no equivalent and stay dark on purpose.
STAGE_TABLES: dict[str, tuple[str, str] | None] = {
    "stage1_mcsi": ("facts", "unit_sales"),
    "stage2_sales_forecast": ("marts", "mart_ui_mc_sales_forecast"),
    "stage3_uio_forecast": ("marts", "mart_ui_parc_series"),
    "stage4_orders_eda": ("marts", "mart_ui_orders_monthly"),
    "stage5_sales_eda": ("marts", "mart_ui_sales_monthly"),
    "stage6_part_master": ("facts", "part_master"),
    # Stock movements are out of scope: stock is a snapshot, not a movement ledger.
    "stage7_stock_movements": None,
    "stage8_spare_parts_eda": ("marts", "mart_ui_sku"),
    "stage9_classification": ("facts", "sku_classification"),
    "stage10_demand_forecast": ("facts", "forecast_protection"),
    "stage11_stock_tracker": ("facts", "stock_position"),
    "stage12_policy": ("facts", "policy_params"),
    "stage13_shipment_report": ("marts", "mart_monthly_order"),
    # No RL agent in this design.
    "stage14_rl_policy": None,
}


def _counts(column: str) -> dict[str, int]:
    frame = mart("mart_ui_sku")
    if frame.empty or column not in frame.columns:
        return {}
    series = frame[column].fillna("UNSET").astype(str).value_counts()
    return {str(k): int(v) for k, v in series.items()}


@router.get("/overview/kpis")
def kpis() -> dict[str, Any]:
    """The Overview cards, straight off the published KPI row."""
    frame = mart("mart_ui_overview")
    if frame.empty:
        raise HTTPException(503, "dashboard marts unavailable; run 15_dashboard")
    row = frame.iloc[0].to_dict()
    numeric_int = {
        "total_skus",
        "active_skus",
        "stockout_skus",
        "critical_skus",
        "excess_skus",
        "immediate_orders",
        "soon_orders",
        "planned_orders",
        "sanity_flag_count",
        "m6_total_skus_to_order",
        "m6_critical_count",
        "m6_high_count",
        "m6_stockout_risk_count",
        "m6_overstock_count",
    }
    payload = {key: (i(value) if key in numeric_int else f(value)) for key, value in row.items()}
    return {
        "kpis": payload,
        "planning": planning_context(),
        "stock_status": _counts("stock_status"),
        "abc_counts": _counts("abc"),
        "tier_counts": _counts("policy_tier"),
        "urgency_counts": _counts("order_urgency"),
        "ss_method_counts": _counts("ss_method"),
    }


@router.get("/overview/pipeline")
def pipeline_status() -> dict[str, bool]:
    """Which stages have published something. A stage with no equivalent reads false."""
    return {
        key: bool(source and table_exists(*source))  # type: ignore[arg-type]
        for key, source in STAGE_TABLES.items()
    }


@router.get("/overview/pipeline/freshness")
def pipeline_freshness() -> dict[str, str | None]:
    """When each stage last wrote, so a stale page is visible rather than silently old."""
    out: dict[str, str | None] = {}
    now = datetime.now(UTC)
    for key, source in STAGE_TABLES.items():
        if not source or not table_exists(*source):
            out[key] = None
            continue
        age = table_age_hours(*source)
        out[key] = None if age is None else (now - timedelta(hours=age)).isoformat()
    return out
