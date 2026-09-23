"""Step 03 — order cleaning and the monthly demand history.

The measured ``Lost Quantity`` is the most valuable column in the project: most inventory
systems must infer stockouts from demand that never appears, while here the shortfall is
recorded on every order line.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.io.excel import read_source
from src.io.parquet import read_table, write_table
from src.parts.supersession import SUPERSEDE_COLUMNS, normalise

KEEP_COLUMNS = [
    "Document Date",
    "Sales Document",
    "Sales Document Item",
    "Sales Document Type",
    "SD Document Category",
    "Sold-to Party",
    "Sold-To Party Name",
    "Material",
    "Material Description",
    "Order Quantity (Item)",
    "Confirmed Quantity (Item)",
    "Net Price",
    "Net Value (Item)",
    "Plant",
    "Storage Location",
    "Reason for Rejection",
    "Delivery Date",
    "Item Category",
    "Sales Office",
    "Created On",
    "Goods Issue Date",
    "Material Availability Date",
]


def dealer_key(value: object) -> str:
    """Trimmed text on both sides of the join.

    Business meaning: ``Sold-to Party`` is int64 in orders while ``Dealer Code`` is text
    in dealers. Joined as-is the match silently misses on every row.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.upper()


def drop_empty(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Fully null columns first, then fully null rows — in that order.

    Doing rows first leaves ~60 empty contract/cancellation columns in place, and they
    then block the row test because no row is entirely null.
    """
    before_cols = frame.shape[1]
    frame = frame.dropna(axis=1, how="all")
    dropped_cols = before_cols - frame.shape[1]
    before_rows = len(frame)
    frame = frame.dropna(axis=0, how="all")
    return frame, dropped_cols, before_rows - len(frame)


def attach_dealer_type(frame: pd.DataFrame, dealers: pd.DataFrame) -> pd.DataFrame:
    """Join on code, fall back to name; unmatched becomes ``"Not Found"``."""
    dealers = dealers.copy()
    dealers["_code"] = dealers["Dealer Code"].map(dealer_key)
    dealers["_name"] = dealers["Dealer Name"].astype(str).str.strip().str.upper()

    by_code = dealers.drop_duplicates("_code").set_index("_code")
    by_name = dealers.drop_duplicates("_name").set_index("_name")

    out = frame.copy()
    code_key = out["Sold-to Party"].map(dealer_key)
    name_key = out["Sold-To Party Name"].astype(str).str.strip().str.upper()

    for column in ("Type", "Province", "District", "ASE", "RM"):
        if column not in dealers.columns:
            continue
        values = code_key.map(by_code[column])
        values = values.fillna(name_key.map(by_name[column]))
        out[column if column != "Type" else "Dealer Type"] = values

    out["Dealer Type"] = out["Dealer Type"].fillna("Not Found")
    return out


def material_category(description: object, dealer_type: object) -> str | None:
    """MC splits by brand keyword; OBM is a single category.

    Business meaning: Dealer Type "Not Found" gets no category and must not be silently
    dropped — it is reported instead.
    """
    kind = str(dealer_type or "").strip().upper()
    if kind == "OBM":
        return "OBM Spare Parts"
    if kind != "MC":
        return None
    text = str(description or "").upper()
    if "YAMALUBE" in text:
        return "Lubricant"
    if "KARATE BATTERY" in text:
        return "Battery"
    if "KATANA TYRE" in text:
        return "Tyre"
    return "MC Spare Parts"


def build_sku_index(part_master: pd.DataFrame) -> dict[str, str]:
    """Every known number — material and all ten supersedes — to its active_sku_id."""
    index: dict[str, str] = {}
    for row in part_master.itertuples(index=False):
        active = str(row.active_sku_id).strip()
        index.setdefault(normalise(row.material), active)
        for column in SUPERSEDE_COLUMNS:
            value = getattr(row, column.replace(" ", "_"), None)
            if value is not None and str(value).strip() not in {"", "None", "nan"}:
                index.setdefault(normalise(value), active)
    return index


@REGISTRY.register(
    "03_orders",
    depends_on=["02_part_master"],
    description="order cleaning, lost sales and monthly demand history",
)
def run(ctx: PlanningContext) -> StageResult:  # noqa: ARG001 — contract requires ctx
    result = StageResult(stage="03_orders")
    raw = read_source("orders")
    raw.columns = [str(c).strip() for c in raw.columns]
    result.rows_in = len(raw)

    frame, dropped_cols, dropped_rows = drop_empty(raw)
    if dropped_cols:
        result.warn(f"dropped {dropped_cols} fully-null column(s)")
    if dropped_rows:
        result.reject("fully null row", dropped_rows)

    keep = [c for c in KEEP_COLUMNS if c in frame.columns]
    missing = [
        c for c in ("SD Document Category", "Material", "Order Quantity (Item)") if c not in keep
    ]
    if missing:
        result.status = StageStatus.FAILED
        result.error = f"orders is missing required column(s): {missing}"
        return result
    frame = frame[keep]

    dealers = read_source("dealers")
    dealers.columns = [str(c).strip() for c in dealers.columns]
    frame = attach_dealer_type(frame, dealers)
    not_found = int((frame["Dealer Type"] == "Not Found").sum())
    result.warn(
        f"dealer join: {len(frame) - not_found:,}/{len(frame):,} matched; "
        f"{not_found:,} Not Found (kept, no material category)"
    )

    frame["material_category"] = [
        material_category(d, t)
        for d, t in zip(frame.get("Material Description"), frame["Dealer Type"], strict=True)
    ]

    part_master = read_table("facts", "part_master")
    index = build_sku_index(part_master)
    frame["active_sku_id"] = frame["Material"].map(lambda m: index.get(normalise(m)))

    unmatched = frame["active_sku_id"].isna()
    if unmatched.any():
        exceptions = frame.loc[unmatched, keep[:12]].copy()
        exceptions["reason"] = "no part master match on Material or any supersede column"
        result.artifact("order_exceptions", write_table(exceptions, "facts", "order_exceptions"))
        result.reject("no part master match", int(unmatched.sum()))
        frame = frame.loc[~unmatched].copy()

    ordered = pd.to_numeric(frame["Order Quantity (Item)"], errors="coerce").fillna(0.0)
    confirmed = pd.to_numeric(frame["Confirmed Quantity (Item)"], errors="coerce").fillna(0.0)
    price = pd.to_numeric(frame.get("Net Price"), errors="coerce").fillna(0.0)

    violations = int((confirmed > ordered).sum())
    if violations:
        result.warn(
            f"{violations:,} line(s) have Confirmed > Ordered — a data error, kept and flagged"
        )
    frame["lost_quantity"] = (ordered - confirmed).clip(lower=0)
    frame["lost_sale_value"] = frame["lost_quantity"] * price
    frame["order_value"] = confirmed * price
    frame["ordered_quantity"] = ordered
    frame["confirmed_quantity"] = confirmed
    frame["confirmed_gt_ordered"] = confirmed > ordered

    dates = pd.to_datetime(frame["Document Date"], errors="coerce")
    frame["month"] = dates.dt.to_period("M").astype(str)
    span = f"{dates.min():%Y-%m} to {dates.max():%Y-%m}" if dates.notna().any() else "unknown"
    result.warn(f"observed order window: {span} ({dates.dt.to_period('M').nunique()} months)")

    category = frame["SD Document Category"].astype(str).str.strip().str.upper()
    sales_orders = frame[category == "C"].copy()
    returns = frame[category == "H"].copy()
    other = frame[~category.isin(["C", "H"])]
    if len(other):
        result.reject("SD Document Category neither C nor H", len(other))

    fill = (
        sales_orders["confirmed_quantity"].sum() / sales_orders["ordered_quantity"].sum()
        if sales_orders["ordered_quantity"].sum()
        else 0.0
    )
    result.warn(
        f"sales orders {len(sales_orders):,} lines / returns {len(returns):,}; fill rate {fill:.3f}"
    )

    demand_history = sales_orders.groupby(["active_sku_id", "month"], as_index=False).agg(
        ordered_quantity=("ordered_quantity", "sum"),
        confirmed_quantity=("confirmed_quantity", "sum"),
        lost_quantity=("lost_quantity", "sum"),
        order_value=("order_value", "sum"),
        lost_sale_value=("lost_sale_value", "sum"),
        order_lines=("Sales Document", "count"),
    )

    result.rows_out = len(demand_history)
    result.artifact("demand_history", write_table(demand_history, "facts", "demand_history"))
    result.artifact("orders_clean", write_table(sales_orders, "facts", "orders_clean"))
    result.artifact("returns_history", write_table(returns, "facts", "returns_history"))

    logger.info(f"demand history: {len(demand_history):,} sku-months, fill {fill:.3f}")
    return result
