"""Orders and sales EDA marts, published at the grain the dashboard filters on.

The UI filters every EDA figure by dealer type, material category and year. Publishing
one pre-rolled answer per combination would mean 45 copies of fifteen tables, so instead
each cut is published at the grain ``(year, dealer_type, material_category, <cut>)``
carrying **only additive measures** — line counts, quantities and values.

The API then filters rows and sums. Ratios it needs (fill rate, value share, return rate)
are quotients of those sums, and distinct counts come from counting rows on the table
whose grain already *is* that entity. No business rule is re-applied in a request
handler; the category split, the C/H document split and the lost-quantity definition all
happen once, here.
"""

from __future__ import annotations

import pandas as pd

from src.core.result import StageResult
from src.io.parquet import read_table

#: Additive measures every orders cut carries.
ORDER_MEASURES = [
    "order_lines",
    "ordered_quantity",
    "confirmed_quantity",
    "lost_quantity",
    "ordered_value",
    "confirmed_value",
    "lost_sale_value",
]

#: The dimensions the UI filters on. Present on every cut so one filter works everywhere.
FILTERS = ["year", "dealer_type", "material_category"]

#: CLAUDE.md's stop-and-ask threshold: one dealer above this share of a month's return
#: value is a concentration worth a human look, not a number to average away.
RETURN_CONCENTRATION_PCT = 40.0


#: Material category shown for a dealer missing from dealers.xlsx (Dealer Type "Not Found").
NOT_IN_MASTER = "Dealer not in master"


def _category_label(frame: pd.DataFrame) -> pd.Series:
    """Material category, with dealer-master gaps named instead of shown as "Unknown".

    Business meaning: the category rule needs the dealer's type (MC / OBM). A dealer not in
    dealers.xlsx has none, so its lines have no category — they are real demand and stay
    in, labelled for what they are so the gap can be fixed in the dealer master.
    """
    category = frame["material_category"].astype("object")
    missing = category.isna() | category.astype(str).str.strip().isin(["", "Unknown", "nan"])
    not_found = (
        frame["dealer_type"].astype(str).str.strip().str.lower().isin(["not found", "unknown"])
    )
    return category.where(~(missing & not_found), NOT_IN_MASTER).fillna("Unknown")


def _prepare_orders() -> pd.DataFrame:
    """Order lines with the filter dimensions and additive measures attached."""
    frame = read_table("facts", "orders_clean").copy()
    frame["month"] = frame["month"].astype(str)
    frame["year"] = (
        pd.to_numeric(frame["month"].str.slice(0, 4), errors="coerce").fillna(0).astype(int)
    )
    frame["dealer_type"] = frame.get("Dealer Type", pd.Series("Unknown", index=frame.index)).fillna(
        "Unknown"
    )
    frame["material_category"] = _category_label(frame)
    frame["order_lines"] = 1
    # Step 03 publishes `order_value` as confirmed quantity x price — what the dealer will
    # actually be billed for. What they *asked* for is that plus the measured lost sale,
    # which reconciles with the source's own `Net Value (Item)` to within rounding. Both
    # are published under names that cannot be mistaken for each other.
    frame["confirmed_value"] = pd.to_numeric(frame["order_value"], errors="coerce").fillna(0.0)
    frame["ordered_value"] = frame["confirmed_value"] + pd.to_numeric(
        frame["lost_sale_value"], errors="coerce"
    ).fillna(0.0)
    for column in ORDER_MEASURES:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def _prepare_returns() -> pd.DataFrame:
    """Return lines (SD document category H), kept apart from demand."""
    frame = read_table("facts", "returns_history").copy()
    frame["month"] = frame["month"].astype(str)
    frame["year"] = (
        pd.to_numeric(frame["month"].str.slice(0, 4), errors="coerce").fillna(0).astype(int)
    )
    frame["dealer_type"] = frame.get("Dealer Type", pd.Series("Unknown", index=frame.index)).fillna(
        "Unknown"
    )
    frame["material_category"] = _category_label(frame)
    frame["return_lines"] = 1
    frame["return_quantity"] = pd.to_numeric(frame["ordered_quantity"], errors="coerce").fillna(0.0)
    frame["return_value"] = pd.to_numeric(frame["order_value"], errors="coerce").fillna(0.0).abs()
    return frame


