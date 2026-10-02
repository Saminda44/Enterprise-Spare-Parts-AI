"""Reorder level = 1 month of demand + buffer, judged on stock when the order lands."""

from __future__ import annotations

import numpy as np
import pandas as pd
from src.forecast.backtest import rmsse
from src.forecast.models import BENCHMARKS, CANDIDATES, INSUFFICIENT_HISTORY_CANDIDATES
from src.inventory.ordering import reorder_quantity, stock_checked
from src.inventory.policy import _parameters

MONTHS = list(pd.period_range("2026-09", "2027-01", freq="M"))  # cycle .. landing


def test_reorder_level_is_one_month_of_demand_plus_buffer() -> None:
    row = {"active_sku_id": "P1", "abc": "A", "mu_p": 500.0, "sigma_p": 0.0, "p95": 500.0}
    params = _parameters(row, {"A": 0.95, "B": 0.9, "C": 0.85}, protection=5, sigma_lead=0.0)
    d_bar, ss = params["d_bar"], params["safety_stock"]
    assert d_bar == 100.0
    assert params["rol"] == d_bar + ss
    assert params["target_at_landing"] == params["S"] - 4 * d_bar  # review month + buffer
    assert params["s"] == params["rol"]  # the simulator's threshold is the reorder level


def test_sparse_part_buffer_is_capped_at_three_months() -> None:
    from src.inventory.policy import safety_stock

    # Ordered twice in three years: monthly forecast 3, but one month of 240.
    row = pd.Series(
        {
            "mu_p": 15.0,
            "sigma_p": 40.0,
            "p95": 400.0,
            "max_monthly_demand": 240.0,
            "insufficient_history": True,
            "quadrant": "lumpy",
        }
    )
    ss = safety_stock(row, 0.95, protection_months=5, sigma_lead_months=0.0, cap_months=3.0)
    assert ss.bracketing > 900  # the old buffer: largest month x lead time
    assert ss.selected == 9.0  # 3 months x 3 per month
    assert "capped at 3 months" in ss.strategy


def test_eoq_floor_never_exceeds_three_months() -> None:
    from src.inventory.ordering import economic_order_quantity

    # 10/month of a cheap part: uncapped EOQ is ~110 (11 months); capped at 30.
    uncapped = economic_order_quantity(120, order_cost=5000, holding_cost=100)
    assert uncapped > 100
    assert economic_order_quantity(120, 5000, 100, cap_months=3.0) == 30


def test_checked_stock_is_on_hand_plus_everything_on_order() -> None:
    assert stock_checked(300, 290) == 590  # every incoming unit counts, no forecast deducted
    assert stock_checked(-5, 0) == 0


def test_order_only_when_checked_stock_is_at_or_below_the_reorder_level() -> None:
    assert reorder_quantity("RS", stock=150, rol=160, target=160) == 10
    assert reorder_quantity("RsS", stock=100, rol=160, target=160) == 60
    assert reorder_quantity("RS", stock=170, rol=160, target=160) == 0
    assert reorder_quantity("ON_DEMAND", stock=0, rol=160, target=160) == 0


def test_last_month_only_and_all_history_mean_are_never_chosen() -> None:
    for pool in (*CANDIDATES.values(), INSUFFICIENT_HISTORY_CANDIDATES):
        assert "naive" not in pool and "mean" not in pool
    assert set(BENCHMARKS) == {"naive", "mean"}


def test_squared_error_score_does_not_reward_forecasting_zero() -> None:
    train = np.array([0, 10, 0, 12, 0, 9, 0, 11], dtype=float)
    actual = np.array([0, 10, 0, 10, 0], dtype=float)
    zero = rmsse(actual, np.zeros(5), train)
    average = rmsse(actual, np.full(5, 4.0), train)
    assert average < zero
