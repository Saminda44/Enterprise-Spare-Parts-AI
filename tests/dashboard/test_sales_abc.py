"""Synthetic contracts for billed-sales ABC publication."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from src.dashboard.sales_abc import build, sales_abc_classes


def test_sales_abc_value_bands_include_the_boundary_crossing_part() -> None:
    values = pd.Series([80.0, 15.0, 5.0], index=["A", "B", "C"])
    assert sales_abc_classes(values).to_dict() == {"A": "A", "B": "B", "C": "C"}
    assert sales_abc_classes(pd.Series([100.0], index=["ONLY"])).iloc[0] == "A"
    assert sales_abc_classes(pd.Series([100.0, -10.0], index=["SOLD", "RETURNED"])).to_dict() == {
        "SOLD": "A",
        "RETURNED": "C",
    }


def test_sales_links_resolve_supersession_and_leave_unevidenced_ambiguity() -> None:
    master = pd.DataFrame(
        [
            {"material": "OLD-1", "active_sku_id": "NEW-1", "description": "Shared chain"},
            {"material": "NEW-1", "active_sku_id": "NEW-1", "description": "Shared chain"},
            {"material": "ONLY-2", "active_sku_id": "ONLY-2", "description": "Unique label"},
            {"material": "AMB-3", "active_sku_id": "AMB-3", "description": "Generic label"},
            {"material": "AMB-4", "active_sku_id": "AMB-4", "description": "Generic label"},
        ]
    )
    sales = pd.DataFrame(
        [
            ("OLD-1", "Shared chain", "2026-08", 80.0, 1.0, False),
            (None, "  Unique  label ", "2026-08", 15.0, 1.0, False),
            (None, "Generic label", "2026-08", 5.0, 1.0, False),
            # A code naming no Part Master number is not evidence: the description decides.
            ("UNKNOWN", "Unique label", "2026-08", 7.0, 1.0, False),
            ("NEW-1", "Shared chain", "2025-08", 100.0, 1.0, False),
        ],
        columns=[
            "material_code",
            "material_description",
            "month",
            "Net Sales",
            "SlsVolQty",
            "is_return",
        ],
    )

    out, audit = build(master, sales, date(2026, 9, 1))
    assert set(out["active_sku_id"]) == {"NEW-1", "ONLY-2"}
    assert out.set_index("active_sku_id").at["NEW-1", "sales_net_lkr"] == 80.0
    assert out.set_index("active_sku_id").at["ONLY-2", "sales_net_lkr"] == 22.0
    assert audit.at[0, "window_start"] == "2025-09"
    assert audit.at[0, "window_end"] == "2026-08"
    assert audit.at[0, "sales_lines"] == 4
    assert audit.at[0, "code_linked_lines"] == 1
    assert audit.at[0, "description_linked_lines"] == 2
    assert audit.at[0, "unmapped_lines"] == 1
    assert audit.at[0, "ambiguous_lines"] == 1  # no order evidence for AMB-3 or AMB-4
    assert audit.at[0, "no_match_lines"] == 0
    assert audit.at[0, "active_skus"] == 2
    assert audit.at[0, "return_only_skus"] == 0


def test_ambiguous_descriptions_resolve_on_order_demand() -> None:
    master = pd.DataFrame(
        [
            {"material": m, "active_sku_id": m, "description": d}
            for m, d in (("ONE-A", "Bolt"), ("ONE-B", "Bolt"), ("TWO-A", "Belt"), ("TWO-B", "Belt"))
        ]
    )
    sales = pd.DataFrame(
        [
            (None, "Bolt", "2025-12", 100.0, 10.0, False),
            (None, "Belt", "2025-12", 100.0, 10.0, False),
        ],
        columns=[
            "material_code",
            "material_description",
            "month",
            "Net Sales",
            "SlsVolQty",
            "is_return",
        ],
    )
    # Only ONE-A was ordered; TWO-A and TWO-B were both ordered, 3:1.
    demand = pd.Series({"ONE-A": 5.0, "TWO-A": 30.0, "TWO-B": 10.0})
    out, audit = build(master, sales, date(2026, 9, 1), order_demand=demand)
    value = out.set_index("active_sku_id")["sales_net_lkr"]
    assert value["ONE-A"] == 100.0 and "ONE-B" not in value
    assert value["TWO-A"] == pytest.approx(75.0) and value["TWO-B"] == pytest.approx(25.0)
    assert audit.at[0, "demand_resolved_lines"] == 1
    assert audit.at[0, "demand_split_lines"] == 1
    assert out.set_index("active_sku_id").at["TWO-B", "sales_link"] == "demand_split"


def test_window_ends_at_last_billed_month_and_skips_other_brands() -> None:
    master = pd.DataFrame(
        [
            {
                "material": "Y-1",
                "active_sku_id": "Y-1",
                "description": "Yamaha part",
                "material_group": "AWPYM0001",
            }
        ]
    )
    sales = pd.DataFrame(
        [
            (None, "Yamaha part", "2025-12", 10.0, 1.0, False, "AWPYM0001"),
            (None, "Castrol oil", "2025-12", 900.0, 1.0, False, "AWLCA0011"),
        ],
        columns=[
            "material_code",
            "material_description",
            "month",
            "Net Sales",
            "SlsVolQty",
            "is_return",
            "Matl Group",
        ],
    )
    out, audit = build(master, sales, date(2026, 9, 1))
    assert (audit.at[0, "window_start"], audit.at[0, "window_end"]) == ("2025-01", "2025-12")
    assert out["active_sku_id"].tolist() == ["Y-1"]
    assert audit.at[0, "out_of_scope_lines"] == 1
    assert audit.at[0, "out_of_scope_value"] == 900.0


def test_returns_only_are_inactive_but_sales_with_net_returns_stay_active() -> None:
    master = pd.DataFrame(
        [
            {"material": "RET-1", "active_sku_id": "RET-1", "description": "Return only"},
            {"material": "SOLD-2", "active_sku_id": "SOLD-2", "description": "Sold then returned"},
        ]
    )
    sales = pd.DataFrame(
        [
            ("RET-1", "Return only", "2026-08", -20.0, -1.0, True),
            ("SOLD-2", "Sold then returned", "2026-08", 10.0, 1.0, False),
            ("SOLD-2", "Sold then returned", "2026-08", -20.0, -2.0, True),
        ],
        columns=[
            "material_code",
            "material_description",
            "month",
            "Net Sales",
            "SlsVolQty",
            "is_return",
        ],
    )

    out, audit = build(master, sales, date(2026, 9, 1))
    assert out["active_sku_id"].tolist() == ["SOLD-2"]
    assert out.iloc[0]["sales_abc"] == "C"
    assert out.iloc[0]["sales_net_lkr"] == -10.0
    assert audit.at[0, "linked_skus"] == 2
    assert audit.at[0, "active_skus"] == 1
    assert audit.at[0, "return_only_skus"] == 1


def test_no_billing_window_does_not_invent_sales_classifications() -> None:
    master = pd.DataFrame(
        [{"material": "SYN-1", "active_sku_id": "SYN-1", "description": "Sample part"}]
    )
    sales = pd.DataFrame(
        [
            {
                "material_code": "SYN-1",
                "material_description": "Sample part",
                "month": "2024-01",
                "Net Sales": 10.0,
                "SlsVolQty": 1.0,
                "is_return": False,
            }
        ]
    )
    out, audit = build(master, sales, date(2026, 9, 1))
    assert out.empty
    assert audit.at[0, "sales_lines"] == 0
    assert audit.at[0, "linked_skus"] == 0


def test_forecast_sales_check_flags_disagreement() -> None:
    from src.dashboard import forecast_check as fc

    history = pd.DataFrame(
        [
            ("AGREE", "2025-06", 10.0, 10.0, 0.0),
            ("ABOVE", "2025-06", 10.0, 10.0, 0.0),
            ("NOBILL", "2025-06", 10.0, 10.0, 0.0),
        ],
        columns=[
            "active_sku_id",
            "month",
            "ordered_quantity",
            "confirmed_quantity",
            "lost_quantity",
        ],
    )
    forecast = pd.DataFrame(
        {
            "active_sku_id": ["AGREE", "ABOVE", "NOBILL"],
            "mu_month": 1.0,
            "mu_month_baseline": 1.0,
            "mu_month_parc": None,
        }
    )
    sales = pd.DataFrame(
        [
            ("AGREE", 9.0, 90.0, "description"),
            ("ABOVE", 30.0, 300.0, "description"),
            ("90890-TOOL", 5.0, 50.0, "description"),
            ("OTHER-1", 4.0, 40.0, "description"),
        ],
        columns=["active_sku_id", "sales_qty", "sales_net_lkr", "sales_link"],
    )
    out = fc.build(forecast, history, sales, "2025-01", "2025-12").set_index("active_sku_id")
    assert out.at["AGREE", "check"] == fc.CONSISTENT
    assert out.at["ABOVE", "check"] == fc.BILLED_ABOVE
    assert out.at["NOBILL", "check"] == fc.ORDERED_NOT_BILLED
    assert out.at["90890-TOOL", "check"] == fc.SERVICE_TOOL
    assert out.at["OTHER-1", "check"] == fc.SOLD_NOT_ORDERED
