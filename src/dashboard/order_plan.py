"""The next order, one row per proposed line, with every input that produced it.

Joins the Step 14 proposal with the inputs behind it — the fleet (UIO) share of the
forecast, the part's classes, the forecast itself and the stock position — so the Order
Plan page can show each line's arithmetic without computing anything in a request.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STATUS_ORDER = "to order"
STATUS_REVIEW = "held for review"

#: The columns published, in the order the page reads them.
COLUMNS = [
    "active_sku_id",
    "description",
    "status",
    "segment",
    "part_category",
    "abc",
    "abc_source",
    "fsn",
    "demand_category",
    "behaviour_class",
    "system",
    "policy",
    "fill_target",
    "forecast_month",
    "history_forecast",
    "fleet_forecast",
    "history_weight",
    "fleet_share",
    "protection_demand",
    "safety_stock",
    "target_level",
    "reorder_level",
    "on_hand",
    "on_order",
    "position",
    "gap_to_target",
    "eoq",
    "q_proposed",
    "q_final",
    "q_review",
    "unit_cost",
    "value",
    "value_review",
    "recent_demand_6m",
    "trigger_reason",
    "flags",
    "cycle_month",
    "expected_arrival",
]


def build(
    proposal: pd.DataFrame,
    sku: pd.DataFrame,
    behaviour: pd.DataFrame | None,
) -> pd.DataFrame:
    """Every proposed line — placeable or held for review — with its inputs.

    Business meaning: the order quantity is the gap between the target level (4-month
    demand plus safety stock for the part's fill target) and the stock position (on hand
    plus on order), floored at an economic quantity. A line above 3x recent demand is held
    for a buyer rather than ordered; both are shown so the buyer sees the whole proposal.
    """
    lines = proposal[proposal["q_proposed"].fillna(0) > 0].copy()
    extra = [
        "active_sku_id",
        "abc_source",
        "demand_category",
        "mu_month_baseline",
        "mu_month_parc",
        "baseline_weight",
        "forecast_m1",
        "mu_p",
        "segment",
        "part_category",
    ]
    lines = lines.merge(sku[[c for c in extra if c in sku.columns]], on="active_sku_id", how="left")
    if behaviour is not None and not behaviour.empty:
        lines = lines.merge(
            behaviour[["active_sku_id", "behaviour_class", "system"]],
            on="active_sku_id",
            how="left",
        )
    else:
        lines["behaviour_class"] = None
        lines["system"] = None

    weight = pd.to_numeric(lines.get("baseline_weight"), errors="coerce").fillna(1.0)
    parc = pd.to_numeric(lines["mu_month_parc"], errors="coerce")
    forecast = pd.to_numeric(lines["forecast_m1"], errors="coerce").fillna(0.0)
    out = pd.DataFrame(
        {
            "active_sku_id": lines["active_sku_id"],
            "description": lines["description"],
            "status": np.where(lines["q_final"] > 0, STATUS_ORDER, STATUS_REVIEW),
            "segment": lines.get("segment"),
            "part_category": lines.get("part_category"),
            "abc": lines["abc_class"],
            "abc_source": lines.get("abc_source"),
            "fsn": lines["fsn"],
            "demand_category": lines.get("demand_category"),
            "behaviour_class": lines["behaviour_class"],
            "system": lines["system"],
            "policy": lines["policy"],
            "fill_target": lines["fill_target"],
            "forecast_month": forecast,
            "history_forecast": lines.get("mu_month_baseline"),
            "fleet_forecast": parc,
            "history_weight": weight,
            # Share of the part's forecast that comes from its fleet (0 without a model link).
            "fleet_share": np.where(
                (forecast > 0) & parc.notna(), (1 - weight) * parc.fillna(0) / forecast, 0.0
            ),
            "protection_demand": lines.get("mu_p"),
            "safety_stock": lines["ss"],
            "target_level": lines["S"],
            "reorder_level": lines["s"],
            "on_hand": lines["on_hand"],
            "on_order": lines["on_order"],
            "position": lines["ip"],
            "gap_to_target": lines["q_raw"],
            "eoq": lines["eoq"],
            "q_proposed": lines["q_proposed"],
            "q_final": lines["q_final"],
            "q_review": lines["q_review"],
            "unit_cost": lines["unit_cost"],
            "value": lines["value"],
            "value_review": lines["value_review"],
            "recent_demand_6m": lines["recent_demand_6m"],
            "trigger_reason": lines["trigger_reason"],
            "flags": lines["flags"],
            "cycle_month": lines["cycle_month"],
            "expected_arrival": lines["expected_arrival"],
        }
    )
    out["proposed_value"] = out["value"].fillna(0) + out["value_review"].fillna(0)
    return out.sort_values("proposed_value", ascending=False).reset_index(drop=True)[
        [*COLUMNS, "proposed_value"]
    ]
