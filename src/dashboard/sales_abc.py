"""Billed-sales ABC for the dashboard, linked conservatively to Part Master SKUs."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pandera.pandas as pa

from src.core.contracts import validate
from src.parts.supersession import normalise

SALES_ABC_MONTHS = 12
ABC_VALUE_CUTS = (0.80, 0.95)


def _description_key(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().str.upper().str.split().str.join(" ")


def _unique_lookup(keys: pd.Series, active_skus: pd.Series) -> pd.Series:
    pairs = pd.DataFrame({"key": keys, "active_sku_id": active_skus})
    pairs = pairs[pairs["key"].ne("")]
    grouped = pairs.groupby("key")["active_sku_id"]
    return grouped.first()[grouped.nunique() == 1]


def sales_abc_classes(net_sales: pd.Series) -> pd.Series:
    """Pareto classes from positive net billed sales, keeping nonpositive values in C.

    Business meaning: a SKU that crosses a Pareto boundary belongs to the class whose
    value band it entered; a net return never counts as positive consumption value.
    """
    ranked = net_sales.clip(lower=0).sort_values(ascending=False)
    total = ranked.sum()
    if total <= 0:
        return pd.Series("C", index=net_sales.index)
    preceding_share = ranked.cumsum().shift(fill_value=0) / total
    labels = np.where(
        preceding_share < ABC_VALUE_CUTS[0],
        "A",
        np.where(preceding_share < ABC_VALUE_CUTS[1], "B", "C"),
    )
    return pd.Series(labels, index=ranked.index).reindex(net_sales.index)


def build(
    master: pd.DataFrame, sales: pd.DataFrame, as_of: date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resolve coded or unique-description sales and publish trailing-year ABC.

    Business meaning: coded material numbers take precedence, including superseded
    numbers. Description-only lines count only when that exact normalized description
    names one active SKU. Ambiguous sales remain unattributed, never guessed.
    """
    master = validate(
        master.copy(),
        pa.DataFrameSchema(
            {
                "material": pa.Column(str, nullable=False),
                "active_sku_id": pa.Column(str, nullable=False),
                "description": pa.Column(str, nullable=True),
            }
        ),
        stage="15_dashboard",
        table="part_master_enriched for sales ABC",
    )
    sales = validate(
        sales.copy(),
        pa.DataFrameSchema(
            {
                "material_code": pa.Column(object, nullable=True),
                "material_description": pa.Column(object, nullable=True),
                "month": pa.Column(object, nullable=True),
                "Net Sales": pa.Column(float, nullable=False, coerce=True),
                "SlsVolQty": pa.Column(float, nullable=False, coerce=True),
                "is_return": pa.Column(bool, nullable=False),
            }
        ),
        stage="15_dashboard",
        table="parts_sales for sales ABC",
    )

    end = pd.Period(as_of, freq="M") - 1
    start = end - (SALES_ABC_MONTHS - 1)
    months = pd.to_datetime(sales["month"], format="%Y-%m", errors="coerce").dt.to_period("M")
    window = sales.loc[months.between(start, end)].copy()

    material_keys = master["material"].map(normalise)
    description_keys = _description_key(master["description"])
    code_lookup = _unique_lookup(material_keys, master["active_sku_id"])
    description_lookup = _unique_lookup(description_keys, master["active_sku_id"])
    code_counts = (
        pd.DataFrame({"key": material_keys, "active": master["active_sku_id"]})
        .groupby("key")["active"]
        .nunique()
    )
    description_counts = (
        pd.DataFrame({"key": description_keys, "active": master["active_sku_id"]})
        .groupby("key")["active"]
        .nunique()
    )
    coded = window["material_code"].notna() & window["material_code"].astype(str).str.strip().ne("")
    sale_codes = window["material_code"].map(normalise)
    sale_descriptions = _description_key(window["material_description"])
    code_match = sale_codes.map(code_lookup)
    description_match = sale_descriptions.map(description_lookup)
    active = code_match.where(coded, description_match)
    ambiguous = (coded & sale_codes.map(code_counts).gt(1)) | (
        ~coded & sale_descriptions.map(description_counts).gt(1)
    )
    method = pd.Series(
        np.where(
            coded & active.notna(), "code", np.where(active.notna(), "description", "unmapped")
        ),
        index=window.index,
    )
    linked = window.loc[active.notna(), ["Net Sales", "SlsVolQty", "is_return"]].copy()
    linked["active_sku_id"] = active.loc[active.notna()]
    linked["is_sale"] = ~linked["is_return"] & linked["SlsVolQty"].gt(0)

    if linked.empty:
        out = pd.DataFrame(columns=["active_sku_id", "sales_abc", "sales_net_lkr", "billed_lines"])
        linked_skus = 0
        return_only_skus = 0
    else:
        grouped = linked.groupby("active_sku_id", as_index=False).agg(
            sales_net_lkr=("Net Sales", "sum"),
            billed_lines=("Net Sales", "size"),
            sale_lines=("is_sale", "sum"),
        )
        linked_skus = len(grouped)
        return_only_skus = int(grouped["sale_lines"].eq(0).sum())
        out = grouped.loc[grouped["sale_lines"].gt(0)].drop(columns="sale_lines").copy()
        out["sales_abc"] = sales_abc_classes(out["sales_net_lkr"])

    audit = pd.DataFrame(
        [
            {
                "source": "sales.xlsx",
                "window_start": str(start),
                "window_end": str(end),
                "sales_lines": len(window),
                "code_linked_lines": int(method.eq("code").sum()),
                "description_linked_lines": int(method.eq("description").sum()),
                "unmapped_lines": int(method.eq("unmapped").sum()),
                "ambiguous_lines": int(ambiguous.sum()),
                "no_match_lines": int((method.eq("unmapped") & ~ambiguous).sum()),
                "linked_skus": linked_skus,
                "active_skus": len(out),
                "return_only_skus": return_only_skus,
                "nonpositive_skus": int((out["sales_net_lkr"] <= 0).sum()) if not out.empty else 0,
            }
        ]
    )
    return out, audit
