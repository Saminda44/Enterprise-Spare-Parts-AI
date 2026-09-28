"""Published compatibility calculations for the existing dashboard."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

from src.core.contracts import validate

SERVICE_HORIZONS = range(1, 25)


def service_plan(sku: pd.DataFrame) -> pd.DataFrame:
    """Publish the existing horizon comparison without introducing a second policy.

    Business meaning: fleet demand is the parc estimate only where available; the
    recommended purchase remains the validated monthly policy's final quantity.
    """
    frames = []
    for horizon in SERVICE_HORIZONS:
        frame = sku.loc[sku["mu_month_parc"].notna()].copy()
        frame["horizon_months"] = horizon
        frame["service_plan_qty"] = frame["mu_month_parc"] * horizon
        frame["recommended_order"] = frame["roq"]
        frame["delta_vs_roq"] = 0.0
        frame["service_value"] = frame["value"]
        frame["rule_value"] = frame["value"]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def validate_output(frame: pd.DataFrame, name: str) -> None:
    """Enforce the required identity and measures at the UI publication boundary."""
    columns = {}
    if name == "mart_ui_part_master_analysis":
        columns = {
            "active_sku_id": pa.Column(str, nullable=False),
            "description": pa.Column(str, nullable=False),
            "has_planning": pa.Column(bool, nullable=False),
            "has_stock_snapshot": pa.Column(bool, nullable=False),
            "sales_abc": pa.Column(str, pa.Check.isin(["A", "B", "C"]), nullable=True),
            "sales_activity_12m": pa.Column(
                str, pa.Check.isin(["ACTIVE", "INACTIVE"]), nullable=False
            ),
        }
    elif name == "mart_ui_sales_abc_audit":
        columns = {
            "source": pa.Column(str, nullable=False),
            "window_start": pa.Column(str, nullable=False),
            "window_end": pa.Column(str, nullable=False),
            "sales_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "code_linked_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "description_linked_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "unmapped_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "ambiguous_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "no_match_lines": pa.Column(int, pa.Check.ge(0), coerce=True),
            "linked_skus": pa.Column(int, pa.Check.ge(0), coerce=True),
            "active_skus": pa.Column(int, pa.Check.ge(0), coerce=True),
            "return_only_skus": pa.Column(int, pa.Check.ge(0), coerce=True),
        }
    elif name in {"mart_ui_sku", "mart_ui_service_plan"}:
        columns = {
            "material_9": pa.Column(str, nullable=False),
            "forecast_lt": pa.Column(float, pa.Check.ge(0), coerce=True),
            "roq": pa.Column(float, pa.Check.ge(0), coerce=True),
            "net_requirement": pa.Column(float, pa.Check.ge(0), coerce=True),
            "value": pa.Column(float, nullable=True, coerce=True),
        }
    unique = (
        ["active_sku_id"]
        if name == "mart_ui_part_master_analysis"
        else (["material_9"] if name == "mart_ui_sku" else None)
    )
    schema = pa.DataFrameSchema(columns, unique=unique)
    validate(frame, schema, stage="15_dashboard", table=name)
