"""Synthetic upload merge contracts; no distributor records are used."""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.errors import SourceDataError
from src.ingestion.merge import merge_upload


def test_history_appends_new_lines_and_holds_changed_document_item() -> None:
    old = pd.DataFrame(
        {"Billing Document": [1, 1], "Item": [1, 2], "SlsVolQty": [2, 3]}
    )
    upload = pd.DataFrame(
        {"Billing Document": [1, 1, 2], "Item": [1, 2, 1], "SlsVolQty": [2, 4, 5]}
    )
    result = merge_upload("sales.xlsx", old, upload)
    assert (result.added, result.unchanged, result.conflicts) == (1, 1, 1)
    assert len(result.frame) == 3
    assert result.frame.loc[result.frame["Billing Document"] == 1, "SlsVolQty"].tolist() == [2, 3]


def test_stock_requires_a_complete_unambiguous_snapshot() -> None:
    old = pd.DataFrame(
        {"Material": ["P1"], "Plant": ["W1B4"], "Storage Location": ["MAIN"], "Unrestricted": [5]}
    )
    new = old.assign(Unrestricted=[8])
    result = merge_upload("current_stock.xlsx", old, new)
    assert result.frame["Unrestricted"].tolist() == [8]
    with pytest.raises(SourceDataError, match="duplicate"):
        merge_upload("current_stock.xlsx", old, pd.concat([new, new], ignore_index=True))


def test_open_orders_are_replaced_by_arrival_month() -> None:
    old = pd.DataFrame({"Material": ["P1"], "Sep 2026": [4], "Oct 2026": [2]})
    new = pd.DataFrame({"Material": ["P1"], "Oct 2026": [1], "Nov 2026": [5]})
    result = merge_upload("On_Orders.xlsx", old, new)
    assert list(result.frame.columns) == ["Material", "Oct 2026", "Nov 2026"]
    assert result.frame["Nov 2026"].tolist() == [5]


def test_dealer_change_is_held_until_explicitly_replaced() -> None:
    old = pd.DataFrame({"Dealer Code": ["D1"], "Dealer Name": ["Synthetic One"], "Province": ["A"]})
    new = old.assign(Province=["B"])
    held = merge_upload("dealers.xlsx", old, new)
    assert held.conflicts == 1 and held.frame["Province"].tolist() == ["A"]
    replaced = merge_upload("dealers.xlsx", old, new, replace_dealers=True)
    assert replaced.replaced == 1 and replaced.frame["Province"].tolist() == ["B"]


def test_pn_new_supersede_column_sets_latest_ss() -> None:
    old = pd.DataFrame(
        [{"Material": "OLD", "Latest SS": "MID", "1st Supersede": "MID", "10th Supersede": None}]
    )
    uploaded = pd.DataFrame([{"Material": "OLD", "11th Supersede": "NEW"}])
    result = merge_upload("PN_Yamaha.xlsx", old, uploaded)
    assert result.frame.at[0, "Latest SS"] == "NEW"
    assert result.frame.at[0, "11th Supersede"] == "NEW"


def test_pn_rejects_new_cycle_but_preserves_existing_latest() -> None:
    old = pd.DataFrame(
        [{"Material": "OLD", "Latest SS": "MID", "1st Supersede": "MID"}]
    )
    with pytest.raises(SourceDataError, match="cycle"):
        merge_upload("PN_Yamaha.xlsx", old, pd.DataFrame([{"Material": "MID", "1st Supersede": "OLD"}]))
