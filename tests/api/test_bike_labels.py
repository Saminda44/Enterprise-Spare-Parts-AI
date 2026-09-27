"""Motorcycle pages label every model "Name (Code)"; filters accept either form."""

from __future__ import annotations

import pandas as pd
from src.api.compat.bikes import combo_label, model_code_for, model_label
from src.core.result import StageResult
from src.dashboard.vehicles import active_model_codes, fill_blank_model_names

NAMES = {"B1N2": "FZ FI V2", "Unknown": "FASINO S 125", "ZZ99": "(blank)"}


def test_label_is_name_then_code() -> None:
    assert model_label("B1N2", NAMES) == "FZ FI V2 (B1N2)"


def test_unnamed_or_blank_named_code_stays_a_code() -> None:
    assert model_label("QQ11", NAMES) == "QQ11"
    assert model_label("ZZ99", NAMES) == "ZZ99"


def test_named_model_without_a_code() -> None:
    assert model_label("Unknown", NAMES) == "FASINO S 125 (no code)"


def test_combo_labels_only_the_model_part() -> None:
    assert combo_label("B1N2 – BLACK METALLIC X", NAMES) == "FZ FI V2 (B1N2) – BLACK METALLIC X"


def test_filter_value_resolves_label_or_code() -> None:
    assert model_code_for("FZ FI V2 (B1N2)", NAMES) == "B1N2"
    assert model_code_for("B1N2", NAMES) == "B1N2"
    assert model_code_for("nothing like it", NAMES) == "nothing like it"


def test_blank_parc_names_filled_from_classification() -> None:
    matrix = pd.DataFrame(
        {
            "model_code": ["2GS2", "2NC1", "1CK4", "9XX9"],
            "model_name": ["(blank)"] * 2 + ["ALPHA", "(blank)"],
        }
    )
    classification = pd.DataFrame(
        {
            "Model": ["2GS2", "2GS2", "2NC1"],
            "Model Name": ["FZ-S VER 2.0", "FZ-S VER 2.0 - FI", "RAY Z"],
        }
    )
    result = StageResult(stage="test")
    out = fill_blank_model_names(matrix, classification, result)
    assert out["model_name"].tolist() == ["FZ-S VER 2.0 - FI", "RAY Z", "ALPHA", "(blank)"]
    assert matrix["model_name"].tolist()[0] == "(blank)"  # input not mutated
    assert any("9XX9" in w for w in result.warnings)


def test_active_models_from_classification_status() -> None:
    classification = pd.DataFrame(
        {
            "Model": ["B1N2", "1CK4", " BST1 ", "2GS2"],
            "Status": ["Active", "Inactive", "active", "(blank)"],
        }
    )
    assert active_model_codes(classification) == {"B1N2", "BST1"}
