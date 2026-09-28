"""The wide per-SKU table the dashboard's parts pages are all built on.

One row per ``active_sku_id``, carrying classification, forecast, stock, policy and the
proposed order side by side. The legacy UI reads this under its old column names
(``material_9``, ``policy_tier``, ``stock_status`` …) so the mapping lives here, once,
rather than being re-derived in five request handlers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.context import PlanningContext
from src.core.result import StageResult
from src.io.parquet import read_table, table_exists

#: A month, in days. Used only to express coverage in the "days of stock" the UI shows.
DAYS_PER_MONTH = 30.4

#: Coverage above this is excess. Twelve months of cover on a three-month lead is four
#: replenishment cycles of stock sitting still — money that is not buying service.
EXCESS_COVER_MONTHS = 12.0

#: Below one month of cover a part cannot survive even the review period, let alone the
#: lead time, so it is critical rather than merely low.
CRITICAL_COVER_MONTHS = 1.0

#: Coverage is capped for display: a part with demand rounding to zero would otherwise
#: report infinite cover and blow up every average on the page.
COVER_CAP_MONTHS = 999.0

#: CLAUDE.md's stop-and-ask rule: a reorder level or quantity more than this multiple of
#: recent realised demand is flagged, not silently shipped to a buyer.
SANITY_MULTIPLE = 3.0


def classify_stock(coverage: float, on_hand: float, demand: float) -> str:
    """Bucket a SKU's stock position.

    Business meaning: what a planner should do about this part today. STOCKOUT means the
    shelf is empty against live demand; EXCESS means capital is tied up in cover nobody
    has asked for.
    """
    if demand <= 0:
        return "NO_DEMAND" if on_hand > 0 else "DORMANT"
    if on_hand <= 0:
        return "STOCKOUT"
    if coverage < CRITICAL_COVER_MONTHS:
        return "CRITICAL"
    if coverage > EXCESS_COVER_MONTHS:
        return "EXCESS"
    return "HEALTHY"


def classify_urgency(ip: float, reorder_point: float, order_qty: float) -> str:
    """How soon the proposed order has to be placed.

    Business meaning: IMMEDIATE is already stocked out against a live reorder level;
    SOON is at or below it; PLANNED is the ordinary review-cycle top-up.
    """
    if order_qty <= 0:
        return "NONE"
    if ip <= 0:
        return "IMMEDIATE"
    if ip <= reorder_point:
        return "SOON"
    return "PLANNED"


def _sanity(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Flag reorder levels and quantities that observed demand cannot justify.

    Business meaning: CLAUDE.md's stop-and-ask rule. The yardstick is demand over the
    protection interval at its 95th percentile, not the mean — an intermittent part's
    reorder level is *supposed* to sit well above its average month, so measuring against
    the mean flags four SKUs in five and tells a buyer nothing.
    """
    upper = frame[["p95", "mu_p"]].max(axis=1).fillna(0.0)
    ceiling = SANITY_MULTIPLE * upper
    rol_hot = (ceiling > 0) & (frame["rol"] > ceiling)
    roq_hot = (ceiling > 0) & (frame["roq"] > ceiling)
    no_demand = (frame["avg_monthly_demand"].fillna(0.0) <= 0) & (frame["roq"] > 0)

    multiple = f"{SANITY_MULTIPLE:.0f}x"
    note = pd.Series("", index=frame.index, dtype=object)
    note[rol_hot] = f"ROL above {multiple} p95 demand over the protection interval"
    note[roq_hot] = f"ROQ above {multiple} p95 demand over the protection interval"
    note[rol_hot & roq_hot] = f"ROL and ROQ both above {multiple} p95 demand over P"
    note[no_demand] = "order proposed for a part with no observed demand"
    return (rol_hot | roq_hot | no_demand), note


