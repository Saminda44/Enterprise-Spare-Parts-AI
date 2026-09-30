"""Step 12 — PDC stock, on-order pipeline and inventory position.

``IP = on_hand + on_order − backorders``. A projected position is provisional when
the source does not establish every incoming order through the planning horizon.
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.errors import SourceDataError
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


def project_on_hand(
    on_hand: pd.DataFrame,
    forecast: pd.DataFrame,
    receipts: pd.DataFrame,
    snapshot_as_of: date,
    cycle_as_of: date,
) -> pd.DataFrame:
    """Project a month-end stock snapshot to the start of a future order cycle.

    Business meaning: receive only documented arrivals after the snapshot, then serve
    forecast demand for each complete intervening month. Unrecorded receipts remain
    unknown; the result is not an actual stock count or a buyer-ready position.
    """
    snapshot = pd.Timestamp(snapshot_as_of)
    cycle = pd.Timestamp(cycle_as_of).to_period("M").to_timestamp()
    if not snapshot.is_month_end or snapshot >= cycle:
        raise SourceDataError("stock snapshot must be a month-end before the cycle")
    if not {"active_sku_id", "on_hand"}.issubset(on_hand):
        raise SourceDataError("stock projection needs active_sku_id and on_hand")
    if not {"active_sku_id", "mu_month"}.issubset(forecast):
        raise SourceDataError("stock projection needs forecast_live mu_month")
    if not {"active_sku_id", "arrival", "qty"}.issubset(receipts):
        raise SourceDataError("stock projection needs a dated arrival schedule")
    if on_hand["active_sku_id"].duplicated().any() or forecast["active_sku_id"].duplicated().any():
        raise SourceDataError("stock or forecast contains duplicate active_sku_id")

    months = pd.period_range(snapshot.to_period("M") + 1, cycle.to_period("M") - 1, freq="M")
    incoming = receipts.copy()
    incoming["arrival"] = pd.to_datetime(incoming["arrival"]).dt.to_period("M")
    incoming = incoming[incoming["arrival"].isin(months)]
    ids = pd.Index(on_hand["active_sku_id"]).union(pd.Index(incoming["active_sku_id"]))
    out = pd.DataFrame({"active_sku_id": ids})
    out = out.merge(on_hand, on="active_sku_id", how="left", validate="one_to_one")
    out["on_hand"] = pd.to_numeric(out["on_hand"], errors="coerce").fillna(0.0)
    if (out["on_hand"] < 0).any():
        raise SourceDataError("stock projection received negative on-hand quantity")
    out = out.merge(
        forecast[["active_sku_id", "mu_month"]],
        on="active_sku_id",
        how="left",
        validate="one_to_one",
    )
    out["forecast_missing"] = out["mu_month"].isna()
    out["mu_month"] = pd.to_numeric(out["mu_month"], errors="coerce").fillna(0.0)
    if (out["mu_month"] < 0).any():
        raise SourceDataError("stock projection received negative forecast demand")
    out["on_hand_snapshot"] = out["on_hand"]
    out["projected_demand"] = 0.0
    out["projected_uncovered_demand"] = 0.0
    out["known_receipts_before_cycle"] = 0.0
    for month in months:
        due = incoming.loc[incoming["arrival"] == month].groupby("active_sku_id")["qty"].sum()
        received = out["active_sku_id"].map(due).fillna(0.0)
        out["on_hand"] += received
        out["known_receipts_before_cycle"] += received
        served = out[["on_hand", "mu_month"]].min(axis=1)
        out["projected_uncovered_demand"] += out["mu_month"] - served
        out["projected_demand"] += out["mu_month"]
        out["on_hand"] -= served
    out["projection_months"] = len(months)
    return out.drop(columns=["mu_month"])


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

    schedule, last_arrival = _on_order_schedule(ctx, result, index)
    outside = ~schedule["active_sku_id"].astype(str).isin(scope)
    if outside.any():
        result.warn(
            f"removed {int(outside.sum()):,} on-order part(s) / "
            f"{float(schedule.loc[outside, 'qty'].sum()):,.0f} units outside Yamaha MC/OBM"
        )
        schedule = schedule.loc[~outside].copy()

    snapshot_value = ctx.option("stock_snapshot_as_of")
    provisional = bool(ctx.option("provisional", False))
    if snapshot_value:
        if not provisional:
            raise SourceDataError("projecting a stock snapshot requires a provisional run")
        try:
            snapshot_as_of = date.fromisoformat(str(snapshot_value))
        except ValueError as exc:
            raise SourceDataError("stock_snapshot_as_of must be YYYY-MM-DD") from exc
        on_hand = project_on_hand(
            on_hand,
            read_table("facts", "forecast_live"),
            schedule,
            snapshot_as_of,
            ctx.as_of,
        )
        result.warn(
            f"PROVISIONAL: projected {snapshot_as_of:%Y-%m-%d} stock through "
            f"{int(on_hand['projection_months'].max())} complete month(s) to "
            f"{ctx.as_of:%Y-%m}; forecast demand is not actual consumption, and "
            f"{int(on_hand['forecast_missing'].sum()):,} stocked part(s) lack a forecast"
        )
        result.warn(
            f"projected demand {float(on_hand['projected_demand'].sum()):,.0f} units; "
            f"potential uncovered demand {float(on_hand['projected_uncovered_demand'].sum()):,.0f} "
            "units. These are scenario estimates, not measured lost sales."
        )
    else:
        snapshot_as_of = ctx.as_of

    cycle_start = pd.Timestamp(ctx.as_of).to_period("M").to_timestamp()
    future = schedule.loc[schedule["arrival"] >= cycle_start]
    on_order = (
        future.groupby("active_sku_id", as_index=False)["qty"]
        .sum()
        .rename(columns={"qty": "on_order"})
    )
    result.warn(
        f"on-order lines: {len(schedule):,} matched, {len(future):,} documented at or after "
        f"{cycle_start:%Y-%m} ({float(schedule['qty'].sum()):,.0f} matched units total, "
        f"{float(future['qty'].sum()):,.0f} known future units)"
    )
    position = on_hand.merge(on_order, on="active_sku_id", how="outer")
    position[["on_hand", "on_order"]] = position[["on_hand", "on_order"]].fillna(0.0)

    # No backorder or open-commitment source exists in any supplied file.
    position["backorders"] = 0.0
    result.warn("backorders = 0 for every part: no backorder or open-commitment source exists")

    position["ip"] = position["on_hand"] + position["on_order"] - position["backorders"]
    position["as_of"] = pd.Timestamp(ctx.as_of)
    position["stock_snapshot_as_of"] = pd.Timestamp(snapshot_as_of)
    position["provisional"] = provisional
    position["on_order_complete"] = bool(ctx.option("on_orders_verified_complete", False))
    if not position["on_order_complete"].all():
        result.warn(
            f"incoming-order coverage after {last_arrival:%Y-%m} is UNVERIFIED; "
            "known on_order is a lower bound, so the proposed purchase quantity can be too high"
        )

    total_ip = float(position["ip"].sum())
    on_order_share = float(position["on_order"].sum()) / total_ip if total_ip else 0.0
    if position["on_order"].sum() <= 0:
        result.warn("no documented future arrivals; this does not prove that no orders are open")
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


def _on_order_schedule(
    ctx: PlanningContext, result: StageResult, index: dict[str, str]
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Resolve the workbook's month columns to dated, matched receipt lines.

    Business meaning: a documented arrival on or before a stock snapshot is already
    reflected in that stock; only later arrivals can increase projected position.
    """
    settings = get_settings()
    frame = read_source("on_orders")
    frame.columns = [str(c).strip() for c in frame.columns]

    month_columns = [c for c in frame.columns if str(c).strip().upper()[:3] in MONTH_ABBR]
    if "PN" not in frame or not month_columns:
        raise SourceDataError("On_Orders needs PN and at least one month column")

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
        + "."
    )

    snapshot_value = ctx.option("stock_snapshot_as_of")
    default_year = pd.Timestamp(snapshot_value).year if snapshot_value else ctx.as_of.year
    year = int(ctx.option("on_order_year", default_year))
    result.warn(
        f"On_Orders month columns carry NO YEAR — using {year} from the "
        f"{'stock snapshot' if snapshot_value else 'cycle date'}; confirm on each new export"
    )

    long = frame.melt(
        id_vars=[c for c in ("PN", "Desc") if c in frame.columns],
        value_vars=month_columns,
        var_name="month_name",
        value_name="qty",
    )
    parsed = pd.to_numeric(long["qty"], errors="coerce")
    invalid = long["qty"].notna() & long["qty"].astype(str).str.strip().ne("") & parsed.isna()
    if invalid.any():
        raise SourceDataError(f"On_Orders has {int(invalid.sum())} nonnumeric quantities")
    long["qty"] = parsed.fillna(0.0)
    if (long["qty"] < 0).any():
        raise SourceDataError("On_Orders has negative incoming quantities")
    long = long[long["qty"] != 0]
    long["month_no"] = long["month_name"].str.strip().str.upper().str[:3].map(MONTH_ABBR)
    long["arrival"] = pd.to_datetime(
        dict(year=year, month=long["month_no"], day=1), errors="coerce"
    )
    if interpretation == "raised":
        long["arrival"] = long["arrival"] + pd.DateOffset(months=ctx.lead_time_months)

    last_month = max(MONTH_ABBR[str(c).strip().upper()[:3]] for c in month_columns)
    last_arrival = pd.Timestamp(year=year, month=last_month, day=1)
    if interpretation == "raised":
        last_arrival += pd.DateOffset(months=ctx.lead_time_months)
    long["active_sku_id"] = long["PN"].map(lambda p: index.get(normalise(p)))
    unmatched = int(long["active_sku_id"].isna().sum())
    if unmatched:
        result.warn(f"{unmatched:,} on-order line(s) have no part master match and are excluded")
    return long.dropna(subset=["active_sku_id"])[["active_sku_id", "arrival", "qty"]], last_arrival
