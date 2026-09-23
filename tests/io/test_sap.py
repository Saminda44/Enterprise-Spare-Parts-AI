"""The glued-column parser, against the five patterns verified in the real exports."""

from __future__ import annotations

import pandas as pd
import pytest
from src.core.errors import SourceDataError
from src.io.sap import (
    GLUED_COLUMNS,
    GluedColumn,
    split_code_label,
    split_columns,
    split_for_source,
)

# The five patterns quoted in Step 00, copied verbatim from the source files.
VERIFIED = [
    ("26198      Yamaha Sales Center", "26198", "Yamaha Sales Center"),
    (
        "676-42115-00       SHAFT STEERING YAMAHA 40 HP",
        "676-42115-00",
        "SHAFT STEERING YAMAHA 40 HP",
    ),
    ("2501 Associated Motorways", "2501", "Associated Motorways"),
    ("W1B1 Seeduwa - PDC", "W1B1", "Seeduwa - PDC"),
    ("00171976 Arosha Edirisinghe", "00171976", "Arosha Edirisinghe"),
]


@pytest.mark.parametrize(("raw", "code", "label"), VERIFIED)
def test_five_verified_patterns(raw: str, code: str, label: str) -> None:
    assert split_code_label(raw) == (code, label)


def test_leading_zeros_survive() -> None:
    """00171976 must stay a string — as an int it would never match the master."""
    parsed_code, _ = split_code_label("00171976 Arosha Edirisinghe")
    assert parsed_code == "00171976"


@pytest.mark.parametrize(
    "raw",
    ["17540-53U01", "0NH9-28471-00", "5VL-F341E-00"],
)
def test_bare_part_number_is_a_code_with_no_label(raw: str) -> None:
    """orders.xlsx Material is a bare part number: a code, never a label."""
    assert split_code_label(raw) == (raw, None)


@pytest.mark.parametrize(
    "raw",
    ["Yamaha Sales Center", "SHAFT STEERING", "No Code"],
)
def test_plain_text_yields_no_code(raw: str) -> None:
    """MCSI Payer holds a retail customer name — it must not produce a dealer code."""
    assert split_code_label(raw) == (None, raw)


@pytest.mark.parametrize("raw", [None, "", "   ", float("nan"), "nan"])
def test_empty_input_is_two_nones(raw: object) -> None:
    assert split_code_label(raw) == (None, None)


def test_label_may_itself_contain_spaces_and_dashes() -> None:
    assert split_code_label("W1B4  Seeduwa - PDC-Parts") == ("W1B4", "Seeduwa - PDC-Parts")


# ── applying the map ────────────────────────────────────────────────────────────
def test_split_columns_adds_code_and_label_and_keeps_raw() -> None:
    df = pd.DataFrame({"Payer": ["26198      Yamaha Sales Center", "No Code"]})
    out = split_columns(df, [GluedColumn("Payer", "payer_code", "payer_name")])

    assert list(out["payer_code"]) == ["26198", None]
    assert list(out["payer_name"]) == ["Yamaha Sales Center", "No Code"]
    assert "Payer" in out.columns, "raw column kept for audit"


def test_split_columns_does_not_mutate_its_input() -> None:
    df = pd.DataFrame({"Payer": ["26198      Yamaha Sales Center"]})
    before = list(df.columns)
    split_columns(df, [GluedColumn("Payer", "payer_code", "payer_name")])
    assert list(df.columns) == before


def test_missing_declared_column_raises() -> None:
    df = pd.DataFrame({"Something Else": ["x"]})
    with pytest.raises(SourceDataError, match="Payer"):
        split_columns(df, [GluedColumn("Payer", "payer_code", "payer_name")])


def test_orders_is_declared_not_glued_and_is_a_no_op() -> None:
    """orders.xlsx carries separate Sold-to Party / Sold-To Party Name — nothing to split."""
    assert GLUED_COLUMNS["orders.xlsx"] == ()

    df = pd.DataFrame(
        {
            "Sold-to Party": [26198, 26199],
            "Sold-To Party Name": ["Yamaha Sales Center", "Another Dealer"],
            "Material": ["17540-53U01", "0NH9-28471-00"],
        }
    )
    out = split_for_source(df, "orders.xlsx")

    pd.testing.assert_frame_equal(out, df)


def test_undeclared_source_raises_rather_than_splitting_nothing() -> None:
    with pytest.raises(SourceDataError, match="no glued-column map"):
        split_for_source(pd.DataFrame({"Payer": ["x"]}), "mystery.xlsx")


def test_mcsi_payer_is_deliberately_not_split() -> None:
    """It is a retail customer name; joining it to dealers.xlsx would be wrong."""
    assert all(spec.source != "Payer" for spec in GLUED_COLUMNS["MCSI.xlsx"])
