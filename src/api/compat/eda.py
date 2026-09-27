"""Spare Parts Analysis: the orders and billed-sales envelopes.

Both endpoints take the same three filters and answer from the cuts published at that
grain. Every figure is a sum of published measures or a quotient of two of them.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, Query
from src.api.compat.filters import (
    apply_filters,
    collapse,
    f,
    i,
    mart,
    ratio,
    s,
    years_available,
)
from src.io.parquet import read_table, table_exists

router = APIRouter(tags=["eda"])

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

ORDER_MEASURES = [
    "order_lines",
    "ordered_quantity",
    "confirmed_quantity",
    "lost_quantity",
    "ordered_value",
    "confirmed_value",
    "lost_sale_value",
]
RETURN_MEASURES = ["return_lines", "return_quantity", "return_value"]
SALES_MEASURES = [
    "sale_lines",
    "return_lines",
    "sale_value_lkr",
    "return_value_lkr",
    "sale_qty",
    "return_qty",
    "margin_lkr",
]

#: Share of cumulative value that defines the Pareto head the UI reports.
PARETO_SHARE = 80.0

#: Dealer tiers by share of order value: the top decile is A, the next two are B.
TIER_A_PCT, TIER_B_PCT = 10.0, 30.0


def _pareto_count(values: pd.Series) -> int:
    """How many entities make up the first 80% of value."""
    if values.empty:
        return 0
    ordered = values.sort_values(ascending=False)
    total = float(ordered.sum())
    if total <= 0:
        return 0
    cumulative = ordered.cumsum() / total * 100.0
    return int((cumulative <= PARETO_SHARE).sum()) + 1


def _tier(rank_pct: float) -> str:
    if rank_pct <= TIER_A_PCT:
        return "A"
    if rank_pct <= TIER_B_PCT:
        return "B"
    return "C"


@router.get("/eda/orders")
def orders_eda(
    dealer_type: str = Query("MC"),
    mc_category: str = Query("ALL"),
    year: int = Query(0),
) -> dict[str, Any]:
    """Ordered demand: what dealers asked for, what was confirmed, and what was lost."""
    filters = {"dealer_type": dealer_type, "mc_category": mc_category, "year": year}
    monthly_all = mart("mart_ui_orders_monthly")
    if not year and years_available(monthly_all):
        year = years_available(monthly_all)[-1]
        filters["year"] = year
    monthly = apply_filters(monthly_all, **filters)

    totals = collapse(monthly, [], ORDER_MEASURES)
    t = totals.iloc[0].to_dict() if not totals.empty else dict.fromkeys(ORDER_MEASURES, 0.0)

    # A part year (the current one) is only comparable with the same months a year earlier.
    year_months = sorted(monthly_all.loc[monthly_all["year"] == year, "month"].astype(str).unique())
    last_mm = int(year_months[-1][5:7]) if year_months else 12
    period_label = f"{year}" if last_mm == 12 else f"{year} Jan–{MONTH_ABBR[last_mm - 1]}"

    def same_months(frame: pd.DataFrame, which_year: int) -> pd.DataFrame:
        rows = frame[frame["year"] == which_year]
        return rows[rows["month"].astype(str).str[5:7].astype(int) <= last_mm]

    prior_frame = same_months(
        apply_filters(monthly_all, dealer_type=dealer_type, mc_category=mc_category), year - 1
    )
    prior_period: dict[str, Any] | None = None
    if not prior_frame.empty:
        pt = collapse(prior_frame, [], ORDER_MEASURES).iloc[0].to_dict()
        prior_period = {
            "year": int(year - 1),
            "label": f"{year - 1}"
            if last_mm == 12
            else f"{year - 1} Jan–{MONTH_ABBR[last_mm - 1]}",
            "order_lines": i(pt.get("order_lines")),
            "ordered_value": f(pt.get("ordered_value")),
            "ordered_quantity": f(pt.get("ordered_quantity")),
            "lost_quantity": f(pt.get("lost_quantity")),
            "fill_rate": ratio(pt.get("confirmed_quantity"), pt.get("ordered_quantity")),
        }

    returns = apply_filters(mart("mart_ui_returns_monthly"), **filters)
    return_totals = collapse(returns, [], RETURN_MEASURES)
    r = (
        return_totals.iloc[0].to_dict()
        if not return_totals.empty
        else dict.fromkeys(RETURN_MEASURES, 0.0)
    )

    parts = collapse(
        apply_filters(mart("mart_ui_orders_by_part"), **filters),
        ["active_sku_id", "description"],
        ORDER_MEASURES,
    )
    dealers = collapse(
        apply_filters(mart("mart_ui_orders_by_dealer"), **filters),
        ["dealer_code", "dealer_name", "province", "district", "rm", "ase"],
        ORDER_MEASURES,
    )
    documents = collapse(
        apply_filters(mart("mart_ui_orders_documents"), **filters), ["doc_class"], ["documents"]
    )
    doc_counts = {s(row["doc_class"]): i(row["documents"]) for _, row in documents.iterrows()}
    total_docs = sum(doc_counts.values())

    fulfilment = collapse(
        apply_filters(mart("mart_ui_orders_fulfilment"), **filters),
        ["fulfilment_class"],
        ORDER_MEASURES,
    )

    ordered_value = f(t.get("ordered_value"))
    confirmed_value = f(t.get("confirmed_value"))
    ordered_qty = f(t.get("ordered_quantity"))
    confirmed_qty = f(t.get("confirmed_quantity"))
    return_value = f(r.get("return_value"))

    monthly_rows = collapse(monthly, ["month"], ORDER_MEASURES).sort_values("month")
    returns_by_month = collapse(returns, ["month"], RETURN_MEASURES)
    monthly_rows = monthly_rows.merge(returns_by_month, on="month", how="left").fillna(
        {"return_lines": 0.0}
    )

    # Dealer tiers and the Pareto head, by share of order value.
    dealer_perf: list[dict[str, Any]] = []
    if not dealers.empty:
        ranked = dealers.sort_values("ordered_value", ascending=False).reset_index(drop=True)
        ranked["rank_pct"] = (ranked.index + 1) / len(ranked) * 100.0
        for _, row in ranked.iterrows():
            dealer_perf.append(
                {
                    "dealer_code": s(row["dealer_code"]),
                    "dealer_name": s(row["dealer_name"]),
                    "province": s(row["province"]),
                    "district": s(row["district"]),
                    "rm": s(row["rm"]),
                    "ase": s(row["ase"]),
                    "po_lines": i(row["order_lines"]),
                    "order_value_lkr": f(row["ordered_value"]),
                    "fill_rate_pct": ratio(
                        row["confirmed_quantity"], row["ordered_quantity"], scale=100
                    ),
                    "return_rate_pct": 0.0,
                    "dealer_tier": _tier(f(row["rank_pct"])),
                    "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
                }
            )

    return_by_dealer = collapse(
        apply_filters(mart("mart_ui_returns_by_dealer"), **filters),
        ["dealer_name"],
        RETURN_MEASURES,
    )
    return_lookup = {
        s(row["dealer_name"]): f(row["return_value"]) for _, row in return_by_dealer.iterrows()
    }
    for row in dealer_perf:
        row["return_rate_pct"] = ratio(
            return_lookup.get(row["dealer_name"], 0.0), row["order_value_lkr"], scale=100
        )

    def hierarchy(table: str, keys: list[str]) -> pd.DataFrame:
        return collapse(apply_filters(mart(table), **filters), keys, ORDER_MEASURES)

    rm_rows = hierarchy("mart_ui_orders_by_rm", ["rm", "province"])
    ase_rows = hierarchy("mart_ui_orders_by_ase", ["ase", "rm", "province"])
    district_rows = hierarchy("mart_ui_orders_by_district", ["province", "district"])
    province_rows = hierarchy("mart_ui_orders_by_province", ["province"])

    def dealer_count(column: str, value: str) -> int:
        if dealers.empty or column not in dealers.columns:
            return 0
        return int(dealers.loc[dealers[column] == value, "dealer_name"].nunique())

    reasons = collapse(
        apply_filters(mart("mart_ui_orders_reasons"), **filters),
        ["reason"],
        ["rejected_lines", "rejected_qty"],
    ).sort_values("rejected_qty", ascending=False)
    total_rejected_qty = float(reasons["rejected_qty"].sum()) if not reasons.empty else 0.0

    return_reasons = collapse(
        apply_filters(mart("mart_ui_returns_reasons"), **filters),
        ["reason"],
        ["rejected_lines", "rejected_qty"],
    ).sort_values("rejected_qty", ascending=False)
    total_return_qty = (
        float(return_reasons["rejected_qty"].sum()) if not return_reasons.empty else 0.0
    )

    return_types = collapse(
        apply_filters(mart("mart_ui_returns_by_type"), **filters),
        ["document_type"],
        ["return_lines"],
    )

    rejections = apply_filters(mart("mart_ui_orders_rejections"), **filters).head(200)

    # Business insights cover every segment for the selected year; the UI labels the period.
    category_all = collapse(
        monthly_all[monthly_all["year"] == year], ["material_category"], ORDER_MEASURES
    )
    book_value = float(category_all["ordered_value"].sum()) if not category_all.empty else 0.0
    category_mix = [
        {
            "segment": s(row["material_category"]),
            "order_lines": i(row["order_lines"]),
            "value_lkr": f(row["ordered_value"]),
            "value_share_pct": ratio(row["ordered_value"], book_value, scale=100),
            "fill_rate_pct": ratio(row["confirmed_quantity"], row["ordered_quantity"], scale=100),
        }
        for _, row in category_all.sort_values("ordered_value", ascending=False).iterrows()
    ]

    yoy: list[dict[str, Any]] = []
    curr_cat = collapse(same_months(monthly_all, year), ["material_category"], ORDER_MEASURES)
    prev_cat = collapse(same_months(monthly_all, year - 1), ["material_category"], ORDER_MEASURES)
    if not curr_cat.empty and not prev_cat.empty:
        prev_by = prev_cat.set_index("material_category")
        for _, row in curr_cat.sort_values("ordered_value", ascending=False).iterrows():
            segment = row["material_category"]
            prev = prev_by.loc[segment] if segment in prev_by.index else None
            prev_value = float(prev["ordered_value"]) if prev is not None else 0.0
            curr_value = float(row["ordered_value"])
            yoy.append(
                {
                    "segment": s(segment),
                    "year_prev": int(year - 1),
                    "year_curr": int(year),
                    "period": "full year" if last_mm == 12 else f"Jan–{MONTH_ABBR[last_mm - 1]}",
                    "value_year_prev": prev_value,
                    "value_year_curr": curr_value,
                    "yoy_pct": ratio(curr_value - prev_value, prev_value, scale=100),
                    "lines_year_prev": i(prev["order_lines"]) if prev is not None else 0,
                    "lines_year_curr": i(row["order_lines"]),
                }
            )

    bands: list[dict[str, Any]] = []
    parts_by_cat = collapse(
        apply_filters(mart("mart_ui_orders_by_part"), year=year),
        ["material_category", "active_sku_id"],
        ORDER_MEASURES,
    )
    if not parts_by_cat.empty:
        parts_by_cat["fill"] = parts_by_cat.apply(
            lambda row: ratio(row["confirmed_quantity"], row["ordered_quantity"]), axis=1
        )
        for segment, group in parts_by_cat.groupby("material_category"):
            bands.append(
                {
                    "segment": s(segment),
                    "above_98": int((group["fill"] >= 0.98).sum()),
                    "between_95_98": int(((group["fill"] >= 0.95) & (group["fill"] < 0.98)).sum()),
                    "between_90_95": int(((group["fill"] >= 0.90) & (group["fill"] < 0.95)).sum()),
                    "below_90": int((group["fill"] < 0.90).sum()),
                }
            )

    short_ship = parts.copy()
    if not short_ship.empty:
        short_ship = short_ship[short_ship["lost_quantity"] > 0].sort_values(
            "lost_quantity", ascending=False
        )

    mc_monthly = collapse(
        apply_filters(mart("mart_ui_orders_monthly"), dealer_type=dealer_type, year=year),
        ["month", "material_category"],
        ["ordered_value"],
    )
    mc_monthly_category: list[dict[str, Any]] = []
    if not mc_monthly.empty:
        pivot = mc_monthly.pivot_table(
            index="month", columns="material_category", values="ordered_value", aggfunc="sum"
        ).fillna(0.0)
        for month, row in pivot.iterrows():
            spare = float(row.get("MC Spare Parts", 0.0)) + float(row.get("OBM Spare Parts", 0.0))
            mc_monthly_category.append(
                {
                    "period": s(month),
                    "lubricant_lkr": float(row.get("Lubricant", 0.0)),
                    "battery_lkr": float(row.get("Battery", 0.0)),
                    "tyre_lkr": float(row.get("Tyre", 0.0)),
                    "spare_parts_lkr": spare,
                    "total_lkr": float(row.sum()),
                }
            )

    concentration = mart("mart_ui_return_concentration")
    fraud_alerts = [
        {
            "dealer_code": s(row["dealer_code"]),
            "dealer_name": s(row["dealer_name"]),
            "month": s(row["month"]),
            "return_share_pct": f(row["return_share_pct"]),
        }
        for _, row in concentration.head(50).iterrows()
    ]

    lead = (
        read_table("facts", "lead_time_stats")
        if table_exists("facts", "lead_time_stats")
        else pd.DataFrame()
    )
    dispatch = lead[lead["scope"] == "ALL"] if not lead.empty else pd.DataFrame()

    tier_counts = pd.Series([row["dealer_tier"] for row in dealer_perf]).value_counts()

    return {
        "data_year": int(year)
        if year
        else (years_available(monthly_all)[-1] if years_available(monthly_all) else 0),
        "available_years": years_available(monthly_all),
        "total_po": i(t.get("order_lines")),
        "period_label": period_label,
        "prior_period": prior_period,
        "lost_quantity": f(t.get("lost_quantity")),
        "total_returns": i(r.get("return_lines")),
        "avg_fill_rate": ratio(confirmed_qty, ordered_qty),
        "avg_lead_time_days": f(dispatch["mean_days"].iloc[0]) if not dispatch.empty else 0.0,
        "fill_rate_lt1_count": int((parts["confirmed_quantity"] < parts["ordered_quantity"]).sum())
        if not parts.empty
        else 0,
        "total_order_value_lkr": ordered_value,
        "total_confirmed_value_lkr": confirmed_value,
        "value_fill_rate_pct": ratio(confirmed_value, ordered_value, scale=100),
        "total_return_value_lkr": return_value,
        "return_rate_value_pct": ratio(return_value, ordered_value, scale=100),
        "unfulfill_value_lkr": f(t.get("lost_sale_value")),
        "sales_qty": confirmed_qty,
        "unique_skus": int(parts["active_sku_id"].nunique()) if not parts.empty else 0,
        "total_po_documents": total_docs,
        "return_order_reasons": [
            {
                "reason": s(row["reason"]),
                "rejected_lines": i(row["rejected_lines"]),
                "rejected_qty": f(row["rejected_qty"]),
                "share_pct": ratio(row["rejected_qty"], total_return_qty, scale=100),
            }
            for _, row in return_reasons.head(20).iterrows()
        ],
        "return_type_breakdown": {
            s(row["document_type"]): i(row["return_lines"]) for _, row in return_types.iterrows()
        },
        "top_dealers": [
            {
                "dealer": row["dealer_name"],
                "order_count": row["po_lines"],
                "total_value_lkr": row["order_value_lkr"],
            }
            for row in dealer_perf[:20]
        ],
        "monthly_trend": [
            {
                "period": s(row["month"]),
                "po_count": i(row["order_lines"]),
                "return_count": i(row.get("return_lines", 0)),
                "total_value_lkr": f(row["ordered_value"]),
                "confirmed_value_lkr": f(row["confirmed_value"]),
            }
            for _, row in monthly_rows.iterrows()
        ],
        "rejections": [
            {
                "material": s(row["material"]),
                "description": s(row["description"]),
                "customer": s(row["customer"]),
                "document_date": s(row["document_date"]),
                "order_qty": f(row["order_qty"]),
                "lost_qty": f(row["lost_qty"]),
                "fill_rate": ratio(row["confirmed_quantity"], row["order_qty"]),
            }
            for _, row in rejections.iterrows()
        ],
        "orders_received_breakdown": {
            "total_documents": total_docs,
            "fully_filled": doc_counts.get("fully_filled", 0),
            "partial_fill": doc_counts.get("partial_fill", 0),
            "complete_zero": doc_counts.get("complete_zero", 0),
        },
        "rejection_reasons": [
            {
                "reason": s(row["reason"]),
                "rejected_lines": i(row["rejected_lines"]),
                "rejected_qty": f(row["rejected_qty"]),
                "share_pct": ratio(row["rejected_qty"], total_rejected_qty, scale=100),
            }
            for _, row in reasons.head(20).iterrows()
        ],
        "part_analysis": [
            {
                "material": s(row["active_sku_id"]),
                "description": s(row["description"]),
                "order_lines": i(row["order_lines"]),
                "order_qty": f(row["ordered_quantity"]),
                "confirmed_qty": f(row["confirmed_quantity"]),
                "total_value_lkr": f(row["ordered_value"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
                "short_qty": f(row["lost_quantity"]),
            }
            for _, row in parts.sort_values("ordered_value", ascending=False).head(500).iterrows()
        ],
        "dealer_perf": dealer_perf,
        "rm_perf": [
            {
                "rm": s(row["rm"]),
                "province": s(row.get("province", "")),
                "unique_dealers": dealer_count("rm", s(row["rm"])),
                "po_lines": i(row["order_lines"]),
                "order_value_lkr": f(row["ordered_value"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "return_rate_pct": 0.0,
                "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
            }
            for _, row in rm_rows.sort_values("ordered_value", ascending=False).iterrows()
        ],
        "ase_perf": [
            {
                "ase": s(row["ase"]),
                "rm": s(row.get("rm", "")),
                "province": s(row.get("province", "")),
                "unique_dealers": dealer_count("ase", s(row["ase"])),
                "po_lines": i(row["order_lines"]),
                "order_value_lkr": f(row["ordered_value"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "return_rate_pct": 0.0,
            }
            for _, row in ase_rows.sort_values("ordered_value", ascending=False).iterrows()
        ],
        "district_perf": [
            {
                "province": s(row["province"]),
                "district": s(row["district"]),
                "unique_dealers": dealer_count("district", s(row["district"])),
                "po_lines": i(row["order_lines"]),
                "order_value_lkr": f(row["ordered_value"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
                "return_rate_pct": 0.0,
            }
            for _, row in district_rows.sort_values("ordered_value", ascending=False).iterrows()
        ],
        "province_analysis": [
            {
                "province": s(row["province"]),
                "unique_dealers": dealer_count("province", s(row["province"])),
                "po_lines": i(row["order_lines"]),
                "order_value_lkr": f(row["ordered_value"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "return_rate_pct": 0.0,
                "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
            }
            for _, row in province_rows.sort_values("ordered_value", ascending=False).iterrows()
        ],
        "category_mix": category_mix,
        "yoy_growth": yoy,
        "province_perf": [
            {
                "province": s(row["province"]),
                "order_value_lkr": f(row["ordered_value"]),
                "value_share_pct": ratio(row["ordered_value"], ordered_value, scale=100),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "dealer_count": dealer_count("province", s(row["province"])),
            }
            for _, row in province_rows.sort_values("ordered_value", ascending=False).iterrows()
        ],
        "top_short_shipped": [
            {
                "material": s(row["active_sku_id"]),
                "description": s(row["description"]),
                "short_qty": f(row["lost_quantity"]),
                "fill_rate_pct": ratio(
                    row["confirmed_quantity"], row["ordered_quantity"], scale=100
                ),
                "occurrences": i(row["order_lines"]),
            }
            for _, row in short_ship.head(50).iterrows()
        ],
        "fill_rate_bands": bands,
        "dealer_health_summary": {
            "a_tier": int(tier_counts.get("A", 0)),
            "b_tier": int(tier_counts.get("B", 0)),
            "c_tier": int(tier_counts.get("C", 0)),
            "dormant_count": 0,
            "total_dealers": len(dealer_perf),
        },
        "pareto_summary": {
            "sku_80pct_count": _pareto_count(parts["ordered_value"]) if not parts.empty else 0,
            "total_skus": int(parts["active_sku_id"].nunique()) if not parts.empty else 0,
            "dealer_80pct_count": _pareto_count(dealers["ordered_value"])
            if not dealers.empty
            else 0,
            "total_dealers": len(dealer_perf),
        },
        "category_cross": {
            "multi_category": 0,
            "single_category": 0,
            "total_mc_dealers": len(dealer_perf),
        },
        "rejection_rate_pct": ratio(t.get("lost_quantity"), ordered_qty, scale=100),
        "fraud_alerts": fraud_alerts,
        "mc_monthly_category": mc_monthly_category,
        "fulfillment": {
            "total_lines": i(t.get("order_lines")),
            **{
                key.replace(" ", "_"): {
                    "lines": i(group["order_lines"].sum()),
                    "pct_of_lines": ratio(
                        group["order_lines"].sum(), t.get("order_lines"), scale=100
                    ),
                    "order_qty": f(group["ordered_quantity"].sum()),
                    "confirmed_qty": f(group["confirmed_quantity"].sum()),
                    "confirmed_value_lkr": f(group["confirmed_value"].sum()),
                }
                for key, group in (
                    fulfilment.groupby("fulfilment_class") if not fulfilment.empty else []
                )
            },
            "total_docs": total_docs,
            "docs_fully_filled": doc_counts.get("fully_filled", 0),
            "docs_fully_filled_pct": ratio(
                doc_counts.get("fully_filled", 0), total_docs, scale=100
            ),
            "docs_partially_filled": doc_counts.get("partial_fill", 0),
            "docs_partially_filled_pct": ratio(
                doc_counts.get("partial_fill", 0), total_docs, scale=100
            ),
            "docs_complete_zero": doc_counts.get("complete_zero", 0),
            "docs_complete_zero_pct": ratio(
                doc_counts.get("complete_zero", 0), total_docs, scale=100
            ),
        },
    }


@router.get("/eda/sales")
def sales_eda(
    dealer_type: str = Query("MC"),
    mc_category: str = Query("ALL"),
    year: int = Query(0),
) -> dict[str, Any]:
    """Billed sales: invoiced revenue, margin and returns."""
    filters = {"dealer_type": dealer_type, "mc_category": mc_category, "year": year}
    monthly_all = mart("mart_ui_sales_monthly")
    if not year and years_available(monthly_all):
        year = years_available(monthly_all)[-1]
        filters["year"] = year
    monthly = apply_filters(monthly_all, **filters)
    totals = collapse(monthly, [], SALES_MEASURES)
    t = totals.iloc[0].to_dict() if not totals.empty else dict.fromkeys(SALES_MEASURES, 0.0)

    orders_slice = apply_filters(mart("mart_ui_orders_monthly"), **filters)
    orders_totals = collapse(orders_slice, [], ["ordered_value", "confirmed_value"])
    orders_value = f(orders_totals.iloc[0].get("ordered_value")) if not orders_totals.empty else 0.0
    orders_confirmed = (
        f(orders_totals.iloc[0].get("confirmed_value")) if not orders_totals.empty else 0.0
    )

    parts = collapse(
        apply_filters(mart("mart_ui_sales_by_part"), **filters), ["material"], SALES_MEASURES
    )
    dealers_raw = apply_filters(mart("mart_ui_sales_by_dealer"), **filters)
    dealers = collapse(
        dealers_raw,
        ["dealer_name", "province", "district", "rm", "ase"],
        [*SALES_MEASURES, "unique_skus"],
    )
    invoices = collapse(apply_filters(mart("mart_ui_sales_invoices"), **filters), [], ["invoices"])

    sale_value = f(t.get("sale_value_lkr"))
    return_value = f(t.get("return_value_lkr"))

    def hierarchy(table: str, keys: list[str]) -> pd.DataFrame:
        return collapse(apply_filters(mart(table), **filters), keys, SALES_MEASURES)

    def hier_rows(frame: pd.DataFrame, key: str) -> list[dict[str, Any]]:
        out = []
        for _, row in frame.sort_values("sale_value_lkr", ascending=False).iterrows():
            entity = s(row[key])
            out.append(
                {
                    key: entity,
                    **({"rm": s(row["rm"])} if key == "ase" and "rm" in row else {}),
                    **(
                        {"province": s(row["province"])}
                        if key == "district" and "province" in row
                        else {}
                    ),
                    "sale_value_lkr": f(row["sale_value_lkr"]),
                    "return_value_lkr": f(row["return_value_lkr"]),
                    "return_rate_pct": ratio(
                        row["return_value_lkr"], row["sale_value_lkr"], scale=100
                    ),
                    "sale_qty": f(row["sale_qty"]),
                    "dealer_count": int(
                        dealers.loc[dealers.get(key, pd.Series(dtype=str)) == entity].shape[0]
                    )
                    if key in dealers.columns
                    else 0,
                    "unique_skus": 0,
                }
            )
        return out

    category = collapse(
        apply_filters(mart("mart_ui_sales_monthly"), dealer_type=dealer_type, year=year),
        ["material_category"],
        SALES_MEASURES,
    )
    category_total = float(category["sale_value_lkr"].sum()) if not category.empty else 0.0

    mc_monthly: list[dict[str, Any]] = []
    by_month_cat = collapse(
        apply_filters(mart("mart_ui_sales_monthly"), dealer_type=dealer_type, year=year),
        ["month", "material_category"],
        ["sale_value_lkr"],
    )
    if not by_month_cat.empty:
        pivot = by_month_cat.pivot_table(
            index="month", columns="material_category", values="sale_value_lkr", aggfunc="sum"
        ).fillna(0.0)
        for month, row in pivot.iterrows():
            spare = float(row.get("MC Spare Parts", 0.0)) + float(row.get("OBM Spare Parts", 0.0))
            mc_monthly.append(
                {
                    "period": s(month),
                    "lubricant_lkr": float(row.get("Lubricant", 0.0)),
                    "battery_lkr": float(row.get("Battery", 0.0)),
                    "tyre_lkr": float(row.get("Tyre", 0.0)),
                    "spare_parts_lkr": spare,
                    "total_lkr": float(row.sum()),
                }
            )

    monthly_rows = collapse(monthly, ["month"], SALES_MEASURES).sort_values("month")
    orders_by_month = collapse(
        apply_filters(mart("mart_ui_orders_monthly"), **filters), ["month"], ["ordered_value"]
    )
    monthly_rows = monthly_rows.merge(orders_by_month, on="month", how="left").fillna(
        {"ordered_value": 0.0}
    )

    return {
        "data_year": int(year)
        if year
        else (years_available(monthly_all)[-1] if years_available(monthly_all) else 0),
        "available_years": years_available(monthly_all),
        "total_sale_value_lkr": sale_value,
        "total_return_value_lkr": return_value,
        "net_sale_value_lkr": sale_value - return_value,
        "return_rate_pct": ratio(return_value, sale_value, scale=100),
        "total_sale_qty": f(t.get("sale_qty")),
        "total_return_qty": f(t.get("return_qty")),
        "unique_parts": int(parts["material"].nunique()) if not parts.empty else 0,
        "unique_dealers": int(dealers["dealer_name"].nunique()) if not dealers.empty else 0,
        "total_sale_lines": i(t.get("sale_lines")),
        "total_return_lines": i(t.get("return_lines")),
        "total_invoices": i(invoices.iloc[0].get("invoices")) if not invoices.empty else 0,
        "order_received_lkr": orders_value,
        # Not billed value over ordered value: the two source files capture different
        # populations — this vintage's orders export covers one sales office and about a
        # quarter of the units that are actually invoiced — so their ratio reads near
        # 900% and means nothing. Fulfilment is reported from the orders file's own
        # confirmed-against-ordered value, which is a real fill rate.
        "fulfillment_pct": ratio(orders_confirmed, orders_value, scale=100),
        "monthly_trend": [
            {
                "period": s(row["month"]),
                "sale_value_lkr": f(row["sale_value_lkr"]),
                "return_value_lkr": f(row["return_value_lkr"]),
                "net_value_lkr": f(row["sale_value_lkr"]) - f(row["return_value_lkr"]),
                "sale_qty": f(row["sale_qty"]),
                "return_qty": f(row["return_qty"]),
                "order_received_lkr": f(row.get("ordered_value", 0.0)),
            }
            for _, row in monthly_rows.iterrows()
        ],
        "part_analysis": [
            {
                "material": s(row["material"]),
                "sale_lines": i(row["sale_lines"]),
                "sale_qty": f(row["sale_qty"]),
                "sale_value_lkr": f(row["sale_value_lkr"]),
                "return_lines": i(row["return_lines"]),
                "return_qty": f(row["return_qty"]),
                "return_value_lkr": f(row["return_value_lkr"]),
                "net_qty": f(row["sale_qty"]) - f(row["return_qty"]),
                "net_value_lkr": f(row["sale_value_lkr"]) - f(row["return_value_lkr"]),
                "return_rate_pct": ratio(row["return_value_lkr"], row["sale_value_lkr"], scale=100),
            }
            for _, row in parts.sort_values("sale_value_lkr", ascending=False).head(500).iterrows()
        ],
        "dealer_perf": [
            {
                "dealer_name": s(row["dealer_name"]),
                "dealer_type": dealer_type,
                "province": s(row["province"]),
                "district": s(row["district"]),
                "ase": s(row["ase"]),
                "rm": s(row["rm"]),
                "sale_qty": f(row["sale_qty"]),
                "sale_value_lkr": f(row["sale_value_lkr"]),
                "return_qty": f(row["return_qty"]),
                "return_value_lkr": f(row["return_value_lkr"]),
                "return_rate_pct": ratio(row["return_value_lkr"], row["sale_value_lkr"], scale=100),
                "unique_skus": i(row.get("unique_skus")),
                "order_received_lkr": 0.0,
                "fulfillment_pct": 0.0,
            }
            for _, row in dealers.sort_values("sale_value_lkr", ascending=False).iterrows()
        ],
        "rm_perf": hier_rows(hierarchy("mart_ui_sales_by_rm", ["rm"]), "rm"),
        "ase_perf": hier_rows(hierarchy("mart_ui_sales_by_ase", ["ase", "rm"]), "ase"),
        "district_perf": hier_rows(
            hierarchy("mart_ui_sales_by_district", ["province", "district"]), "district"
        ),
        "province_perf": hier_rows(
            hierarchy("mart_ui_sales_by_province", ["province"]), "province"
        ),
        "mc_category_mix": [
            {
                "mc_category": s(row["material_category"]),
                "sale_lines": i(row["sale_lines"]),
                "sale_qty": f(row["sale_qty"]),
                "sale_value_lkr": f(row["sale_value_lkr"]),
                "return_value_lkr": f(row["return_value_lkr"]),
                "value_share_pct": ratio(row["sale_value_lkr"], category_total, scale=100),
                "return_rate_pct": ratio(row["return_value_lkr"], row["sale_value_lkr"], scale=100),
                "unique_skus": 0,
            }
            for _, row in category.sort_values("sale_value_lkr", ascending=False).iterrows()
        ],
        "mc_monthly_category": mc_monthly,
    }
