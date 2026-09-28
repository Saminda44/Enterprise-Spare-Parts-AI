"""sales.xlsx Material: descriptions with double spaces are not code + label."""

from __future__ import annotations

import pandas as pd
from src.demand.sales import material_code_and_description


def test_double_spaced_description_stays_whole() -> None:
    material = pd.Series(["SEAL VALVE STEM  YAM 2GS2", "5VL-F341E-00  BRAKE PAD", "V-BELT"])
    codes, descriptions = material_code_and_description(material, {"5VLF341E00"})
    assert codes.tolist() == [None, "5VL-F341E-00", None]
    assert descriptions.tolist() == ["SEAL VALVE STEM YAM 2GS2", "BRAKE PAD", "V-BELT"]


def test_exact_duplicate_billing_lines_are_removed_once() -> None:
    from src.demand.sales import drop_duplicate_billing_lines

    row = {"Billing Document": 1.0, "Item": 10.0, "SlsVolQty": 2.0, "Net Sales_1": 50.0}
    other = {**row, "Item": 20.0}
    frame = pd.DataFrame([row, row, other])
    kept, removed, value = drop_duplicate_billing_lines(frame)
    assert (len(kept), removed) == (2, 1)
    assert value == 50.0
