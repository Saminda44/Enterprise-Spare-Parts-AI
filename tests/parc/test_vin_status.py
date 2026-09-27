"""Step 09: a VIN is sold when its SlsVolQty sums to 1, returned when it sums to 0."""

from __future__ import annotations

import pandas as pd
from src.parc.unit_sales import classify_vins

VIN_A, VIN_B, VIN_C, VIN_D = (f"ME1TESTVIN0000{n:03d}" for n in range(1, 5))


def _rows() -> pd.DataFrame:
    rows = [
        # (vin, qty, month, model, net_sales)
        (VIN_A, 1, "2026-01", "B2UG", 100.0),  # plain sale
        (VIN_B, 1, "2026-01", "B2UG", 100.0),  # billed, reversed, re-billed
        (VIN_B, -1, "2026-02", "B2UG", -100.0),
        (VIN_B, 1, "2026-02", "B2UH", 110.0),
        (VIN_C, 1, "2026-03", "BGB8", 90.0),  # returned, not resold
        (VIN_C, -1, "2026-04", "BGB8", -90.0),
        (VIN_D, 1, "2026-03", "BGB8", 90.0),  # two sales, no reversal: sums to 2
        (VIN_D, 1, "2026-03", "BGB8", 90.0),
        ("0", 1, "2026-05", "B2UG", 50.0),  # placeholder VIN
        ("0", -1, "2026-05", "B2UG", -50.0),
    ]
    frame = pd.DataFrame(rows, columns=["vin", "qty", "month", "model_name", "net_sales"])
    frame["is_return"] = frame["qty"] < 0
    frame["cost"] = 0.0
    frame["dealer_name"] = "D1"
    return frame


def test_vin_status_follows_the_sum_of_slsvolqty() -> None:
    out = classify_vins(_rows()).set_index("vin")
    assert out.loc[VIN_A, "status"] == "sold"
    assert out.loc[VIN_B, "status"] == "sold"  # a re-billed reversal stays one sale
    assert out.loc[VIN_C, "status"] == "returned"
    assert out.loc[VIN_D, "status"] == "exception"  # sums to 2
    assert out.loc["0", "status"] == "no_vin"


def test_rebilled_vin_takes_the_invoice_that_stands() -> None:
    out = classify_vins(_rows()).set_index("vin")
    assert out.loc[VIN_B, "billing_reversals"] == 1
    assert out.loc[VIN_B, "model_name"] == "B2UH"  # the last sale row
    assert out.loc[VIN_B, "month"] == "2026-02"
    assert out.loc[VIN_B, "net_sales"] == 110.0  # every row netted


def test_model_name_is_the_commonest_spelling_and_labels_carry_the_code() -> None:
    from src.api.compat.bikes import model_label
    from src.dashboard.vehicles import model_names

    frame = pd.DataFrame(
        {
            "model_name": ["B1N2", "B1N2", "B1N2", "B626", "DR01"],
            "model_description": ["FZ FI V2", "FZ FI V2", "FZ-FI V2", "Ray ZR Disc", None],
        }
    )
    names = dict(zip(*model_names(frame).T.values, strict=True))
    assert names == {"B1N2": "FZ FI V2", "B626": "Ray ZR Disc"}
    assert model_label("B1N2", names) == "FZ FI V2 (B1N2)"
    assert model_label("DR01", names) == "DR01"  # no name recorded: the code alone
