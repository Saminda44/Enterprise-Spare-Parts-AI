"""Synthetic upload merge contracts; no distributor records are used."""

from __future__ import annotations

import pandas as pd
import pytest
from src.core.errors import SourceDataError
from src.ingestion.merge import merge_upload, next_on_order_month

#: A supersession chain OLD -> MID -> NEW, as PN_Yamaha writes it.
PN = pd.DataFrame(
    [
        {"Material": "OLD", "Latest SS": "NEW", "1st Supersede": "MID", "2nd Supersede": "NEW"},
        {"Material": "MID", "Latest SS": "NEW", "1st Supersede": "NEW", "2nd Supersede": None},
        {"Material": "NEW", "Latest SS": "NEW", "1st Supersede": None, "2nd Supersede": None},
        {"Material": "P2", "Latest SS": "P2", "1st Supersede": None, "2nd Supersede": None},
    ]
)


def test_history_appends_new_lines_and_holds_changed_document_item() -> None:
    old = pd.DataFrame({"Billing Document": [1, 1], "Item": [1, 2], "SlsVolQty": [2, 3]})
    upload = pd.DataFrame(
        {"Billing Document": [1, 1, 2], "Item": [1, 2, 1], "SlsVolQty": [2, 4, 5]}
    )
    result = merge_upload("sales.xlsx", old, upload)
    assert (result.added, result.unchanged, result.conflicts) == (1, 1, 1)
    assert len(result.frame) == 3
    assert result.frame.loc[result.frame["Billing Document"] == 1, "SlsVolQty"].tolist() == [2, 3]


