"""Filtering and ratio helpers shared by the compatibility handlers.

The EDA marts are published at ``(year, dealer_type, material_category, <cut>)``. These
helpers narrow those rows to what the UI asked for and take the quotients it displays —
nothing else.
"""

from __future__ import annotations

from contextvars import ContextVar
from functools import lru_cache
from typing import Any

import pandas as pd
from src.io.parquet import read_table, table_exists, table_path

#: The UI's "SpareParts" category means a different row per dealer type.
SPARE_PARTS = {"MC": "MC Spare Parts", "OBM": "OBM Spare Parts"}

#: The UI's category names as they appear in the published marts.
CATEGORY_ALIASES = {
    "Lubricant": ["Lubricant"],
    "Battery": ["Battery"],
    "Tyre": ["Tyre"],
    "SpareParts": ["MC Spare Parts", "OBM Spare Parts"],
}


#: The spare-parts section a request comes from — "MC", "OBM" or None (whole book). Set
#: once per request from its ``segment`` query parameter (``src/api/main.py``).
REQUEST_SEGMENT: ContextVar[str | None] = ContextVar("request_segment", default=None)
#: Within MC: "Spare Parts", "Lubricant", "Battery" or "Tyre" (``?category=``), or None.
REQUEST_CATEGORY: ContextVar[str | None] = ContextVar("request_category", default=None)


def request_segment() -> str | None:
    """The MC / OBM section this request asked for, or None for every part."""
    return REQUEST_SEGMENT.get()


def mart(name: str) -> pd.DataFrame:
    """A published UI mart, cached. Missing tables read as empty, never as an error.

    Business meaning: a request from the MC or OBM spare-parts section sees only that
    section's rows of every mart that carries a ``segment`` column, so every figure on the
    page — totals, lists, charts — is the section's own. Marts without one are shared.
    """
    if not table_exists("marts", name):
        return pd.DataFrame()
    path = table_path("marts", name).resolve()
    stamp = path.stat()
    frame = _cached_mart(name, str(path), stamp.st_mtime_ns, stamp.st_size)
    segment = request_segment()
    if segment and "segment" in frame.columns:
        frame = frame[frame["segment"].astype(str).str.upper() == segment]
    category = REQUEST_CATEGORY.get()
    if category and "part_category" in frame.columns:
        frame = frame[frame["part_category"].astype(str) == category]
    return frame


@lru_cache(maxsize=128)
def _cached_mart(name: str, path: str, modified: int, size: int) -> pd.DataFrame:
    frame = read_table("marts", name)
    if name in {"mart_ui_sku", "mart_ui_service_plan", "mart_ui_part_master_analysis"}:
        frame = frame.copy()
        if "stock_status" in frame:
            frame["stock_status"] = frame["stock_status"].str.lower().replace({"healthy": "ok"})
        if "order_urgency" in frame:
            frame["order_urgency"] = frame["order_urgency"].str.lower()
    return frame


def segment_skus() -> set[str] | None:
    """The ``active_sku_id``s of the requested MC / OBM section, or None for every part.

    For handlers that read facts rather than a segmented mart (history, exports, the Part
    Master fallback): the Part Master analysis mart is the one list of every part with its
    section.
    """
    if request_segment() is None and REQUEST_CATEGORY.get() is None:
        return None
    frame = mart("mart_ui_part_master_analysis")
    return set(frame["active_sku_id"].astype(str)) if "active_sku_id" in frame else set()


def clear_cache() -> None:
    _cached_mart.cache_clear()


def apply_filters(
    frame: pd.DataFrame,
    *,
    dealer_type: str = "ALL",
    mc_category: str = "ALL",
    year: int = 0,
) -> pd.DataFrame:
    """Narrow a published cut to the dashboard's three filters."""
    if frame.empty:
        return frame
    out = frame
    if dealer_type and dealer_type != "ALL" and "dealer_type" in out.columns:
        out = out[out["dealer_type"].astype(str).str.upper() == dealer_type.upper()]
    if mc_category and mc_category != "ALL" and "material_category" in out.columns:
        wanted = CATEGORY_ALIASES.get(mc_category, [mc_category])
        if mc_category == "SpareParts" and dealer_type in SPARE_PARTS:
            wanted = [SPARE_PARTS[dealer_type]]
        out = out[out["material_category"].isin(wanted)]
    if year and "year" in out.columns:
        out = out[pd.to_numeric(out["year"], errors="coerce") == int(year)]
    return out


def collapse(frame: pd.DataFrame, keys: list[str], measures: list[str]) -> pd.DataFrame:
    """Sum the additive measures away from the filter dimensions."""
    if frame.empty:
        return pd.DataFrame(columns=[*keys, *measures])
    present_keys = [k for k in keys if k in frame.columns]
    present_measures = [m for m in measures if m in frame.columns]
    if not present_keys:
        return frame[present_measures].sum().to_frame().T
    return frame.groupby(present_keys, as_index=False, dropna=False)[present_measures].sum()


def ratio(numerator: float, denominator: float, *, scale: float = 1.0) -> float:
    """A quotient of two published sums, zero when there is nothing to divide by."""
    if denominator in (0, None) or pd.isna(denominator):
        return 0.0
    value = float(numerator) / float(denominator) * scale
    return 0.0 if pd.isna(value) else float(value)


def f(value: Any, default: float = 0.0) -> float:
    """A JSON-safe float. NaN and inf become the default — the UI calls .toFixed on these."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(out) or out in (float("inf"), float("-inf")):
        return default
    return out


def i(value: Any, default: int = 0) -> int:
    """A JSON-safe int."""
    return int(f(value, default))


def s(value: Any, default: str = "") -> str:
    """A JSON-safe string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return str(value)


def years_available(frame: pd.DataFrame) -> list[int]:
    """The years present on a published cut, for the UI's year picker."""
    if frame.empty or "year" not in frame.columns:
        return []
    values = pd.to_numeric(frame["year"], errors="coerce").dropna().astype(int)
    return sorted({int(v) for v in values if v > 0})


def records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    """Rows as JSON-safe dicts."""
    if frame.empty:
        return []
    out = frame.head(limit) if limit else frame
    return out.replace({pd.NA: None}).where(pd.notna(out), None).to_dict("records")
