"""Planning metadata used by the existing dashboard's labels and summaries."""

from __future__ import annotations

from typing import Any

import pandas as pd
from src.api.compat.filters import mart, s
from src.core.settings import get_settings
from src.dashboard.sku import EXCESS_COVER_MONTHS


def _local_current_month() -> str:
    return pd.Timestamp.now(tz="Asia/Colombo").strftime("%Y-%m")


def planning_context() -> dict[str, Any]:
    """Expose the timing actually used by the published plan and its acceptance verdict."""
    settings = get_settings()
    sku = mart("mart_ui_sku")
    proposal = mart("mart_monthly_order")
    gate = mart("mart_service_and_stock")
    selected = gate[gate["arm"] == "selected"] if not gate.empty else gate
    lead = settings.lead_time_months
    for frame in (proposal, sku):
        if "lead_time_months" in frame:
            published = pd.to_numeric(frame["lead_time_months"], errors="coerce").dropna()
            if not published.empty:
                lead = int(published.iloc[0])
                break
    inventory_note = "Open-order schedule unavailable; backorders unavailable"
    if not proposal.empty and {"stock_snapshot_as_of", "on_orders_coverage_end"} <= set(proposal):
        snapshot = pd.to_datetime(proposal["stock_snapshot_as_of"], errors="coerce").max()
        coverage = proposal["on_orders_coverage_end"].dropna()
        if pd.notna(snapshot) and not coverage.empty:
            inventory_note = (
                f"On_Orders expected arrivals through {coverage.max()}; stock snapshot "
                f"{snapshot:%Y-%m-%d}; backorders unavailable"
            )
    return {
        "lead_time_months": lead,
        "review_period_months": settings.review_period_months,
        "protection_interval_months": lead + settings.review_period_months,
        "plant": settings.plant,
        "currency": settings.currency,
        "cycle_month": s(sku["cycle_month"].dropna().max()) if not sku.empty else None,
        "policy_verdict": s(selected.iloc[0].get("verdict"))
        if not selected.empty
        else "UNAVAILABLE",
        "excess_cover_months": EXCESS_COVER_MONTHS,
        "inventory_position_note": inventory_note,
    }


def published_order_hold_reason() -> str | None:
    """Block release unless the published order carries corrected, verified assumptions.

    Business meaning: an old proposal must not become buyer-ready merely because the
    application's current settings changed after it was calculated.
    """
    settings = get_settings()
    proposal = mart("mart_monthly_order")
    if proposal.empty:
        return "No published order plan is available."
    if settings.on_order_interpretation != "arrival":
        return "On_Orders must be interpreted as expected arrival months."
    if "lead_time_months" not in proposal:
        return "Published order has no recorded import lead time."
    leads = pd.to_numeric(proposal["lead_time_months"], errors="coerce")
    if leads.isna().any() or not leads.eq(settings.lead_time_months).all():
        return "Published order uses an outdated import lead time; recalculate it."
    required = (
        "on_order_interpretation",
        "incoming_orders_status",
        "stock_snapshot_as_of",
        "on_orders_coverage_end",
        "on_orders_sha256",
        "cycle_month",
    )
    if any(column not in proposal for column in required):
        return "Published order lacks the corrected arrival and incoming-order provenance."
    if not proposal["on_order_interpretation"].eq("arrival").all():
        return "Published order was not calculated from expected arrival months."
    if not proposal["incoming_orders_status"].eq("VERIFIED").all():
        return "Incoming orders for this cycle are unverified; do not place this order."
    snapshots = pd.to_datetime(proposal["stock_snapshot_as_of"], errors="coerce")
    cycles = pd.to_datetime(proposal["cycle_month"].astype(str) + "-01", errors="coerce")
    if (
        snapshots.isna().any()
        or cycles.isna().any()
        or not (snapshots + pd.Timedelta(days=1)).eq(cycles).all()
    ):
        return "Published order has no matching month-end stock snapshot; recalculate it."
    if (
        proposal["on_orders_sha256"].isna().any()
        or proposal["on_orders_sha256"].astype(str).str.len().ne(64).any()
    ):
        return "Published order lacks On_Orders source provenance; recalculate it."
    if not proposal["cycle_month"].eq(_local_current_month()).all():
        return (
            "Published order is for a past or future cycle; refresh stock and "
            "recalculate the current month before placing it."
        )
    return None
