"""Non-movers, the stop-and-ask review hold, and the per-part fleet forecast."""

from __future__ import annotations

import pandas as pd
import pytest
from src.forecast.parc_demand import AGE_BANDS, blend_weight, exposure, model_codes
from src.inventory.ordering import REVIEW_MULTIPLE, review_hold
from src.inventory.policy import candidate_policies


def test_non_mover_with_short_history_is_not_cycle_stocked() -> None:
    row = pd.Series({"fsn": "N", "abc": "C", "quadrant": "lumpy", "insufficient_history": True})
    assert candidate_policies(row) == ["ON_DEMAND", "NO_STOCK"]


def test_non_mover_backed_by_its_fleet_is_still_stocked() -> None:
    row = pd.Series(
        {
            "fsn": "N",
            "abc": "C",
            "quadrant": "lumpy",
            "insufficient_history": True,
            "mu_month_parc": 4.0,
        }
    )
    assert candidate_policies(row) == ["RS"]


def test_moving_part_with_short_history_keeps_rs() -> None:
    row = pd.Series({"fsn": "F", "abc": "A", "quadrant": "smooth", "insufficient_history": True})
    assert candidate_policies(row) == ["RS"]


def test_review_hold_holds_orders_far_above_recent_demand() -> None:
    placeable, held, flags = review_hold(q_final=100, rol=10, recent_protection_demand=20)
    assert (placeable, held) == (0.0, 100)
    assert "REVIEW" in flags


def test_review_hold_lets_normal_orders_through() -> None:
    limit = REVIEW_MULTIPLE * 20
    placeable, held, flags = review_hold(q_final=limit, rol=10, recent_protection_demand=20)
    assert (placeable, held, flags) == (limit, 0.0, "")


def test_review_hold_names_parts_with_no_demand() -> None:
    _, held, flags = review_hold(q_final=5, rol=0, recent_protection_demand=0)
    assert held == 5 and "no demand" in flags


def test_blend_keeps_both_forecasts_in_play() -> None:
    assert blend_weight(30, True) == pytest.approx(0.8)  # long history: still 20% fleet
    assert blend_weight(3, True) == pytest.approx(0.2)  # young part: leans on the fleet
    assert blend_weight(0, True) == 0.0  # no history: fleet only
    assert blend_weight(30, False) == 1.0  # no fleet link: history only


def test_model_codes_from_catalogue_labels() -> None:
    assert model_codes(["R 15 - 2FB6", "FZ & FZS - B971", "no code"]) == ["2FB6", "B971"]
    assert model_codes('{"LIBERO - 5TSD"}') == ["5TSD"]
    assert model_codes(None) == []


def test_exposure_sums_only_the_parts_models() -> None:
    index = pd.MultiIndex.from_tuples(
        [("A", 2025), ("A", 2026), ("B", 2026)], names=["model_code", "year"]
    )
    fleet = pd.DataFrame(0.0, index=index, columns=list(AGE_BANDS))
    fleet.loc[("A", 2025), "0-2"] = 10
    fleet.loc[("A", 2026), "0-2"] = 30
    fleet.loc[("B", 2026), "3-5"] = 7
    only_a = exposure(fleet, ["A"])
    assert only_a.loc[2026, "0-2"] == 30 and only_a.loc[2026, "3-5"] == 0
    whole = exposure(fleet, ["*"])
    assert whole.loc[2026].sum() == 37
    assert exposure(fleet, ["ZZZZ"]).empty


def test_stock_status_counts_stock_on_order() -> None:
    from src.dashboard.sku import classify_stock

    assert classify_stock(0.0, on_hand=0, demand=5, on_order=0) == "STOCKOUT"
    assert classify_stock(4.0, on_hand=0, demand=5, on_order=20) == "AWAITING_STOCK"
    assert classify_stock(0.5, on_hand=2, demand=5, on_order=0) == "CRITICAL"
    assert classify_stock(6.0, on_hand=10, demand=5, on_order=20) == "HEALTHY"
    assert classify_stock(20.0, on_hand=40, demand=5, on_order=60) == "EXCESS"
    assert classify_stock(999.0, on_hand=0, demand=0, on_order=10) == "NO_DEMAND"
    assert classify_stock(999.0, on_hand=0, demand=0, on_order=0) == "DORMANT"


def test_planning_scope_is_yamaha_mc_and_obm_only() -> None:
    from src.inventory.stock import in_scope_skus

    master = pd.DataFrame({"active_sku_id": ["MC-1", "OB-1", "KT-1"], "brand": ["YM", "OB", "KT"]})
    assert in_scope_skus(master) == {"MC-1", "OB-1"}


def test_order_plan_joins_fleet_class_forecast_and_stock() -> None:
    from src.dashboard import order_plan

    base = {
        "description": "Part",
        "cycle_month": "2026-09",
        "expected_arrival": "2026-12",
        "policy": "RS",
        "abc_class": "A",
        "fsn": "F",
        "fill_target": 0.98,
        "ss": 10.0,
        "S": 50.0,
        "s": 30.0,
        "on_hand": 5.0,
        "on_order": 5.0,
        "ip": 10.0,
        "q_raw": 40.0,
        "eoq": 8.0,
        "unit_cost": 2.0,
        "recent_demand_6m": 60.0,
        "trigger_reason": "r",
    }
    proposal = pd.DataFrame(
        [
            {
                **base,
                "active_sku_id": "ORDER",
                "q_proposed": 40.0,
                "q_final": 40.0,
                "q_review": 0.0,
                "value": 80.0,
                "value_review": 0.0,
                "flags": "",
            },
            {
                **base,
                "active_sku_id": "HELD",
                "q_proposed": 40.0,
                "q_final": 0.0,
                "q_review": 40.0,
                "value": 0.0,
                "value_review": 80.0,
                "flags": "REVIEW",
            },
            {
                **base,
                "active_sku_id": "NONE",
                "q_proposed": 0.0,
                "q_final": 0.0,
                "q_review": 0.0,
                "value": 0.0,
                "value_review": 0.0,
                "flags": "",
            },
        ]
    )
    sku = pd.DataFrame(
        {
            "active_sku_id": ["ORDER", "HELD", "NONE"],
            "abc_source": "sales",
            "demand_category": "smooth",
            "mu_month_baseline": 10.0,
            "mu_month_parc": [6.0, None, None],
            "baseline_weight": [0.5, 1.0, 1.0],
            "forecast_m1": [8.0, 10.0, 10.0],
            "mu_p": 40.0,
        }
    )
    plan = order_plan.build(proposal, sku, None).set_index("active_sku_id")
    assert set(plan.index) == {"ORDER", "HELD"}  # nothing proposed, nothing listed
    assert plan.at["ORDER", "status"] == order_plan.STATUS_ORDER
    assert plan.at["HELD", "status"] == order_plan.STATUS_REVIEW
    assert plan.at["ORDER", "fleet_share"] == pytest.approx(0.5 * 6.0 / 8.0)
    assert plan.at["HELD", "fleet_share"] == 0.0
    assert (
        plan.at["ORDER", "target_level"] - plan.at["ORDER", "position"]
        == plan.at["ORDER", "gap_to_target"]
    )
