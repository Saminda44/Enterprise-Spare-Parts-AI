"""Layer access: staging, facts and marts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from src.core.errors import SourceDataError
from src.core.settings import get_settings
from src.io.parquet import (
    read_table,
    table_age_hours,
    table_exists,
    table_path,
    write_table,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SPI_ROOT", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    yield tmp_path
    get_settings.cache_clear()


def test_write_then_read_round_trips(workspace: Path) -> None:
    frame = pd.DataFrame({"active_sku_id": ["5VL-F341E-10"], "on_hand": [42]})

    path = write_table(frame, "facts", "stock_position")

    assert path == table_path("facts", "stock_position")
    assert table_exists("facts", "stock_position")
    pd.testing.assert_frame_equal(read_table("facts", "stock_position"), frame)


def test_layers_are_separate_directories(workspace: Path) -> None:
    write_table(pd.DataFrame({"a": [1]}), "staging", "x")
    write_table(pd.DataFrame({"a": [2]}), "marts", "x")

    assert read_table("staging", "x")["a"].tolist() == [1]
    assert read_table("marts", "x")["a"].tolist() == [2]


def test_reading_a_missing_table_raises(workspace: Path) -> None:
    with pytest.raises(SourceDataError, match="run its stage first"):
        read_table("marts", "never_built")


def test_unknown_layer_is_rejected(workspace: Path) -> None:
    with pytest.raises(ValueError, match="unknown layer"):
        table_path("nowhere", "x")  # type: ignore[arg-type]


def test_age_is_none_when_absent_and_small_when_fresh(workspace: Path) -> None:
    assert table_age_hours("marts", "absent") is None

    write_table(pd.DataFrame({"a": [1]}), "marts", "fresh")
    age = table_age_hours("marts", "fresh")

    assert age is not None
    assert age < 1
