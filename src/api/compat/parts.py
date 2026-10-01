"""Spare-parts pages backed by published per-SKU and Part Master marts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from src.api.compat.context import planning_context, published_order_hold_reason
from src.api.compat.filters import (
    REQUEST_CATEGORY,
    f,
    i,
    mart,
    ratio,
    records,
    request_segment,
    s,
    segment_skus,
)
from src.dashboard.segments import part_category, sku_segments
from src.io.parquet import read_table, table_exists

router = APIRouter(tags=["parts"])


def _sku(
    *,
    source: str = "mart_ui_sku",
    abc: str | None = None,
    tier: str | None = None,
    urgency: str | None = None,
    ss_method: str | None = None,
    method: str | None = None,
    status: str | None = None,
    demand_class: str | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    frame = mart(source)
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
        matched = frame["material_9"].astype(str).str.upper().str.contains(
            needle, na=False, regex=False
        ) | frame["description"].astype(str).str.upper().str.contains(needle, na=False, regex=False)
        if "superseded_numbers" in frame:
            matched |= (
                frame["superseded_numbers"]
                .astype(str)
                .str.upper()
                .str.contains(needle, na=False, regex=False)
            )
        frame = frame[matched]
    return frame


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(k): int(v) for k, v in frame[column].fillna("UNSET").astype(str).value_counts().items()
    }


def _classification_coverage(frame: pd.DataFrame, column: str) -> dict[str, int]:
    """Count assigned and missing labels against the same filtered Part Master set."""
    labels = frame[column].fillna("").astype(str).str.strip().str.lower()
    assigned = int((~labels.isin(("", "unclassified", "unset"))).sum())
    return {"assigned": assigned, "not_classified": len(frame) - assigned}


def _planned_f(row: pd.Series, column: str) -> float | None:
    """Do not report an unmeasured Part Master planning measure as zero."""
    return f(row[column]) if row["has_planning"] else None


@router.get("/forecast")
def forecast(
    method: str | None = None,
    abc: str | None = None,
    search: str | None = None,
    basis: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The one forecast the order uses: own history blended with the fleet, per part.

    ``basis`` = ``fleet`` keeps parts with a fleet (UIO) estimate in the blend,
    ``history`` keeps parts forecast from their own history alone.
    """
    frame = _sku(method=method, abc=abc, search=search)
    everything = frame
    has_fleet = frame["mu_month_parc"].notna()
    if basis == "fleet":
        frame = frame[has_fleet]
    elif basis == "history":
        frame = frame[~has_fleet]
    total = len(frame)
    page = frame.sort_values(["forecast_m1", "total_issue_value_lkr"], ascending=False).iloc[
        offset : offset + limit
    ]
    weight = pd.to_numeric(everything.get("baseline_weight"), errors="coerce").fillna(1.0)
    parc = pd.to_numeric(everything["mu_month_parc"], errors="coerce").fillna(0.0)
    monthly = float(everything["forecast_m1"].sum())
    fleet_units = float(((1.0 - weight) * parc).sum())
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
            "demand_category": s(r.get("demand_category")),
            "history_forecast": f(r.get("mu_month_baseline")),
            "fleet_forecast": f(r["mu_month_parc"]) if pd.notna(r["mu_month_parc"]) else None,
            "history_weight": f(r.get("baseline_weight"))
            if pd.notna(r.get("baseline_weight"))
            else 1.0,
            "protection_demand": f(r.get("mu_p")),
            "protection_p90": f(r.get("p90")),
        }
        for _, r in page.iterrows()
    ]
    return {
        "total": total,
        "rows": rows,
        "method_counts": _counts(everything, "method"),
        "parc_skus": int(everything["mu_month_parc"].notna().sum()),
        "zero_demand_skus": int((everything["forecast_m1"] <= 0).sum()),
        "all_skus": int(len(everything)),
        "monthly_forecast_units": monthly,
        "fleet_share_pct": fleet_units / monthly * 100.0 if monthly else 0.0,
        "planning": planning_context(),
    }


