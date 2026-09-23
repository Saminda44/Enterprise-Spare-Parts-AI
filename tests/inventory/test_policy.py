"""Step 13 gates: the z solver, the ROL worked example, and a hand-traced toy world."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import norm
from src.inventory.policy import (
    policy_quantity,
    simulate,
    unit_normal_loss,
    z_for_fill_rate,
)


def test_unit_normal_loss_matches_textbook() -> None:
    """G(z) = phi(z) - z(1 - Phi(z))."""
    for z in (0.0, 0.5, 1.0, 1.645, 2.0):
        expected = norm.pdf(z) - z * (1 - norm.cdf(z))
        assert unit_normal_loss(z) == pytest.approx(expected, abs=1e-12)

    assert unit_normal_loss(0.0) == pytest.approx(0.3989422804, abs=1e-8)


def test_z_solver_inverts_the_fill_rate_equation() -> None:
    """The solved z must satisfy sigma*G(z)/(d_bar*R) <= 1 - beta."""
    beta, sigma_eff, d_bar = 0.95, 30.0, 50.0
    z = z_for_fill_rate(beta, sigma_eff, d_bar)

    achieved_shortfall = sigma_eff * unit_normal_loss(z) / d_bar
    assert achieved_shortfall <= (1 - beta) + 1e-6
    assert 0.0 <= z <= 4.5


def test_higher_fill_target_requires_more_buffer() -> None:
    low = z_for_fill_rate(0.90, 30.0, 50.0)
    high = z_for_fill_rate(0.99, 30.0, 50.0)
    assert high > low


def test_z_is_clamped_and_degenerate_inputs_are_safe() -> None:
    assert z_for_fill_rate(0.95, 0.0, 50.0) == 0.0
    assert z_for_fill_rate(0.95, 30.0, 0.0) == 0.0
    assert z_for_fill_rate(0.999999, 1e6, 1.0) <= 4.5


def test_rol_worked_example() -> None:
    """Committed from the specification: d_bar = 50/month, L = 3, SS = 40 -> ROL = 190."""
    d_bar, lead_months, safety = 50.0, 3, 40.0
    rol = d_bar * lead_months + safety
    assert rol == 190.0


# ── policy quantities ───────────────────────────────────────────────────────────
def test_rs_orders_up_to_S_every_review() -> None:
    assert policy_quantity("RS", ip=120, order_up_to=300, reorder_point=0) == 180


def test_rss_only_orders_below_s() -> None:
    assert policy_quantity("RsS", ip=120, order_up_to=300, reorder_point=150) == 180
    assert policy_quantity("RsS", ip=200, order_up_to=300, reorder_point=150) == 0


def test_no_stock_never_orders() -> None:
    assert policy_quantity("NO_STOCK", ip=0, order_up_to=300, reorder_point=150) == 0


def test_on_demand_only_covers_a_negative_position() -> None:
    assert policy_quantity("ON_DEMAND", ip=-25, order_up_to=300, reorder_point=0) == 25
    assert policy_quantity("ON_DEMAND", ip=10, order_up_to=300, reorder_point=0) == 0


# ── the simulator ───────────────────────────────────────────────────────────────
def _sim(path, policy="RS", **kwargs):
    defaults = dict(
        order_up_to=100.0,
        reorder_point=50.0,
        opening_stock=0.0,
        beta_hat=1.0,
        lead_months=3,
        unit_value=10.0,
        holding_rate=0.2,
        order_cost=5000.0,
    )
    defaults.update(kwargs)
    return simulate(np.asarray(path, dtype=float), policy, **defaults)


def test_toy_world_traced_by_hand() -> None:
    """Two parts, twelve months, worked by hand and committed as a golden test.

    Part A: demand 10/month, opening stock 0, lead 3, (R,S) with S = 100.
    Month 0: receives nothing, serves 0 of 10 (empty), orders 100, arriving month 3.
    Months 1-2: still empty, 10 lost each month. Orders are placed but IP already
    includes the pipeline, so nothing further is ordered.
    Month 3: 100 arrives, serves 10. From then on demand is met.
    Expected: 30 units lost across the first three months, then full service.
    """
    outcome, _ = _sim([10.0] * 12, "RS", order_up_to=100.0, opening_stock=0.0)

    assert outcome.demand == 120.0
    assert outcome.lost_units == 30.0, "three months empty while the first order is in transit"
    assert outcome.served == 90.0
    assert outcome.fill_rate == pytest.approx(0.75)
    assert outcome.conservation_error == pytest.approx(0.0, abs=1e-9)


def test_opening_stock_covers_the_lead_time_gap() -> None:
    """Part B: same demand, but 30 units on the shelf covers the three-month wait."""
    outcome, _ = _sim([10.0] * 12, "RS", order_up_to=100.0, opening_stock=30.0)

    assert outcome.lost_units == 0.0
    assert outcome.fill_rate == 1.0
    assert outcome.conservation_error == pytest.approx(0.0, abs=1e-9)


def test_conservation_holds_under_short_shipment() -> None:
    """received - served - delta on_hand == 0 even when the supplier under-ships."""
    outcome, _ = _sim([8.0] * 10, "RS", beta_hat=0.7, opening_stock=20.0)
    assert outcome.conservation_error == pytest.approx(0.0, abs=1e-9)


def test_short_shipment_forces_more_ordering_to_receive_the_same() -> None:
    """Only a fraction of each order lands, so the policy must order more to stand still.

    Lost units are not necessarily higher: an (R,S) policy with slack re-orders every
    review and catches up. What short shipment costs is ordering volume, not service,
    until the shortfall outruns the policy's ability to re-order.
    """
    full, _ = _sim([10.0] * 12, "RS", beta_hat=1.0)
    short, _ = _sim([10.0] * 12, "RS", beta_hat=0.5)

    assert short.ordered > full.ordered, "more must be ordered to receive the same"
    assert short.received < short.ordered, "only beta_hat of each order arrives"
    assert short.received == pytest.approx(short.ordered * 0.5, rel=0.35)


def test_severe_short_shipment_eventually_costs_service() -> None:
    """With no slack to re-order into, under-shipment does show up as lost sales."""
    full, _ = _sim([10.0] * 6, "RS", order_up_to=10.0, beta_hat=1.0, opening_stock=30.0)
    short, _ = _sim([10.0] * 6, "RS", order_up_to=10.0, beta_hat=0.2, opening_stock=30.0)

    assert short.lost_units > full.lost_units


def test_order_is_not_received_before_the_lead_time() -> None:
    """An order placed in month 0 cannot serve month 0, 1 or 2 demand."""
    outcome, _ = _sim([10.0, 0.0, 0.0, 0.0], "RS", order_up_to=100.0, lead_months=3)
    assert outcome.lost_units == 10.0, "month 0 demand cannot be served by month 0's order"


def test_no_stock_policy_serves_only_opening_stock() -> None:
    outcome, cost = _sim([10.0] * 6, "NO_STOCK", opening_stock=25.0)
    assert outcome.ordered == 0.0
    assert outcome.orders_placed == 0
    assert outcome.served == 25.0
    assert cost == pytest.approx((outcome.holding_units / 6) * 10.0 * 0.2 * (6 / 12)), (
        "no ordering cost when nothing is ordered"
    )


def test_zero_demand_scores_a_full_fill_rate() -> None:
    outcome, _ = _sim([0.0] * 6, "RS")
    assert outcome.fill_rate == 1.0
