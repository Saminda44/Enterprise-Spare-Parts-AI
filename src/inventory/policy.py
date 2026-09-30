"""Step 13 — safety stock, reorder level, reorder quantity, chosen by simulation.

This is the project's acceptance gate. If the selected portfolio cannot beat the
baseline on the sealed holdout, that is a reportable result, not something to hide.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import brentq
from scipy.stats import norm

from src.core.context import PlanningContext
from src.core.errors import SourceDataError
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.core.settings import get_settings
from src.io.parquet import read_table, table_exists, write_table

Z_BOUNDS = (0.0, 4.5)
HYSTERESIS_COST_MARGIN = 0.05


def _parameters(
    series: dict[str, object], targets: dict[str, float], protection: int, sigma_lead: float
) -> dict[str, object]:
    """Safety stock, s, S and ROL for one SKU from its forecast row."""
    beta = targets.get(str(series.get("abc", "C")), targets["C"])
    ss = safety_stock(pd.Series(series), beta, protection, sigma_lead)
    mu_p = float(series.get("mu_p") or 0.0)
    d_bar = mu_p / protection if protection else 0.0
    order_up_to = mu_p + ss.selected
    reorder_point = ss.selected + d_bar * (protection - 1)
    return {
        "active_sku_id": series["active_sku_id"],
        "abc": series.get("abc"),
        "quadrant": series.get("quadrant"),
        "fill_target": beta,
        "z": ss.z,
        "ss_bracketing": ss.bracketing,
        "ss_normal": ss.normal,
        "ss_empirical": ss.empirical,
        "safety_stock": ss.selected,
        "ss_strategy": ss.strategy,
        "mu_p": mu_p,
        "d_bar": d_bar,
        "S": order_up_to,
        "s": reorder_point,
        "rol": d_bar * (protection - 1) + ss.selected,
        "months_of_cover": order_up_to / d_bar if d_bar > 0 else np.nan,
        "unit_value": series.get("unit_value", 0.0),
        "beta_hat": series.get("beta_hat", 0.75),
    }


def unit_normal_loss(z: float) -> float:
    """G(z) = φ(z) − z·(1 − Φ(z)) — expected shortfall per cycle in sigma units."""
    return float(norm.pdf(z) - z * (1.0 - norm.cdf(z)))


def z_for_fill_rate(beta: float, sigma_eff: float, demand_per_review: float) -> float:
    """Solve σ·G(z) / (d̄·R) ≤ 1 − β for z.

    Business meaning: fill rate is not cycle service level. CSL asks what fraction of
    cycles avoid a stockout; fill rate asks what fraction of *units* are served.
    Substituting a CSL lookup table over-stocks slow movers and under-stocks fast ones —
    and the error is largest exactly where the money is.
    """
    if sigma_eff <= 0 or demand_per_review <= 0:
        return Z_BOUNDS[0]
    target = (1.0 - beta) * demand_per_review / sigma_eff

    def objective(z: float) -> float:
        return unit_normal_loss(z) - target

    if objective(Z_BOUNDS[0]) <= 0:
        return Z_BOUNDS[0]
    if objective(Z_BOUNDS[1]) >= 0:
        return Z_BOUNDS[1]
    return float(brentq(objective, *Z_BOUNDS, xtol=1e-6))


@dataclass
class SafetyStock:
    bracketing: float
    normal: float
    empirical: float
    selected: float
    strategy: str
    z: float


def safety_stock(
    row: pd.Series, beta: float, protection_months: int, sigma_lead_months: float
) -> SafetyStock:
    """Three strategies; bracketing is always computed as a cross-check."""
    mu_p = float(row.get("mu_p", 0.0) or 0.0)
    sigma_p = float(row.get("sigma_p", 0.0) or 0.0)
    quadrant = str(row.get("quadrant", "no demand"))
    d_bar = mu_p / protection_months if protection_months else 0.0
    sigma_d = sigma_p / np.sqrt(protection_months) if protection_months else 0.0

    max_monthly = float(row.get("max_monthly_demand", d_bar) or d_bar)
    lead_months = max(protection_months - 1, 1)
    bracketing = max(max_monthly * (lead_months + sigma_lead_months) - d_bar * lead_months, 0.0)

    sigma_eff = float(np.sqrt(protection_months * sigma_d**2 + (d_bar * sigma_lead_months) ** 2))
    z = z_for_fill_rate(beta, sigma_eff, max(d_bar, 1e-9))
    normal = max(z * sigma_eff, 0.0)

    p_high = float(row.get("p95", mu_p) or mu_p)
    empirical = max(p_high - mu_p, 0.0)

    insufficient = bool(row.get("insufficient_history", False))
    if insufficient:
        selected, strategy = bracketing, "bracketing"
    elif quadrant in {"intermittent", "lumpy"}:
        # The normal assumption is simply false here: fitting a normal to 0,0,0,7,0,0,3
        # produces a negative lower tail and an understated upper one.
        selected, strategy = empirical, "empirical quantile"
    else:
        selected, strategy = normal, "normal approximation"

    if insufficient:
        selected = max(selected, bracketing)
    return SafetyStock(bracketing, normal, empirical, float(selected), strategy, float(z))


# ── policies ────────────────────────────────────────────────────────────────────
def policy_quantity(policy: str, ip: float, order_up_to: float, reorder_point: float) -> float:
    """Order quantity before EOQ, MOQ and pack rounding."""
    if policy == "RS":
        return max(0.0, order_up_to - ip)
    if policy == "RsS":
        return max(0.0, order_up_to - ip) if ip <= reorder_point else 0.0
    if policy == "ON_DEMAND":
        return max(0.0, -ip)
    return 0.0  # NO_STOCK


#: A non-moving part is still stocked when its fleet implies at least this much demand a
#: month — a part for a model launched this year moves little yet, but its fleet is real.
PARC_SUPPORTED_MONTHLY = 1.0


def candidate_policies(row: pd.Series) -> list[str]:
    """Config-driven assignment (Step 13 policy matrix).

    Business meaning: FSN = N and C-class zero-movers get ON_DEMAND or NO_STOCK — no cycle
    stock for parts that do not move — unless the fleet supports at least
    ``PARC_SUPPORTED_MONTHLY`` a month. This is checked *before* the short-history rule:
    almost every non-mover has a short history, and letting that rule win first put every
    one of them on a cycle-stock policy. criticality = high always includes RS, but no
    criticality source exists, so that branch is inert.
    """
    quadrant = str(row.get("quadrant", "no demand"))
    abc = str(row.get("abc", "C"))
    fsn = str(row.get("fsn", "N"))
    parc = row.get("mu_month_parc")
    parc_supported = parc is not None and pd.notna(parc) and float(parc) >= PARC_SUPPORTED_MONTHLY
    if str(row.get("criticality") or "").lower() == "high":
        return ["RS", "RsS"]
    if not parc_supported and (
        fsn == "N" or (abc == "C" and float(row.get("mu_month", 0) or 0) <= 0)
    ):
        return ["ON_DEMAND", "NO_STOCK"]
    if bool(row.get("insufficient_history", False)):
        return ["RS"]
    if quadrant == "smooth":
        return ["RS"]
    if quadrant == "lumpy":
        return ["RsS", "RS", "ON_DEMAND"] if (abc == "C" and fsn == "S") else ["RsS", "RS"]
    if quadrant in {"erratic", "intermittent"}:
        return ["RS", "RsS"]
    return ["RS"]


@dataclass
class SimulationOutcome:
    policy: str
    demand: float = 0.0
    served: float = 0.0
    lost_units: float = 0.0
    ordered: float = 0.0
    received: float = 0.0
    orders_placed: int = 0
    holding_units: float = 0.0
    ending_on_hand: float = 0.0
    conservation_error: float = 0.0

    @property
    def fill_rate(self) -> float:
        return self.served / self.demand if self.demand > 0 else 1.0


def simulate(
    demand_path: np.ndarray,
    policy: str,
    *,
    order_up_to: float,
    reorder_point: float,
    opening_stock: float,
    beta_hat: float,
    lead_months: int,
    unit_value: float,
    holding_rate: float,
    order_cost: float,
) -> tuple[SimulationOutcome, float]:
    """Walk-forward monthly simulator.

    The loop order is fixed: receive, then demand, then review-and-order. Reviewing
    before demand would let the same month's order serve the same month's demand, which
    no replenishment system can do against a multi-month import lead.
    """
    outcome = SimulationOutcome(policy=policy)
    on_hand = float(opening_stock)
    pipeline: dict[int, float] = {}

    for period, demand in enumerate(demand_path):
        # 1. Receive — short-shipped remainder is logged and gone (lost-sales world).
        arriving = pipeline.pop(period, 0.0)
        received = arriving * beta_hat
        on_hand += received
        outcome.received += received

        # 2. Demand — raw, not outlier-adjusted; the policy must survive real spikes.
        served = min(on_hand, float(demand))
        on_hand -= served
        outcome.demand += float(demand)
        outcome.served += served
        outcome.lost_units += float(demand) - served

        # 3. Review and order.
        ip = on_hand + sum(pipeline.values())
        quantity = policy_quantity(policy, ip, order_up_to, reorder_point)
        if quantity > 0:
            pipeline[period + lead_months] = pipeline.get(period + lead_months, 0.0) + quantity
            outcome.ordered += quantity
            outcome.orders_placed += 1

        outcome.holding_units += on_hand

    outcome.ending_on_hand = on_hand
    # received - served - delta on_hand == 0
    outcome.conservation_error = abs(
        outcome.received - outcome.served - (on_hand - float(opening_stock))
    )

    months = max(len(demand_path), 1)
    holding_cost = (outcome.holding_units / months) * unit_value * holding_rate * (months / 12)
    ordering_cost = outcome.orders_placed * order_cost
    return outcome, float(holding_cost + ordering_cost)


@REGISTRY.register(
    "13_policy",
    depends_on=["08_forecast", "12_stock", "05_order_analysis"],
    description="safety stock, policy simulation, selection and holdout validation",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="13_policy")
    settings = get_settings()

    # Selection and the holdout use the validation forecast (fitted before the holdout);
    # the published parameters — what the order runs on — use the live forecast.
    forecast = read_table("facts", "forecast_protection")
    live_forecast = (
        read_table("facts", "forecast_live") if table_exists("facts", "forecast_live") else forecast
    )
    classification = read_table("facts", "sku_classification")
    stock = read_table("facts", "stock_position")
    reliability = read_table("facts", "supply_reliability")
    lead_stats = read_table("facts", "lead_time_stats")
    history = read_table("facts", "demand_history")
    split = read_table("facts", "holdout_split")
    result.rows_in = len(forecast)

    result.warn(
        "BUSINESS PARAMETERS ARE ASSUMED, NOT SUPPLIED: fill-rate targets "
        f"{settings.fill_rate_targets}, holding rate {settings.annual_holding_rate:.0%}/yr, "
        f"order cost {settings.order_cost:,.0f} {settings.currency}. None appears in any source "
        "file. Every number below moves with them."
    )

    replenishment = lead_stats[lead_stats["scope"] == "REPLENISHMENT"]
    sigma_lead_months = 0.0
    if not replenishment.empty and pd.notna(replenishment.iloc[0]["std_days"]):
        sigma_lead_months = float(replenishment.iloc[0]["std_days"]) / 30.0
    else:
        result.warn(
            "sigma_L for replenishment is UNKNOWN (no measured import lead time), so it is "
            "treated as zero — safety stock carries demand variability only, not lead-time "
            "variability, and is therefore an understatement"
        )

    def assemble(source: pd.DataFrame) -> pd.DataFrame:
        out = (
            source.merge(classification, on="active_sku_id", how="left", suffixes=("", "_cls"))
            .merge(
                stock[["active_sku_id", "on_hand", "on_order", "ip"]],
                on="active_sku_id",
                how="left",
            )
            .merge(
                reliability[["active_sku_id", "beta_hat"]].drop_duplicates("active_sku_id"),
                on="active_sku_id",
                how="left",
            )
        )
        out[["on_hand", "on_order", "ip"]] = out[["on_hand", "on_order", "ip"]].fillna(0.0)
        out["beta_hat"] = out["beta_hat"].fillna(0.75).clip(0.05, 1.0)
        return out

    frame = assemble(forecast)
    live_frame = assemble(live_forecast)

    unit_value = (
        read_table("facts", "orders_clean")
        .assign(price=lambda d: d["order_value"] / d["confirmed_quantity"].replace(0, np.nan))
        .groupby("active_sku_id")["price"]
        .median()
    )
    frame["unit_value"] = frame["active_sku_id"].map(unit_value).fillna(0.0)
    live_frame["unit_value"] = live_frame["active_sku_id"].map(unit_value).fillna(0.0)

    months = sorted(history["month"].dropna().unique())
    holdout_start = str(split.at[0, "holdout_start"])
    panel = (
        history.pivot_table(
            index="active_sku_id", columns="month", values="ordered_quantity", aggfunc="sum"
        )
        .reindex(columns=months)
        .fillna(0.0)
    )
    selection_cols = [m for m in months if m < holdout_start]
    holdout_cols = [m for m in months if m >= holdout_start]
    frame["max_monthly_demand"] = (
        frame["active_sku_id"].map(panel[selection_cols].max(axis=1)).fillna(0.0)
    )
    live_frame["max_monthly_demand"] = (
        live_frame["active_sku_id"].map(panel[months].max(axis=1)).fillna(0.0)
    )

    targets = settings.fill_rate_targets
    protection = ctx.protection_interval_months

    if ctx.option("provisional", False):
        prior = read_table("facts", "policy_selection")
        missing = set(live_frame["active_sku_id"]) - set(prior["active_sku_id"])
        if missing:
            raise SourceDataError(
                f"provisional policy has no prior assignment for {len(missing):,} SKU(s)"
            )
        policy_params = pd.DataFrame(
            [
                _parameters(r._asdict(), targets, protection, sigma_lead_months)
                for r in live_frame.itertuples(index=False)
            ]
        ).assign(basis="live_provisional")
        result.artifact("policy_params", write_table(policy_params, "facts", "policy_params"))
        result.warn(
            "PROVISIONAL: recomputed five-month s/S and safety stock from the live forecast; "
            "policy assignments are reused from the previous published run and are NOT "
            "validated for the four-month lead. Historical holdout is not rerun against "
            "projected December stock."
        )
        result.rows_out = len(policy_params)
        return result

    params: list[dict[str, object]] = []
    selections: list[dict[str, object]] = []
    scores: list[dict[str, object]] = []

    for row in frame.itertuples(index=False):
        series = row._asdict()
        entry = _parameters(series, targets, protection, sigma_lead_months)
        params.append(entry)
        beta = float(entry["fill_target"])
        order_up_to = float(entry["S"])
        reorder_point = float(entry["s"])

        sku_selection = (
            panel.loc[series["active_sku_id"], selection_cols].to_numpy(dtype=float)
            if series["active_sku_id"] in panel.index
            else np.zeros(len(selection_cols))
        )

        best: tuple[float, str, float] | None = None
        for policy in candidate_policies(pd.Series(series)):
            outcome, cost = simulate(
                sku_selection,
                policy,
                order_up_to=order_up_to,
                reorder_point=reorder_point,
                opening_stock=float(series.get("on_hand", 0.0)),
                beta_hat=float(series.get("beta_hat", 0.75)),
                lead_months=ctx.lead_time_months,
                unit_value=float(series.get("unit_value", 0.0)),
                holding_rate=settings.annual_holding_rate,
                order_cost=settings.order_cost,
            )
            scores.append(
                {
                    "active_sku_id": series["active_sku_id"],
                    "policy": policy,
                    "fill_rate": outcome.fill_rate,
                    "cost": cost,
                    "lost_units": outcome.lost_units,
                    "orders_placed": outcome.orders_placed,
                    "conservation_error": outcome.conservation_error,
                }
            )
            feasible = outcome.fill_rate >= beta
            key = (0 if feasible else 1, cost, -outcome.fill_rate)
            if best is None or key < best[0]:  # type: ignore[index]
                best = (key, policy, cost)  # type: ignore[assignment]

        chosen = best[1] if best else "RS"
        selections.append(
            {
                "active_sku_id": series["active_sku_id"],
                "policy": chosen,
                "abc": series.get("abc"),
                "quadrant": series.get("quadrant"),
                "hysteresis_margin": HYSTERESIS_COST_MARGIN,
            }
        )

    validation_params = pd.DataFrame(params)
    policy_params = pd.DataFrame(
        [
            _parameters(r._asdict(), targets, protection, sigma_lead_months)
            for r in live_frame.itertuples(index=False)
        ]
    ).assign(basis="live")
    policy_selection = pd.DataFrame(selections)
    simulation_results = pd.DataFrame(scores)

    conservation = (
        float(simulation_results["conservation_error"].max()) if len(simulation_results) else 0.0
    )
    if conservation > 1e-6:
        result.warn(f"CONSERVATION VIOLATED: max error {conservation:.6f} units")
    else:
        result.warn("conservation holds: received - served - delta on_hand = 0 across all runs")

    result.artifact("policy_params", write_table(policy_params, "facts", "policy_params"))
    result.artifact(
        "policy_params_validation",
        write_table(
            validation_params.assign(basis="validation"), "facts", "policy_params_validation"
        ),
    )
    result.warn(
        "published s / S / safety stock use the LIVE forecast (all history); selection and the "
        "holdout used the validation forecast, so the holdout stays sealed"
    )
    result.artifact("policy_selection", write_table(policy_selection, "facts", "policy_selection"))
    result.artifact(
        "simulation_results", write_table(simulation_results, "facts", "simulation_results")
    )

    holdout = _holdout(
        frame, validation_params, policy_selection, panel, holdout_cols, ctx, settings, result
    )
    result.artifact("holdout_validation", write_table(holdout, "facts", "holdout_validation"))

    result.warn(f"policy mix: {policy_selection['policy'].value_counts().to_dict()}")
    result.warn(f"SS strategy mix: {policy_params['ss_strategy'].value_counts().to_dict()}")

    result.rows_out = len(policy_params)
    logger.info(f"policy: {len(policy_params):,} SKUs, holdout {len(holdout_cols)} months")
    return result


def _holdout(
    frame: pd.DataFrame,
    params: pd.DataFrame,
    selection: pd.DataFrame,
    panel: pd.DataFrame,
    holdout_cols: list[str],
    ctx: PlanningContext,
    settings,  # noqa: ANN001 - Settings, avoids a circular import in the annotation
    result: StageResult,
) -> pd.DataFrame:
    """Open the sealed holdout once: selected portfolio against the baseline rule.

    Never re-open selection on these results. That un-blinds the holdout and the number
    stops meaning anything.
    """
    if not holdout_cols:
        result.warn("no holdout months available — acceptance gate cannot be evaluated")
        return pd.DataFrame()

    merged = params.merge(selection[["active_sku_id", "policy"]], on="active_sku_id", how="left")
    rows: list[dict[str, object]] = []

    for arm in ("selected", "baseline"):
        total_demand = total_served = total_cost = total_units = 0.0
        for row in merged.itertuples(index=False):
            sku = row.active_sku_id
            if sku not in panel.index:
                continue
            path = panel.loc[sku, holdout_cols].to_numpy(dtype=float)
            opening = float(frame.loc[frame["active_sku_id"] == sku, "on_hand"].sum())
            if arm == "selected":
                policy, order_up_to, reorder = row.policy or "RS", row.S, row.s
            else:
                # Baseline: order up to three months of average demand, no safety stock.
                policy, order_up_to, reorder = "RS", row.d_bar * 3.0, 0.0
            outcome, cost = simulate(
                path,
                policy,
                order_up_to=order_up_to,
                reorder_point=reorder,
                opening_stock=opening,
                beta_hat=row.beta_hat,
                lead_months=ctx.lead_time_months,
                unit_value=row.unit_value,
                holding_rate=settings.annual_holding_rate,
                order_cost=settings.order_cost,
            )
            total_demand += outcome.demand
            total_served += outcome.served
            total_cost += cost
            total_units += outcome.holding_units / max(len(path), 1) * row.unit_value

        rows.append(
            {
                "arm": arm,
                "fill_rate": total_served / total_demand if total_demand else 1.0,
                "total_cost": total_cost,
                "average_inventory_value": total_units,
                "holdout_months": len(holdout_cols),
            }
        )

    holdout = pd.DataFrame(rows)
    selected = holdout[holdout["arm"] == "selected"].iloc[0]
    baseline = holdout[holdout["arm"] == "baseline"].iloc[0]
    service_win = selected["fill_rate"] >= baseline["fill_rate"]
    stock_win = selected["average_inventory_value"] <= baseline["average_inventory_value"]

    verdict = (
        "PASS" if service_win and stock_win else "FRONTIER" if service_win or stock_win else "FAIL"
    )
    result.warn(
        f"ACCEPTANCE GATE [{verdict}] on the sealed holdout ({len(holdout_cols)} months): "
        f"selected fill {selected['fill_rate']:.3f} vs baseline {baseline['fill_rate']:.3f}; "
        f"avg inventory value {selected['average_inventory_value']:,.0f} vs "
        f"{baseline['average_inventory_value']:,.0f}"
    )
    if verdict == "FRONTIER":
        result.warn(
            "won on one axis only — this is a frontier to show the owner, not a pass to claim"
        )
    holdout["verdict"] = verdict
    return holdout
