"""Link billed sales (sales.xlsx) to Part Master SKUs, and classify parts on them.

sales.xlsx carries no part number for most lines — its ``Material`` column is the
description — so every link is made on the description, and a description that names
several parts is resolved with dealer order demand (orders.xlsx does carry part numbers).
Nothing is guessed: a line that cannot be attributed stays unattributed and is counted.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pandera.pandas as pa

from src.core.contracts import validate
from src.parts.supersession import normalise

#: Months of billed sales the classification looks back over.
SALES_WINDOW_MONTHS = 12
#: Pareto cuts on net billed value: A = first 80%, B = next 15%, C = the rest.
ABC_VALUE_CUTS = (0.80, 0.95)
#: Coefficient-of-variation cuts on monthly quantity sold.
XYZ_CV_CUTS = (0.5, 1.0)
#: Months since the last sale for F (fast) and S (slow); older or none is N.
FSN_MONTHS = (3, 12)
#: Material-group family = the first five characters (``AWPYM0021`` -> ``AWPYM``). A sale
#: is in scope when its family is one the Part Master carries.
GROUP_FAMILY_CHARS = 5

#: How a line reached its SKU, strongest first.
LINK_CODE = "code"
LINK_DESCRIPTION = "description"
LINK_DEMAND_RESOLVED = "demand_resolved"
LINK_DEMAND_SPLIT = "demand_split"
LINK_AMBIGUOUS = "ambiguous"
LINK_NO_MATCH = "no_match"
LINK_OUT_OF_SCOPE = "out_of_scope"
LINKED = (LINK_CODE, LINK_DESCRIPTION, LINK_DEMAND_RESOLVED, LINK_DEMAND_SPLIT)

MASTER_SCHEMA = pa.DataFrameSchema(
    {
        "material": pa.Column(str, nullable=False),
        "active_sku_id": pa.Column(str, nullable=False),
        "description": pa.Column(str, nullable=True),
        "material_group": pa.Column(object, nullable=True, required=False),
    }
)
SALES_SCHEMA = pa.DataFrameSchema(
    {
        "material_code": pa.Column(object, nullable=True),
        "material_description": pa.Column(object, nullable=True),
        "month": pa.Column(object, nullable=True),
        "Net Sales": pa.Column(float, nullable=False, coerce=True),
        "SlsVolQty": pa.Column(float, nullable=False, coerce=True),
        "is_return": pa.Column(bool, nullable=False),
    }
)


def description_key(values: pd.Series) -> pd.Series:
    """Upper-cased, whitespace-collapsed description — the only key sales.xlsx offers."""
    return values.fillna("").astype(str).str.strip().str.upper().str.split().str.join(" ")


def sales_window(sales_months: pd.Series, as_of: date) -> tuple[pd.Period, pd.Period]:
    """The last ``SALES_WINDOW_MONTHS`` months of billed sales that actually exist.

    Business meaning: the window ends at the last month with billing, never after the
    planning cycle. sales.xlsx lags the order file, so a window ending at the cycle would
    see only the few months the two overlap and classify parts on a fragment of a year.
    """
    cycle_end = pd.Period(as_of, freq="M") - 1
    months = pd.to_datetime(sales_months, format="%Y-%m", errors="coerce").dt.to_period("M")
    observed = months[months.notna() & (months <= cycle_end)]
    end = observed.max() if len(observed) else cycle_end
    # Billing that stopped more than a window before the cycle is too old to rank parts on;
    # the window then sits on the cycle and finds nothing, rather than reviving stale sales.
    if (cycle_end - end).n >= SALES_WINDOW_MONTHS:
        end = cycle_end
    return end - (SALES_WINDOW_MONTHS - 1), end


def value_classes(net_value: pd.Series) -> pd.Series:
    """ABC on net billed value; a part whose value crosses a boundary takes the band it entered.

    Business meaning: net returns never count as consumption, so non-positive value is C.
    """
    ranked = net_value.clip(lower=0).sort_values(ascending=False)
    total = ranked.sum()
    if total <= 0:
        return pd.Series("C", index=net_value.index)
    preceding = ranked.cumsum().shift(fill_value=0) / total
    labels = np.where(
        preceding < ABC_VALUE_CUTS[0], "A", np.where(preceding < ABC_VALUE_CUTS[1], "B", "C")
    )
    return pd.Series(labels, index=ranked.index).reindex(net_value.index)


def _unique(keys: pd.Series, skus: pd.Series) -> tuple[pd.Series, pd.Series]:
    pairs = pd.DataFrame({"key": keys, "sku": skus})
    pairs = pairs[pairs["key"].ne("")]
    counts = pairs.groupby("key")["sku"].nunique()
    return pairs.groupby("key")["sku"].first()[counts == 1], counts


def link_lines(
    master: pd.DataFrame,
    sales: pd.DataFrame,
    order_demand: pd.Series,
    as_of: date,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Attribute every in-window sales line to SKUs, with a weight and a method.

    Args:
        master: Part Master rows (``material``, ``active_sku_id``, ``description``,
            optionally ``material_group``).
        sales: billed lines from Step 04 (``parts_sales``).
        order_demand: ordered quantity per ``active_sku_id`` over the same window — the
            evidence used to resolve a description that names several parts.
        as_of: the planning cycle; the window never runs past it.

    Returns:
        (allocations, audit). ``allocations`` has one row per line and SKU with
        ``weight`` (the line's share, summing to 1 per attributed line), the weighted
        ``net_value`` and ``quantity``, and ``link``. ``audit`` counts lines and value
        per outcome.

    Business meaning: a part number wins over a description; a unique description is
    taken as is; an ambiguous one goes to the only candidate dealers ordered, or is split
    by their order share when several were ordered; with no order evidence it is left
    unattributed rather than spread evenly over parts that may never have sold.
    """
    master = validate(master.copy(), MASTER_SCHEMA, stage="06_classification", table="part master")
    sales = validate(sales.copy(), SALES_SCHEMA, stage="06_classification", table="parts_sales")

    start, end = sales_window(sales["month"], as_of)
    months = pd.to_datetime(sales["month"], format="%Y-%m", errors="coerce").dt.to_period("M")
    window = sales.loc[months.between(start, end)].copy()
    window["line_id"] = np.arange(len(window))
    window["month"] = months.loc[window.index].astype(str)

    families = (
        set(master["material_group"].dropna().astype(str).str.strip().str[:GROUP_FAMILY_CHARS])
        if "material_group" in master.columns
        else set()
    )
    sale_group = (
        window["Matl Group"].astype("object")
        if "Matl Group" in window.columns
        else pd.Series(None, index=window.index, dtype="object")
    )
    sale_family = sale_group.astype(str).str.strip().str[:GROUP_FAMILY_CHARS]
    coded = window["material_code"].notna() & window["material_code"].astype(str).str.strip().ne("")
    # A line with no group is judged by its match, not excluded blind; with no groups in
    # the master at all there is nothing to scope on, so every line is in scope.
    in_scope = coded | sale_group.isna() | sale_family.isin(families)
    if not families:
        in_scope[:] = True

    code_lookup, _ = _unique(master["material"].map(normalise), master["active_sku_id"])
    desc_keys = description_key(master["description"])
    candidates = (
        pd.DataFrame({"key": desc_keys, "sku": master["active_sku_id"]})
        .query("key != ''")
        .groupby("key")["sku"]
        .agg(lambda s: sorted(set(s)))
    )

    rows: list[tuple[int, str, float, str]] = []
    outcome = pd.Series(LINK_OUT_OF_SCOPE, index=window.index, dtype="object")
    code_hit = window["material_code"].map(normalise).map(code_lookup)
    sale_keys = description_key(window["material_description"])
    demand = order_demand.astype(float)
    resolved: dict[str, pd.Series] = {}  # one resolution per ambiguous description
    for idx in window.index[in_scope.to_numpy()]:
        line = int(window.at[idx, "line_id"])
        # A code that names no Part Master number is not evidence; the description decides.
        if coded.at[idx] and pd.notna(code_hit.at[idx]):
            rows.append((line, str(code_hit.at[idx]), 1.0, LINK_CODE))
            outcome.at[idx] = LINK_CODE
            continue
        options = candidates.get(sale_keys.at[idx])
        if not options:
            outcome.at[idx] = LINK_NO_MATCH
            continue
        if len(options) == 1:
            rows.append((line, options[0], 1.0, LINK_DESCRIPTION))
            outcome.at[idx] = LINK_DESCRIPTION
            continue
        key = sale_keys.at[idx]
        if key not in resolved:
            found = demand.reindex(options).fillna(0.0)
            resolved[key] = found[found > 0]
        evidence = resolved[key]
        if evidence.empty:
            outcome.at[idx] = LINK_AMBIGUOUS
        elif len(evidence) == 1:
            rows.append((line, str(evidence.index[0]), 1.0, LINK_DEMAND_RESOLVED))
            outcome.at[idx] = LINK_DEMAND_RESOLVED
        else:
            shares = evidence / evidence.sum()
            rows.extend((line, str(sku), float(w), LINK_DEMAND_SPLIT) for sku, w in shares.items())
            outcome.at[idx] = LINK_DEMAND_SPLIT

    alloc = pd.DataFrame(rows, columns=["line_id", "active_sku_id", "weight", "link"])
    lines = window.set_index("line_id")
    alloc["month"] = alloc["line_id"].map(lines["month"])
    alloc["net_value"] = alloc["line_id"].map(lines["Net Sales"]) * alloc["weight"]
    alloc["quantity"] = alloc["line_id"].map(lines["SlsVolQty"]) * alloc["weight"]
    alloc["is_return"] = alloc["line_id"].map(lines["is_return"]).astype(bool)

    value = window["Net Sales"]
    audit: dict[str, object] = {
        "source": "sales.xlsx",
        "window_start": str(start),
        "window_end": str(end),
        "sales_lines": int(len(window)),
        "sales_value": float(value.sum()),
        "out_of_scope_lines": int(outcome.eq(LINK_OUT_OF_SCOPE).sum()),
        "out_of_scope_value": float(value[outcome.eq(LINK_OUT_OF_SCOPE)].sum()),
        "in_scope_lines": int(in_scope.sum()),
        "in_scope_value": float(value[in_scope].sum()),
    }
    for name in (*LINKED, LINK_AMBIGUOUS, LINK_NO_MATCH):
        audit[f"{name}_lines"] = int(outcome.eq(name).sum())
        audit[f"{name}_value"] = float(value[outcome.eq(name)].sum())
    audit["linked_lines"] = int(outcome.isin(LINKED).sum())
    audit["linked_value"] = float(value[outcome.isin(LINKED)].sum())
    return alloc, audit