def _stock(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Material", "Plant", "Storage Location", "Unrestricted"])


def test_stock_updates_matched_rows_and_keeps_the_rest() -> None:
    old = _stock([("OLD", "W1B4", "MAIN", 5), ("P2", "W1B4", "MAIN", 3)])
    upload = _stock([("OLD", "W1B4", "MAIN", 8), ("P9", "W1B4", "MAIN", 4)])
    result = merge_upload("current_stock.xlsx", old, upload, pn_yamaha=PN)
    stock = dict(zip(result.frame["Material"], result.frame["Unrestricted"], strict=True))
    assert stock == {"OLD": 8, "P2": 3, "P9": 4}  # P2 not in upload: kept; P9: appended
    assert (result.replaced, result.added, result.conflicts) == (1, 1, 0)


def test_stock_matches_a_new_number_to_its_chain_row_at_the_same_location() -> None:
    old = _stock([("OLD", "W1B4", "MAIN", 5), ("OLD", "W1B4", "BRANCH", 2)])
    upload = _stock([("NEW", "W1B4", "MAIN", 9)])
    result = merge_upload("current_stock.xlsx", old, upload, pn_yamaha=PN)
    assert result.frame["Unrestricted"].tolist() == [9, 2]
    assert len(result.frame) == 2 and "through their Latest SS" in result.notes[0]


def test_stock_location_codes_match_however_excel_typed_them() -> None:
    old = _stock([("OLD", "W1B4", "0001", 5)])
    upload = pd.DataFrame(
        {"Material": ["OLD"], "Plant": ["W1B4"], "Storage Location": [1], "Unrestricted": [7]}
    )
    result = merge_upload("current_stock.xlsx", old, upload, pn_yamaha=PN)
    assert result.frame["Unrestricted"].tolist() == [7] and result.added == 0


def test_stock_exact_match_wins_and_rejects_repeated_keys() -> None:
    old = _stock([("OLD", "W1B4", "MAIN", 5)])
    upload = _stock([("OLD", "W1B4", "MAIN", 6), ("NEW", "W1B4", "MAIN", 1)])
    result = merge_upload("current_stock.xlsx", old, upload, pn_yamaha=PN)
    # OLD keeps its own row; NEW cannot take a claimed row, so it is a new row.
    assert result.frame.set_index("Material")["Unrestricted"].to_dict() == {"OLD": 6, "NEW": 1}
    with pytest.raises(SourceDataError, match="repeats"):
        merge_upload("current_stock.xlsx", old, pd.concat([upload, upload]), pn_yamaha=PN)


def test_on_orders_quantity_becomes_the_next_month_column() -> None:
    old = pd.DataFrame(
        {
            "Material": ["OLD", "P2"],
            "Latest SS": ["NEW", "P2"],
            "Nov 2027": [4, 0],
            "Dec 2027": [2, 1],
        }
    )
    upload = pd.DataFrame({"Material": ["NEW", "P2", "P2", "P9"], "Quantity": [10, 3, 2, 7]})
    assert next_on_order_month(old) == "Jan 2028"
    result = merge_upload("On_Orders.xlsx", old, upload, pn_yamaha=PN)
    frame = result.frame.set_index("Material")
    assert list(result.frame.columns)[-1] == "Jan 2028"
    assert frame.loc["OLD", "Jan 2028"] == 10  # NEW matched OLD's row through Latest SS
    assert frame.loc["P2", "Jan 2028"] == 5  # two P2 lines summed
    assert frame.loc["P9", "Jan 2028"] == 7  # new material appended
    assert frame.loc["OLD", "Dec 2027"] == 2  # earlier months untouched
    assert result.notes[0].endswith("Jan 2028")


def test_on_orders_needs_one_quantity_column() -> None:
    old = pd.DataFrame({"Material": ["P2"], "Dec 2027": [1]})
    with pytest.raises(SourceDataError, match="quantity column"):
        merge_upload("On_Orders.xlsx", old, pd.DataFrame({"Material": ["P2"], "Amount": [1]}))


def test_dealer_change_is_held_until_explicitly_replaced() -> None:
    old = pd.DataFrame({"Dealer Code": ["D1"], "Dealer Name": ["Synthetic One"], "Province": ["A"]})
    new = old.assign(Province=["B"])
    held = merge_upload("dealers.xlsx", old, new)
    assert held.conflicts == 1 and held.frame["Province"].tolist() == ["A"]
    replaced = merge_upload("dealers.xlsx", old, new, replace_dealers=True)
    assert replaced.replaced == 1 and replaced.frame["Province"].tolist() == ["B"]


def test_pn_new_supersede_goes_to_the_next_empty_column_and_the_chain_follows() -> None:
    result = merge_upload(
        "PN_Yamaha.xlsx", PN, pd.DataFrame([{"Material": "NEW", "New Supersede": "NEWER"}])
    )
    frame = result.frame.set_index("Material")
    assert frame.loc["NEW", "1st Supersede"] == "NEWER"
    assert frame.loc["MID", "2nd Supersede"] == "NEWER"  # older numbers extended too
    assert frame.loc["OLD", "3rd Supersede"] == "NEWER"  # a column added when full
    assert frame.loc["OLD", "1st Supersede"] == "MID"  # history never overwritten
    assert set(frame["Latest SS"].loc[["OLD", "MID", "NEW"]]) == {"NEWER"}
    assert result.replaced == 3


def test_pn_appends_new_materials_and_ignores_known_numbers() -> None:
    upload = pd.DataFrame(
        [
            {"Material": "P5", "Material description": "SYNTHETIC BOLT", "New Supersede": None},
            {"Material": "MID", "New Supersede": "NEW"},  # already in its chain
        ]
    )
    result = merge_upload("PN_Yamaha.xlsx", PN, upload)
    frame = result.frame.set_index("Material")
    assert frame.loc["P5", "Latest SS"] == "P5"
    assert (result.added, result.replaced, result.unchanged) == (1, 0, 1)


def test_pn_rejects_new_cycle() -> None:
    old = pd.DataFrame([{"Material": "OLD", "Latest SS": "MID", "1st Supersede": "MID"}])
    with pytest.raises(SourceDataError, match="cycle"):
        merge_upload(
            "PN_Yamaha.xlsx", old, pd.DataFrame([{"Material": "MID", "1st Supersede": "OLD"}])
        )
