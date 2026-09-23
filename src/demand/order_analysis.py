"""Step 05 — fulfilment, supply reliability and lead time.

These three feed the safety-stock maths in Step 13 directly. In particular the lead-time
**standard deviation** matters: a point estimate cannot size a buffer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.io.parquet import read_table, write_table

#: Below this many order lines a part's own fill rate is noise, so it is shrunk toward
#: its category mean rather than taken at face value.
SHRINKAGE_PRIOR_LINES = 10


def classify_fulfilment(ordered: pd.Series, confirmed: pd.Series) -> pd.Series:
    """Three mutually exclusive classes that partition the line set exactly."""
    return np.select(
        [confirmed >= ordered, confirmed <= 0],
        ["fully confirmed", "fully rejected"],
        default="partially confirmed",
    )


def shrink(confirmed: pd.Series, ordered: pd.Series, lines: pd.Series, prior: float) -> pd.Series:
    """James-Stein style shrinkage toward the category mean.

    Business meaning: one fully-rejected line would otherwise give a part beta_hat = 0
    and make Step 13 size its buffer off a single observation.
    """
    raw = confirmed / ordered.replace(0, np.nan)
    weight = lines / (lines + SHRINKAGE_PRIOR_LINES)
    return (weight * raw.fillna(prior) + (1 - weight) * prior).clip(0, 1)


@REGISTRY.register(
    "05_order_analysis",
    depends_on=["03_orders"],
    description="fulfilment classes, supply reliability and lead time",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="05_order_analysis")
    orders = read_table("facts", "orders_clean")
    result.rows_in = len(orders)

    ordered = orders["ordered_quantity"]
    confirmed = orders["confirmed_quantity"]
    orders = orders.assign(fulfilment_class=classify_fulfilment(ordered, confirmed))

    # ── Part A — fulfilment ─────────────────────────────────────────────────────
    by_class = (
        orders.groupby("fulfilment_class", as_index=False)
        .agg(
            lines=("fulfilment_class", "count"),
            ordered_quantity=("ordered_quantity", "sum"),
            confirmed_quantity=("confirmed_quantity", "sum"),
            lost_quantity=("lost_quantity", "sum"),
        )
        .sort_values("lines", ascending=False)
    )
    total_lines = int(by_class["lines"].sum())
    if total_lines != len(orders):
        result.warn(
            f"fulfilment classes do not partition the line set: {total_lines} vs {len(orders)}"
        )
    fill_rate = float(confirmed.sum() / ordered.sum()) if ordered.sum() else 0.0
    result.artifact("fulfilment_stats", write_table(by_class, "facts", "fulfilment_stats"))

    # Roll the same classification up to the purchase order.
    po = orders.groupby("Sales Document", as_index=False).agg(
        lines=("Sales Document", "count"),
        ordered_quantity=("ordered_quantity", "sum"),
        confirmed_quantity=("confirmed_quantity", "sum"),
        fully_confirmed_lines=(
            "fulfilment_class",
            lambda s: int((s == "fully confirmed").sum()),
        ),
    )
    po["po_class"] = np.select(
        [po["fully_confirmed_lines"] == po["lines"], po["confirmed_quantity"] <= 0],
        ["fully confirmed", "fully rejected"],
        default="partially confirmed",
    )
    result.artifact("fulfilment_by_po", write_table(po, "facts", "fulfilment_by_po"))
    result.warn(
        f"fill rate {fill_rate:.3f} over {len(orders):,} lines / {len(po):,} purchase orders; "
        + ", ".join(f"{r.fulfilment_class} {r.lines:,}" for r in by_class.itertuples())
    )

    # ── Part B — supply reliability ─────────────────────────────────────────────
    category_prior = (
        orders.groupby("material_category")
        .apply(
            lambda g: (
                g["confirmed_quantity"].sum() / g["ordered_quantity"].sum()
                if g["ordered_quantity"].sum()
                else fill_rate
            ),
            include_groups=False,
        )
        .to_dict()
    )
    per_part = orders.groupby(["active_sku_id", "material_category"], as_index=False).agg(
        ordered_quantity=("ordered_quantity", "sum"),
        confirmed_quantity=("confirmed_quantity", "sum"),
        lines=("ordered_quantity", "count"),
    )
    prior = per_part["material_category"].map(category_prior).fillna(fill_rate)
    per_part["beta_hat_raw"] = (
        per_part["confirmed_quantity"] / per_part["ordered_quantity"].replace(0, np.nan)
    ).clip(0, 1)
    per_part["beta_hat"] = shrink(
        per_part["confirmed_quantity"], per_part["ordered_quantity"], per_part["lines"], prior
    )
    per_part["shrunk"] = per_part["lines"] < SHRINKAGE_PRIOR_LINES
    result.artifact("supply_reliability", write_table(per_part, "facts", "supply_reliability"))

    zeros = per_part[per_part["beta_hat_raw"].fillna(1) <= 0]
    result.warn(
        f"beta_hat: {len(per_part):,} parts; {len(zeros):,} with raw beta_hat = 0 "
        f"(median {int(zeros['lines'].median()) if len(zeros) else 0} lines each, shrunk toward "
        f"category mean); global {fill_rate:.3f}"
    )

    monthly = orders.groupby(["month", "material_category"], as_index=False).agg(
        ordered_quantity=("ordered_quantity", "sum"),
        confirmed_quantity=("confirmed_quantity", "sum"),
    )
    monthly["beta_hat"] = monthly["confirmed_quantity"] / monthly["ordered_quantity"].replace(
        0, np.nan
    )
    result.artifact(
        "supply_reliability_monthly", write_table(monthly, "facts", "supply_reliability_monthly")
    )

    # ── Part C — lead time ──────────────────────────────────────────────────────
    lead_stats = _lead_time(orders, ctx, result)
    result.artifact("lead_time_stats", write_table(lead_stats, "facts", "lead_time_stats"))

    # ── Part D — returns ────────────────────────────────────────────────────────
    returns = read_table("facts", "returns_history")
    returns_summary = pd.DataFrame(
        [
            {
                "return_lines": len(returns),
                "return_invoices": returns["Sales Document"].nunique() if len(returns) else 0,
                "return_quantity": float(returns["ordered_quantity"].sum()) if len(returns) else 0,
                "return_value": float(returns["order_value"].sum()) if len(returns) else 0,
                "unique_skus_returned": returns["active_sku_id"].nunique() if len(returns) else 0,
                "return_rate_lines": (len(returns) / len(orders)) if len(orders) else 0,
            }
        ]
    )
    result.artifact("returns_summary", write_table(returns_summary, "facts", "returns_summary"))

    # ── Part E — performance cuts ───────────────────────────────────────────────
    for column, name in (
        ("active_sku_id", "orders_by_material"),
        ("Sold-To Party Name", "orders_by_dealer"),
        ("RM", "orders_by_rm"),
        ("ASE", "orders_by_ase"),
        ("Province", "orders_by_province"),
        ("District", "orders_by_district"),
    ):
        if column not in orders.columns:
            continue
        agg = (
            orders.groupby(column, as_index=False)
            .agg(
                order_lines=("ordered_quantity", "count"),
                ordered_quantity=("ordered_quantity", "sum"),
                confirmed_quantity=("confirmed_quantity", "sum"),
                lost_quantity=("lost_quantity", "sum"),
                order_value=("order_value", "sum"),
            )
            .sort_values("order_value", ascending=False)
        )
        agg["fill_rate"] = agg["confirmed_quantity"] / agg["ordered_quantity"].replace(0, np.nan)
        result.artifact(name, write_table(agg, "facts", name))

    result.rows_out = len(per_part)
    logger.info(f"order analysis: fill {fill_rate:.3f}, {len(per_part):,} parts scored")
    return result


def _lead_time(orders: pd.DataFrame, ctx: PlanningContext, result: StageResult) -> pd.DataFrame:
    """Lead time per part and category, or the planning assumption if unusable."""
    document = pd.to_datetime(orders.get("Document Date"), errors="coerce")
    delivery = pd.to_datetime(orders.get("Delivery Date"), errors="coerce")
    days = (delivery - document).dt.days
    usable = days.notna() & (days >= 0) & (days < 365)
    share = float(usable.mean()) if len(orders) else 0.0

    if share < 0.5 or days[usable].std() == 0:
        assumed = ctx.lead_time_months * 30
        result.warn(
            f"LEAD TIME FALLBACK: only {share:.1%} of lines have a usable "
            f"Delivery − Document interval, so the {ctx.lead_time_months}-month planning "
            f"assumption ({assumed} days) is used and sigma_L is unknown. A wrong sigma_L "
            f"mis-sizes every buffer."
        )
        return pd.DataFrame(
            [
                {
                    "scope": "ALL",
                    "source": "planning assumption",
                    "mean_days": float(assumed),
                    "std_days": np.nan,
                    "p50_days": float(assumed),
                    "p90_days": float(assumed),
                    "lines": int(len(orders)),
                    "usable_share": share,
                }
            ]
        )

    frame = orders.loc[usable].assign(lead_days=days[usable])
    measured_mean = float(frame["lead_days"].mean())
    planning_days = ctx.lead_time_months * 30

    # Delivery Date − Document Date measures dispatch to the dealer, not replenishment
    # from India. If it is far below the planning assumption it is the wrong clock, and
    # sizing a buffer with it would understate every safety stock in the portfolio.
    if measured_mean < planning_days / 3:
        result.warn(
            f"LEAD TIME IS THE WRONG CLOCK: Delivery − Document averages {measured_mean:.1f} days "
            f"against a {ctx.lead_time_months}-month ({planning_days}-day) import lead. This "
            f"measures dealer dispatch from the PDC, not replenishment from India. Step 13 uses "
            f"the planning assumption; the measured distribution is published as dispatch "
            f"performance only, and sigma_L for replenishment remains UNKNOWN."
        )
        dispatch = pd.DataFrame(
            [
                {
                    "scope": "ALL",
                    "source": "dispatch to dealer (not replenishment)",
                    "mean_days": measured_mean,
                    "std_days": float(frame["lead_days"].std()),
                    "p50_days": float(frame["lead_days"].quantile(0.5)),
                    "p90_days": float(frame["lead_days"].quantile(0.9)),
                    "lines": int(len(frame)),
                    "usable_share": share,
                },
                {
                    "scope": "REPLENISHMENT",
                    "source": "planning assumption",
                    "mean_days": float(planning_days),
                    "std_days": np.nan,
                    "p50_days": float(planning_days),
                    "p90_days": float(planning_days),
                    "lines": int(len(orders)),
                    "usable_share": 0.0,
                },
            ]
        )
        return dispatch

    result.warn(
        f"lead time measured on {share:.1%} of lines: mean "
        f"{measured_mean:.1f}d, sigma {frame['lead_days'].std():.1f}d"
    )
    rows = [
        {
            "scope": "REPLENISHMENT",
            "source": "measured",
            "mean_days": float(frame["lead_days"].mean()),
            "std_days": float(frame["lead_days"].std()),
            "p50_days": float(frame["lead_days"].quantile(0.5)),
            "p90_days": float(frame["lead_days"].quantile(0.9)),
            "lines": int(len(frame)),
            "usable_share": share,
        }
    ]
    for category, group in frame.groupby("material_category"):
        rows.append(
            {
                "scope": str(category),
                "source": "measured",
                "mean_days": float(group["lead_days"].mean()),
                "std_days": float(group["lead_days"].std()),
                "p50_days": float(group["lead_days"].quantile(0.5)),
                "p90_days": float(group["lead_days"].quantile(0.9)),
                "lines": int(len(group)),
                "usable_share": share,
            }
        )
    return pd.DataFrame(rows)
