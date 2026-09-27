"""Source refresh: which stages go stale, and the cycle date the data implies."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
import src.refresh as refresh
from src.core.registry import REGISTRY
from src.stages import load_stages


@pytest.fixture(scope="module", autouse=True)
def _stages() -> None:
    if not REGISTRY.stages:
        load_stages()


def test_every_watched_workbook_maps_to_real_stages() -> None:
    assert set(refresh.SOURCE_STAGES) == set(refresh.SOURCE_WORKBOOKS)
    for stages in refresh.SOURCE_STAGES.values():
        for stage in stages:
            assert stage in REGISTRY.stages


def test_orders_change_reruns_its_downstream_only() -> None:
    stale = REGISTRY.downstream(refresh.SOURCE_STAGES["orders.xlsx"])
    assert {"03_orders", "05_order_analysis", "08_forecast", "13_policy", "15_dashboard"} <= stale
    assert not stale & {"01_catalogue", "02_part_master", "04_sales", "09_unit_sales", "12_stock"}


def test_mcsi_change_starts_at_unit_sales() -> None:
    stale = REGISTRY.downstream(refresh.SOURCE_STAGES["MCSI.xlsx"])
    assert {"09_unit_sales", "10_uio_cohorts", "11_targets", "15_dashboard"} <= stale
    assert "03_orders" not in stale


@pytest.mark.parametrize(
    ("last", "cycle"),
    [
        ("2026-08-31", date(2026, 9, 1)),  # complete month: the next one is the cycle
        ("2026-09-15", date(2026, 9, 1)),  # part month: not treated as closed
        ("2025-12-31", date(2026, 1, 1)),
    ],
)
def test_cycle_date_from_order_history(
    monkeypatch: pytest.MonkeyPatch, last: str, cycle: date
) -> None:
    frame = pd.DataFrame({refresh.ORDER_DATE_COLUMN: ["2024-01-02", last]})
    monkeypatch.setattr("src.io.excel.read_source", lambda name, **_: frame)
    assert refresh.data_cycle_date() == cycle


def test_watcher_waits_for_the_save_to_settle(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed workbook triggers one refresh, only after it stops changing."""
    import os
    import threading
    import time
    from types import SimpleNamespace

    for name in refresh.SOURCE_WORKBOOKS:
        (tmp_path / name).write_bytes(b"v1")
    settings = SimpleNamespace(
        raw_dir=tmp_path, source_poll_seconds=0.05, source_settle_seconds=0.2
    )
    monkeypatch.setattr(refresh, "get_settings", lambda: settings)
    calls: list[str] = []
    monkeypatch.setattr(refresh, "refresh", lambda reason, **_: calls.append(reason) or {})

    stop = threading.Event()
    watcher = threading.Thread(target=refresh._watch, args=(stop,), daemon=True)
    watcher.start()
    time.sleep(0.15)
    assert calls == ["startup check"]

    target = tmp_path / "orders.xlsx"
    for i in range(3):  # Excel writing in pieces: each write moves the mtime
        target.write_bytes(b"v2" * (i + 1))
        os.utime(target, ns=(time.time_ns(), time.time_ns() + i))
        time.sleep(0.06)
    assert calls == ["startup check"]  # still settling
    time.sleep(0.6)
    stop.set()
    watcher.join(timeout=2)
    assert calls == ["startup check", "orders.xlsx changed"]
