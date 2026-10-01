"""Month-by-month stock projection and expected-arrival parsing."""

from datetime import date

import pandas as pd
import pytest
from src.core.context import PlanningContext
from src.core.errors import ContractViolation, SourceDataError
from src.core.result import StageResult
from src.inventory import stock


def test_projection_does_not_count_snapshot_month_receipts_twice() -> None:
    on_hand = pd.DataFrame({"active_sku_id": ["A"], "on_hand": [100.0]})
    forecast = pd.DataFrame({"active_sku_id": ["A"], "mu_month": [20.0]})
    receipts = pd.DataFrame(
        {
            "active_sku_id": ["A", "A", "A"],
            "arrival": pd.to_datetime(["2026-08-01", "2026-10-01", "2026-12-01"]),
            "qty": [25.0, 10.0, 30.0],
        }
    )

    projected = stock.project_on_hand(
        on_hand, forecast, receipts, date(2026, 8, 31), date(2026, 12, 1)
    ).iloc[0]

    assert projected["on_hand_snapshot"] == 100.0
    assert projected["known_receipts_before_cycle"] == 10.0
    assert projected["projected_demand"] == 60.0
    assert projected["projection_months"] == 3
    assert projected["on_hand"] == 50.0


def test_projection_floors_stock_and_records_uncovered_demand() -> None:
    on_hand = pd.DataFrame({"active_sku_id": ["A"], "on_hand": [10.0]})
    forecast = pd.DataFrame({"active_sku_id": ["A"], "mu_month": [20.0]})
    receipts = pd.DataFrame(columns=["active_sku_id", "arrival", "qty"])

    projected = stock.project_on_hand(
        on_hand, forecast, receipts, date(2026, 8, 31), date(2026, 12, 1)
    ).iloc[0]

    assert projected["on_hand"] == 0.0
    assert projected["projected_uncovered_demand"] == 50.0


def test_projection_requires_month_end_snapshot() -> None:
    on_hand = pd.DataFrame({"active_sku_id": ["A"], "on_hand": [10.0]})
    forecast = pd.DataFrame({"active_sku_id": ["A"], "mu_month": [1.0]})
    receipts = pd.DataFrame(columns=["active_sku_id", "arrival", "qty"])

    with pytest.raises(SourceDataError, match="month-end"):
        stock.project_on_hand(on_hand, forecast, receipts, date(2026, 8, 30), date(2026, 12, 1))


def test_on_orders_month_is_expected_arrival(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame(
        {
            "Material": ["OLD-A"],
            "Description": ["Synthetic"],
            "Dec 2026": [25],
            "Jan 2027": [30],
        }
    )
    monkeypatch.setattr(stock, "read_source", lambda name: frame.copy())
    ctx = PlanningContext(as_of=date(2026, 9, 1))

    schedule, latest = stock._on_order_schedule(
        ctx, StageResult(stage="12_stock"), {"OLDA": "CURRENT-A"}
    )

    assert schedule["arrival"].dt.strftime("%Y-%m").tolist() == ["2026-12", "2027-01"]
    assert schedule["active_sku_id"].tolist() == ["CURRENT-A", "CURRENT-A"]
    assert schedule["qty"].sum() == 55
    assert latest == pd.Timestamp("2027-01-01")


def test_on_orders_rejects_yearless_or_gapped_months(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = PlanningContext(as_of=date(2026, 9, 1))
    for columns in ({"Sep": [1]}, {"Sep 2026": [1], "Nov 2026": [1]}):
        frame = pd.DataFrame({"Material": ["A"], **columns})
        monkeypatch.setattr(stock, "read_source", lambda name, frame=frame: frame.copy())
        with pytest.raises(SourceDataError):
            stock._on_order_schedule(ctx, StageResult(stage="12_stock"), {"A": "A"})


@pytest.mark.parametrize("quantity", ["not a quantity", -1])
def test_on_orders_rejects_invalid_quantities(
    monkeypatch: pytest.MonkeyPatch, quantity: object
) -> None:
    frame = pd.DataFrame({"Material": ["A"], "Sep 2026": [quantity]})
    monkeypatch.setattr(stock, "read_source", lambda name: frame.copy())
    with pytest.raises(ContractViolation):
        stock._on_order_schedule(
            PlanningContext(as_of=date(2026, 9, 1)), StageResult(stage="12_stock"), {"A": "A"}
        )


def test_live_order_cannot_reuse_an_older_stock_snapshot() -> None:
    stock.validate_live_snapshot(date(2026, 9, 1), date(2026, 8, 31))
    with pytest.raises(SourceDataError, match="matching month-end stock"):
        stock.validate_live_snapshot(date(2026, 10, 1), date(2026, 8, 31))


def test_open_orders_must_be_refreshed_for_a_new_stock_snapshot() -> None:
    kwargs = {
        "owner_confirmed": True,
        "interpretation": "arrival",
        "coverage_end": pd.Timestamp("2027-12-01"),
        "required_through": pd.Timestamp("2027-01-01"),
        "source_modified": date(2026, 9, 30),
    }
    assert stock.verified_open_orders(**kwargs, snapshot_as_of=date(2026, 8, 31))
    assert not stock.verified_open_orders(**kwargs, snapshot_as_of=date(2026, 12, 31))
