"""Step 12 — PDC stock, on-order pipeline and inventory position.

``IP = on_hand + on_order − backorders``. Comparing against on-hand alone over-orders by
roughly a lead time of demand every month until the pipeline lands: with a 3-month lead
and monthly review there can be three orders in flight at once.
"""

from __future__ import annotations

import calendar

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.core.settings import get_settings
from src.demand.orders import build_sku_index
from src.io.excel import read_source
from src.io.parquet import append_columns, read_table, write_table
from src.parts.supersession import normalise

MONTH_ABBR = {name.upper(): number for number, name in enumerate(calendar.month_abbr) if name}


#: PN_Yamaha brands in planning scope: YM = Yamaha motorcycle parts, OB = Yamaha outboard
#: (OBM) parts. Anything else PN_Yamaha carries (KT = Katana tyres) is not planned here.
PLANNING_BRANDS = ("YM", "OB")


def in_scope_skus(part_master: pd.DataFrame) -> set[str]:
    """Active SKUs whose PN_Yamaha brand is Yamaha MC or OBM.

    Business meaning: inventory status and the order plan cover Yamaha motorcycle and
    outboard parts only; other brands in the master, and any material not in PN_Yamaha at
    all (lubricants, other makes), are excluded from stock and from the pipeline alike.
    """
    brand = part_master["brand"].astype(str).str.strip().str.upper()
    return set(part_master.loc[brand.isin(PLANNING_BRANDS), "active_sku_id"].astype(str))


@REGISTRY.register(
    "12_stock",
    depends_on=["02_part_master"],
    description="PDC stock, on-order pipeline and inventory position",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="12_stock")
    stock = read_source("current_stock")
    stock.columns = [str(c).strip() for c in stock.columns]
    result.rows_in = len(stock)

    if "Unrestricted" not in stock.columns:
        result.status = StageStatus.FAILED
        result.error = "current_stock has no Unrestricted column"
        return result
    result.warn(
        "on_hand = Unrestricted: this export carries no Quality Inspection, Restricted, "
        "Blocked, Returns or Transit bucket, so non-sellable stock is invisible here"
    )

    stock = stock.dropna(axis=1, how="all").dropna(axis=0, how="all")
    stock["Unrestricted"] = pd.to_numeric(stock["Unrestricted"], errors="coerce").fillna(0.0)

    negatives = int((stock["Unrestricted"] < 0).sum())
    if negatives:
        result.warn(
            f"{negatives:,} row(s) carry a negative quantity — asserted absent, investigate"
        )

    network_units = float(stock["Unrestricted"].sum())
    pdc = stock[stock["Plant"].astype(str).str.strip().str.upper() == ctx.plant.upper()].copy()
    pdc_units = float(pdc["Unrestricted"].sum())
    result.warn(
        f"PDC scope {ctx.plant}: {len(pdc):,}/{len(stock):,} rows, {pdc_units:,.0f} of "
        f"{network_units:,.0f} network units ({pdc_units / network_units:.1%}). Branch stock "
        f"is visibility only and never enters inventory position."
    )
    if pdc.empty:
        result.status = StageStatus.FAILED
        result.error = f"no rows for plant {ctx.plant}"
        return result

    part_master = read_table("facts", "part_master")
    index = build_sku_index(part_master)
    pdc["active_sku_id"] = pdc["Material"].map(lambda m: index.get(normalise(m)))

    unknown = pdc["active_sku_id"].isna()
    if unknown.any():
        dropped_units = float(pdc.loc[unknown, "Unrestricted"].sum())
        result.reject("material absent from PN_Yamaha", int(unknown.sum()))
        result.warn(
            f"removed {int(unknown.sum()):,} PDC row(s) / {dropped_units:,.0f} units not present "
            f"in PN_Yamaha (matched on Material and all ten supersede columns)"
        )
        pdc = pdc.loc[~unknown].copy()

    scope = in_scope_skus(part_master)
    other_brand = ~pdc["active_sku_id"].astype(str).isin(scope)
    if other_brand.any():
        result.reject(
            f"not a Yamaha MC/OBM part (PN_Yamaha brand outside {PLANNING_BRANDS})",
            int(other_brand.sum()),
        )
        result.warn(
            f"removed {int(other_brand.sum()):,} PDC row(s) / "
            f"{float(pdc.loc[other_brand, 'Unrestricted'].sum()):,.0f} units of other brands "
            f"in PN_Yamaha — only Yamaha MC (YM) and OBM (OB) parts are planned"
        )
        pdc = pdc.loc[~other_brand].copy()

    on_hand = pdc.groupby("active_sku_id", as_index=False).agg(
        on_hand=("Unrestricted", "sum"),
        storage_locations=("Storage Location", "nunique"),
        description=("Material Description", "first"),
    )

    on_order = _on_order(ctx, result, index)
    outside = ~on_order["active_sku_id"].astype(str).isin(scope)
    if outside.any():
        result.warn(
            f"removed {int(outside.sum()):,} on-order part(s) / "
            f"{float(on_order.loc[outside, 'on_order'].sum()):,.0f} units outside Yamaha MC/OBM"
        )
        on_order = on_order.loc[~outside]
    position = on_hand.merge(on_order, on="active_sku_id", how="outer")
    position[["on_hand", "on_order"]] = position[["on_hand", "on_order"]].fillna(0.0)

    # No backorder or open-commitment source exists in any supplied file.
    position["backorders"] = 0.0
    result.warn("backorders = 0 for every part: no backorder or open-commitment source exists")

    position["ip"] = position["on_hand"] + position["on_order"] - position["backorders"]
    position["as_of"] = pd.Timestamp(ctx.as_of)

    total_ip = float(position["ip"].sum())
    on_order_share = float(position["on_order"].sum()) / total_ip if total_ip else 0.0
    if position["on_order"].sum() <= 0:
        result.warn(
            "on_order is zero for every part — that is a data problem, not a fact, and IP "
            "collapses to on_hand"
        )
    else:
        result.warn(
            f"on_order is {on_order_share:.1%} of total inventory position: "
            f"{float(position['on_hand'].sum()):,.0f} on hand + "
            f"{float(position['on_order'].sum()):,.0f} on order across {len(position):,} parts"
        )

    result.rows_out = len(position)
    result.artifact("stock_position", write_table(position, "facts", "stock_position"))

    enriched = append_columns(
        read_table("facts", "part_master_enriched"),
        position.drop(columns=["description"], errors="ignore"),
        "active_sku_id",
    )
    result.artifact("part_master_enriched", write_table(enriched, "facts", "part_master_enriched"))

    by_plant = (
        stock.groupby("Plant", as_index=False)["Unrestricted"]
        .sum()
        .sort_values("Unrestricted", ascending=False)
    )
    result.artifact("stock_by_plant", write_table(by_plant, "facts", "stock_by_plant"))

    logger.info(f"stock position: {len(position):,} SKUs, IP {total_ip:,.0f}")
    return result


