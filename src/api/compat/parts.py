"""Spare-parts pages: forecast, policy, classification, inventory and the part master.

All of these read one published table — ``mart_ui_sku`` — which carries classification,
forecast, stock, policy and the proposed order for every active SKU on a single row.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Query
from src.api.compat.context import planning_context
from src.api.compat.filters import f, i, mart, records, s
from src.io.parquet import read_table, table_exists

router = APIRouter(tags=["parts"])


def _sku(
    *,
    abc: str | None = None,
    tier: str | None = None,
    urgency: str | None = None,
    ss_method: str | None = None,
    method: str | None = None,
    status: str | None = None,
    demand_class: str | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    frame = mart("mart_ui_sku")
    if frame.empty:
        from fastapi import HTTPException

        raise HTTPException(503, "dashboard marts unavailable; run 15_dashboard")
    for column, value in (
        ("abc", abc),
        ("policy_tier", tier),
        ("order_urgency", urgency),
        ("ss_method", ss_method),
        ("method", method),
        ("stock_status", status),
        ("demand_category", demand_class),
    ):
        if value:
            frame = frame[frame[column].astype(str).str.upper() == value.upper()]
    if search:
        needle = search.strip().upper()
        frame = frame[
            frame["material_9"].astype(str).str.upper().str.contains(needle, na=False, regex=False)
            | frame["description"]
            .astype(str)
            .str.upper()
            .str.contains(needle, na=False, regex=False)
        ]
    return frame


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(k): int(v) for k, v in frame[column].fillna("UNSET").astype(str).value_counts().items()
    }


@router.get("/forecast")
def forecast(
    method: str | None = None,
    abc: str | None = None,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Per-SKU demand forecast over the protection interval."""
    frame = _sku(method=method, abc=abc, search=search)
    total = len(frame)
    page = frame.sort_values("total_issue_value_lkr", ascending=False).iloc[offset : offset + limit]
    rows = [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "xyz": s(r["xyz"]),
            "fsn": s(r["fsn"]),
            "policy_tier": s(r["policy_tier"]),
            "method": s(r["method"]),
            "forecast_m1": f(r["forecast_m1"]),
            "forecast_m2": f(r["forecast_m2"]),
            "forecast_m3": f(r["forecast_m3"]),
            "forecast_lt": f(r["forecast_lt"]),
            "avg_monthly_demand": f(r["avg_monthly_demand"]),
            "demand_std_monthly": f(r["demand_std_monthly"]),
            "demand_std_lt": f(r["demand_std_lt"]),
            "cv_hist": f(r["cv_hist"]),
            "total_issue_value_lkr": f(r["total_issue_value_lkr"]),
            "active_months": i(r["active_months"]),
        }
        for _, r in page.iterrows()
    ]
    return {
        "total": total,
        "rows": rows,
        "method_counts": _counts(frame, "method"),
        "parc_skus": int(frame["mu_month_parc"].notna().sum()),
        "zero_demand_skus": int((frame["forecast_m1"] <= 0).sum()),
        "planning": planning_context(),
    }


@router.get("/forecast/trend")
def trend(sku: str | None = None) -> list[dict[str, Any]]:
    """Monthly demand history — one SKU, or the whole book when none is named."""
    if not table_exists("facts", "demand_history"):
        return []
    history = read_table("facts", "demand_history")
    if sku:
        history = history[history["active_sku_id"].astype(str).str.upper() == sku.strip().upper()]
    grouped = history.groupby("month", as_index=False).agg(
        issue_qty=("confirmed_quantity", "sum"),
        issue_value_lkr=("order_value", "sum"),
        ordered_qty=("ordered_quantity", "sum"),
    )
    if table_exists("facts", "returns_history"):
        returns = read_table("facts", "returns_history")
        if sku:
            returns = returns[
                returns["active_sku_id"].astype(str).str.upper() == sku.strip().upper()
            ]
        by_month = (
            returns.groupby("month", as_index=False)["ordered_quantity"]
            .sum()
            .rename(columns={"ordered_quantity": "return_quantity"})
        )
        grouped = grouped.merge(by_month, on="month", how="outer")
    grouped["return_quantity"] = grouped.get(
        "return_quantity", pd.Series(0.0, index=grouped.index)
    ).fillna(0.0)
    return [
        {
            "year_month_str": s(r["month"]),
            "issue_qty": f(r["issue_qty"]),
            "issue_value_lkr": f(r["issue_value_lkr"]),
            "return_qty": f(r["return_quantity"]),
            "net_demand": f(r["ordered_qty"]),
        }
        for _, r in grouped.sort_values("month").iterrows()
    ]


