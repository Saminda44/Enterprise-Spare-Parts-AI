"""Forecast-vs-sales check: does billed sales history agree with the order history the
forecast is built on?

The forecast runs on dealer **orders** (ordered quantity, lost sales included, to the
latest month). sales.xlsx records the **billed** part of the same orders and ends earlier.
Where both exist the two should broadly agree; where they don't, the part is flagged so a
planner can see which source to question before trusting its forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Billed ÷ confirmed inside this band counts as agreement (billing lags and partial
#: shipments move it month to month).
AGREEMENT_BAND = (0.5, 1.5)
#: "90890-" part numbers are special service tools — dealer workshop kits, not wear parts.
SERVICE_TOOL_PREFIX = "90890-"

CONSISTENT = "consistent"
BILLED_ABOVE = "billed above orders"
BILLED_BELOW = "billed well below confirmed"
ORDERED_NOT_BILLED = "ordered, no linked billing"
SOLD_NOT_ORDERED = "sold, never ordered"
SERVICE_TOOL = "service tool, sold not ordered"


def build(
    forecast: pd.DataFrame,
    history: pd.DataFrame,
    sales_classes: pd.DataFrame,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """One row per part that has a forecast or a linked sale in the window.

    Business meaning: orders and billing describe the same dealer demand, so a large gap
    means one source is incomplete for that part — billing above orders suggests demand
    the order file missed (the forecast may be low); billing far below confirmed suggests
    a billing gap or a description that splits across parts. A part sold but never
    ordered is not forecast from its sales: those are one-off sales (the service-tool
    kit rollout) or demand the order file does not carry, and either needs a person.
    """
    in_window = history["month"].astype(str).between(window_start, window_end)
    orders = (
        history[in_window]
        .groupby("active_sku_id")[["ordered_quantity", "confirmed_quantity", "lost_quantity"]]
        .sum()
    )
    billed = sales_classes.set_index("active_sku_id")[["sales_qty", "sales_net_lkr", "sales_link"]]
    live = forecast.set_index("active_sku_id")[["mu_month", "mu_month_baseline", "mu_month_parc"]]
    frame = orders.join(billed, how="outer").join(live, how="left")
    frame = frame[(frame.index.isin(live.index)) | frame["sales_qty"].notna()]
    for column in ("ordered_quantity", "confirmed_quantity", "lost_quantity", "sales_qty"):
        frame[column] = frame[column].fillna(0.0)

    ratio = frame["sales_qty"] / frame["confirmed_quantity"].where(frame["confirmed_quantity"] > 0)
    frame["billed_to_confirmed"] = ratio
    tool = frame.index.to_series().astype(str).str.startswith(SERVICE_TOOL_PREFIX)
    frame["check"] = np.select(
        [
            (frame["ordered_quantity"] <= 0) & (frame["sales_qty"] > 0) & tool,
            (frame["ordered_quantity"] <= 0) & (frame["sales_qty"] > 0),
            (frame["confirmed_quantity"] > 0) & (frame["sales_qty"] <= 0),
            ratio > AGREEMENT_BAND[1],
            ratio < AGREEMENT_BAND[0],
        ],
        [SERVICE_TOOL, SOLD_NOT_ORDERED, ORDERED_NOT_BILLED, BILLED_ABOVE, BILLED_BELOW],
        default=CONSISTENT,
    )
    # No confirmed quantity and no billing in the window: nothing to compare.
    frame.loc[(frame["confirmed_quantity"] <= 0) & (frame["sales_qty"] <= 0), "check"] = (
        "no overlap in window"
    )
    months = len(pd.period_range(window_start, window_end, freq="M"))
    frame["billed_per_month"] = frame["sales_qty"] / months
    frame["ordered_per_month"] = frame["ordered_quantity"] / months
    frame["window_start"] = window_start
    frame["window_end"] = window_end
    return frame.reset_index().rename(columns={"index": "active_sku_id"})
