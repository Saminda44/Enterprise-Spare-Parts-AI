"""Step 15b — publish the marts the dashboard reads.

This runs after the monthly order so it can see every published fact, and it exists so
that the ``/api/v1`` contract the React dashboard speaks is satisfied by *published
tables*. Nothing in a request handler computes a KPI, a bucket or a share: if the UI
shows a number, a stage wrote it.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.dashboard import eda, sku, vehicles
from src.dashboard.compatibility import service_plan, validate_output
from src.io.parquet import write_table


@REGISTRY.register(
    "15_dashboard",
    depends_on=["14_monthly_order", "09_unit_sales", "10_uio_cohorts", "11_targets"],
    description="legacy-dashboard marts: per-SKU table, EDA cuts, motorcycle and parc series",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="15_dashboard")
    written: dict[str, pd.DataFrame] = {}

    per_sku = sku.build(ctx, result)
    written["mart_ui_sku"] = per_sku
    written["mart_ui_service_plan"] = service_plan(per_sku)
    written["mart_ui_overview"] = sku.overview(per_sku, result)

    written.update(eda.build_orders(result))
    written.update(eda.build_sales(result))
    written.update(vehicles.build_mcsi(result))
    written.update(vehicles.build_sales_forecast(result))
    written.update(vehicles.build_parc(result))
    written.update(vehicles.build_uio_snapshot(result))

    result.rows_in = len(per_sku)
    rows_out = 0
    for name, frame in written.items():
        validate_output(frame, name)
        result.artifact(name, write_table(frame, "marts", name))
        rows_out += len(frame)
    result.rows_out = rows_out

    logger.info(f"dashboard: {len(written)} mart(s), {rows_out:,} row(s)")
    return result