def build(ctx: PlanningContext, result: StageResult) -> pd.DataFrame:
    """Assemble the wide per-SKU dashboard table."""
    classification = read_table("facts", "sku_classification")
    # The live forecast (all history) is what the order runs on; the validation forecast
    # exists only for the Step 13 holdout and is not what a planner should see.
    forecast = read_table(
        "facts",
        "forecast_live" if table_exists("facts", "forecast_live") else "forecast_protection",
    )
    params = read_table("facts", "policy_params")
    selection = read_table("facts", "policy_selection")
    stock = read_table("facts", "stock_position")
    proposal = read_table("facts", "monthly_order_proposal")
    demand = read_table("facts", "orders_by_material")
    master = read_table("facts", "part_master_enriched")

    frame = classification.rename(columns={"quadrant": "demand_category"})
    frame = frame.merge(
        forecast[
            [
                "active_sku_id",
                "model",
                "mu_month",
                "mu_month_baseline",
                "mu_month_parc",
                "mu_p",
                "sigma_p",
                "p50",
                "p90",
                "p95",
            ]
        ],
        on="active_sku_id",
        how="left",
    )
    frame = frame.merge(
        params[
            [
                "active_sku_id",
                "fill_target",
                "z",
                "safety_stock",
                "ss_strategy",
                "rol",
                "months_of_cover",
                "unit_value",
            ]
        ],
        on="active_sku_id",
        how="left",
    )
    frame = frame.merge(selection[["active_sku_id", "policy"]], on="active_sku_id", how="left")
    frame = frame.merge(
        stock[["active_sku_id", "on_hand", "on_order", "backorders", "ip", "storage_locations"]],
        on="active_sku_id",
        how="left",
    )
    frame = frame.merge(
        proposal[
            [
                "active_sku_id",
                "q_final",
                "q_raw",
                "unit_cost",
                "value",
                "cycle_month",
                "lead_time_months",
                "trigger_reason",
                *[
                    c
                    for c in ("q_proposed", "q_review", "value_review", "recent_demand_6m", "flags")
                    if c in proposal.columns
                ],
            ]
        ],
        on="active_sku_id",
        how="left",
    )
    frame = frame.merge(
        demand[
            ["active_sku_id", "ordered_quantity", "confirmed_quantity", "order_value", "fill_rate"]
        ],
        on="active_sku_id",
        how="left",
    )

    # One row per active SKU from the master, for compatible models and part kind.
    heads = master.sort_values("chain_depth").drop_duplicates("active_sku_id", keep="first")[
        ["active_sku_id", "compatible_models", "part_kind", "material_group", "brand"]
    ]
    frame = frame.merge(heads, on="active_sku_id", how="left")

    if table_exists("facts", "returns_history"):
        returns = read_table("facts", "returns_history")
        by_sku = (
            returns.groupby("active_sku_id", as_index=False)["ordered_quantity"]
            .sum()
            .rename(columns={"ordered_quantity": "total_return_qty"})
        )
        frame = frame.merge(by_sku, on="active_sku_id", how="left")
    else:
        frame["total_return_qty"] = 0.0

    numeric = [
        "on_hand",
        "on_order",
        "backorders",
        "ip",
        "q_final",
        "q_raw",
        "q_proposed",
        "q_review",
        "value_review",
        "recent_demand_6m",
        "unit_cost",
        "unit_value",
        "rol",
        "safety_stock",
        "z",
        "fill_target",
        "ordered_quantity",
        "confirmed_quantity",
        "order_value",
        "total_return_qty",
        "mean_monthly_demand",
    ]
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame["lead_time_months"] = pd.to_numeric(
        frame.get("lead_time_months"), errors="coerce"
    ).fillna(float(ctx.lead_time_months))

    # Legacy names. material_9 was the old nine-character key; the new identity is the
    # supersession-resolved active SKU, which is what every number here is keyed on.
    frame["material_9"] = frame["active_sku_id"]
    frame["policy_tier"] = frame["policy"].fillna("UNSET")
    frame["method"] = frame["model"].fillna("none")
    frame["ss_method"] = frame["ss_strategy"].fillna("none")
    frame["service_level"] = frame["fill_target"]
    frame["z_score"] = frame["z"]
    frame["roq"] = frame["q_final"]
    frame["net_requirement"] = frame["q_final"]
    frame["unit_value_lkr"] = np.where(
        frame["unit_cost"] > 0, frame["unit_cost"], frame["unit_value"]
    )
    frame["avg_monthly_demand"] = frame["mean_monthly_demand"]
    frame["cv"] = pd.to_numeric(frame["cv_monthly"], errors="coerce").fillna(0.0)
    frame["cv_hist"] = frame["cv"]
    frame["active_months"] = pd.to_numeric(frame["nonzero_months"], errors="coerce").fillna(0)
    frame["total_months"] = pd.to_numeric(frame["months_observed"], errors="coerce").fillna(0)
    frame["p_zero"] = np.where(
        frame["total_months"] > 0, 1.0 - frame["active_months"] / frame["total_months"], 1.0
    )
    frame["abc_xyz_fsn"] = (
        frame["abc"].fillna("?").astype(str)
        + frame["xyz"].fillna("?").astype(str)
        + frame["fsn"].fillna("?").astype(str)
    )
    frame["total_issue_qty"] = frame["confirmed_quantity"]
    frame["total_issue_value_lkr"] = pd.to_numeric(
        frame["annual_consumption_value"], errors="coerce"
    ).fillna(0.0)
    frame["last_issue_date"] = frame["last_demand_month"]
    frame["part_type"] = frame["part_kind"]
    # SSOP is out of scope in the new design (CLAUDE.md §6), so this is genuinely unknown
    # rather than false — the UI renders it as a tri-state.
    frame["in_ssop"] = None

    # The forecast is a mean rate over the protection interval, not a month-by-month
    # path, so m1..m3 are the same number. Saying so beats inventing a shape.
    frame["forecast_m1"] = frame["mu_month"].fillna(0.0)
    frame["forecast_m2"] = frame["forecast_m1"]
    frame["forecast_m3"] = frame["forecast_m1"]
    frame["forecast_lt"] = frame["forecast_m1"] * ctx.lead_time_months
    sigma_p = pd.to_numeric(frame["sigma_p"], errors="coerce").fillna(0.0)
    protection = max(float(ctx.protection_interval_months), 1.0)
    frame["demand_std_monthly"] = sigma_p / np.sqrt(protection)
    frame["demand_std_lt"] = frame["demand_std_monthly"] * np.sqrt(ctx.lead_time_months)
    frame["forecast_month"] = str(pd.Period(ctx.as_of, freq="M") + 1)

    frame["stock_on_hand"] = frame["on_hand"]
    frame["stock_value_lkr"] = frame["on_hand"] * frame["unit_value_lkr"]
    frame["coverage_months"] = np.where(
        frame["avg_monthly_demand"] > 0,
        np.minimum(
            frame["on_hand"] / frame["avg_monthly_demand"].replace(0, np.nan), COVER_CAP_MONTHS
        ),
        COVER_CAP_MONTHS,
    )
    frame["coverage_months"] = frame["coverage_months"].fillna(COVER_CAP_MONTHS)
    frame["days_of_stock"] = frame["coverage_months"] * DAYS_PER_MONTH

    frame["stock_status"] = [
        classify_stock(cov, hand, dem)
        for cov, hand, dem in zip(
            frame["coverage_months"], frame["on_hand"], frame["avg_monthly_demand"], strict=True
        )
    ]
    frame["order_urgency"] = [
        classify_urgency(ip, rol, qty)
        for ip, rol, qty in zip(frame["ip"], frame["rol"], frame["roq"], strict=True)
    ]

    flag, note = _sanity(frame)
    frame["sanity_flag"] = flag
    frame["sanity_note"] = note

    frame["description"] = frame["description"].fillna("").astype(str)
    frame["review_flags"] = (
        frame["flags"].fillna("").astype(str) if "flags" in frame.columns else ""
    )

    columns = [
        "material_9",
        "active_sku_id",
        "description",
        "abc",
        "xyz",
        "fsn",
        "abc_xyz_fsn",
        "policy_tier",
        "demand_category",
        "behaviour_class",
        "criticality",
        "part_type",
        "in_ssop",
        "compatible_models",
        "material_group",
        "brand",
        "method",
        "forecast_month",
        "mu_month_baseline",
        "mu_month_parc",
        "value",
        "cycle_month",
        "forecast_m1",
        "forecast_m2",
        "forecast_m3",
        "forecast_lt",
        "demand_std_monthly",
        "demand_std_lt",
        "p50",
        "p90",
        "p95",
        "avg_monthly_demand",
        "cv",
        "cv_hist",
        "p_zero",
        "active_months",
        "total_months",
        "total_issue_qty",
        "total_issue_value_lkr",
        "total_return_qty",
        "last_issue_date",
        "stock_on_hand",
        "stock_value_lkr",
        "on_order",
        "backorders",
        "ip",
        "storage_locations",
        "coverage_months",
        "days_of_stock",
        "stock_status",
        "service_level",
        "z_score",
        "safety_stock",
        "ss_method",
        "rol",
        "roq",
        "net_requirement",
        "order_urgency",
        "unit_value_lkr",
        "lead_time_months",
        "trigger_reason",
        "sanity_flag",
        "sanity_note",
        "fill_rate",
        "q_proposed",
        "q_review",
        "value_review",
        "recent_demand_6m",
        "review_flags",
    ]
    out = frame[[c for c in columns if c in frame.columns]].copy()

    result.warn(
        f"per-SKU dashboard table: {len(out):,} SKUs; "
        f"{int((out['stock_status'] == 'STOCKOUT').sum()):,} stockout, "
        f"{int((out['stock_status'] == 'EXCESS').sum()):,} excess, "
        f"{int(out['sanity_flag'].sum()):,} sanity-flagged"
    )
    return out


