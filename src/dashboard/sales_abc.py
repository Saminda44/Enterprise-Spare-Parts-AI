"""Billed-sales classification for the dashboard.

The link from sales.xlsx to Part Master SKUs, and the ABC / XYZ / FSN built on it, are
made once in Step 06 (``src/demand/sales_link.py``) — the same classes that set fill-rate
targets. This module only reshapes those published facts for the UI marts.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.demand import sales_link
from src.io.parquet import read_table, table_exists

#: Kept for callers of the previous module; the rule lives in ``sales_link``.
sales_abc_classes = sales_link.value_classes

CLASS_COLUMNS = [
    "active_sku_id",
    "sales_abc",
    "sales_xyz",
    "sales_fsn",
    "sales_net_lkr",
    "sales_qty",
    "billed_lines",
    "sales_months",
    "last_sale_month",
    "sales_link",
]


def audit_mart(audit: dict[str, object], classes: pd.DataFrame) -> pd.DataFrame:
    """One audit row: the previous UI fields plus the scope and resolution counts.

    Business meaning: every billed line is accounted for — out of scope, linked (and how),
    or left unattributed — so the UI can say how much of the value the classes rest on.
    """
    get = lambda key: audit.get(key, 0)  # noqa: E731 - tiny local accessor
    resolved = int(get("demand_resolved_lines")) + int(get("demand_split_lines"))
    return pd.DataFrame(
        [
            {
                "source": audit.get("source", "sales.xlsx"),
                "window_start": str(audit.get("window_start", "")),
                "window_end": str(audit.get("window_end", "")),
                "sales_lines": int(get("sales_lines")),
                "code_linked_lines": int(get("code_lines")),
                "description_linked_lines": int(get("description_lines")) + resolved,
                "unmapped_lines": int(get("ambiguous_lines")) + int(get("no_match_lines")),
                "ambiguous_lines": int(get("ambiguous_lines")),
                "no_match_lines": int(get("no_match_lines")),
                "linked_skus": int(get("linked_skus") or len(classes)),
                "active_skus": int(len(classes)),
                "return_only_skus": int(get("return_only_skus")),
                "out_of_scope_lines": int(get("out_of_scope_lines")),
                "out_of_scope_value": float(get("out_of_scope_value")),
                "in_scope_lines": int(get("in_scope_lines")),
                "in_scope_value": float(get("in_scope_value")),
                "linked_value": float(get("linked_value")),
                "demand_resolved_lines": int(get("demand_resolved_lines")),
                "demand_split_lines": int(get("demand_split_lines")),
            }
        ]
    )


def build(
    master: pd.DataFrame,
    sales: pd.DataFrame,
    as_of: date,
    order_demand: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Link and classify directly — for callers without Step 06's published facts."""
    demand = order_demand if order_demand is not None else pd.Series(dtype=float)
    alloc, audit = sales_link.link_lines(master, sales, demand, as_of)
    classes = sales_link.classify(alloc, str(audit["window_end"]))
    audit["linked_skus"] = int(alloc["active_sku_id"].nunique()) if len(alloc) else 0
    audit["return_only_skus"] = audit["linked_skus"] - len(classes)
    return classes[CLASS_COLUMNS], audit_mart(audit, classes)


def published() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Step 06's sales classes and link audit, reshaped for the marts; None if not run."""
    if not (
        table_exists("facts", "sales_classification") and table_exists("facts", "sales_link_audit")
    ):
        return None
    classes = read_table("facts", "sales_classification")
    audit = read_table("facts", "sales_link_audit").iloc[0].to_dict()
    return classes[CLASS_COLUMNS], audit_mart(audit, classes)
