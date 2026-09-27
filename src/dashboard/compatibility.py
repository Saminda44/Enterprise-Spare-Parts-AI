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
    if name in {"mart_ui_sku", "mart_ui_service_plan"}:
        columns = {
            "material_9": pa.Column(str, nullable=False),
            "forecast_lt": pa.Column(float, pa.Check.ge(0), coerce=True),
            "roq": pa.Column(float, pa.Check.ge(0), coerce=True),
            "net_requirement": pa.Column(float, pa.Check.ge(0), coerce=True),
            "value": pa.Column(float, nullable=True, coerce=True),
        }
    schema = pa.DataFrameSchema(columns, unique=["material_9"] if name == "mart_ui_sku" else None)
    validate(frame, schema, stage="15_dashboard", table=name)
