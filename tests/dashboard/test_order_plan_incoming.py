"""Month-by-month incoming-stock view on the order plan; synthetic parts only."""

from __future__ import annotations

import json

import pandas as pd
from src.dashboard.order_plan import project_incoming


def _parts(on_hand: float, forecast: float = 30, buffer: float = 25) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "active_sku_id": "P1",
                "on_hand": on_hand,
                "forecast_month": forecast,
                "safety_stock": buffer,
            }
        ]
    )


def _schedule(*arrivals: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"active_sku_id": "P1", "arrival": pd.Timestamp(m), "qty": q} for m, q in arrivals]
    )


def test_empty_shelf_before_a_later_arrival_is_flagged_for_expediting() -> None:
    row = project_incoming(_parts(0), _schedule(("2026-12-01", 100)), "2026-09", "2027-01").iloc[0]
    assert row["run_out_month"] == "2026-09"
    assert row["expedite"] and row["next_arrival_month"] == "2026-12"
    assert row["next_arrival_qty"] == 100
    assert row["short_units"] == 90  # Sep, Oct, Nov demand cannot be met
    assert row["stock_at_order_arrival"] == 40  # 100 - 30 (Dec) - 30 (Jan)
    assert json.loads(row["incoming_by_month"]) == [{"month": "2026-12", "qty": 100.0}]


def test_enough_stock_is_not_flagged() -> None:
    row = project_incoming(_parts(500), _schedule(("2026-10-01", 50)), "2026-09", "2027-01").iloc[0]
    assert row["run_out_month"] is None and not row["expedite"]
    assert row["below_buffer_month"] is None
    assert row["incoming_in_window"] == 50


def test_running_out_with_nothing_incoming_is_not_an_expedite() -> None:
    row = project_incoming(_parts(40), None, "2026-09", "2027-01").iloc[0]
    assert row["run_out_month"] == "2026-10"  # 40 covers September only
    assert not row["expedite"] and row["short_units"] == 0
    assert row["below_buffer_month"] == "2026-09"  # 10 left, under the buffer of 25


def test_monthly_reorder_level_starts_from_todays_decision() -> None:
    parts = _parts(100).assign(on_order=50, reorder_level=145)
    row = project_incoming(parts, _schedule(("2026-10-01", 50)), "2026-09", "2027-01").iloc[0]
    monthly = json.loads(row["monthly_rol"])
    assert [m["month"] for m in monthly] == ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]
    # Each month: what is on the shelf plus that month's arrivals, against the month's ROL
    # (1 month of demand + buffer).
    assert monthly[0] == {
        "month": "2026-09",
        "stock_start": 100.0,
        "incoming": 0.0,
        "position": 100.0,
        "rol": 145.0,
        "at_or_below": True,
    }
    # October: 100 - 30 = 70 on the shelf + the 50 landing = 120.
    assert monthly[1]["position"] == 120 and monthly[1]["at_or_below"]
    assert row["reorder_due_month"] == "2026-09"
    assert {m["rol"] for m in monthly} == {145.0}  # one forecast rate: same level each month


def test_arrivals_outside_the_window_are_ignored() -> None:
    row = project_incoming(_parts(0), _schedule(("2027-04-01", 70)), "2026-09", "2027-01").iloc[0]
    assert row["incoming_in_window"] == 0 and not row["expedite"]
