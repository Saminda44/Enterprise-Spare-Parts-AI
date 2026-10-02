"""The next order, one row per line, with every input that produced it.

Joins the Step 14 proposal with the inputs behind it — the fleet (UIO) share of the
forecast, the part's classes, the forecast itself and the stock position — so the Order
Plan page can show each line's arithmetic without computing anything in a request.

One table (owner, 2026-10-02): lines **to order**, lines **held for review** (each with a
release / trim / drop recommendation), and parts to **expedite** (stock runs out before
their incoming stock lands); every line to order also carries an audit against the real
order history, so a buyer sees which lines need a second look and why.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

STATUS_ORDER = "to order"
STATUS_REVIEW = "held for review"
STATUS_EXPEDITE = "expedite"

#: Audit thresholds for a line to order (a buyer looks again when one is crossed).
CHECK_ORDER_MONTHS = 6.0  # the order covers more than this many months of recent demand
CHECK_FORECAST_RATIO = (0.5, 2.0)  # forecast outside this multiple of recent demand
CHECK_STOCK_MONTHS = 3.0  # stock already covers this many months, yet an order is proposed
CHECK_SPARSE_MONTHS = 2  # ordered in this few months or fewer since the history began
#: A held line is released when it is within this margin of what recent demand needs.
RELEASE_MARGIN = 1.25
#: A part with no recent orders is kept for a buyer when its fleet implies this much a month.
FLEET_SUPPORTED_MONTHLY = 1.0

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
    "stock_checked",
    "landing_month",
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
    "incoming_by_month",
    "incoming_in_window",
    "run_out_month",
    "below_buffer_month",
    "expedite",
    "stock_at_order_arrival",
    "monthly_rol",
    "reorder_due_month",
    "recent_monthly_demand",
    "last_order_month",
    "needs_check",
    "check_reasons",
    "recommendation",
    "suggested_qty",
    "suggested_value",
    "recommendation_reason",
]

#: Published by ``incoming_watch``: every part whose shelf empties before its stock lands.
WATCH_COLUMNS = [
    "active_sku_id",
    "description",
    "segment",
    "part_category",
    "abc",
    "forecast_month",
    "safety_stock",
    "on_hand",
    "on_order",
    "incoming_by_month",
    "incoming_in_window",
    "run_out_month",
    "next_arrival_month",
    "next_arrival_qty",
    "short_units",
    "in_order_plan",
]


def _months(cycle_month: str, through: str) -> list[pd.Period]:
    """Calendar months from the cycle month to the month the new order lands, inclusive."""
    start, end = pd.Period(cycle_month, freq="M"), pd.Period(through, freq="M")
    return list(pd.period_range(start, max(start, end), freq="M"))


def project_incoming(
    parts: pd.DataFrame, schedule: pd.DataFrame | None, cycle_month: str, through: str
) -> pd.DataFrame:
    """Month by month: on hand + that month's arrivals − forecast, never below zero.

    Business meaning: the order quantity nets every incoming unit at once (inventory
    position), but a shelf can be empty for months before a dated arrival lands. This
    shows, per part, what arrives each month until the new order lands and the first month
    projected stock cannot meet forecast demand — when stock runs out while an arrival is
    still to come, the buyer can expedite it. Informational only: it does not change buffer
    stock, the reorder level or the order quantity (owner, 2026-10-02).

    Args:
        parts: ``active_sku_id``, ``on_hand``, ``forecast_month``, ``safety_stock``.
        schedule: dated receipts (``active_sku_id``, ``arrival``, ``qty``), or None.
        cycle_month: the planning month, ``YYYY-MM``.
        through: the month a new order would land, ``YYYY-MM``.

    Returns:
        One row per part: arrivals per month (JSON), units arriving in the window, the
        run-out and below-buffer months, whether an arrival comes after the run-out
        (expedite), projected stock when the new order lands, and the next arrival after
        the run-out with the units short until then.
    """
    months = _months(cycle_month, through)
    ids = parts["active_sku_id"].astype(str)
    arrivals = pd.DataFrame(0.0, index=pd.Index(ids.unique()), columns=months)
    if schedule is not None and not schedule.empty:
        sched = schedule.assign(
            active_sku_id=schedule["active_sku_id"].astype(str),
            month=pd.to_datetime(schedule["arrival"]).dt.to_period("M"),
        )
        sched = sched[sched["month"].isin(months) & sched["active_sku_id"].isin(arrivals.index)]
        pivot = sched.pivot_table(
            index="active_sku_id", columns="month", values="qty", aggfunc="sum", fill_value=0.0
        )
        arrivals.loc[pivot.index, pivot.columns] = pivot.to_numpy()

    rows = []
    for row in parts.assign(active_sku_id=ids).itertuples(index=False):
        sku = row.active_sku_id
        demand = max(float(row.forecast_month or 0.0), 0.0)
        buffer = max(float(row.safety_stock or 0.0), 0.0)
        stock = max(float(row.on_hand or 0.0), 0.0)
        incoming = arrivals.loc[sku] if sku in arrivals.index else pd.Series(0.0, index=months)
        rol_now = getattr(row, "reorder_level", None)
        rol_now = float(rol_now) if rol_now is not None and pd.notna(rol_now) else None
        monthly: list[dict[str, object]] = []
        reorder_due = None
        run_out = below = None
        short = 0.0
        relieved = False  # an arrival has landed after the run-out
        for month in months:
            if rol_now is not None:
                # This month's reorder level is one month of this month's demand + buffer
                # (owner, 2026-10-02). The forecast is one monthly rate, so every month's
                # level equals the current month's; a month-by-month forecast would move it.
                month_demand = demand
                rol_month = rol_now + (month_demand - demand)
                # Stock this month: what is on the shelf plus this month's arrivals.
                position = stock + float(incoming[month])
                at_or_below = position <= rol_month
                if at_or_below and reorder_due is None:
                    reorder_due = month
                monthly.append(
                    {
                        "month": str(month),
                        "stock_start": round(stock, 2),
                        "incoming": round(float(incoming[month]), 2),
                        "position": round(position, 2),
                        "rol": round(rol_month, 2),
                        "at_or_below": bool(at_or_below),
                    }
                )
            available = stock + float(incoming[month])
            if available < demand and run_out is None and demand > 0:
                run_out = month
            if run_out is not None and not relieved:
                if month > run_out and float(incoming[month]) > 0:
                    relieved = True
                else:
                    # Demand that cannot be met until the next arrival lands.
                    short += max(demand - available, 0.0)
            stock = max(available - demand, 0.0)
            if below is None and demand > 0 and stock < buffer:
                below = month
        later = [m for m in months if run_out is not None and m > run_out and incoming[m] > 0]
        rows.append(
            {
                "active_sku_id": sku,
                "incoming_by_month": json.dumps(
                    [
                        {"month": str(m), "qty": round(float(incoming[m]), 2)}
                        for m in months
                        if incoming[m] > 0
                    ]
                ),
                "incoming_in_window": float(incoming.sum()),
                "run_out_month": str(run_out) if run_out is not None else None,
                "below_buffer_month": str(below) if below is not None else None,
                "expedite": bool(later),
                "stock_at_order_arrival": stock,
                "next_arrival_month": str(later[0]) if later else None,
                "next_arrival_qty": float(incoming[later[0]]) if later else 0.0,
                "short_units": round(short, 2) if later else 0.0,
                "monthly_rol": json.dumps(monthly),
                "reorder_due_month": str(reorder_due) if reorder_due is not None else None,
            }
        )
    return pd.DataFrame(rows)


def incoming_watch(
    sku: pd.DataFrame,
    schedule: pd.DataFrame | None,
    plan: pd.DataFrame,
) -> pd.DataFrame:
    """Every forecast part whose stock runs out before incoming stock lands.

    Business meaning: the order plan lists only parts being ordered; a part with a large
    arrival on the way is usually not ordered, yet its shelf can be empty until then.
    """
    has_stock = "stock_on_hand" in sku or "on_hand" in sku
    if plan.empty or sku.empty or not has_stock or "forecast_m1" not in sku:
        return pd.DataFrame(columns=WATCH_COLUMNS)
    cycle, through = str(plan["cycle_month"].iloc[0]), str(plan["expected_arrival"].iloc[0])
    # The per-SKU mart publishes on-hand stock as ``stock_on_hand``.
    on_hand = sku["stock_on_hand"] if "stock_on_hand" in sku else sku["on_hand"]
    parts = pd.DataFrame(
        {
            "active_sku_id": sku["active_sku_id"].astype(str),
            "on_hand": pd.to_numeric(on_hand, errors="coerce").fillna(0.0),
            "forecast_month": pd.to_numeric(sku["forecast_m1"], errors="coerce").fillna(0.0),
            "safety_stock": pd.to_numeric(sku.get("safety_stock"), errors="coerce").fillna(0.0),
        }
    )
    parts = parts[parts["forecast_month"] > 0]
    projected = project_incoming(parts, schedule, cycle, through)
    flagged = projected[projected["expedite"]]
    out = flagged.merge(
        sku.assign(active_sku_id=sku["active_sku_id"].astype(str)).drop(
            columns=["on_hand"], errors="ignore"
        ),
        on="active_sku_id",
    )
    out = out.assign(
        on_hand=out["active_sku_id"].map(parts.set_index("active_sku_id")["on_hand"]),
        abc=out["abc"] if "abc" in out else out.get("abc_class"),
        forecast_month=pd.to_numeric(out["forecast_m1"], errors="coerce"),
        in_order_plan=out["active_sku_id"].isin(set(plan["active_sku_id"].astype(str))),
    )
    return (
        out.reindex(columns=WATCH_COLUMNS)
        .sort_values(["run_out_month", "short_units"], ascending=[True, False])
        .reset_index(drop=True)
    )


def recent_demand(history: pd.DataFrame) -> pd.DataFrame:
    """Each part's real order rate: 6- and 12-month averages, active months, last order.

    Business meaning: the yardstick a buyer judges a line by — what dealers actually
    ordered (sales orders, ordered quantity, all chain numbers combined).
    """
    if history.empty:
        return pd.DataFrame(
            columns=["active_sku_id", "avg6", "avg12", "active_months", "last_order_month"]
        )
    frame = history.assign(month=pd.to_datetime(history["month"].astype(str)).dt.to_period("M"))
    last = frame["month"].max()
    qty = "ordered_quantity"
    six = frame[frame["month"] > last - 6].groupby("active_sku_id")[qty].sum() / 6
    twelve = frame[frame["month"] > last - 12].groupby("active_sku_id")[qty].sum() / 12
    ordered = frame[frame[qty] > 0]
    out = pd.DataFrame(
        {
            "avg6": six,
            "avg12": twelve,
            "active_months": ordered.groupby("active_sku_id")["month"].nunique(),
            "last_order_month": ordered.groupby("active_sku_id")["month"].max().astype(str),
        }
    )
    out[["avg6", "avg12", "active_months"]] = out[["avg6", "avg12", "active_months"]].fillna(0)
    return out.rename_axis("active_sku_id").reset_index()


def audit_line(row: pd.Series) -> list[str]:
    """Reasons a line to order needs a second look (empty when it is in line)."""
    reasons: list[str] = []
    rate, qty = float(row["recent_monthly_demand"]), float(row["q_final"] or 0)
    if rate <= 0:
        reasons.append("no orders in the last 12 months")
    else:
        if qty / rate > CHECK_ORDER_MONTHS:
            reasons.append(f"order = {qty / rate:.1f} months of recent demand")
        forecast = float(row["forecast_month"] or 0)
        low, high = CHECK_FORECAST_RATIO
        if forecast > 0 and not low <= forecast / rate <= high:
            reasons.append(f"forecast {forecast:,.0f}/mo vs recent orders {rate:,.0f}/mo")
        if float(row["stock_checked"] or 0) >= CHECK_STOCK_MONTHS * rate:
            months = float(row["stock_checked"]) / rate
            reasons.append(f"on hand + on order already = {months:.1f} months")
    if int(row.get("active_months") or 0) <= CHECK_SPARSE_MONTHS:
        reasons.append(f"ordered in only {int(row.get('active_months') or 0)} month(s) on record")
    return reasons


def recommend_held(row: pd.Series, cap_months: float) -> tuple[str, float, str]:
    """Release, trim, drop or review a held line, judged on what the part really sells.

    Business meaning: a held line is sized against one month of recent demand plus a
    buffer of at most ``cap_months`` of it, less on hand and on order. Within
    ``RELEASE_MARGIN`` of that it is released as proposed; above it, trimmed to it; with
    nothing needed, dropped. A part with no recent orders is dropped unless its fleet
    implies demand, which a buyer then decides on.
    """
    held, rate = float(row["q_review"] or 0), float(row["recent_monthly_demand"])
    if rate <= 0:
        fleet = row.get("fleet_forecast")
        if fleet is not None and pd.notna(fleet) and float(fleet) >= FLEET_SUPPORTED_MONTHLY:
            return (
                "review",
                0.0,
                (
                    f"no orders in 12 months; the fleet suggests {float(fleet):,.1f}/mo "
                    "— buyer decides"
                ),
            )
        return "drop", 0.0, "no orders in the last 12 months"
    need = float(np.ceil(max(rate * (1 + cap_months) - float(row["stock_checked"] or 0), 0.0)))
    if need <= 0:
        return (
            "drop",
            0.0,
            (
                f"on hand + on order {float(row['stock_checked']):,.0f} already covers "
                f"{1 + cap_months:g} months of recent demand ({rate:,.0f}/mo)"
            ),
        )
    if held <= need * RELEASE_MARGIN:
        return "release", held, f"in line with recent demand ({rate:,.0f}/mo)"
    return (
        "trim",
        need,
        (
            f"trim {held:,.0f} to {need:,.0f}: {1 + cap_months:g} months of recent demand "
            f"({rate:,.0f}/mo) less on hand + on order"
        ),
    )


def build(
    proposal: pd.DataFrame,
    sku: pd.DataFrame,
    behaviour: pd.DataFrame | None,
    schedule: pd.DataFrame | None = None,
    demand: pd.DataFrame | None = None,
    cap_months: float = 3.0,
) -> pd.DataFrame:
    """Every line — to order, held for review, or to expedite — with its inputs.

    Business meaning: the reorder level is one month of demand plus buffer stock, checked
    against on hand + all on order; a line is ordered up to it (raised to the capped
    economic quantity). A line above 3x recent demand is held for a buyer, with a
    recommendation. Parts whose stock runs out before incoming stock lands are listed to
    expedite even when nothing is ordered.
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
            # Landing-month rule (owner, 2026-10-02): the order fills the landing month up
            # to this; the reorder level is one month of demand + buffer.
            "target_level": lines.get("target_at_landing", lines["S"]),
            "reorder_level": lines["rol"] if "rol" in lines else lines["s"],
            "stock_checked": lines.get("stock_checked", lines["ip"]),
            "landing_month": lines.get("landing_month"),
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
    projected_columns = [c for c in COLUMNS if c.startswith(("incoming", "run_out", "below"))]
    projected_columns += ["expedite", "stock_at_order_arrival", "monthly_rol", "reorder_due_month"]
    if out.empty:
        for column in projected_columns:
            out[column] = None
    else:
        projected = project_incoming(
            out[
                [
                    "active_sku_id",
                    "on_hand",
                    "on_order",
                    "forecast_month",
                    "safety_stock",
                    "reorder_level",
                ]
            ],
            schedule,
            str(out["cycle_month"].iloc[0]),
            str(out["expected_arrival"].iloc[0]),
        )
        out = out.merge(
            projected[["active_sku_id", *projected_columns]], on="active_sku_id", how="left"
        )
    out = _with_review(out, demand, cap_months)
    out = _with_expedite_only(out, sku, schedule)
    return out.sort_values("proposed_value", ascending=False).reset_index(drop=True)[
        [*COLUMNS, "proposed_value"]
    ]