@router.get("/forecast/trend")
def trend(sku: str | None = None) -> list[dict[str, Any]]:
    """Monthly demand history — one SKU, or the whole book when none is named."""
    if not table_exists("facts", "demand_history"):
        return []
    history = read_table("facts", "demand_history")
    scope = segment_skus()
    if scope is not None:
        history = history[history["active_sku_id"].astype(str).isin(scope)]
    if sku:
        history = history[history["active_sku_id"].astype(str).str.upper() == sku.strip().upper()]
    grouped = history.groupby("month", as_index=False).agg(
        issue_qty=("confirmed_quantity", "sum"),
        issue_value_lkr=("order_value", "sum"),
        ordered_qty=("ordered_quantity", "sum"),
    )
    if table_exists("facts", "returns_history"):
        returns = read_table("facts", "returns_history")
        if scope is not None:
            returns = returns[returns["active_sku_id"].astype(str).isin(scope)]
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


@router.get("/forecast/sales-check")
def forecast_sales_check(
    check: str | None = None,
    search: str | None = None,
    limit: int = Query(200, ge=1, le=50000),
) -> dict[str, Any]:
    """Per part: does billed sales history agree with the orders the forecast runs on?"""
    frame = mart("mart_ui_forecast_sales_check")
    if frame.empty:
        return {"total": 0, "counts": {}, "window": None, "rows": [], "totals": {}}
    descriptions = mart("mart_ui_part_master_analysis")
    if not descriptions.empty:
        frame = frame.merge(
            descriptions[["active_sku_id", "description"]], on="active_sku_id", how="left"
        )
    counts = _counts(frame, "check")
    totals = {
        "ordered": f(frame["ordered_quantity"].sum()),
        "confirmed": f(frame["confirmed_quantity"].sum()),
        "billed": f(frame["sales_qty"].sum()),
    }
    if check:
        frame = frame[frame["check"] == check]
    if search:
        needle = search.lower()
        frame = frame[
            frame["active_sku_id"].astype(str).str.lower().str.contains(needle, regex=False)
            | frame.get("description", pd.Series("", index=frame.index))
            .astype(str)
            .str.lower()
            .str.contains(needle, regex=False)
        ]
    ranked = frame.assign(gap=(frame["sales_qty"] - frame["confirmed_quantity"]).abs())
    ranked = ranked.sort_values("gap", ascending=False)
    return {
        "total": int(len(frame)),
        "counts": counts,
        "totals": totals,
        "window": {
            "start": s(ranked["window_start"].iloc[0]) if len(ranked) else None,
            "end": s(ranked["window_end"].iloc[0]) if len(ranked) else None,
        },
        "rows": [
            {
                "part_no": s(r["active_sku_id"]),
                "description": s(r.get("description")),
                "check": s(r["check"]),
                "ordered": f(r["ordered_quantity"]),
                "confirmed": f(r["confirmed_quantity"]),
                "lost": f(r["lost_quantity"]),
                "billed": f(r["sales_qty"]),
                "billed_to_confirmed": f(r["billed_to_confirmed"])
                if pd.notna(r["billed_to_confirmed"])
                else None,
                "forecast_month": f(r["mu_month"]) if pd.notna(r["mu_month"]) else None,
                "billed_per_month": f(r["billed_per_month"]),
                "ordered_per_month": f(r["ordered_per_month"]),
                "sales_link": s(r.get("sales_link")) or None,
            }
            for _, r in ranked.head(limit).iterrows()
        ],
    }


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