def _on_order(ctx: PlanningContext, result: StageResult, index: dict[str, str]) -> pd.DataFrame:
    """Reshape the wide month pivot to long and keep only months at or after as_of.

    Business meaning: earlier months have already arrived and sit inside on_hand;
    counting them again double-counts the pipeline.
    """
    settings = get_settings()
    frame = read_source("on_orders")
    frame.columns = [str(c).strip() for c in frame.columns]

    month_columns = [c for c in frame.columns if str(c).strip().upper()[:3] in MONTH_ABBR]
    if not month_columns:
        result.warn("On_Orders carries no month columns — on_order set to zero")
        return pd.DataFrame({"active_sku_id": [], "on_order": []})

    interpretation = settings.on_order_interpretation
    result.warn(
        f"ON-ORDER INTERPRETATION = '{interpretation}': month columns "
        f"{month_columns[0]}..{month_columns[-1]} are read as "
        + (
            "expected arrival"
            if interpretation == "arrival"
            else "the month the PO was raised, "
            f"so {ctx.lead_time_months} months are added to derive arrival"
        )
        + ". This single assumption shifts the whole pipeline by a quarter."
    )

    #: The columns carry no year. Assume the cycle year of as_of, and say so.
    year = ctx.as_of.year
    result.warn(
        f"On_Orders month columns carry NO YEAR — assumed {year} from as_of. Confirm with "
        f"procurement; a wrong year moves the entire pipeline by twelve months."
    )

    long = frame.melt(
        id_vars=[c for c in ("PN", "Desc") if c in frame.columns],
        value_vars=month_columns,
        var_name="month_name",
        value_name="qty",
    )
    long["qty"] = pd.to_numeric(long["qty"], errors="coerce").fillna(0.0)
    long = long[long["qty"] != 0]
    long["month_no"] = long["month_name"].str.strip().str.upper().str[:3].map(MONTH_ABBR)
    long["arrival"] = pd.to_datetime(
        dict(year=year, month=long["month_no"], day=1), errors="coerce"
    )
    if interpretation == "raised":
        long["arrival"] = long["arrival"] + pd.DateOffset(months=ctx.lead_time_months)

    cycle_start = pd.Timestamp(ctx.as_of).to_period("M").to_timestamp()
    future = long[long["arrival"] >= cycle_start]
    result.warn(
        f"on-order lines: {len(long):,} total, {len(future):,} at or after {cycle_start:%Y-%m} "
        f"counted as pipeline ({long['qty'].sum():,.0f} units total, "
        f"{future['qty'].sum():,.0f} counted)"
    )

    if "PN" not in future.columns:
        return pd.DataFrame({"active_sku_id": [], "on_order": []})
    future = future.assign(active_sku_id=future["PN"].map(lambda p: index.get(normalise(p))))
    unmatched = int(future["active_sku_id"].isna().sum())
    if unmatched:
        result.warn(f"{unmatched:,} on-order line(s) have no part master match and are excluded")
    return (
        future.dropna(subset=["active_sku_id"])
        .groupby("active_sku_id", as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "on_order"})
    )