def _cut(frame: pd.DataFrame, keys: list[str], measures: list[str]) -> pd.DataFrame:
    """Group to ``FILTERS + keys`` summing ``measures``. Empty groups are dropped."""
    present = [k for k in keys if k in frame.columns]
    group = FILTERS + present
    out = frame.groupby(group, as_index=False, dropna=False)[measures].sum()
    for key in present:
        out[key] = out[key].fillna("Unknown").astype(str)
    return out


def build_orders(result: StageResult) -> dict[str, pd.DataFrame]:
    """Every orders-EDA cut the dashboard asks for."""
    orders = _prepare_orders()
    returns = _prepare_returns()

    tables: dict[str, pd.DataFrame] = {}

    tables["mart_ui_orders_monthly"] = _cut(orders, ["month"], ORDER_MEASURES)
    tables["mart_ui_orders_by_part"] = _cut(
        orders, ["active_sku_id", "Material Description"], ORDER_MEASURES
    ).rename(columns={"Material Description": "description"})
    tables["mart_ui_orders_by_dealer"] = _cut(
        orders,
        ["Sold-to Party", "Sold-To Party Name", "Province", "District", "RM", "ASE"],
        ORDER_MEASURES,
    ).rename(
        columns={
            "Sold-to Party": "dealer_code",
            "Sold-To Party Name": "dealer_name",
            "Province": "province",
            "District": "district",
            "RM": "rm",
            "ASE": "ase",
        }
    )
    tables["mart_ui_orders_by_rm"] = _cut(orders, ["RM", "Province"], ORDER_MEASURES).rename(
        columns={"RM": "rm", "Province": "province"}
    )
    tables["mart_ui_orders_by_ase"] = _cut(
        orders, ["ASE", "RM", "Province"], ORDER_MEASURES
    ).rename(columns={"ASE": "ase", "RM": "rm", "Province": "province"})
    tables["mart_ui_orders_by_district"] = _cut(
        orders, ["Province", "District"], ORDER_MEASURES
    ).rename(columns={"Province": "province", "District": "district"})
    tables["mart_ui_orders_by_province"] = _cut(orders, ["Province"], ORDER_MEASURES).rename(
        columns={"Province": "province"}
    )

    # Fulfilment at line level, bucketed the way the UI shows it.
    ordered = orders["ordered_quantity"]
    confirmed = orders["confirmed_quantity"]
    bucket = pd.Series("partially confirmed", index=orders.index, dtype=object)
    bucket[confirmed >= ordered] = "fully confirmed"
    bucket[confirmed <= 0] = "fully rejected"
    orders = orders.assign(fulfilment_class=bucket)
    tables["mart_ui_orders_fulfilment"] = _cut(orders, ["fulfilment_class"], ORDER_MEASURES)

    # Documents, so "fully filled / partial / zero" can be reported per purchase order.
    doc = orders.groupby(
        ["year", "dealer_type", "material_category", "Sales Document"], as_index=False
    )[["ordered_quantity", "confirmed_quantity"]].sum()
    doc_class = pd.Series("partial_fill", index=doc.index, dtype=object)
    doc_class[doc["confirmed_quantity"] >= doc["ordered_quantity"]] = "fully_filled"
    doc_class[doc["confirmed_quantity"] <= 0] = "complete_zero"
    doc = doc.assign(doc_class=doc_class, documents=1)
    tables["mart_ui_orders_documents"] = doc.groupby(
        [*FILTERS, "doc_class"], as_index=False, dropna=False
    )["documents"].sum()

    # Why lines were rejected, as recorded on the line — not inferred from the shortfall.
    reason = orders.copy()
    reason["reason"] = (
        reason.get("Reason for Rejection", pd.Series("", index=reason.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "not recorded")
    )
    rejected = reason[reason["lost_quantity"] > 0]
    tables["mart_ui_orders_reasons"] = (
        rejected.groupby([*FILTERS, "reason"], as_index=False, dropna=False)
        .agg(rejected_lines=("order_lines", "sum"), rejected_qty=("lost_quantity", "sum"))
        .sort_values("rejected_qty", ascending=False)
    )

    # The worst individual short-shipments, for the rejections table.
    worst = (
        rejected.sort_values("lost_quantity", ascending=False)
        .head(2000)[
            [
                *FILTERS,
                "Material",
                "Material Description",
                "Sold-To Party Name",
                "Document Date",
                "ordered_quantity",
                "lost_quantity",
                "confirmed_quantity",
                "reason",
            ]
        ]
        .rename(
            columns={
                "Material": "material",
                "Material Description": "description",
                "Sold-To Party Name": "customer",
                "Document Date": "document_date",
                "ordered_quantity": "order_qty",
                "lost_quantity": "lost_qty",
            }
        )
    )
    worst["document_date"] = worst["document_date"].astype(str)
    tables["mart_ui_orders_rejections"] = worst

    # Returns, kept as their own cut so they are never netted into demand.
    return_measures = ["return_lines", "return_quantity", "return_value"]
    tables["mart_ui_returns_monthly"] = _cut(returns, ["month"], return_measures)
    tables["mart_ui_returns_by_dealer"] = _cut(
        returns, ["Sold-to Party", "Sold-To Party Name"], return_measures
    ).rename(columns={"Sold-to Party": "dealer_code", "Sold-To Party Name": "dealer_name"})
    returns_reason = returns.copy()
    returns_reason["reason"] = (
        returns_reason.get("Reason for Rejection", pd.Series("", index=returns_reason.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "not recorded")
    )
    tables["mart_ui_returns_reasons"] = (
        returns_reason.groupby([*FILTERS, "reason"], as_index=False, dropna=False)
        .agg(rejected_lines=("return_lines", "sum"), rejected_qty=("return_quantity", "sum"))
        .sort_values("rejected_qty", ascending=False)
    )
    tables["mart_ui_returns_by_type"] = (
        returns.groupby([*FILTERS, "Sales Document Type"], as_index=False, dropna=False)[
            "return_lines"
        ]
        .sum()
        .rename(columns={"Sales Document Type": "document_type"})
    )

    # CLAUDE.md's stop-and-ask rule: a single dealer above 40% of a month's return value
    # is flagged. Computed here, once, rather than re-derived per request.
    by_dealer_month = returns.groupby(
        ["month", "Sold-to Party", "Sold-To Party Name"], as_index=False, dropna=False
    )["return_value"].sum()
    month_total = (
        by_dealer_month.groupby("month", as_index=False)["return_value"]
        .sum()
        .rename(columns={"return_value": "month_total"})
    )
    concentration = by_dealer_month.merge(month_total, on="month", how="left")
    concentration["return_share_pct"] = (
        concentration["return_value"] / concentration["month_total"].replace(0, pd.NA) * 100.0
    ).fillna(0.0)
    concentration = concentration.rename(
        columns={"Sold-to Party": "dealer_code", "Sold-To Party Name": "dealer_name"}
    )
    flagged = concentration[concentration["return_share_pct"] >= RETURN_CONCENTRATION_PCT]
    tables["mart_ui_return_concentration"] = flagged.sort_values(
        "return_share_pct", ascending=False
    ).reset_index(drop=True)
    if not flagged.empty:
        result.warn(
            f"return concentration: {len(flagged)} dealer-month(s) at or above "
            f"{RETURN_CONCENTRATION_PCT:.0f}% of that month's return value — flagged for review"
        )

    result.warn(
        f"orders EDA cuts: {len(orders):,} lines and {len(returns):,} return lines rolled into "
        f"{len([k for k in tables if k.startswith('mart_ui_orders')])} orders cuts, "
        f"years {sorted(orders['year'].unique().tolist())}"
    )
    return tables


def build_sales(result: StageResult) -> dict[str, pd.DataFrame]:
    """Every billed-sales cut the dashboard asks for."""
    sales = read_table("facts", "parts_sales").copy()
    sales["month"] = sales["month"].astype(str)
    sales["year"] = (
        pd.to_numeric(sales["month"].str.slice(0, 4), errors="coerce").fillna(0).astype(int)
    )
    sales["dealer_type"] = sales.get("Dealer Type", pd.Series("Unknown", index=sales.index)).fillna(
        "Unknown"
    )
    sales["material_category"] = sales["material_category"].fillna("Unknown")

    is_return = sales["is_return"].fillna(False).astype(bool)
    value = pd.to_numeric(sales["Net Sales"], errors="coerce").fillna(0.0)
    qty = pd.to_numeric(sales["SlsVolQty"], errors="coerce").fillna(0.0)

    sales["sale_lines"] = (~is_return).astype(int)
    sales["return_lines"] = is_return.astype(int)
    sales["sale_value_lkr"] = value.where(~is_return, 0.0)
    sales["return_value_lkr"] = value.where(is_return, 0.0).abs()
    sales["sale_qty"] = qty.where(~is_return, 0.0)
    sales["return_qty"] = qty.where(is_return, 0.0).abs()
    sales["margin_lkr"] = pd.to_numeric(sales["margin"], errors="coerce").fillna(0.0)

    measures = [
        "sale_lines",
        "return_lines",
        "sale_value_lkr",
        "return_value_lkr",
        "sale_qty",
        "return_qty",
        "margin_lkr",
    ]

    tables: dict[str, pd.DataFrame] = {}
    tables["mart_ui_sales_monthly"] = _cut(sales, ["month"], measures)
    tables["mart_ui_sales_by_part"] = _cut(sales, ["material_description"], measures).rename(
        columns={"material_description": "material"}
    )
    tables["mart_ui_sales_by_dealer"] = _cut(
        sales, ["payer_name", "Province", "District", "RM", "ASE"], measures
    ).rename(
        columns={
            "payer_name": "dealer_name",
            "Province": "province",
            "District": "district",
            "RM": "rm",
            "ASE": "ase",
        }
    )
    tables["mart_ui_sales_by_rm"] = _cut(sales, ["RM"], measures).rename(columns={"RM": "rm"})
    tables["mart_ui_sales_by_ase"] = _cut(sales, ["ASE", "RM"], measures).rename(
        columns={"ASE": "ase", "RM": "rm"}
    )
    tables["mart_ui_sales_by_district"] = _cut(sales, ["Province", "District"], measures).rename(
        columns={"Province": "province", "District": "district"}
    )
    tables["mart_ui_sales_by_province"] = _cut(sales, ["Province"], measures).rename(
        columns={"Province": "province"}
    )

    # Distinct SKUs per dealer cannot be summed, so it is published at the dealer grain.
    skus = (
        sales.groupby([*FILTERS, "payer_name"], as_index=False, dropna=False)[
            "material_description"
        ]
        .nunique()
        .rename(columns={"payer_name": "dealer_name", "material_description": "unique_skus"})
    )
    tables["mart_ui_sales_by_dealer"] = tables["mart_ui_sales_by_dealer"].merge(
        skus, on=[*FILTERS, "dealer_name"], how="left"
    )
    tables["mart_ui_sales_by_dealer"]["unique_skus"] = (
        tables["mart_ui_sales_by_dealer"]["unique_skus"].fillna(0).astype(int)
    )

    invoices = (
        sales.groupby(FILTERS, as_index=False, dropna=False)["Billing Document"]
        .nunique()
        .rename(columns={"Billing Document": "invoices"})
    )
    tables["mart_ui_sales_invoices"] = invoices

    result.warn(
        f"sales EDA cuts: {len(sales):,} billed lines, "
        f"net {sales['sale_value_lkr'].sum() - sales['return_value_lkr'].sum():,.0f} LKR"
    )
    return tables
