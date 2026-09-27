"""Step 14 — the monthly purchase order and the published marts.

Objective, stated precisely because "maximise profit and service and minimise cost" is
three objectives that conflict::

    minimise   holding_cost + ordering_cost + lost_margin
    subject to achieved_fill_rate >= target(ABC class)
               q respects MOQ, pack size and any budget cap

Treating service as a *constraint* and cost as the *objective* is what makes the problem
well-posed. Every proposed line carries why it was proposed — a buyer who cannot see the
reason will not send the order, and they would be right not to.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.core.settings import get_settings
from src.inventory.policy import policy_quantity
from src.io.parquet import read_table, write_table


def economic_order_quantity(annual_demand: float, order_cost: float, holding_cost: float) -> float:
    """EOQ = sqrt(2DS/H).

    Used as a **floor** on a triggered order, never as the order itself: EOQ assumes
    constant deterministic demand, which no spare part has.
    """
    if annual_demand <= 0 or holding_cost <= 0 or order_cost <= 0:
        return 0.0
    return float(np.sqrt(2.0 * annual_demand * order_cost / holding_cost))


def order_quantity(
    *,
    policy: str,
    ip: float,
    order_up_to: float,
    reorder_point: float,
    eoq: float,
    moq: float,
    pack_size: float,
    beta_hat: float,
    use_eoq: bool,
    use_supply_inflation: bool,
    inflation_cap: float,
) -> dict[str, float]:
    """The order function, step by step, so every quantity can be explained."""
    q_raw = policy_quantity(policy, ip, order_up_to, reorder_point)
    q_econ = max(q_raw, eoq) if (q_raw > 0 and use_eoq) else q_raw
    q_moq = max(q_econ, moq) if q_econ > 0 else 0.0
    q_pack = math.ceil(q_moq / pack_size) * pack_size if (q_moq > 0 and pack_size > 0) else q_moq

    q_final = q_pack
    if use_supply_inflation and q_pack > 0 and beta_hat > 0:
        factor = min(1.0 / beta_hat, inflation_cap)
        q_final = (
            math.ceil((q_pack * factor) / pack_size) * pack_size
            if pack_size > 0
            else q_pack * factor
        )

    return {
        "q_raw": float(q_raw),
        "q_econ": float(q_econ),
        "q_moq": float(q_moq),
        "q_pack": float(q_pack),
        "q_final": float(q_final),
    }


def trigger_reason(policy: str, ip: float, reorder_point: float, q_raw: float) -> str:
    if q_raw <= 0:
        if policy == "NO_STOCK":
            return "no-stock policy: ordering stopped pending owner review"
        if policy == "ON_DEMAND":
            return "on-demand: no firm requirement this cycle"
        return f"IP {ip:,.0f} above reorder point {reorder_point:,.0f}"
    if policy == "RsS":
        return f"IP {ip:,.0f} at or below s {reorder_point:,.0f} — ordered up to S"
    if policy == "RS":
        return f"review cycle: ordered up to S from IP {ip:,.0f}"
    return "firm requirement"


#: CLAUDE.md stop-and-ask: an order or ROL above this multiple of recent realised demand
#: over the protection interval goes to a human before it goes to a supplier.
REVIEW_MULTIPLE = 3.0
#: Months of realised demand the review test looks back over.
REVIEW_LOOKBACK_MONTHS = 6


def review_hold(
    q_final: float, rol: float, recent_protection_demand: float
) -> tuple[float, float, str]:
    """Split a proposed quantity into (placeable, held for review) and say why.

    Business meaning: an order more than ``REVIEW_MULTIPLE``x what the part actually sold
    over the protection interval — including any order for a part that sold nothing — is
    not placed automatically; a buyer confirms it. An inflated ROL is flagged but the line
    is not held for that alone.
    """
    flags: list[str] = []
    held = 0.0
    limit = REVIEW_MULTIPLE * recent_protection_demand
    if q_final > 0 and q_final > limit:
        held, q_final = q_final, 0.0
        flags.append(
            f"REVIEW: no demand in the last {REVIEW_LOOKBACK_MONTHS} months"
            if recent_protection_demand <= 0
            else f"REVIEW: order > {REVIEW_MULTIPLE:g}x recent demand"
        )
    if rol > 0 and rol > limit:
        flags.append(f"ROL > {REVIEW_MULTIPLE:g}x recent demand")
    return q_final, held, "; ".join(flags)


@REGISTRY.register(
    "14_monthly_order",
    depends_on=["13_policy"],
    description="the buyer-ready monthly order proposal and published marts",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="14_monthly_order")
    settings = get_settings()

    params = read_table("facts", "policy_params")
    selection = read_table("facts", "policy_selection")
    stock = read_table("facts", "stock_position")
    master = read_table("facts", "part_master")
    classification = read_table("facts", "sku_classification")
    history = read_table("facts", "demand_history")
    result.rows_in = len(params)

    # Realised demand over the last REVIEW_LOOKBACK_MONTHS months, scaled to the
    # protection interval — the yardstick for the stop-and-ask review.
    recent_months = sorted(history["month"].dropna().astype(str).unique())[-REVIEW_LOOKBACK_MONTHS:]
    recent = (
        history[history["month"].astype(str).isin(recent_months)]
        .groupby("active_sku_id")["ordered_quantity"]
        .sum()
    )

    frame = (
        params.merge(selection[["active_sku_id", "policy"]], on="active_sku_id", how="left")
        .merge(
            stock[["active_sku_id", "on_hand", "on_order", "ip"]], on="active_sku_id", how="left"
        )
        .merge(
            master[["active_sku_id", "description"]].drop_duplicates("active_sku_id"),
            on="active_sku_id",
            how="left",
        )
        .merge(
            classification[["active_sku_id", "fsn", "criticality"]].drop_duplicates(
                "active_sku_id"
            ),
            on="active_sku_id",
            how="left",
        )
    )
    frame[["on_hand", "on_order", "ip"]] = frame[["on_hand", "on_order", "ip"]].fillna(0.0)
    frame["policy"] = frame["policy"].fillna("RS")

    result.warn(
        f"MOQ and pack size are absent from every source file — defaulting to "
        f"{settings.default_moq:g} and {settings.default_pack_size:g}. A silent pack default of 1 "
        f"on a part that ships in cartons of 24 produces orders that cannot be placed."
    )
    result.warn(
        f"supply inflation q/beta_hat is {'ON' if settings.use_supply_inflation else 'OFF'} "
        f"(cap {settings.supply_inflation_cap:g}x) — the simulator in Step 13 used the same "
        f"setting, so the policy executed is the policy that was validated"
    )
    result.warn(
        f"EOQ floor is {'ON' if settings.use_eoq else 'OFF'}; order cost "
        f"{settings.order_cost:,.0f} {settings.currency}, holding rate "
        f"{settings.annual_holding_rate:.0%}/yr — both assumed, and the answer moves with them"
    )

    rows: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        holding_cost_per_unit = float(row.unit_value) * settings.annual_holding_rate
        annual_demand = float(row.d_bar) * 12.0
        eoq = economic_order_quantity(annual_demand, settings.order_cost, holding_cost_per_unit)

        quantities = order_quantity(
            policy=str(row.policy),
            ip=float(row.ip),
            order_up_to=float(row.S),
            reorder_point=float(row.s),
            eoq=eoq,
            moq=settings.default_moq,
            pack_size=settings.default_pack_size,
            beta_hat=float(row.beta_hat),
            use_eoq=settings.use_eoq,
            use_supply_inflation=settings.use_supply_inflation,
            inflation_cap=settings.supply_inflation_cap,
        )
        recent_6m = float(recent.get(row.active_sku_id, 0.0))
        recent_p = recent_6m / max(len(recent_months), 1) * ctx.protection_interval_months
        placeable, held, flags = review_hold(float(quantities["q_final"]), float(row.rol), recent_p)
        proposed = float(quantities["q_final"])
        quantities = {**quantities, "q_final": placeable}
        rows.append(
            {
                "active_sku_id": row.active_sku_id,
                "description": row.description,
                "cycle_month": f"{ctx.as_of:%Y-%m}",
                "policy": row.policy,
                "ip": row.ip,
                "on_hand": row.on_hand,
                "on_order": row.on_order,
                "s": row.s,
                "S": row.S,
                "ss": row.safety_stock,
                "ss_strategy": row.ss_strategy,
                "rol": row.rol,
                "eoq": eoq,
                **quantities,
                "unit_cost": row.unit_value,
                "value": quantities["q_final"] * float(row.unit_value),
                "q_proposed": proposed,
                "q_review": held,
                "value_review": held * float(row.unit_value),
                "recent_demand_6m": recent_6m,
                "flags": flags,
                "lead_time_months": ctx.lead_time_months,
                "expected_arrival": (
                    pd.Timestamp(ctx.as_of) + pd.DateOffset(months=ctx.lead_time_months)
                ).strftime("%Y-%m"),
                "trigger_reason": trigger_reason(
                    str(row.policy), float(row.ip), float(row.s), quantities["q_raw"]
                ),
                "criticality": row.criticality,
                "abc_class": row.abc,
                "fsn": row.fsn,
                "fill_target": row.fill_target,
                "z": row.z,
                "beta_hat": row.beta_hat,
            }
        )

    proposal = pd.DataFrame(rows)
    triggered = proposal[proposal["q_final"] > 0]
    result.rows_out = len(triggered)

    result.artifact(
        "monthly_order_proposal", write_table(proposal, "facts", "monthly_order_proposal")
    )
    result.artifact("mart_monthly_order", write_table(triggered, "marts", "mart_monthly_order"))
    review = proposal[proposal["q_review"] > 0]
    result.artifact("mart_order_review", write_table(review, "marts", "mart_order_review"))

    policy_summary = proposal.groupby(["policy", "abc_class"], as_index=False).agg(
        skus=("active_sku_id", "nunique"),
        triggered=("q_final", lambda s: int((s > 0).sum())),
        safety_stock=("ss", "sum"),
        order_value=("value", "sum"),
    )
    result.artifact(
        "mart_policy_summary", write_table(policy_summary, "marts", "mart_policy_summary")
    )

    service = read_table("facts", "holdout_validation")
    if not service.empty:
        result.artifact(
            "mart_service_and_stock", write_table(service, "marts", "mart_service_and_stock")
        )

    backtest_available = True
    try:
        accuracy = read_table("facts", "model_registry")
    except Exception:  # noqa: BLE001 - mart is optional if Step 07 produced nothing
        backtest_available = False
    if backtest_available:
        result.artifact(
            "mart_forecast_accuracy", write_table(accuracy, "marts", "mart_forecast_accuracy")
        )

    exceptions = []
    for name in ("order_exceptions", "catalogue_exceptions"):
        try:
            part = read_table("facts", name).assign(source=name)
            exceptions.append(part)
        except Exception:  # noqa: BLE001 - not every exception table exists every run
            continue
    if exceptions:
        combined = pd.concat(exceptions, ignore_index=True)
        result.artifact("mart_exceptions", write_table(combined, "marts", "mart_exceptions"))

    total_value = float(triggered["value"].sum())
    result.warn(
        f"STOP-AND-ASK: {len(review):,} line(s) held for buyer review "
        f"({float(review['value_review'].sum()):,.0f} {settings.currency}) — order above "
        f"{REVIEW_MULTIPLE:g}x the last {len(recent_months)} months' demand over the protection "
        f"interval, {int((review['recent_demand_6m'] <= 0).sum()):,} of them with no demand at all"
    )
    result.warn(
        f"{len(triggered):,} of {len(proposal):,} SKUs triggered an order this cycle, "
        f"total {total_value:,.0f} {settings.currency}; arrival "
        f"{proposal['expected_arrival'].iloc[0] if len(proposal) else 'n/a'}"
    )
    logger.info(f"monthly order: {len(triggered):,} lines, {total_value:,.0f} LKR")
    return result
