"""Mart loading and caching.

The API serves published tables. It computes nothing: every number it returns was
computed in a step, tested, and written to a table. A figure derived in a request
handler is a figure nobody can reproduce.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd
from src.core.errors import SourceDataError
from src.io.parquet import Layer, read_table, table_age_hours, table_exists

#: Tables the service exposes, and the layer each lives in.
SERVED_TABLES: dict[str, Layer] = {
    "mart_monthly_order": "marts",
    "mart_policy_summary": "marts",
    "mart_service_and_stock": "marts",
    "mart_forecast_accuracy": "marts",
    "mart_exceptions": "marts",
    "part_master": "facts",
    "demand_history": "facts",
    "forecast_protection": "facts",
    "uio_age_matrix": "facts",
    "stock_position": "facts",
    "policy_params": "facts",
    "policy_selection": "facts",
    "monthly_order_proposal": "facts",
    "scenarios": "facts",
    "supersession_chains": "facts",
}


@lru_cache(maxsize=32)
def load(name: str) -> pd.DataFrame:
    """Load a served table, cached for the process lifetime."""
    layer = SERVED_TABLES.get(name)
    if layer is None:
        raise SourceDataError(f"{name!r} is not a served table")
    return read_table(layer, name)


def clear_cache() -> None:
    load.cache_clear()


def freshness() -> list[dict[str, Any]]:
    """Age of every served table, so a stale pipeline is visible rather than silently
    serving last month's numbers."""
    rows: list[dict[str, Any]] = []
    for name, layer in SERVED_TABLES.items():
        exists = table_exists(layer, name)
        rows.append(
            {
                "table": name,
                "layer": layer,
                "present": exists,
                "age_hours": round(table_age_hours(layer, name) or 0.0, 2) if exists else None,
            }
        )
    return rows


def paginate(frame: pd.DataFrame, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Anything that can return 30,000 rows is paginated."""
    total = len(frame)
    page = frame.iloc[offset : offset + limit]
    return page.replace({pd.NA: None}).where(pd.notna(page), None).to_dict("records"), total