def classify(alloc: pd.DataFrame, window_end: str) -> pd.DataFrame:
    """Per-SKU billed value, quantity and the sales ABC / XYZ / FSN labels.

    Business meaning: only SKUs with at least one real (non-return) sale are classified —
    a part that was only returned has no consumption to rank. XYZ is the variability of
    monthly quantity sold over the window; FSN is how recently it last sold.
    """
    columns = [
        "active_sku_id",
        "sales_net_lkr",
        "sales_qty",
        "billed_lines",
        "sales_months",
        "last_sale_month",
        "sales_link",
        "sales_abc",
        "sales_xyz",
        "sales_fsn",
    ]
    if alloc.empty:
        return pd.DataFrame(columns=columns)
    sales_only = alloc[~alloc["is_return"] & (alloc["quantity"] > 0)]
    per_sku = alloc.groupby("active_sku_id").agg(
        sales_net_lkr=("net_value", "sum"),
        sales_qty=("quantity", "sum"),
        billed_lines=("line_id", "nunique"),
    )
    sold = sales_only.groupby("active_sku_id").agg(
        sales_months=("month", "nunique"), last_sale_month=("month", "max")
    )
    per_sku = per_sku.join(sold, how="inner")
    # The method that carried most of a SKU's value names how it was linked.
    by_link = alloc.groupby(["active_sku_id", "link"])["net_value"].sum().abs().reset_index()
    per_sku["sales_link"] = (
        by_link.sort_values("net_value", ascending=False)
        .drop_duplicates("active_sku_id")
        .set_index("active_sku_id")["link"]
    )
    per_sku["sales_abc"] = value_classes(per_sku["sales_net_lkr"])

    end = pd.Period(window_end, freq="M")
    months = pd.period_range(end - (SALES_WINDOW_MONTHS - 1), end, freq="M").astype(str)
    monthly = (
        alloc.pivot_table(index="active_sku_id", columns="month", values="quantity", aggfunc="sum")
        .reindex(index=per_sku.index, columns=months)
        .fillna(0.0)
        .clip(lower=0)
    )
    mean = monthly.mean(axis=1)
    cv = (monthly.std(axis=1, ddof=0) / mean.where(mean > 0)).fillna(np.inf)
    per_sku["sales_xyz"] = np.where(
        cv <= XYZ_CV_CUTS[0], "X", np.where(cv <= XYZ_CV_CUTS[1], "Y", "Z")
    )
    since = [
        (end - pd.Period(m, freq="M")).n + 1 if isinstance(m, str) else np.inf
        for m in per_sku["last_sale_month"]
    ]
    per_sku["sales_fsn"] = np.where(
        np.array(since) <= FSN_MONTHS[0], "F", np.where(np.array(since) <= FSN_MONTHS[1], "S", "N")
    )
    return per_sku.reset_index()[columns]