def _with_review(out: pd.DataFrame, demand: pd.DataFrame | None, cap_months: float) -> pd.DataFrame:
    """Audit every line to order; recommend release / trim / drop for every held line."""
    rates = demand if demand is not None else recent_demand(pd.DataFrame())
    out = out.merge(rates, on="active_sku_id", how="left")
    out[["avg6", "avg12", "active_months"]] = out[["avg6", "avg12", "active_months"]].fillna(0)
    out["recent_monthly_demand"] = out[["avg6", "avg12"]].max(axis=1)
    reasons = out.apply(lambda r: audit_line(r) if r["status"] == STATUS_ORDER else [], axis=1)
    out["needs_check"] = reasons.map(bool)
    out["check_reasons"] = reasons.map(lambda items: "; ".join(items))
    held = out["status"] == STATUS_REVIEW
    advice = out[held].apply(lambda r: recommend_held(r, cap_months), axis=1)
    out["recommendation"] = None
    out["suggested_qty"] = np.nan
    out["recommendation_reason"] = None
    if held.any():
        out.loc[held, "recommendation"] = [a[0] for a in advice]
        out.loc[held, "suggested_qty"] = [a[1] for a in advice]
        out.loc[held, "recommendation_reason"] = [a[2] for a in advice]
    out["suggested_value"] = out["suggested_qty"] * out["unit_cost"]
    return out