@router.get("/forecast/fused-demand")
def fused_demand(
    method: str | None = None,
    demand_class: str | None = None,
    limit: int = Query(100, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The blended forecast: history baseline weighted against the parc-driven estimate."""
    frame = _sku(method=method, demand_class=demand_class)
    total = len(frame)
    page = frame.sort_values("forecast_lt", ascending=False).iloc[offset : offset + limit]
    rows = [
        {
            "part_no": s(r["material_9"]),
            "month": s(r["forecast_month"]),
            "demand_qty": f(r["forecast_m1"]),
            "method": s(r["method"]),
            "cv": f(r["cv"]),
            "demand_class": s(r["demand_category"]),
        }
        for _, r in page.iterrows()
    ]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
        "method_counts": _counts(frame, "method"),
        "demand_class_counts": _counts(frame, "demand_category"),
    }


def _policy_row(r: pd.Series) -> dict[str, Any]:
    return {
        "material_9": s(r["material_9"]),
        "description": s(r["description"]),
        "abc": s(r["abc"]),
        "xyz": s(r["xyz"]),
        "fsn": s(r["fsn"]),
        "policy_tier": s(r["policy_tier"]),
        "stock_status": s(r["stock_status"]),
        "coverage_months": f(r["coverage_months"]),
        "days_of_stock": f(r["days_of_stock"]),
        "method": s(r["method"]),
        "service_level": f(r["service_level"]),
        "z_score": f(r["z_score"]),
        "safety_stock": f(r["safety_stock"]),
        "ss_method": s(r["ss_method"]),
        "rol": f(r["rol"]),
        "roq": f(r["roq"]),
        "net_requirement": f(r["net_requirement"]),
        "order_value_lkr": f(r.get("value")),
        "order_urgency": s(r["order_urgency"]),
        "unit_value_lkr": f(r["unit_value_lkr"]),
        "stock_on_hand": f(r["stock_on_hand"]),
        "forecast_lt": f(r["forecast_lt"]),
        "cv": f(r["cv"]),
        "sanity_flag": bool(r["sanity_flag"]),
        "sanity_note": s(r["sanity_note"]),
        # Held for buyer review (CLAUDE.md stop-and-ask): proposed but not auto-ordered.
        "q_review": f(r.get("q_review")),
        "value_review_lkr": f(r.get("value_review")),
        "recent_demand_6m": f(r.get("recent_demand_6m")),
        "review_flags": s(r.get("review_flags")),
    }


@router.get("/policy")
def policy(
    urgency: str | None = None,
    tier: str | None = None,
    ss_method: str | None = None,
    abc: str | None = None,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Reorder level, order quantity and why, per SKU."""
    frame = _sku(urgency=urgency, tier=tier, ss_method=ss_method, abc=abc, search=search)
    total = len(frame)
    page = frame.sort_values("roq", ascending=False).iloc[offset : offset + limit]
    return {
        "total": total,
        "rows": [_policy_row(r) for _, r in page.iterrows()],
        "total_order_value_lkr": f(frame["value"].sum()),
        "review_lines": int(
            (pd.to_numeric(frame.get("q_review"), errors="coerce").fillna(0) > 0).sum()
        )
        if "q_review" in frame.columns
        else 0,
        "review_value_lkr": f(frame["value_review"].sum())
        if "value_review" in frame.columns
        else 0.0,
        "planning": planning_context(),
        "urgency_counts": _counts(frame, "order_urgency"),
        "tier_counts": _counts(frame, "policy_tier"),
        "ss_method_counts": _counts(frame, "ss_method"),
    }


@router.get("/policy/review")
def policy_review(limit: int = Query(500, ge=1, le=50000)) -> dict[str, Any]:
    """Lines held for buyer review instead of being ordered automatically.

    CLAUDE.md stop-and-ask: a proposed order more than 3x the last six months' demand over
    the protection interval — including any order for a part that sold nothing — goes to a
    human first. The buyer confirms, trims or drops each one.
    """
    frame = mart("mart_ui_sku")
    if frame.empty or "q_review" not in frame.columns:
        return {"total": 0, "total_value_lkr": 0.0, "no_demand": 0, "rows": []}
    held = frame[pd.to_numeric(frame["q_review"], errors="coerce").fillna(0) > 0].sort_values(
        "value_review", ascending=False
    )
    return {
        "total": int(len(held)),
        "total_value_lkr": f(held["value_review"].sum()),
        "no_demand": int(
            (pd.to_numeric(held["recent_demand_6m"], errors="coerce").fillna(0) <= 0).sum()
        ),
        "rows": [
            {
                "material_9": s(r["material_9"]),
                "description": s(r["description"]),
                "abc": s(r["abc"]),
                "fsn": s(r["fsn"]),
                "policy_tier": s(r["policy_tier"]),
                "q_review": f(r["q_review"]),
                "value_review_lkr": f(r["value_review"]),
                "recent_demand_6m": f(r["recent_demand_6m"]),
                "forecast_month": f(r["forecast_m1"]),
                "stock_on_hand": f(r["stock_on_hand"]),
                "on_order": f(r["on_order"]),
                "review_flags": s(r["review_flags"]),
            }
            for _, r in held.head(limit).iterrows()
        ],
    }


@router.get("/policy/sanity")
def sanity(limit: int = Query(200, ge=1, le=5000)) -> list[dict[str, Any]]:
    """SKUs whose reorder level or quantity observed demand cannot justify."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return []
    flagged = frame[frame["sanity_flag"].fillna(False).astype(bool)].sort_values(
        "roq", ascending=False
    )
    return [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "policy_tier": s(r["policy_tier"]),
            "sanity_note": s(r["sanity_note"]),
            "rol": f(r["rol"]),
            "roq": f(r["roq"]),
            "net_requirement": f(r["net_requirement"]),
            "avg_monthly_demand": f(r["avg_monthly_demand"]),
            "order_urgency": s(r["order_urgency"]),
        }
        for _, r in flagged.head(limit).iterrows()
    ]


@router.get("/policy/uio-service-plan")
def uio_service_plan(
    horizon_months: int | None = Query(None, ge=1, le=24), limit: int = Query(500, ge=1, le=50000)
) -> dict[str, Any]:
    """What the parc says to stock over a horizon, against what the rule-based policy asks.

    The comparison the buyer actually wants: a service plan sized on realised demand over
    the horizon, next to the policy's own order quantity, with the value difference stated.
    """
    planning = planning_context()
    horizon_months = horizon_months or planning["protection_interval_months"]
    frame = mart("mart_ui_sku")
    if frame.empty:
        return {
            "total_skus": 0,
            "skus_with_history": 0,
            "horizon_months": horizon_months,
            "avg_monthly_demand_total": 0.0,
            "total_service_plan_value": 0.0,
            "total_rule_based_value": 0.0,
            "value_delta": 0.0,
            "rows": [],
        }

    work = mart("mart_ui_service_plan")
    if work.empty:
        from fastapi import HTTPException

        raise HTTPException(503, "service-plan mart unavailable; run 15_dashboard")
    work = work[work["horizon_months"] == horizon_months]
    service_value = float(work["service_value"].sum())
    rule_value = float(work["rule_value"].sum())

    page = work.sort_values("recommended_order", ascending=False).head(limit)
    rows = [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "policy_tier": s(r["policy_tier"]),
            "order_urgency": s(r["order_urgency"]),
            "catalog_models": s(r["compatible_models"]),
            "hist_months": i(r["total_months"]),
            "hist_demand_total": f(r["total_issue_qty"]),
            "avg_monthly": f(r["mu_month_parc"]),
            "service_plan_qty": f(r["service_plan_qty"]),
            "base_roq": f(r["roq"]),
            "net_requirement": f(r["net_requirement"]),
            "recommended_order": f(r["recommended_order"]),
            "delta_vs_roq": f(r["delta_vs_roq"]),
            "delta_pct": (f(r["delta_vs_roq"]) / f(r["roq"]) * 100.0) if f(r["roq"]) else 0.0,
            "stock_on_hand": f(r["stock_on_hand"]),
            "unit_value_lkr": f(r["unit_value_lkr"]),
            "in_catalog": bool(s(r["compatible_models"])),
        }
        for _, r in page.iterrows()
    ]
    return {
        "total_skus": int(len(work)),
        "skus_with_history": int((work["active_months"] > 0).sum()),
        "horizon_months": horizon_months,
        "avg_monthly_demand_total": float(work["mu_month_parc"].sum()),
        "planning": planning,
        "total_service_plan_value": service_value,
        "total_rule_based_value": rule_value,
        "value_delta": service_value - rule_value,
        "rows": rows,
    }


@router.get("/classification")
def classification(
    abc: str | None = None,
    xyz: str | None = None,
    tier: str | None = None,
    part_type: str | None = None,
    demand_class: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The ABC/XYZ/FSN and demand-pattern view of the book."""
    frame = _sku(abc=abc, tier=tier, demand_class=demand_class)
    if part_type:
        frame = frame[frame["part_type"].astype(str) == part_type]
    if xyz:
        frame = frame[frame["xyz"].astype(str).str.upper() == xyz.upper()]
    total = len(frame)
    page = frame.sort_values("total_issue_value_lkr", ascending=False).iloc[offset : offset + limit]
    rows = [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "xyz": s(r["xyz"]),
            "fsn": s(r["fsn"]),
            "abc_xyz_fsn": s(r["abc_xyz_fsn"]),
            "policy_tier": s(r["policy_tier"]),
            "demand_category": s(r["demand_category"]),
            "demand_cluster": None,
            "demand_segment": s(r["behaviour_class"]),
            "in_ssop": None,
            "avg_monthly_demand": f(r["avg_monthly_demand"]),
            "cv": f(r["cv"]),
            "p_zero": f(r["p_zero"]),
            "active_months": i(r["active_months"]),
            "total_months": i(r["total_months"]),
            "total_issue_qty": f(r["total_issue_qty"]),
            "total_issue_value_lkr": f(r["total_issue_value_lkr"]),
            "total_return_qty": f(r["total_return_qty"]),
            "last_issue_date": s(r["last_issue_date"]) or None,
            "part_type": s(r["part_type"]) or None,
        }
        for _, r in page.iterrows()
    ]
    return {
        "total": total,
        "rows": rows,
        "abc_counts": _counts(frame, "abc"),
        "xyz_counts": _counts(frame, "xyz"),
        "fsn_counts": _counts(frame, "fsn"),
        "segment_counts": _counts(frame, "behaviour_class"),
        "demand_category_counts": _counts(frame, "demand_category"),
        "tier_counts": _counts(frame, "policy_tier"),
        "part_type_counts": _counts(frame, "part_type"),
    }


@router.get("/inventory")
def inventory(
    status: str | None = None,
    abc: str | None = None,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Stock on hand, cover and status per SKU."""
    frame = _sku(status=status, abc=abc, search=search)
    total = len(frame)
    page = frame.sort_values("stock_value_lkr", ascending=False).iloc[offset : offset + limit]
    rows = [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "xyz": s(r["xyz"]),
            "fsn": s(r["fsn"]),
            "policy_tier": s(r["policy_tier"]),
            "stock_on_hand": f(r["stock_on_hand"]),
            "stock_value_lkr": f(r["stock_value_lkr"]),
            "coverage_months": f(r["coverage_months"]),
            "days_of_stock": f(r["days_of_stock"]),
            "stock_status": s(r["stock_status"]),
            "avg_monthly_demand": f(r["avg_monthly_demand"]),
            "forecast_lt": f(r["forecast_lt"]),
            "method": s(r["method"]),
            "total_receipts": 0.0,
            "total_issues": f(r["total_issue_qty"]),
            "total_returns": f(r["total_return_qty"]),
            "last_movement_date": s(r["last_issue_date"]) or None,
        }
        for _, r in page.iterrows()
    ]
    excess = frame[frame["stock_status"] == "excess"]
    return {
        "total": total,
        "rows": rows,
        "status_counts": _counts(frame, "stock_status"),
        # Zero stock AND at least one unit a month of demand: the stockouts that need ordering.
        # Most zero-stock parts are slow movers selling well under one a month.
        "stockout_regular": int(
            (
                (frame["stock_status"].astype(str).str.lower() == "stockout")
                & (pd.to_numeric(frame.get("avg_monthly_demand"), errors="coerce").fillna(0) >= 1)
            ).sum()
        )
        if not frame.empty and "avg_monthly_demand" in frame.columns
        else 0,
        "planning": planning_context(),
        "total_value_lkr": float(frame["stock_value_lkr"].sum()) if not frame.empty else 0.0,
        "excess_value_lkr": float(excess["stock_value_lkr"].sum()) if not excess.empty else 0.0,
    }


@router.get("/inventory/position")
def inventory_position(
    limit: int = Query(500, ge=1, le=50000), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    """IP = on hand + on order − backorders, per SKU."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return {
            "total": 0,
            "offset": offset,
            "limit": limit,
            "rows": [],
            "total_stock_qty": 0.0,
            "total_pipeline_qty": 0.0,
            "total_net_position": 0.0,
        }
    page = frame.sort_values("stock_on_hand", ascending=False).iloc[offset : offset + limit]
    return {
        "total": int(len(frame)),
        "offset": offset,
        "limit": limit,
        "rows": [
            {
                "part_no": s(r["material_9"]),
                "stock_qty": f(r["stock_on_hand"]),
                "pipeline_qty": f(r["on_order"]),
                "backorder_qty": f(r["backorders"]),
                "net_position": f(r["ip"]),
            }
            for _, r in page.iterrows()
        ],
        "total_stock_qty": float(frame["stock_on_hand"].sum()),
        "total_pipeline_qty": float(frame["on_order"].sum()),
        "total_net_position": float(frame["ip"].sum()),
    }


@router.get("/inventory/at-risk")
def at_risk(limit: int = Query(50, ge=1, le=5000)) -> list[dict[str, Any]]:
    """Parts that will stock out first."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return []
    risky = frame[frame["stock_status"].isin(["stockout", "critical"])].sort_values(
        "total_issue_value_lkr", ascending=False
    )
    return [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "policy_tier": s(r["policy_tier"]),
            "stock_on_hand": f(r["stock_on_hand"]),
            "stock_status": s(r["stock_status"]),
            "coverage_months": f(r["coverage_months"]),
            "net_requirement": f(r["net_requirement"]),
            "order_urgency": s(r["order_urgency"]),
            "unit_value_lkr": f(r["unit_value_lkr"]),
        }
        for _, r in risky.head(limit).iterrows()
    ]


@router.get("/inventory/excess")
def excess(limit: int = Query(100, ge=1, le=5000)) -> list[dict[str, Any]]:
    """Parts with more cover than anyone has asked for."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return []
    fat = frame[frame["stock_status"] == "excess"].sort_values("stock_value_lkr", ascending=False)
    return [
        {
            "material_9": s(r["material_9"]),
            "description": s(r["description"]),
            "abc": s(r["abc"]),
            "policy_tier": s(r["policy_tier"]),
            "stock_on_hand": f(r["stock_on_hand"]),
            "stock_value_lkr": f(r["stock_value_lkr"]),
            "coverage_months": f(r["coverage_months"]),
            "avg_monthly_demand": f(r["avg_monthly_demand"]),
        }
        for _, r in fat.head(limit).iterrows()
    ]


@router.get("/inventory/stock-by-location")
def stock_by_location() -> list[dict[str, Any]]:
    """Units by plant. Only the PDC counts as inventory position; the rest is visibility."""
    if not table_exists("facts", "stock_by_plant"):
        return []
    plants = read_table("facts", "stock_by_plant")
    return [
        {
            "description": s(r["Plant"]),
            "qty": f(r["Unrestricted"]),
            "value_lkr": None,
            "sku_count": None,
            "is_excluded": s(r["Plant"]) != "W1B4",
        }
        for _, r in plants.sort_values("Unrestricted", ascending=False).iterrows()
    ]


@router.get("/inventory/coverage-histogram")
def coverage_histogram() -> list[dict[str, Any]]:
    """Distribution of months of cover, in the bins the UI draws."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return []
    edges = [0, 1, 2, 3, 4, 6, 9, 12, 18, 24, 999]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        count = int(((frame["coverage_months"] >= lo) & (frame["coverage_months"] < hi)).sum())
        out.append({"bin_start": lo, "bin_end": hi, "count": count})
    return out


@router.get("/parts")
def part_master(
    search: str | None = None,
    limit: int = Query(500, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The part master, with the supersession chain each number resolves through."""
    if not table_exists("facts", "part_master_enriched"):
        return {"total": 0, "supersession_count": 0, "rows": [], "supersessions": []}
    master = read_table("facts", "part_master_enriched")
    sku_frame = mart("mart_ui_sku")
    lookup = (
        sku_frame.set_index("material_9")[
            ["stock_on_hand", "on_order", "roq", "forecast_m1"]
        ].to_dict("index")
        if not sku_frame.empty
        else {}
    )

    frame = master
    if search:
        needle = search.strip().upper()
        frame = frame[
            frame["material"].astype(str).str.upper().str.contains(needle, na=False, regex=False)
            | frame["description"]
            .astype(str)
            .str.upper()
            .str.contains(needle, na=False, regex=False)
        ]
    total = len(frame)
    page = frame.iloc[offset : offset + limit]

    rows = []
    for _, r in page.iterrows():
        stats = lookup.get(s(r["active_sku_id"]), {})
        superseded = s(r["active_sku_id"]) != s(r["material"])
        rows.append(
            {
                "part_number": s(r["material"]),
                "description": s(r["description"]),
                "compatible_models": s(r["compatible_models"]) or None,
                "order_qty": f(stats.get("roq")),
                "eod_rate": 0.0,
                "stock": f(stats.get("stock_on_hand")),
                "on_order": f(stats.get("on_order")),
                "revised_order_qty": f(stats.get("roq")),
                "forecast_monthly_qty": f(stats.get("forecast_m1")),
                "superseded_from": s(r["material"]) if superseded else None,
                "has_supersession": superseded,
                "part_type": s(r["part_kind"]) or None,
            }
        )

    chains = (
        read_table("facts", "supersession_chains")
        if table_exists("facts", "supersession_chains")
        else pd.DataFrame()
    )
    supersessions: list[dict[str, Any]] = []
    if not chains.empty:
        moved = chains[chains["depth"] > 0].head(2000)
        descriptions = dict(
            zip(master["material"].astype(str), master["description"].astype(str), strict=False)
        )
        supersessions = [
            {
                "requested_pn": s(r["material"]),
                "current_pn": s(r["active_sku_id"]),
                "hops": i(r["depth"]),
                "current_description": descriptions.get(s(r["active_sku_id"]), ""),
                "old_description": descriptions.get(s(r["material"]), ""),
            }
            for _, r in moved.iterrows()
        ]

    return {
        "total": total,
        "supersession_count": int((chains["depth"] > 0).sum()) if not chains.empty else 0,
        "rows": rows,
        "supersessions": supersessions,
    }


_SUPERSEDE_COLUMNS = [
    f"{n} Supersede"
    for n in ("1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th")
]


def _catalogue_compatibility(master: pd.DataFrame) -> tuple[dict[str, set[str]], dict[str, Any]]:
    """Compatible model variants per current identity, from the catalogue database.

    Every catalogue part number is matched, separators ignored and its 10- and 12-digit
    forms taken as one, against every number in the part master — the material itself
    and each number it superseded — and its
    models are credited to that chain's ``active_sku_id``. So an old and a new number
    for one physical part show one merged list, per the one-identity rule.

    Returns the models per active_sku_id and a summary; an empty mapping with the
    reason when the database cannot be reached.
    """
    from src.catalogue.store import (  # noqa: PLC0415
        connect,
        ensure_schema,
        material_key,
        material_key_forms,
    )
    from src.core.errors import CatalogueStoreError  # noqa: PLC0415

    try:
        with connect() as conn:
            ensure_schema(conn)
            rows = conn.execute(
                "SELECT material_key, compatible_models FROM part_compatible_models"
            ).fetchall()
    except CatalogueStoreError as exc:
        return {}, {"source": "step_02", "error": str(exc)}

    to_active: dict[str, str] = {}
    for column in ["material", *[c for c in _SUPERSEDE_COLUMNS if c in master.columns]]:
        for number, active in zip(master[column], master["active_sku_id"], strict=True):
            if isinstance(number, str) and number.strip():
                for form in material_key_forms(material_key(number)):
                    to_active.setdefault(form, active)
    per_active: dict[str, set[str]] = {}
    unmatched = 0
    for key, models in rows:
        # "B65-E3907-10" in the catalogue is "B65-E3907-10-00" in the master.
        active = next((to_active[f] for f in material_key_forms(key) if f in to_active), None)
        if active is None:
            unmatched += 1
            continue
        per_active.setdefault(active, set()).update(models or [])
    return per_active, {
        "source": "catalogue_database",
        "catalogue_part_numbers": len(rows),
        "catalogue_part_numbers_not_in_master": unmatched,
    }


def _pn_yamaha_master_view(
    search: str | None, model: str | None, limit: int, offset: int
) -> dict[str, Any] | None:
    """The Part Master table from the database: PN_Yamaha Brand "YM" materials.

    Each material carries the catalogue's part name and compatible model variants when
    its Material, Latest SS or any of its ten superseded numbers is a catalogue part
    (``pn_yamaha_compatibility``). None when the database is unreachable or PN_Yamaha has
    not been loaded, so the page falls back to Step 02.
    """
    from src.catalogue.store import connect, ensure_schema, material_key  # noqa: PLC0415
    from src.core.errors import CatalogueStoreError  # noqa: PLC0415

    try:
        with connect() as conn:
            ensure_schema(conn)
            rows = conn.execute(
                "SELECT v.material, v.latest_ss, v.material_description, "
                "v.catalogue_description, v.compatible_models, v.matched_on, "
                "v.catalogue_part_nos, v.in_catalogue, "
                "ARRAY[p.supersede_1, p.supersede_2, p.supersede_3, p.supersede_4, "
                "p.supersede_5, p.supersede_6, p.supersede_7, p.supersede_8, "
                "p.supersede_9, p.supersede_10] "
                "FROM pn_yamaha_compatibility v JOIN pn_yamaha p USING (material) "
                "ORDER BY v.material"
            ).fetchall()
    except CatalogueStoreError:
        return None
    if not rows:
        return None
    records = [
        {
            "part_no": r[0],
            "latest_ss": r[1] or "",
            "description": r[2] or "",
            "catalogue_description": r[3] or "",
            "compatible_models": ", ".join(r[4] or []),
            "matched_on": r[5] or "",
            "catalogue_part_nos": ", ".join(r[6] or []),
            "in_catalogue": bool(r[7]),
            "section": "",
            "variant_count": len(r[4] or []),
            "source_count": None,
            "kind": "in_catalogue" if r[7] else "not_in_catalogue",
            # PN_Yamaha's 1st..10th Supersede, in order; "" where the chain is shorter.
            "supersedes": [s_ or "" for s_ in (r[8] or [])],
        }
        for r in rows
    ]
    models = sorted({m for r in rows for m in (r[4] or [])})
    in_catalogue = sum(1 for r in records if r["in_catalogue"])
    if search:
        needle, key = search.lower(), material_key(search)
        records = [
            r
            for r in records
            if needle in r["part_no"].lower()
            or (key and key in material_key(r["part_no"]))
            or needle in r["description"].lower()
            or needle in r["catalogue_description"].lower()
        ]
    if model:
        records = [r for r in records if model.lower() in r["compatible_models"].lower()]
    return {
        "indexed": True,
        "source": "pn_yamaha_db",
        "agent_master": False,
        "compatibility": {
            "source": "catalogue_database",
            "brand": "YM",
            "materials": len(rows),
            "parts_with_models": in_catalogue,
        },
        "total": len(records),
        "total_models": len(models),
        "models": models,
        "rows": records[offset : offset + limit],
    }


@router.get("/parts/master-view")
def master_view(
    search: str | None = None,
    model: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Serve PN_Yamaha identities in the existing Part Master table contract.

    Business meaning: one current part identity per supersession chain, including
    master parts that have no catalogue coverage. Compatible model variants ("AEROX -
    B65L") come from the catalogue database, merged across each chain's part numbers;
    Step 02's catalogue join is the fallback when the database cannot be reached.
    """
    served = _pn_yamaha_master_view(search, model, limit, offset)
    if served is not None:
        return served
    if not table_exists("facts", "part_master_enriched"):
        return {
            "indexed": False,
            "total": 0,
            "total_models": 0,
            "rows": [],
            "models": [],
            "source": "PN_Yamaha",
        }
    master = read_table("facts", "part_master_enriched")
    per_active, compatibility = _catalogue_compatibility(master)
    frame = master.sort_values("chain_depth").drop_duplicates("active_sku_id").copy()
    if per_active:
        frame["compatible_models"] = frame["active_sku_id"].map(
            lambda active: ", ".join(sorted(per_active.get(active, ())))
        )
    models = sorted(
        {
            m.strip()
            for value in frame["compatible_models"].dropna()
            for m in str(value).split(",")
            if m.strip()
        }
    )
    compatibility["parts_with_models"] = int(
        frame["compatible_models"].fillna("").astype(str).str.strip().astype(bool).sum()
    )
    if search:
        key = "".join(ch for ch in search if ch.isalnum()).upper()
        frame = frame[
            frame["active_sku_id"].str.contains(search, case=False, regex=False, na=False)
            | frame["active_sku_id"]
            .str.replace(r"[^A-Za-z0-9]", "", regex=True)
            .str.upper()
            .str.contains(key, regex=False, na=False)
            | frame["description"].str.contains(search, case=False, regex=False, na=False)
        ]
    if model:
        frame = frame[
            frame["compatible_models"].str.contains(model, case=False, regex=False, na=False)
        ]
    return {
        "indexed": True,
        "source": "PN_Yamaha",
        "compatibility": compatibility,
        "agent_master": False,
        "total": len(frame),
        "total_models": len(models),
        "models": models,
        "rows": [
            {
                "part_no": s(r["active_sku_id"]),
                "description": s(r["description"]),
                "compatible_models": s(r["compatible_models"]),
                "section": s(r.get("material_group")),
                "variant_count": None,
                "source_count": None,
                "kind": "colour_specific"
                if s(r["part_kind"]) == "colour"
                else s(r["part_kind"]) or "unclassified",
            }
            for _, r in frame.iloc[offset : offset + limit].iterrows()
        ],
    }


@router.get("/parts/from-catalog")
def parts_from_catalog(
    search: str = Query("", description="Filter by part number or description"),
    model: str = Query("", description="Filter by model folder name"),
    kind: str = Query("", description="Filter by kind: 'shared' or 'colour_specific'"),
    limit: int = Query(50000, le=100000),
) -> dict[str, Any]:
    """Unique parts from the catalogue part master, as the previous build derived it.

    Source order, richest first:

    1. the agent-derived part master, written by ``POST /catalog/part-master/rebuild``;
    2. the browser's own batch extraction from ``POST /catalog/run-extraction``;
    3. Step 01's published ``catalogue_parts`` fact.

    The first two are the previous build's own artefacts and are preferred, because they
    carry the section and per-colour variant detail the agent resolves. The third is the
    fallback so the page still shows the catalogue before anyone has run a rebuild —
    the previous build returned ``indexed: false`` and an empty page until then.
    ``agent_master`` tells the UI which source it actually got.
    """
    from src.api.compat.catalog import get_catalog_parts  # noqa: PLC0415 — avoids a cycle
    from src.catalogue.browser.part_master import load_part_master  # noqa: PLC0415

    frame = load_part_master()
    is_agent_master = not frame.empty and "section" in frame.columns
    source = "agent_master"

    if not is_agent_master:
        frame = get_catalog_parts()
        source = "browser_extraction"
        if frame.empty or "part_no" not in frame.columns:
            if not table_exists("facts", "catalogue_parts"):
                return {
                    "indexed": False,
                    "agent_master": False,
                    "source": "none",
                    "total": 0,
                    "total_models": 0,
                    "rows": [],
                    "models": [],
                }
            fact = read_table("facts", "catalogue_parts")
            frame = fact.rename(columns={"model_code": "model", "pdf_file": "source_file"})
            source = "step_01_facts"

        frame = frame[frame["part_no"].astype(str).str.strip().astype(bool)].copy()
        grouped = (
            frame.groupby("part_no", sort=True)
            .agg(
                description=(
                    "description",
                    lambda x: x.mode().iloc[0] if not x.mode().empty else "",
                ),
                compatible_models=("model", lambda x: ", ".join(sorted(x.dropna().unique()))),
                source_count=("source_file", "count"),
            )
            .reset_index()
        )
        grouped["section"] = ""
        grouped["variant_count"] = 1
        grouped["kind"] = "shared"
        all_models = sorted(frame["model"].dropna().astype(str).unique().tolist())
    else:
        grouped = frame.copy()
        # "AEROX B65J" and "AEROX B65J/DBNM8" both name the model AEROX.
        model_names: set[str] = set()
        for compatible in grouped["compatible_models"].dropna():
            for entry in str(compatible).split(", "):
                name = entry.split(" ")[0].split("/")[0].strip()
                if name:
                    model_names.add(name)
        all_models = sorted(model_names)

    if search:
        needle = search.lower()
        grouped = grouped[
            grouped["part_no"].astype(str).str.lower().str.contains(needle, na=False, regex=False)
            | grouped["description"]
            .astype(str)
            .str.lower()
            .str.contains(needle, na=False, regex=False)
        ]

    if model:
        grouped = grouped[
            grouped["compatible_models"]
            .astype(str)
            .str.contains(model, case=False, na=False, regex=False)
        ]

    if kind in ("shared", "colour_specific") and "kind" in grouped.columns:
        grouped = grouped[grouped["kind"] == kind]

    rows = [
        {
            "part_no": s(r["part_no"]),
            "description": s(r.get("description", "")),
            "section": s(r.get("section", "")),
            "compatible_models": s(r.get("compatible_models", "")),
            "variant_count": i(r.get("variant_count", 1) or 1),
            "source_count": i(r.get("source_count", 1) or 1),
            "kind": s(r.get("kind", "shared")) or "shared",
        }
        for _, r in grouped.head(limit).iterrows()
    ]

    return {
        "indexed": True,
        "agent_master": is_agent_master,
        "source": source,
        "total": int(len(grouped)),
        "total_models": len(all_models),
        "rows": rows,
        "models": all_models,
    }


@router.get("/rl")
def rl(limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
    """No RL agent in this design — reported as empty, not faked."""
    _ = limit
    return {
        "summary": {
            "scored_skus": 0,
            "flagged_skus": 0,
            "avg_multiplier": 1.0,
            "avg_order_reduction_pct": 0.0,
            "skus_reduce_order": 0,
            "skus_increase_order": 0,
            "skus_unchanged": 0,
        },
        "rows": [],
    }


@router.get("/eda/spare-parts")
def spare_parts_eda() -> dict[str, Any]:
    """The demand-pattern summary of the parts book."""
    frame = mart("mart_ui_sku")
    if frame.empty:
        return {
            "total_skus": 0,
            "in_ssop_count": 0,
            "total_issue_value_lkr": 0.0,
            "median_cv": 0.0,
            "median_p_zero": 0.0,
            "demand_category_counts": {},
            "p_zero_bins": [],
            "ingestion_summary": [],
            "top_skus": [],
            "intermittent_skus": [],
        }
    ranked = frame.sort_values("total_issue_value_lkr", ascending=False).copy()
    total_value = float(ranked["total_issue_value_lkr"].sum()) or 1.0
    ranked["cumulative_share_pct"] = ranked["total_issue_value_lkr"].cumsum() / total_value * 100.0

    bins = []
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.01]
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        bins.append(
            {
                "bin": f"{lo:.1f}-{min(hi, 1.0):.1f}",
                "lo": lo,
                "hi": min(hi, 1.0),
                "count": int(((frame["p_zero"] >= lo) & (frame["p_zero"] < hi)).sum()),
            }
        )

    intermittent = frame[frame["demand_category"].isin(["intermittent", "lumpy"])].sort_values(
        "total_issue_value_lkr", ascending=False
    )
    return {
        "total_skus": int(len(frame)),
        # SSOP is out of scope in this design, so this is genuinely unknown, not zero.
        "in_ssop_count": 0,
        "total_issue_value_lkr": float(frame["total_issue_value_lkr"].sum()),
        "median_cv": float(frame["cv"].median()),
        "median_p_zero": float(frame["p_zero"].median()),
        "demand_category_counts": _counts(frame, "demand_category"),
        "p_zero_bins": bins,
        "ingestion_summary": [],
        "top_skus": [
            {
                "rank": n + 1,
                "material_9": s(r["material_9"]),
                "description": s(r["description"]),
                "demand_category": s(r["demand_category"]) or None,
                "total_issue_value_lkr": f(r["total_issue_value_lkr"]),
                "total_issue_qty": f(r["total_issue_qty"]),
                "cumulative_share_pct": f(r["cumulative_share_pct"]),
            }
            for n, (_, r) in enumerate(ranked.head(100).iterrows())
        ],
        "intermittent_skus": [
            {
                "material_9": s(r["material_9"]),
                "description": s(r["description"]),
                "demand_category": s(r["demand_category"]),
                "p_zero": f(r["p_zero"]),
                "cv": f(r["cv"]),
                "active_months": i(r["active_months"]),
                "avg_monthly_demand": f(r["avg_monthly_demand"]),
                "total_issue_value_lkr": f(r["total_issue_value_lkr"]),
            }
            for _, r in intermittent.head(100).iterrows()
        ],
    }


@router.get("/eda/movements")
def movements() -> dict[str, Any]:
    """Stock movements are out of scope — stock is a snapshot, not a ledger."""
    return {
        "total_records": 0,
        "date_from": "",
        "date_to": "",
        "by_class": {},
        "monthly_trend": [],
    }


__all__ = ["router", "records"]
