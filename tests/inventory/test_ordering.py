"""Step 14 gates: the order function's worked example and its rounding rules."""

from __future__ import annotations

import pytest
from src.inventory.ordering import economic_order_quantity, order_quantity, trigger_reason


def _order(**kwargs):
    defaults = dict(
        policy="RS",
        ip=120.0,
        order_up_to=300.0,
        reorder_point=150.0,
        eoq=140.0,
        moq=50.0,
        pack_size=25.0,
        beta_hat=0.745,
        use_eoq=True,
        use_supply_inflation=False,
        inflation_cap=1.5,
    )
    defaults.update(kwargs)
    return order_quantity(**defaults)


def test_worked_example_from_the_specification() -> None:
    """IP = 120, S = 300, MOQ = 50, pack = 25 -> q_final = 200.

    q_raw 180 (300 - 120), EOQ 140 has no effect, MOQ 50 has no effect,
    pack rounds 180 up to 200.
    """
    result = _order()

    assert result["q_raw"] == 180.0
    assert result["q_econ"] == 180.0, "EOQ is a floor, and 180 already clears 140"
    assert result["q_moq"] == 180.0, "MOQ 50 has no effect on 180"
    assert result["q_pack"] == 200.0, "ceil(180/25) * 25"
    assert result["q_final"] == 200.0


def test_pack_rounding_never_rounds_down() -> None:
    for raw, pack, expected in ((101.0, 25.0, 125.0), (100.0, 25.0, 100.0), (1.0, 24.0, 24.0)):
        result = _order(ip=300.0 - raw, order_up_to=300.0, pack_size=pack, eoq=0.0, moq=0.0)
        assert result["q_final"] == expected


def test_moq_never_applies_to_a_zero_order() -> None:
    """A part that is not triggered must not be dragged up to the minimum."""
    result = _order(policy="RsS", ip=200.0, reorder_point=150.0)

    assert result["q_raw"] == 0.0
    assert result["q_moq"] == 0.0
    assert result["q_final"] == 0.0


def test_eoq_acts_as_a_floor_not_the_order() -> None:
    result = _order(ip=290.0, eoq=140.0, pack_size=1.0, moq=1.0)
    assert result["q_raw"] == 10.0
    assert result["q_econ"] == 140.0, "EOQ lifts a small triggered order"


def test_eoq_can_be_switched_off() -> None:
    result = _order(ip=290.0, eoq=140.0, pack_size=1.0, moq=1.0, use_eoq=False)
    assert result["q_econ"] == 10.0


def test_supply_inflation_is_off_by_default_and_capped_when_on() -> None:
    plain = _order()
    inflated = _order(use_supply_inflation=True, beta_hat=0.5)

    assert plain["q_final"] == 200.0, "off by default"
    # 1/0.5 = 2.0 but the cap is 1.5, so 200 * 1.5 = 300
    assert inflated["q_final"] == 300.0


def test_inflation_respects_the_pack_size() -> None:
    result = _order(use_supply_inflation=True, beta_hat=0.8, pack_size=25.0)
    assert result["q_final"] % 25 == 0


# ── EOQ ─────────────────────────────────────────────────────────────────────────
def test_eoq_formula() -> None:
    """EOQ = sqrt(2DS/H)."""
    assert economic_order_quantity(1200.0, 5000.0, 10.0) == pytest.approx(
        (2 * 1200 * 5000 / 10) ** 0.5
    )


@pytest.mark.parametrize(
    ("demand", "order_cost", "holding"),
    [(0.0, 5000.0, 10.0), (1200.0, 0.0, 10.0), (1200.0, 5000.0, 0.0), (-5.0, 5000.0, 10.0)],
)
def test_eoq_guards_degenerate_inputs(demand: float, order_cost: float, holding: float) -> None:
    assert economic_order_quantity(demand, order_cost, holding) == 0.0


# ── explainability ──────────────────────────────────────────────────────────────
def test_every_line_carries_a_reason() -> None:
    assert "ordered up to S" in trigger_reason("RS", 120.0, 150.0, 180.0)
    assert "at or below s" in trigger_reason("RsS", 120.0, 150.0, 180.0)
    assert "above reorder point" in trigger_reason("RsS", 200.0, 150.0, 0.0)
    assert "ordering stopped" in trigger_reason("NO_STOCK", 0.0, 0.0, 0.0)
    assert "no firm requirement" in trigger_reason("ON_DEMAND", 10.0, 0.0, 0.0)
