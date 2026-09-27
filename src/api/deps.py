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
from src.io.parquet import Layer, read_table, table_age_hours, table_exists, table_path

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
    "unit_sales_by_model": "facts",
    "unit_sales_monthly": "facts",
    "unit_sales_by_province": "facts",
    "unit_sales_by_district": "facts",
    "unit_sales_by_rm": "facts",
    "unit_sales_by_ase": "facts",
    "unit_sales_by_dealer": "facts",
    "uio_age_histogram": "facts",
    "uio_totals_by_scenario": "facts",
    "survival_curves": "facts",
    "scenario_uio": "facts",
    "scenario_demand": "facts",
    "registration_forecast": "facts",
    "sku_classification": "facts",
    "fulfilment_stats": "facts",
    "fulfilment_by_po": "facts",
    "supply_reliability": "facts",
    "supply_reliability_monthly": "facts",
    "lead_time_stats": "facts",
    "returns_summary": "facts",
    "orders_by_material": "facts",
    "orders_by_dealer": "facts",
    "orders_by_rm": "facts",
    "orders_by_ase": "facts",
    "orders_by_province": "facts",
    "orders_by_district": "facts",
    "sales_by_material": "facts",
    "sales_by_dealer": "facts",
    "sales_by_rm": "facts",
    "sales_by_ase": "facts",
    "sales_by_province": "facts",
    "sales_by_district": "facts",
    "sales_monthly": "facts",
    "sales_kpis": "facts",
    "model_registry": "facts",
    "backtest_results": "facts",
    "lambda_curves": "facts",
    "holdout_split": "facts",
    "holdout_validation": "facts",
    "simulation_results": "facts",
    "stock_by_plant": "facts",
    "catalogue_layouts": "facts",
    "catalogue_parts": "facts",
    "model_colour_variants": "facts",
    "catalogue_exceptions": "facts",
    "order_exceptions": "facts",
    "part_master_enriched": "facts",
}


def load(name: str) -> pd.DataFrame:
    """Load a served table, cached until its file changes.

    Keyed on the file's modification time and size, so a pipeline run — from the CLI or
    a source refresh — is served on the next request without restarting the API.
    """
    layer = SERVED_TABLES.get(name)
    if layer is None:
        raise SourceDataError(f"{name!r} is not a served table")
    try:
        stamp = table_path(layer, name).stat()
        version = (stamp.st_mtime_ns, stamp.st_size)
    except OSError:
        version = (0, 0)
    return _load(name, layer, version)


@lru_cache(maxsize=64)
def _load(name: str, layer: Layer, version: tuple[int, int]) -> pd.DataFrame:
    return read_table(layer, name)


def clear_cache() -> None:
    _load.cache_clear()
    from src.api.compat.filters import clear_cache as clear_ui_cache

    clear_ui_cache()


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