@router.get("/order-plan")
def order_plan(
    status: str | None = None,
    abc: str | None = None,
    behaviour: str | None = None,
    system: str | None = None,
    search: str | None = None,
    limit: int = Query(200, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The next order: every proposed line with the fleet, class, forecast and stock behind it."""
    from src.core.settings import get_settings  # noqa: PLC0415

    frame = mart("mart_ui_order_plan")
    if frame.empty:
        raise HTTPException(503, "order plan unavailable; run 15_dashboard")
    whole = frame
    to_order = whole[whole["status"] == "to order"]
    held = whole[whole["status"] == "held for review"]
    for column, value in (
        ("status", status),
        ("abc", abc),
        ("behaviour_class", behaviour),
        ("system", system),
    ):
        if value:
            frame = frame[frame[column].astype(str).str.lower() == value.lower()]
    if search:
        needle = search.lower()
        frame = frame[
            frame["active_sku_id"].astype(str).str.lower().str.contains(needle, regex=False)
            | frame["description"].astype(str).str.lower().str.contains(needle, regex=False)
        ]

    def by(column: str) -> list[dict[str, Any]]:
        grouped = to_order.groupby(to_order[column].fillna("Unassigned"))
        rows = grouped.agg(lines=("q_final", "size"), value=("value", "sum")).reset_index()
        return [
            {"name": s(r[column]), "lines": i(r["lines"]), "value": f(r["value"])}
            for _, r in rows.sort_values("value", ascending=False).iterrows()
        ]

    settings = get_settings()
    planning = planning_context()
    hold_reason = published_order_hold_reason()
    published = mart("mart_monthly_order")
    page = frame.iloc[offset : offset + limit]
    number = lambda v: f(v) if pd.notna(v) else None  # noqa: E731 - nullable float
    return {
        "total": int(len(frame)),
        "cycle_month": s(whole["cycle_month"].iloc[0]),
        "expected_arrival": s(whole["expected_arrival"].iloc[0]),
        "buyer_ready": hold_reason is None,
        "hold_reason": hold_reason,
        "summary": {
            "lines": int(len(to_order)),
            "value": f(to_order["value"].sum()),
            "units": f(to_order["q_final"].sum()),
            "held_lines": int(len(held)),
            "held_value": f(held["value_review"].sum()),
            "fleet_linked_lines": int((to_order["fleet_forecast"].notna()).sum()),
            "fleet_value_share_pct": ratio(
                float((to_order["value"] * to_order["fleet_share"]).sum()),
                float(to_order["value"].sum()),
                scale=100,
            ),
            "stock_on_hand": f(to_order["on_hand"].sum()),
            "stock_on_order": f(to_order["on_order"].sum()),
        },
        "by_abc": by("abc"),
        "by_system": by("system"),
        "by_behaviour": by("behaviour_class"),
        "assumptions": {
            "fill_targets": settings.fill_rate_targets,
            "holding_rate": settings.annual_holding_rate,
            "order_cost": settings.order_cost,
            "moq": settings.default_moq,
            "pack_size": settings.default_pack_size,
            "lead_time_months": planning["lead_time_months"],
            "protection_interval_months": planning["protection_interval_months"],
            "on_order_interpretation": (
                s(published["on_order_interpretation"].iloc[0])
                if not published.empty and "on_order_interpretation" in published
                else "unrecorded"
            ),
        },
        "rows": [
            {
                "part_no": s(r["active_sku_id"]),
                "description": s(r["description"]),
                "status": s(r["status"]),
                "abc": s(r["abc"]),
                "abc_source": s(r["abc_source"]) or None,
                "fsn": s(r["fsn"]),
                "demand_category": s(r["demand_category"]) or None,
                "behaviour_class": s(r["behaviour_class"]) or None,
                "system": s(r["system"]) or None,
                "policy": s(r["policy"]),
                "fill_target": f(r["fill_target"]),
                "forecast_month": f(r["forecast_month"]),
                "history_forecast": number(r["history_forecast"]),
                "fleet_forecast": number(r["fleet_forecast"]),
                "history_weight": f(r["history_weight"]),
                "fleet_share": f(r["fleet_share"]),
                "protection_demand": number(r["protection_demand"]),
                "safety_stock": f(r["safety_stock"]),
                "target_level": f(r["target_level"]),
                "on_hand": f(r["on_hand"]),
                "on_order": f(r["on_order"]),
                "position": f(r["position"]),
                "gap_to_target": f(r["gap_to_target"]),
                "eoq": f(r["eoq"]),
                "q_final": f(r["q_final"]),
                "q_review": f(r["q_review"]),
                "unit_cost": f(r["unit_cost"]),
                "value": f(r["value"]),
                "value_review": f(r["value_review"]),
                "recent_demand_6m": f(r["recent_demand_6m"]),
                "trigger_reason": s(r["trigger_reason"]),
                "flags": s(r["flags"]) or None,
            }
            for _, r in page.iterrows()
        ],
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


def classification_frame(
    abc: str | None = None,
    xyz: str | None = None,
    fsn: str | None = None,
    tier: str | None = None,
    part_type: str | None = None,
    demand_class: str | None = None,
    behaviour: str | None = None,
    system: str | None = None,
    planning_abc: str | None = None,
    abc_source: str | None = None,
    scope: str | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    """Every Part Master SKU matching the classification filters (the list and the download
    use the same rows, so the file always matches the screen)."""
    frame = _sku(
        source="mart_ui_part_master_analysis",
        tier=tier,
        demand_class=demand_class,
        search=search,
    )
    if scope in {"active", "classified"}:
        frame = frame[frame["sales_activity_12m"] == "ACTIVE"]
    elif scope in {"inactive", "unclassified"}:
        frame = frame[frame["sales_activity_12m"] == "INACTIVE"]
    exact = (
        # ABC is the planning class (sets the fill target) — the same one the Overview and
        # Order Plan show. Sales ABC stays on each row as detail.
        ("abc", abc),
        ("part_type", part_type),
        ("xyz", xyz),
        ("fsn", fsn),
        ("behaviour_class", behaviour),
        ("system", system),
        ("abc", planning_abc),
        ("abc_source", abc_source),
    )
    for column, value in exact:
        if value and column in frame.columns:
            frame = frame[frame[column].astype(str).str.upper() == value.upper()]
    return frame


@router.get("/classification")
def classification(
    abc: str | None = None,
    xyz: str | None = None,
    fsn: str | None = None,
    tier: str | None = None,
    part_type: str | None = None,
    demand_class: str | None = None,
    behaviour: str | None = None,
    system: str | None = None,
    planning_abc: str | None = None,
    abc_source: str | None = None,
    scope: str | None = None,
    search: str | None = None,
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The ABC/XYZ/FSN, behaviour and demand-pattern view of the whole Part Master."""
    frame = classification_frame(
        abc=abc,
        xyz=xyz,
        fsn=fsn,
        tier=tier,
        part_type=part_type,
        demand_class=demand_class,
        behaviour=behaviour,
        system=system,
        planning_abc=planning_abc,
        abc_source=abc_source,
        scope=scope,
        search=search,
    )
    total = len(frame)
    classified = frame[frame["has_planning"]]
    billed = frame[frame["sales_abc"].notna()]
    page = frame.sort_values(
        ["sales_net_lkr", "active_sku_id"], ascending=[False, True], na_position="last"
    ).iloc[offset : offset + limit]
    rows = [
        {
            "material_9": s(r["material_9"]),
            "active_sku_id": s(r["active_sku_id"]),
            "description": s(r["description"]),
            "material_type": s(r["material_type"]),
            "material_group": s(r["material_group"]),
            "brand": s(r["brand"]),
            "compatible_models": s(r["compatible_models"]),
            "alias_count": i(r["alias_count"]),
            "superseded_numbers": s(r["superseded_numbers"]),
            "has_planning": bool(r["has_planning"]),
            "abc": s(r["sales_abc"]),
            "sales_activity_12m": s(r["sales_activity_12m"]),
            # The ABC that sets fill targets: sales value, or order value where no sale linked.
            "planning_abc": s(r["abc"]),
            "abc_source": s(r.get("abc_source")) or None,
            "order_abc": s(r.get("abc_orders")) or s(r["abc"]),
            "sales_xyz": s(r.get("sales_xyz")) or None,
            "sales_fsn": s(r.get("sales_fsn")) or None,
            "sales_link": s(r.get("sales_link")) or None,
            "sales_qty": f(r.get("sales_qty")) if pd.notna(r["sales_abc"]) else None,
            "last_sale_month": s(r.get("last_sale_month")) or None,
            "sales_net_lkr": f(r["sales_net_lkr"]) if pd.notna(r["sales_abc"]) else None,
            "billed_lines": i(r["billed_lines"]) if pd.notna(r["sales_abc"]) else None,
            "xyz": s(r["xyz"]),
            "fsn": s(r["fsn"]),
            "abc_xyz_fsn": s(r["abc_xyz_fsn"]),
            "policy_tier": s(r["policy_tier"]),
            "demand_category": s(r["demand_category"]),
            "demand_cluster": None,
            "demand_segment": s(r["behaviour_class"]),
            "behaviour_source": s(r.get("behaviour_source")) or None,
            "system": s(r.get("system")) or None,
            "catalogue_section": s(r.get("catalogue_section")) or None,
            "in_ssop": None,
            "avg_monthly_demand": _planned_f(r, "avg_monthly_demand"),
            "cv": _planned_f(r, "cv"),
            "p_zero": _planned_f(r, "p_zero"),
            "active_months": i(r["active_months"]) if r["has_planning"] else None,
            "total_months": i(r["total_months"]) if r["has_planning"] else None,
            "total_issue_qty": _planned_f(r, "total_issue_qty"),
            "total_issue_value_lkr": _planned_f(r, "total_issue_value_lkr"),
            "total_return_qty": _planned_f(r, "total_return_qty"),
            "last_issue_date": s(r["last_issue_date"]) or None,
            "part_type": s(r["part_type"]) or None,
        }
        for _, r in page.iterrows()
    ]
    sales_audit = mart("mart_ui_sales_abc_audit")
    return {
        "total": total,
        "rows": rows,
        "classified_count": len(billed),
        "unclassified_count": total - len(billed),
        "active_count": len(billed),
        "inactive_count": total - len(billed),
        "order_classified_count": len(classified),
        "sales_abc_audit": (
            {
                "window_start": s(sales_audit.at[0, "window_start"]),
                "window_end": s(sales_audit.at[0, "window_end"]),
                "sales_lines": i(sales_audit.at[0, "sales_lines"]),
                "code_linked_lines": i(sales_audit.at[0, "code_linked_lines"]),
                "description_linked_lines": i(sales_audit.at[0, "description_linked_lines"]),
                "unmapped_lines": i(sales_audit.at[0, "unmapped_lines"]),
                "ambiguous_lines": i(sales_audit.at[0, "ambiguous_lines"]),
                "no_match_lines": i(sales_audit.at[0, "no_match_lines"]),
                "linked_skus": i(sales_audit.at[0, "linked_skus"]),
                "active_skus": i(sales_audit.at[0, "active_skus"]),
                "return_only_skus": i(sales_audit.at[0, "return_only_skus"]),
                **{
                    key: (f if key.endswith("_value") else i)(sales_audit.at[0, key])
                    for key in (
                        "out_of_scope_lines",
                        "out_of_scope_value",
                        "in_scope_lines",
                        "in_scope_value",
                        "linked_value",
                        "demand_resolved_lines",
                        "demand_split_lines",
                    )
                    if key in sales_audit.columns
                },
            }
            if not sales_audit.empty
            else None
        ),
        "classification_coverage": {
            label: _classification_coverage(frame, column)
            for label, column in (
                ("ABC", "abc"),
                ("XYZ", "xyz"),
                ("FSN", "fsn"),
                ("Demand pattern", "demand_category"),
                ("Behaviour", "behaviour_class"),
                ("Catalogue type", "part_type"),
            )
        },
        "abc_counts": _counts(classified, "abc"),
        "xyz_counts": _counts(classified, "xyz"),
        "fsn_counts": _counts(classified, "fsn"),
        "segment_counts": _counts(frame, "behaviour_class"),
        "system_counts": _counts(frame, "system"),
        "behaviour_source_counts": _counts(frame, "behaviour_source"),
        "demand_category_counts": _counts(classified, "demand_category"),
        "tier_counts": _counts(classified, "policy_tier"),
        "part_type_counts": _counts(frame, "part_type"),
        "abc_fsn_counts": {
            abc_key: {
                fsn_key: int(
                    ((classified["abc"] == abc_key) & (classified["fsn"] == fsn_key)).sum()
                )
                for fsn_key in ("F", "S", "N")
            }
            for abc_key in ("A", "B", "C")
        },
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
    frame = _sku(source="mart_ui_part_master_analysis", status=status, abc=abc, search=search)
    total = len(frame)
    # Highest stock value first; among equal values (every stockout is zero) the part with
    # the most monthly demand comes first, so the parts that matter lead the list.
    keys = [c for c in ("stock_value_lkr", "cover_demand_monthly") if c in frame.columns]
    page = frame.sort_values(keys, ascending=False, na_position="last").iloc[
        offset : offset + limit
    ]
    rows = [
        {
            "material_9": s(r["material_9"]),
            "active_sku_id": s(r["active_sku_id"]),
            "description": s(r["description"]),
            "material_type": s(r["material_type"]),
            "material_group": s(r["material_group"]),
            "brand": s(r["brand"]),
            "compatible_models": s(r["compatible_models"]),
            "alias_count": i(r["alias_count"]),
            "superseded_numbers": s(r["superseded_numbers"]),
            "has_planning": bool(r["has_planning"]),
            "has_stock_snapshot": bool(r["has_stock_snapshot"]),
            "abc": s(r["abc"]),
            "xyz": s(r["xyz"]),
            "fsn": s(r["fsn"]),
            "policy_tier": s(r["policy_tier"]),
            "stock_on_hand": f(r["stock_on_hand"])
            if r["has_planning"] or r["has_stock_snapshot"]
            else None,
            "stock_value_lkr": _planned_f(r, "stock_value_lkr"),
            "coverage_months": _planned_f(r, "coverage_months"),
            "on_order": f(r.get("on_order")) if pd.notna(r.get("on_order")) else 0.0,
            "position_qty": f(
                (r.get("stock_on_hand") if pd.notna(r.get("stock_on_hand")) else 0.0)
                + (r.get("on_order") if pd.notna(r.get("on_order")) else 0.0)
            ),
            "on_hand_coverage_months": _planned_f(r, "on_hand_coverage_months"),
            "cover_demand_monthly": _planned_f(r, "cover_demand_monthly"),
            "on_order_value_lkr": _planned_f(r, "on_order_value_lkr"),
            "order_qty": _planned_f(r, "roq"),
            "days_of_stock": _planned_f(r, "days_of_stock"),
            "stock_status": s(r["stock_status"]),
            "avg_monthly_demand": _planned_f(r, "avg_monthly_demand"),
            "forecast_lt": _planned_f(r, "forecast_lt"),
            "method": s(r["method"]),
            "total_receipts": None,
            "total_issues": _planned_f(r, "total_issue_qty"),
            "total_returns": _planned_f(r, "total_return_qty"),
            "last_movement_date": s(r["last_issue_date"]) or None,
        }
        for _, r in page.iterrows()
    ]
    excess = frame[frame["stock_status"] == "excess"]
    return {
        "total": total,
        "rows": rows,
        "classified_count": int(frame["has_planning"].sum()),
        "stock_snapshot_count": int(frame["has_stock_snapshot"].sum()),
        "unassessed_count": int((~frame["has_planning"]).sum()),
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
        "on_order_units": float(
            pd.to_numeric(frame.get("on_order"), errors="coerce").fillna(0).sum()
        )
        if "on_order" in frame.columns
        else 0.0,
        "on_hand_units": float(
            pd.to_numeric(frame.get("stock_on_hand"), errors="coerce").fillna(0).sum()
        ),
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
            "compatible_models": s(r["compatible_models"]),
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
            "compatible_models": s(r["compatible_models"]),
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
    scope = segment_skus()
    if scope is not None:
        master = master[master["active_sku_id"].astype(str).isin(scope)]
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


def _models_by_active_sku(
    master: pd.DataFrame, rows: Iterable[tuple[str, str, list[str]]]
) -> tuple[dict[str, set[str]], int]:
    """Match catalogue models to current identities within their product type.

    Business meaning: an MC catalogue match on an old number does not make its
    current OBM replacement an MC model variant on the OBM page.
    """
    from src.catalogue.store import material_key, material_key_forms  # noqa: PLC0415

    segments = sku_segments(master)
    to_active: dict[tuple[str, str], str] = {}
    for column in ["material", *[c for c in _SUPERSEDE_COLUMNS if c in master.columns]]:
        for number, active in zip(master[column], master["active_sku_id"], strict=True):
            if isinstance(number, str) and number.strip():
                segment = segments.get(active)
                if segment:
                    for form in material_key_forms(material_key(number)):
                        to_active.setdefault((form, segment), active)

    per_active: dict[str, set[str]] = {}
    unmatched = 0
    for key, product_type, models in rows:
        segment = str(product_type).strip().upper()
        active = next(
            (
                to_active[(form, segment)]
                for form in material_key_forms(material_key(key))
                if (form, segment) in to_active
            ),
            None,
        )
        if active is None:
            unmatched += 1
            continue
        per_active.setdefault(active, set()).update(models or [])
    return per_active, unmatched


def _catalogue_compatibility(master: pd.DataFrame) -> tuple[dict[str, set[str]], dict[str, Any]]:
    """Compatible model variants per current identity, from the catalogue database.

    Business meaning: match material and superseded numbers to the current identity,
    but credit only catalogue models from its MC or OBM product type. A cross-brand
    chain does not leak motorcycle models into the OBM Part Master.

    Returns the models per active_sku_id and a summary; an empty mapping with the
    reason when the database cannot be reached.
    """
    from src.catalogue.store import (  # noqa: PLC0415
        connect,
        ensure_schema,
    )
    from src.core.errors import CatalogueStoreError  # noqa: PLC0415

    try:
        with connect() as conn:
            ensure_schema(conn)
            rows = conn.execute(
                "SELECT upper(regexp_replace(p.part_no, '[^A-Za-z0-9]', '', 'g')), "
                "c.product_type, "
                "array_agg(DISTINCT m.model_name || ' - ' || m.model_code "
                "ORDER BY m.model_name || ' - ' || m.model_code) "
                "FROM catalogue_parts p JOIN models m USING (model_code) "
                "JOIN catalogues c USING (catalogue_id) WHERE c.status = 'loaded' "
                "GROUP BY 1, 2"
            ).fetchall()
    except CatalogueStoreError as exc:
        return {}, {"source": "step_02", "error": str(exc)}

    per_active, unmatched = _models_by_active_sku(master, rows)
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
    # The database view contains raw YM materials, whereas both section pages show
    # one current identity per supersession chain. Use the same grain for MC and OBM.
    narrowed = request_segment() is not None or REQUEST_CATEGORY.get() is not None
    served = None if narrowed else _pn_yamaha_master_view(search, model, limit, offset)
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
    segments = sku_segments(master)
    frame = master.sort_values("chain_depth").drop_duplicates("active_sku_id").copy()
    frame["segment"] = frame["active_sku_id"].map(segments)
    if request_segment():
        frame = frame[frame["segment"] == request_segment()]
    if category := REQUEST_CATEGORY.get():
        frame = frame[part_category(frame["description"], frame["segment"]) == category]
    scoped_master = master[master["active_sku_id"].isin(frame["active_sku_id"])]
    per_active, compatibility = _catalogue_compatibility(scoped_master)
    if compatibility["source"] == "catalogue_database":
        frame["compatible_models"] = frame["active_sku_id"].map(
            lambda active: ", ".join(sorted(per_active.get(active, ())))
        )
    else:
        frame.loc[frame["segment"] == "OBM", "compatible_models"] = ""
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
                "latest_ss": s(r.get("latest_ss")),
                "description": s(r["description"]),
                "compatible_models": s(r["compatible_models"]),
                "in_catalogue": bool(s(r["compatible_models"]).strip()),
                "supersedes": [s(r.get(column)) for column in _SUPERSEDE_COLUMNS],
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