def build_part_master_analysis(
    sku: pd.DataFrame, sales_abc: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Publish every resolved Part Master SKU with any available planning and stock data.

    Business meaning: a part absent from demand classification is still in the master;
    its missing planning measures must not be mistaken for measured zero demand.
    """
    master = read_table("facts", "part_master_enriched")
    stock = read_table("facts", "stock_position")
    heads = master.sort_values("chain_depth").drop_duplicates("active_sku_id", keep="first")
    heads = heads[
        [
            "active_sku_id",
            "description",
            "material_type",
            "material_group",
            "brand",
            "compatible_models",
            "part_kind",
        ]
    ].copy()
    aliases = master.groupby("active_sku_id").size().rename("alias_count")
    heads = heads.join(aliases, on="active_sku_id")
    old_numbers = master[master["material"] != master["active_sku_id"]]
    old_numbers = (
        old_numbers.groupby("active_sku_id")["material"]
        .agg(lambda values: ", ".join(sorted(set(values.astype(str)))))
        .rename("superseded_numbers")
    )
    heads = heads.join(old_numbers, on="active_sku_id")
    heads["superseded_numbers"] = heads["superseded_numbers"].fillna("")
    planned = sku.drop(
        columns=[
            "material_9",
            "description",
            "material_group",
            "brand",
            "compatible_models",
            "part_type",
        ]
    ).copy()
    planned["has_planning"] = True
    out = heads.merge(planned, on="active_sku_id", how="left", validate="one_to_one")
    snapshot = stock[["active_sku_id", "on_hand"]].rename(columns={"on_hand": "snapshot_on_hand"})
    out = out.merge(snapshot, on="active_sku_id", how="left", validate="one_to_one")
    out["has_planning"] = out["has_planning"].eq(True)
    out["has_stock_snapshot"] = out["snapshot_on_hand"].notna()
    out["stock_on_hand"] = out["snapshot_on_hand"].combine_first(out["stock_on_hand"])
    out["part_type"] = out["part_kind"]
    out["material_9"] = out["active_sku_id"]
    out["stock_status"] = out["stock_status"].fillna("NOT_ASSESSED")
    if sales_abc is None:
        out["sales_abc"] = None
        out["sales_net_lkr"] = float("nan")
        out["billed_lines"] = float("nan")
    else:
        out = out.merge(sales_abc, on="active_sku_id", how="left", validate="one_to_one")
    out["sales_activity_12m"] = out["sales_abc"].notna().map({True: "ACTIVE", False: "INACTIVE"})
    return out.drop(columns=["snapshot_on_hand", "part_kind"])


def overview(sku: pd.DataFrame, result: StageResult) -> pd.DataFrame:
    """The single KPI row behind the dashboard's Overview cards."""
    master = read_table("facts", "part_master_enriched")
    triggered = sku["roq"] > 0
    excess = sku["stock_status"] == "EXCESS"
    gate = (
        read_table("marts", "mart_service_and_stock")
        if table_exists("marts", "mart_service_and_stock")
        else pd.DataFrame()
    )
    selected = gate[gate["arm"] == "selected"] if not gate.empty else pd.DataFrame()

    row = {
        "total_skus": int(master["active_sku_id"].nunique()),
        "active_skus": int(len(sku)),
        "stockout_skus": int((sku["stock_status"] == "STOCKOUT").sum()),
        "critical_skus": int((sku["stock_status"] == "CRITICAL").sum()),
        "excess_skus": int(excess.sum()),
        "immediate_orders": int((sku["order_urgency"] == "IMMEDIATE").sum()),
        "soon_orders": int((sku["order_urgency"] == "SOON").sum()),
        "planned_orders": int((sku["order_urgency"] == "PLANNED").sum()),
        "total_order_value_lkr": float(sku["value"].sum()),
        "total_stock_value_lkr": float(sku["stock_value_lkr"].sum()),
        "excess_stock_value_lkr": float(sku.loc[excess, "stock_value_lkr"].sum()),
        "avg_coverage_months": float(
            sku["coverage_months"].replace(COVER_CAP_MONTHS, np.nan).mean()
        ),
        "sanity_flag_count": int(sku["sanity_flag"].sum()),
        # No RL agent in this design (CLAUDE.md §7) — reported as zero, not hidden.
        "rl_avg_order_reduction_pct": 0.0,
        "m6_total_skus_to_order": int(triggered.sum()),
        "m6_critical_count": int((sku["order_urgency"] == "IMMEDIATE").sum()),
        "m6_high_count": int((sku["order_urgency"] == "SOON").sum()),
        "m6_stockout_risk_count": int((sku["ip"] <= sku["rol"]).sum()),
        "m6_overstock_count": int(excess.sum()),
        "m6_weighted_fill_rate_pct": (
            float(selected["fill_rate"].iloc[0]) * 100.0 if not selected.empty else 0.0
        ),
        "m3_total_stock_qty": float(sku["stock_on_hand"].sum()),
        "m3_total_pipeline_qty": float(sku["on_order"].sum()),
        "m3_total_net_position": float(sku["ip"].sum()),
    }
    result.warn(
        f"overview KPIs: {row['active_skus']:,} active SKUs, "
        f"order value {row['total_order_value_lkr']:,.0f} LKR, "
        f"stock value {row['total_stock_value_lkr']:,.0f} LKR"
    )
    return pd.DataFrame([row])
