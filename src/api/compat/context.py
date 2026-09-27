"""Planning metadata used by the existing dashboard's labels and summaries."""

from __future__ import annotations

from typing import Any

from src.api.compat.filters import mart, s
from src.core.settings import get_settings
from src.dashboard.sku import EXCESS_COVER_MONTHS


def planning_context() -> dict[str, Any]:
    """Expose configured timing and the already-published acceptance verdict."""
    settings = get_settings()
    sku = mart("mart_ui_sku")
    gate = mart("mart_service_and_stock")
    selected = gate[gate["arm"] == "selected"] if not gate.empty else gate
    return {
        "lead_time_months": settings.lead_time_months,
        "review_period_months": settings.review_period_months,
        "protection_interval_months": settings.lead_time_months + settings.review_period_months,
        "plant": settings.plant,
        "currency": settings.currency,
        "cycle_month": s(sku["cycle_month"].dropna().max()) if not sku.empty else None,
        "policy_verdict": s(selected.iloc[0].get("verdict"))
        if not selected.empty
        else "UNAVAILABLE",
        "excess_cover_months": EXCESS_COVER_MONTHS,
        "inventory_position_note": "On-order year/timing unconfirmed; backorders unavailable",
    }
