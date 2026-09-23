"""Step 09 — VIN-level vehicle registrations, the cohort feed for the parc model."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.demand.sales import parse_billing_date
from src.io.excel import read_source
from src.io.parquet import write_table
from src.io.sap import split_code_label

#: Literal placeholder that must be treated as null, not as a value.
NULL_TOKENS = {"No order record", "nan", "None", ""}

GEO_COLUMNS = ("Province", "District", "RM", "ASE")


def detect_office_leak(frame: pd.DataFrame) -> pd.Series:
    """Rows where every geography field carries the same value.

    Business meaning: in some rows the sales office name leaks into Dealer, Province,
    District, RM and ASE alike (every field reads "Borella"). That is not geography and
    must be reported rather than aggregated.
    """
    present = [c for c in GEO_COLUMNS if c in frame.columns]
    if len(present) < 2:
        return pd.Series(False, index=frame.index)
    first = frame[present[0]].astype(str).str.strip()
    same = pd.Series(True, index=frame.index)
    for column in present[1:]:
        same &= frame[column].astype(str).str.strip() == first
    return same & first.ne("")


@REGISTRY.register("09_unit_sales", description="VIN-level vehicle registrations from MCSI")
def run(ctx: PlanningContext) -> StageResult:  # noqa: ARG001 — contract requires ctx
    result = StageResult(stage="09_unit_sales")
    frame = read_source("mcsi")
    frame.columns = [str(c).strip() for c in frame.columns]
    result.rows_in = len(frame)

    if "VIN" not in frame.columns:
        result.status = StageStatus.FAILED
        result.error = "MCSI has no VIN column"
        return result

    frame = frame.replace(list(NULL_TOKENS - {""}), None)

    # Glued columns — Payer is deliberately excluded: it is a retail customer name,
    # not a dealer, and joining it to dealers.xlsx would be wrong.
    for column, code_name, label_name in (
        ("Sales Organization", "sales_org_code", "sales_org_name"),
        ("Sales Office", "sales_office_code", "sales_office_name"),
        ("Sales Employee", "sales_employee_code", "sales_employee_name"),
    ):
        if column in frame.columns:
            parsed = frame[column].map(split_code_label)
            frame[code_name] = [p[0] for p in parsed]
            frame[label_name] = [p[1] for p in parsed]

    dates = parse_billing_date(frame.get("Billing Date", frame.get("Date")))
    frame["year"] = dates.dt.year
    frame["month_no"] = dates.dt.month
    frame["month"] = dates.dt.to_period("M").astype(str)
    if dates.notna().any():
        result.warn(
            f"registration window {dates.min():%Y-%m} to {dates.max():%Y-%m} "
            f"({dates.dt.to_period('M').nunique()} months)"
        )

    quantity = pd.to_numeric(frame.get("SlsVolQty"), errors="coerce").fillna(0)
    frame["qty"] = quantity
    frame["is_return"] = quantity < 0
    returns = int(frame["is_return"].sum())
    result.warn(f"{returns:,} negative-quantity row(s) treated as returns and netted, not dropped")

    leak = detect_office_leak(frame)
    if leak.any():
        result.warn(
            f"GEOGRAPHY UNUSABLE on {int(leak.sum()):,}/{len(frame):,} rows "
            f"({leak.mean():.1%}): Province, District, RM and ASE all carry the same value — "
            f"the sales office leaking into the dealer fields"
        )
    frame["geography_is_office_leak"] = leak

    vins = frame["VIN"].nunique()
    result.warn(
        f"{vins:,} distinct VINs across {len(frame):,} rows — the difference is returns "
        f"and amendments, netted by quantity"
    )

    dealer_name = next(
        (c for c in ("Delaer Name", "Dealer Name", "Dealer") if c in frame.columns), None
    )
    unit_sales = pd.DataFrame(
        {
            "vin": frame["VIN"],
            "model_name": frame.get("Model"),
            "year": frame["year"],
            "month": frame["month"],
            "month_no": frame["month_no"],
            "qty": frame["qty"],
            "is_return": frame["is_return"],
            "dealer_code": frame.get("Dealer Code"),
            "dealer_name": frame.get(dealer_name) if dealer_name else None,
            "province": frame.get("Province"),
            "district": frame.get("District"),
            "rm": frame.get("RM"),
            "ase": frame.get("ASE"),
            "net_sales": pd.to_numeric(frame.get("Net Sales"), errors="coerce"),
            "cost": pd.to_numeric(frame.get("Cost"), errors="coerce"),
            "geography_is_office_leak": frame["geography_is_office_leak"],
        }
    )
    result.rows_out = len(unit_sales)
    result.artifact("unit_sales", write_table(unit_sales, "facts", "unit_sales"))

    by_model = (
        unit_sales.groupby("model_name", as_index=False)
        .agg(units=("qty", "sum"), vins=("vin", "nunique"), net_sales=("net_sales", "sum"))
        .sort_values("units", ascending=False)
    )
    by_model["avg_price"] = by_model["net_sales"] / by_model["units"].replace(0, pd.NA)
    result.artifact("unit_sales_by_model", write_table(by_model, "facts", "unit_sales_by_model"))

    monthly = (
        unit_sales.groupby(["month", "model_name"], as_index=False)
        .agg(units=("qty", "sum"), net_sales=("net_sales", "sum"))
        .sort_values("month")
    )
    result.artifact("unit_sales_monthly", write_table(monthly, "facts", "unit_sales_monthly"))

    clean_geo = unit_sales[~unit_sales["geography_is_office_leak"]]
    for column, name in (
        ("province", "unit_sales_by_province"),
        ("district", "unit_sales_by_district"),
        ("rm", "unit_sales_by_rm"),
        ("ase", "unit_sales_by_ase"),
        ("dealer_name", "unit_sales_by_dealer"),
    ):
        if column in clean_geo.columns and len(clean_geo):
            agg = (
                clean_geo.groupby(column, as_index=False)
                .agg(units=("qty", "sum"), net_sales=("net_sales", "sum"))
                .sort_values("units", ascending=False)
            )
            result.artifact(name, write_table(agg, "facts", name))

    logger.info(f"unit sales: {len(unit_sales):,} rows, {vins:,} VINs")
    return result