def _with_expedite_only(
    out: pd.DataFrame, sku: pd.DataFrame, schedule: pd.DataFrame | None
) -> pd.DataFrame:
    """Add parts not being ordered whose stock runs out before their incoming stock lands."""
    if out.empty:
        return out
    watch = incoming_watch(sku, schedule, out)
    watch = watch[~watch["active_sku_id"].isin(set(out["active_sku_id"].astype(str)))]
    if watch.empty:
        return out
    extra = watch.assign(
        status=STATUS_EXPEDITE,
        expedite=True,
        q_proposed=0.0,
        q_final=0.0,
        q_review=0.0,
        value=0.0,
        value_review=0.0,
        proposed_value=0.0,
        stock_checked=watch["on_hand"].fillna(0) + watch["on_order"].fillna(0),
        cycle_month=out["cycle_month"].iloc[0],
        expected_arrival=out["expected_arrival"].iloc[0],
        trigger_reason="not ordered: on hand + on order is above the reorder level, but the "
        "shelf empties before the incoming stock lands",
    )
    sku_cols = sku.assign(active_sku_id=sku["active_sku_id"].astype(str))
    for column in ("reorder_level", "rol"):
        if column in sku_cols:
            extra["reorder_level"] = extra["active_sku_id"].map(
                sku_cols.set_index("active_sku_id")[column]
            )
            break
    combined = pd.concat([out, extra.reindex(columns=out.columns)], ignore_index=True)
    for column in ("needs_check", "expedite"):
        combined[column] = combined[column].fillna(False).astype(bool)
    combined["check_reasons"] = combined["check_reasons"].fillna("")
    return combined
