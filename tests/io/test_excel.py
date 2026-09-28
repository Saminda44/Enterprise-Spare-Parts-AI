"""Workbook conversion: read once, hash, skip when unchanged."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from src.core.errors import SourceDataError
from src.core.settings import get_settings
from src.io.excel import (
    coerce_for_parquet,
    read_source,
    source_vintage,
    workbook_to_parquet,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SPI_ROOT", str(tmp_path))
    get_settings.cache_clear()
    (tmp_path / "data" / "raw").mkdir(parents=True)
    yield tmp_path
    get_settings.cache_clear()


def _write_workbook(path: Path, frame: pd.DataFrame) -> Path:
    frame.to_excel(path, index=False, sheet_name="Sheet1")
    return path


def test_converts_then_skips_when_unchanged(workspace: Path) -> None:
    source = _write_workbook(
        workspace / "data" / "raw" / "orders.xlsx",
        pd.DataFrame({"Material": ["17540-53U01"], "Order Quantity (Item)": [4]}),
    )

    first = workbook_to_parquet(source)
    assert first.converted is True
    assert first.rows == 1
    assert first.columns == 2
    assert first.parquet.exists()
    assert first.parquet.parent == get_settings().source_parquet_dir
    assert not (source.parent / "orders.parquet").exists()

    second = workbook_to_parquet(source)
    assert second.converted is False, "unchanged hash means no re-read"
    assert second.sha256 == first.sha256


def test_changed_source_is_reconverted(workspace: Path) -> None:
    path = workspace / "data" / "raw" / "orders.xlsx"
    _write_workbook(path, pd.DataFrame({"Material": ["A"]}))
    first = workbook_to_parquet(path)

    _write_workbook(path, pd.DataFrame({"Material": ["A", "B"]}))
    second = workbook_to_parquet(path)

    assert second.converted is True
    assert second.sha256 != first.sha256
    assert second.rows == 2


def test_round_trip_preserves_the_frame(workspace: Path) -> None:
    frame = pd.DataFrame(
        {"Material": ["17540-53U01", "0NH9-28471-00"], "Confirmed Quantity (Item)": [4, 0]}
    )
    _write_workbook(workspace / "data" / "raw" / "orders.xlsx", frame)
    workbook_to_parquet(workspace / "data" / "raw" / "orders.xlsx")

    pd.testing.assert_frame_equal(read_source("orders"), frame)


def test_vintage_records_hash_rows_and_ingestion_time(workspace: Path) -> None:
    _write_workbook(workspace / "data" / "raw" / "orders.xlsx", pd.DataFrame({"a": [1, 2, 3]}))
    workbook_to_parquet(workspace / "data" / "raw" / "orders.xlsx")

    vintage = source_vintage("orders")

    assert vintage["rows"] == 3
    assert len(vintage["sha256"]) == 64
    assert vintage["source"] == "orders.xlsx"
    assert "ingested_at" in vintage


def test_missing_workbook_raises(workspace: Path) -> None:
    with pytest.raises(SourceDataError, match="not found"):
        workbook_to_parquet(workspace / "data" / "raw" / "absent.xlsx")


def test_mixed_type_column_is_coerced_to_text(workspace: Path) -> None:
    """Dealer Code arrives as 26198 on some rows and "26198" on others."""
    frame = pd.DataFrame({"Dealer Code": [26198, "26199", None], "qty": [1, 2, 3]})

    out, coerced = coerce_for_parquet(frame)

    assert coerced == ["Dealer Code"]
    assert out["Dealer Code"].tolist() == ["26198", "26199", None]
    assert out["qty"].tolist() == [1, 2, 3], "clean columns are left alone"


def test_coercion_does_not_turn_codes_into_floats() -> None:
    """A NaN in the column must not make 26198 into '26198.0'."""
    frame = pd.DataFrame({"code": [26198.0, "x", None]})

    out, _ = coerce_for_parquet(frame)

    assert out["code"].tolist() == ["26198", "x", None]


def test_coercion_does_not_mutate_its_input() -> None:
    frame = pd.DataFrame({"Dealer Code": [26198, "26199"]})
    coerce_for_parquet(frame)
    assert frame["Dealer Code"].tolist() == [26198, "26199"]


def test_mixed_type_workbook_converts_and_records_the_coercion(workspace: Path) -> None:
    path = workspace / "data" / "raw" / "dealers.xlsx"
    pd.DataFrame({"Dealer Code": [26198, "No Code"], "Type": ["MC", "OBM"]}).to_excel(
        path, index=False
    )

    result = workbook_to_parquet(path)

    assert result.coerced_to_text == ["Dealer Code"]
    assert source_vintage("dealers")["coerced_to_text"] == ["Dealer Code"]
    assert read_source("dealers")["Dealer Code"].tolist() == ["26198", "No Code"]


def test_named_sheet_gets_its_own_parquet(workspace: Path) -> None:
    path = workspace / "data" / "raw" / "Sales_Summery.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Year": [2025]}).to_excel(writer, sheet_name="All Years", index=False)
        pd.DataFrame({"Model": ["B2UG"]}).to_excel(
            writer, sheet_name="Model Classification", index=False
        )

    a = workbook_to_parquet(path, sheet="All Years")
    b = workbook_to_parquet(path, sheet="Model Classification")

    assert a.parquet.name == "sales_summery__all_years.parquet"
    assert b.parquet.name == "sales_summery__model_classification.parquet"
    assert a.parquet != b.parquet
