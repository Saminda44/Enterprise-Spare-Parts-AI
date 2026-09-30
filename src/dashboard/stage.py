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
from src.dashboard import eda, forecast_check, order_plan, sales_abc, sku, vehicles
from src.dashboard.compatibility import service_plan, validate_output
from src.dashboard.segments import SEGMENT_MC, part_category, sku_segments
from src.io.parquet import read_table, table_exists, write_table


@REGISTRY.register(
    "15_dashboard",
    depends_on=["04_sales", "14_monthly_order", "09_unit_sales", "10_uio_cohorts", "11_targets"],
    description="legacy-dashboard marts: per-SKU table, EDA cuts, motorcycle and parc series",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="15_dashboard")
    written: dict[str, pd.DataFrame] = {}

    per_sku = sku.build(ctx, result)
    written["mart_ui_sku"] = per_sku
    from_step06 = sales_abc.published()
    if from_step06 is None:
        result.warn("Step 06 sales classes not published — linking sales directly for the UI")
        from_step06 = sales_abc.build(
            read_table("facts", "part_master_enriched"),
            read_table("facts", "parts_sales"),
            ctx.as_of,
        )
    billed_abc, billed_audit = from_step06
    written["mart_ui_part_master_analysis"] = sku.build_part_master_analysis(per_sku, billed_abc)
    written["mart_ui_sales_abc_audit"] = billed_audit
    if table_exists("facts", "forecast_live") and not billed_audit.empty:
        check = forecast_check.build(
            read_table("facts", "forecast_live"),
            read_table("facts", "demand_history"),
            billed_abc,
            str(billed_audit.at[0, "window_start"]),
            str(billed_audit.at[0, "window_end"]),
        )
        check["segment"] = (
            check["active_sku_id"]
            .map(sku_segments(read_table("facts", "part_master")))
            .fillna(SEGMENT_MC)
        )
        categories = per_sku.set_index("active_sku_id")["part_category"]
        check["part_category"] = (
            check["active_sku_id"]
            .map(categories)
            .fillna(
                part_category(
                    check["active_sku_id"].map(
                        read_table("facts", "part_master")
                        .drop_duplicates("active_sku_id")
                        .set_index("active_sku_id")["description"]
                    ),
                    check["segment"],
                )
            )
        )
        written["mart_ui_forecast_sales_check"] = check
        result.warn(
            f"forecast-vs-sales check {billed_audit.at[0, 'window_start']}.."
            f"{billed_audit.at[0, 'window_end']}: {check['check'].value_counts().to_dict()}"
        )
    missing = int(
        (written["mart_ui_part_master_analysis"]["description"] == sku.MISSING_DESCRIPTION).sum()
    )
    if missing:
        result.warn(
            f"part master: {missing:,} SKU(s) have no description on any number in PN_Yamaha — "
            f"published labelled {sku.MISSING_DESCRIPTION!r}, not dropped"
        )
    result.warn(
        f"sales ABC: {len(billed_abc):,} active SKUs from "
        f"{int(billed_audit.at[0, 'sales_lines']):,} billed lines; "
        f"{int(billed_audit.at[0, 'unmapped_lines']):,} in-scope lines unattributed, "
        f"{int(billed_audit.at[0, 'out_of_scope_lines']):,} out of scope; "
        f"{int(billed_audit.at[0, 'return_only_skus']):,} linked SKUs have returns only"
    )
    written["mart_ui_service_plan"] = service_plan(per_sku)
    written["mart_ui_order_plan"] = order_plan.build(
        read_table("facts", "monthly_order_proposal"),
        per_sku,
        read_table("facts", "part_behaviour") if table_exists("facts", "part_behaviour") else None,
    )
    plan = written["mart_ui_order_plan"]
    result.warn(
        f"order plan: {int((plan['status'] == order_plan.STATUS_ORDER).sum()):,} lines to order "
        f"({plan['value'].sum():,.0f} LKR), "
        f"{int((plan['status'] == order_plan.STATUS_REVIEW).sum()):,} held for review "
        f"({plan['value_review'].sum():,.0f} LKR)"
    )
    written["mart_ui_overview"] = sku.overview(per_sku, result)

    written.update(eda.build_orders(result))
    written.update(eda.build_sales(result))
    written.update(vehicles.build_mcsi(result))
    written.update(vehicles.build_sales_forecast(result))
    written.update(vehicles.build_model_price(result))
    written.update(vehicles.build_buyer_age(result))
    written.update(vehicles.build_vehicle_lookup(result))
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
