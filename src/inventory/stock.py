"""Step 12 — PDC stock, on-order pipeline and inventory position.

``IP = on_hand + on_order − backorders``. A projected position is provisional when
the source does not establish every incoming order through the planning horizon.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

import pandas as pd
import pandera.pandas as pa
from loguru import logger

from src.core.context import PlanningContext
from src.core.contracts import validate
from src.core.errors import SourceDataError
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.core.settings import get_settings
from src.demand.orders import build_sku_index
from src.io.excel import file_digest, read_source, source_vintage
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


def validate_live_snapshot(cycle_as_of: date, snapshot_as_of: date) -> None:
    """Require a real month-end stock snapshot immediately before a live cycle.

    Business meaning: a later order cannot silently reuse August stock after sales
    and receipts have changed the physical inventory position.
    """
    if cycle_as_of.day != 1 or snapshot_as_of != cycle_as_of - timedelta(days=1):
        raise SourceDataError(
            f"live order cycle {cycle_as_of:%Y-%m-%d} needs a matching month-end stock "
            f"snapshot; configured snapshot is {snapshot_as_of:%Y-%m-%d}. "
            "Update current_stock.xlsx and SPI_STOCK_SNAPSHOT_AS_OF before advancing the cycle"
        )


def verified_open_orders(
    *,
    owner_confirmed: bool,
    interpretation: str,
    coverage_end: pd.Timestamp,
    required_through: pd.Timestamp,
    source_modified: date,
    snapshot_as_of: date,
) -> bool:
    """Check whether dated open orders support this snapshot and protection horizon.

    Business meaning: future column headings do not verify an old open-PO export for
    a newer stock snapshot; the complete list must be refreshed for each cycle.
    """
    return (
        owner_confirmed
        and interpretation == "arrival"
        and coverage_end >= required_through
        and source_modified >= snapshot_as_of
    )


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

    from src.ingestion.store import active_excel_path, stock_snapshot_date

    on_orders_source = active_excel_path("On_Orders.xlsx")
    on_orders_vintage = source_vintage("on_orders")
    excel_backend = get_settings().data_backend == "excel"
    if excel_backend and file_digest(on_orders_source) != on_orders_vintage["sha256"]:
        raise SourceDataError("On_Orders source mirror is stale; ingest the updated workbook first")
    modified_at = pd.to_datetime(
        on_orders_vintage.get("source_modified"), utc=True, errors="coerce"
    )
    if pd.isna(modified_at):
        raise SourceDataError("On_Orders source mirror lacks a valid file modification timestamp")
    source_modified = modified_at.tz_convert("Asia/Colombo").date()
    schedule, coverage_end = _on_order_schedule(ctx, result, index)
    outside = ~schedule["active_sku_id"].astype(str).isin(scope)
    if outside.any():
        result.warn(
            f"removed {int(outside.sum()):,} on-order part(s) / "
            f"{float(schedule.loc[outside, 'qty'].sum()):,.0f} units outside Yamaha MC/OBM"
        )
        schedule = schedule.loc[~outside].copy()
    schedule = validate(
        schedule,
        pa.DataFrameSchema(
            {
                "active_sku_id": pa.Column(str, nullable=False),
                "arrival": pa.Column("datetime64[ns]", nullable=False),
                "qty": pa.Column(float, pa.Check.ge(0), nullable=False, coerce=True),
            }
        ),
        stage="12_stock",
        table="on_order_schedule",
    )
    result.artifact("on_order_schedule", write_table(schedule, "facts", "on_order_schedule"))
    saved_schedule = read_table("facts", "on_order_schedule")
    if len(saved_schedule) != len(schedule) or saved_schedule["qty"].sum() != schedule["qty"].sum():
        raise SourceDataError("on_order_schedule failed its publication round trip")

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
        snapshot_as_of = stock_snapshot_date()
        validate_live_snapshot(ctx.as_of, snapshot_as_of)

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
    required_through = cycle_start + pd.DateOffset(months=ctx.protection_interval_months - 1)
    verified_by_owner = bool(
        ctx.option("on_orders_verified_complete", get_settings().on_orders_verified_complete)
    )
    position["on_order_complete"] = verified_open_orders(
        owner_confirmed=verified_by_owner,
        interpretation=get_settings().on_order_interpretation,
        coverage_end=coverage_end,
        required_through=required_through,
        source_modified=source_modified,
        snapshot_as_of=snapshot_as_of,
    )
    position["on_orders_coverage_end"] = coverage_end.strftime("%Y-%m")
    position["on_orders_sha256"] = on_orders_vintage["sha256"]
    if not position["on_order_complete"].all():
        result.warn(
            f"incoming orders UNVERIFIED: columns through {coverage_end:%Y-%m}, "
            f"required through {required_through:%Y-%m}, source modified "
            f"{source_modified:%Y-%m-%d}, stock snapshot {snapshot_as_of:%Y-%m-%d}; "
            "known on_order is a lower bound, so the proposed purchase quantity can be too high"
        )
    else:
        result.warn(
            f"open orders VERIFIED by owner: dated expected arrivals through "
            f"{coverage_end:%Y-%m} cover the {required_through:%Y-%m} protection horizon; "
            f"source refreshed {source_modified:%Y-%m-%d} after the stock snapshot"
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
    position = validate(
        position,
        pa.DataFrameSchema(
            {
                "active_sku_id": pa.Column(str, nullable=False),
                "on_hand": pa.Column(float, pa.Check.ge(0), nullable=False, coerce=True),
                "on_order": pa.Column(float, pa.Check.ge(0), nullable=False, coerce=True),
                "ip": pa.Column(float, pa.Check.ge(0), nullable=False, coerce=True),
                "on_order_complete": pa.Column(bool, nullable=False),
            },
            unique=["active_sku_id"],
        ),
        stage="12_stock",
        table="stock_position",
    )
    result.artifact("stock_position", write_table(position, "facts", "stock_position"))
    saved_position = read_table("facts", "stock_position")
    if len(saved_position) != len(position) or saved_position["ip"].sum() != position["ip"].sum():
        raise SourceDataError("stock_position failed its publication round trip")

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

    if "Material" not in frame:
        raise SourceDataError("On_Orders needs a Material column")
    month_dates: dict[str, pd.Timestamp] = {}
    for column in frame.columns:
        if column[:3].upper() not in MONTH_ABBR:
            continue
        match = re.fullmatch(r"([A-Za-z]{3})\s+(20\d{2})", column)
        if match is None:
            raise SourceDataError(
                f"On_Orders month column {column!r} needs an explicit year, e.g. 'Sep 2026'"
            )
        month_dates[column] = pd.Timestamp(
            year=int(match.group(2)), month=MONTH_ABBR[match.group(1).upper()], day=1
        )
    if not month_dates:
        raise SourceDataError("On_Orders needs dated month columns such as 'Sep 2026'")
    ordered_months = sorted(month_dates.values())
    if len(set(ordered_months)) != len(ordered_months):
        raise SourceDataError("On_Orders has duplicate arrival month columns")
    expected_months = pd.period_range(ordered_months[0], ordered_months[-1], freq="M")
    if len(expected_months) != len(ordered_months):
        raise SourceDataError("On_Orders arrival month columns have a gap")

    frame = validate(
        frame,
        pa.DataFrameSchema(
            {
                "Material": pa.Column(str, nullable=False),
                **{
                    column: pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True)
                    for column in month_dates
                },
            }
        ),
        stage="12_stock",
        table="On_Orders",
    )

    interpretation = settings.on_order_interpretation
    result.warn(
        f"ON-ORDER INTERPRETATION = '{interpretation}': dated columns "
        f"{ordered_months[0]:%Y-%m}..{ordered_months[-1]:%Y-%m} are read as "
        + (
            "expected arrival"
            if interpretation == "arrival"
            else "the month the PO was raised, "
            f"so {ctx.lead_time_months} months are added to derive arrival"
        )
        + "."
    )

    long = frame.melt(
        id_vars=["Material"],
        value_vars=list(month_dates),
        var_name="month_name",
        value_name="qty",
    )
    long["qty"] = long["qty"].fillna(0.0)
    long = long[long["qty"] != 0]
    long["arrival"] = pd.to_datetime(long["month_name"].map(month_dates))
    if interpretation == "raised":
        long["arrival"] = long["arrival"] + pd.DateOffset(months=ctx.lead_time_months)

    coverage_end = ordered_months[-1]
    if interpretation == "raised":
        coverage_end += pd.DateOffset(months=ctx.lead_time_months)
    result.warn(
        f"On_Orders source: {len(frame):,} material rows, {len(long):,} nonzero "
        f"arrival cells, {float(long['qty'].sum()):,.0f} units across dated columns"
    )
    long["active_sku_id"] = long["Material"].map(lambda part: index.get(normalise(part)))
    unmatched = int(long["active_sku_id"].isna().sum())
    if unmatched:
        result.warn(
            f"{unmatched:,} on-order line(s) / "
            f"{float(long.loc[long['active_sku_id'].isna(), 'qty'].sum()):,.0f} units "
            "have no part master match and are excluded"
        )
    return (
        long.dropna(subset=["active_sku_id"])[["active_sku_id", "arrival", "qty"]].reset_index(
            drop=True
        ),
        coverage_end,
    )
