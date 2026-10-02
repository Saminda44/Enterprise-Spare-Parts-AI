"""Existing order-plan Excel download, reconciled to the published proposal."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from src.core.errors import ContractViolation
from src.core.settings import get_settings
from src.io.parquet import table_exists, table_path

router = APIRouter(tags=["exports"])


def order_workbook(proposal: pd.DataFrame, metadata: dict[str, Any]) -> bytes:
    """Write an order workbook and verify its quantities and values round-trip.

    Business meaning: exported quantities are the published final recommendation,
    including MOQ and pack rounding; every sheet identifies its provenance.
    """
    stream = BytesIO()
    with pd.ExcelWriter(
        stream,
        engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as writer:
        proposal.to_excel(writer, sheet_name="Order Plan", index=False)
        pd.DataFrame(
            {"field": list(metadata), "value": [str(v) for v in metadata.values()]}
        ).to_excel(writer, sheet_name="Metadata", index=False)
        footer = "Source hashes, commit, timestamp and model version: see Metadata sheet"
        for sheet in writer.sheets.values():
            sheet.set_footer("&L" + footer)
    payload = stream.getvalue()
    restored = pd.read_excel(
        BytesIO(payload), sheet_name="Order Plan", dtype={"active_sku_id": str}
    )
    if len(restored) != len(proposal):
        raise ContractViolation("order export row count failed round-trip")
    for column in ("q_final", "value"):
        if column in proposal:
            pd.testing.assert_series_equal(
                restored[column].astype(float),
                proposal[column].reset_index(drop=True).astype(float),
                check_names=False,
            )
    if (
        "active_sku_id" in proposal
        and restored["active_sku_id"].tolist() != proposal["active_sku_id"].astype(str).tolist()
    ):
        raise ContractViolation("order export identity failed round-trip")
    return payload


#: The buyer-ready order sheet (owner, 2026-10-02): readable headings, no internal codes.
ORDER_SHEET = {
    "active_sku_id": "Part no.",
    "description": "Description",
    "abc": "ABC",
    "q_final": "Order qty",
    "unit_cost": "Unit cost (LKR)",
    "value": "Value (LKR)",
    "expected_arrival": "Arrives (month)",
    "forecast_month": "Forecast / month",
    "safety_stock": "Buffer stock",
    "reorder_level": "Reorder level",
    "stock_checked": "On hand + on order",
    "needs_check": "Needs a second look",
    "check_reasons": "Why",
}
REVIEW_SHEET = {
    "active_sku_id": "Part no.",
    "description": "Description",
    "abc": "ABC",
    "q_review": "Held qty",
    "value_review": "Held value (LKR)",
    "recommendation": "Recommendation",
    "suggested_qty": "Suggested qty",
    "suggested_value": "Suggested value (LKR)",
    "recommendation_reason": "Why",
    "recent_monthly_demand": "Recent orders / month",
    "stock_checked": "On hand + on order",
}
EXPEDITE_SHEET = {
    "active_sku_id": "Part no.",
    "description": "Description",
    "abc": "ABC",
    "forecast_month": "Forecast / month",
    "on_hand": "On hand",
    "incoming": "Incoming by month",
    "run_out_month": "Runs out",
    "status": "In this order",
}


def buyer_workbook(plan: pd.DataFrame, metadata: dict[str, Any]) -> bytes:
    """The order a buyer places, the lines a buyer decides on, and parts to expedite.

    Business meaning: one clean sheet to send — part, quantity, cost, value and arrival —
    with the held lines (and what to do with each) and the parts to chase beside it, and
    the provenance every generated report carries. Quantities and values are verified to
    round-trip before the file is served.
    """
    to_order = plan[plan["status"] == "to order"].sort_values("value", ascending=False)
    held = plan[plan["status"] == "held for review"].sort_values("value_review", ascending=False)
    expedite = plan[plan["expedite"].fillna(False).astype(bool)].copy()
    expedite["incoming"] = expedite["incoming_by_month"].map(_incoming_text)
    expedite["status"] = expedite["status"].map(
        {"to order": "ordered", "held for review": "held", "expedite": "not ordered"}
    )
    order_out = to_order[list(ORDER_SHEET)].rename(columns=ORDER_SHEET)
    order_out["Needs a second look"] = order_out["Needs a second look"].map(
        lambda v: "yes" if bool(v) else ""
    )
    stream = BytesIO()
    with pd.ExcelWriter(
        stream,
        engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as writer:
        order_out.to_excel(writer, sheet_name="Order", index=False)
        held[list(REVIEW_SHEET)].rename(columns=REVIEW_SHEET).to_excel(
            writer, sheet_name="Buyer review", index=False
        )
        expedite[list(EXPEDITE_SHEET)].rename(columns=EXPEDITE_SHEET).to_excel(
            writer, sheet_name="Expedite", index=False
        )
        pd.DataFrame(
            {"field": list(metadata), "value": [str(v) for v in metadata.values()]}
        ).to_excel(writer, sheet_name="Metadata", index=False)
        footer = "Source hashes, commit, timestamp and model version: see Metadata sheet"
        for sheet in writer.sheets.values():
            sheet.set_footer("&L" + footer)
    payload = stream.getvalue()
    restored = pd.read_excel(BytesIO(payload), sheet_name="Order", dtype={"Part no.": str})
    if (
        len(restored) != len(to_order)
        or restored["Part no."].tolist() != to_order["active_sku_id"].astype(str).tolist()
    ):
        raise ContractViolation("order export identity failed round-trip")
    for column, heading in (("q_final", "Order qty"), ("value", "Value (LKR)")):
        pd.testing.assert_series_equal(
            restored[heading].astype(float),
            to_order[column].reset_index(drop=True).astype(float),
            check_names=False,
        )
    return payload


def _incoming_text(raw: object) -> str:
    try:
        items = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return ""
    return ", ".join(f"{i['month']}: {i['qty']:,.0f}" for i in items)


@router.get("/policy/export.xlsx")
def export_policy(
    urgency: str | None = None,
    tier: str | None = None,
    ss_method: str | None = None,
    search: str | None = None,
) -> Response:
    """Download the buyer-ready order for the section shown on the Order Plan screen."""
    from src.api.compat.context import published_order_hold_reason  # noqa: PLC0415
    from src.api.compat.filters import mart  # noqa: PLC0415

    hold_reason = published_order_hold_reason()
    if hold_reason:
        raise HTTPException(409, hold_reason)
    plan = mart("mart_ui_order_plan")
    if plan.empty or "stock_checked" not in plan:
        return _legacy_export(urgency, tier, ss_method, search)
    if any((urgency, tier, ss_method, search)):
        from src.api.compat.parts import _sku

        sku = _sku(urgency=urgency, tier=tier, ss_method=ss_method, search=search)
        if sku.empty:
            raise HTTPException(503, "dashboard mart unavailable")
        plan = plan[plan["active_sku_id"].isin(sku["active_sku_id"])]
    settings = get_settings()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=settings.root, capture_output=True, text=True, check=False
    )
    hashes = {
        f"{name}.parquet": hashlib.sha256(table_path("marts", name).read_bytes()).hexdigest()
        for name in ("mart_ui_order_plan", "mart_monthly_order")
        if table_exists("marts", name)
    }
    for path in sorted(settings.source_parquet_dir.glob("*.meta.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        hashes[path.name] = info.get(
            "source_sha256", info.get("sha256", info.get("source_hash", "see source metadata"))
        )
    metadata = {
        "cycle_month": str(plan["cycle_month"].iloc[0]),
        "order_arrives": str(plan["expected_arrival"].iloc[0]),
        "source_file_hashes": json.dumps(hashes, sort_keys=True),
        "code_commit_sha": commit.stdout.strip() or "unavailable",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model_version": "planning-pipeline-v1 · ROL = 1 month + buffer (≤ 3 months), "
        "checked on on hand + all on order; EOQ ≤ 3 months",
        "currency": settings.currency,
        "assumptions": json.dumps(settings.summary(), default=str),
    }
    return Response(
        buyer_workbook(plan, metadata),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="order-plan.xlsx"'},
    )


def _legacy_export(
    urgency: str | None, tier: str | None, ss_method: str | None, search: str | None
) -> Response:
    """The published proposal as-is, for marts built before the reworked order plan."""
    if not table_exists("marts", "mart_monthly_order"):
        raise HTTPException(503, "monthly order mart unavailable")
    from src.api.compat.filters import segment_skus  # noqa: PLC0415
    from src.io.parquet import read_table  # noqa: PLC0415

    proposal = read_table("marts", "mart_monthly_order")
    scope = segment_skus()
    if scope is not None:
        proposal = proposal[proposal["active_sku_id"].astype(str).isin(scope)]
    if any((urgency, tier, ss_method, search)):
        from src.api.compat.parts import _sku  # noqa: PLC0415

        sku = _sku(urgency=urgency, tier=tier, ss_method=ss_method, search=search)
        if sku.empty:
            raise HTTPException(503, "dashboard mart unavailable")
        proposal = proposal[proposal["active_sku_id"].isin(sku["active_sku_id"])]
    metadata = _provenance(["mart_monthly_order"])
    metadata["currency"] = get_settings().currency
    metadata["assumptions"] = json.dumps(get_settings().summary(), default=str)
    return Response(
        order_workbook(proposal, metadata),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="order-plan.xlsx"'},
    )


#: Columns of the classification download, in order, with the headings a buyer reads.
CLASSIFICATION_COLUMNS = {
    "active_sku_id": "Part no.",
    "description": "Description",
    "superseded_numbers": "Superseded numbers",
    "brand": "Brand",
    "material_group": "Material group",
    "compatible_models": "Compatible models",
    "behaviour_class": "Behaviour class",
    "system": "System",
    "catalogue_section": "Catalogue section",
    "behaviour_source": "Behaviour decided by",
    "abc": "Planning ABC",
    "abc_source": "ABC source",
    "sales_abc": "Sales ABC",
    "sales_xyz": "Sales XYZ",
    "sales_fsn": "Sales FSN",
    "sales_link": "Sales linked by",
    "sales_net_lkr": "Billed sales (LKR)",
    "sales_qty": "Billed qty",
    "xyz": "Order XYZ",
    "fsn": "Order FSN",
    "demand_category": "Demand pattern",
    "policy_tier": "Policy",
    "avg_monthly_demand": "Avg monthly demand",
    "sales_activity_12m": "Sales activity (12m)",
    "has_planning": "Has demand history",
}


def _provenance(tables: list[str]) -> dict[str, Any]:
    """Source hashes, commit, timestamp and model version for a generated report."""
    settings = get_settings()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=settings.root, capture_output=True, text=True, check=False
    )
    hashes = {
        f"{name}.parquet": hashlib.sha256(table_path("marts", name).read_bytes()).hexdigest()
        for name in tables
        if table_exists("marts", name)
    }
    for path in sorted(settings.source_parquet_dir.glob("*.meta.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        hashes[path.name] = info.get("source_sha256", info.get("sha256", "see source metadata"))
    return {
        "source_file_hashes": json.dumps(hashes, sort_keys=True),
        "code_commit_sha": commit.stdout.strip() or "unavailable",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model_version": "planning-pipeline-v1",
    }


@router.get("/classification/export.xlsx")
def export_classification(
    abc: str | None = None,
    xyz: str | None = None,
    fsn: str | None = None,
    tier: str | None = None,
    part_type: str | None = None,
    demand_class: str | None = None,
    behaviour: str | None = None,
    system: str | None = None,
    planning_abc: str | None = None,
    abc_source: str | None = None,
    scope: str | None = None,
    search: str | None = None,
) -> Response:
    """Every part matching the SKU Classification filters, as an Excel list.

    Business meaning: the screen pages 100 rows at a time; a planner working a class (all
    A-class wear parts, every electrical part) needs the whole list, with where each label
    came from, and the provenance footer every generated report carries.
    """
    from src.api.compat.parts import classification_frame  # noqa: PLC0415

    filters = {
        "abc": abc,
        "xyz": xyz,
        "fsn": fsn,
        "tier": tier,
        "part_type": part_type,
        "demand_class": demand_class,
        "behaviour": behaviour,
        "system": system,
        "planning_abc": planning_abc,
        "abc_source": abc_source,
        "scope": scope,
        "search": search,
    }
    frame = classification_frame(**filters)
    columns = [c for c in CLASSIFICATION_COLUMNS if c in frame.columns]
    out = (
        frame.sort_values(["behaviour_class", "active_sku_id"], na_position="last")[columns]
        .rename(columns=CLASSIFICATION_COLUMNS)
        .reset_index(drop=True)
    )
    applied = {k: v for k, v in filters.items() if v}
    metadata = {
        **_provenance(["mart_ui_part_master_analysis"]),
        "filters": json.dumps(applied) if applied else "none (whole Part Master)",
        "rows": len(out),
    }
    stream = BytesIO()
    with pd.ExcelWriter(
        stream,
        engine="xlsxwriter",
        engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}},
    ) as writer:
        out.to_excel(writer, sheet_name="Parts", index=False)
        pd.DataFrame(
            {"field": list(metadata), "value": [str(v) for v in metadata.values()]}
        ).to_excel(writer, sheet_name="Metadata", index=False)
        sheet = writer.sheets["Parts"]
        sheet.freeze_panes(1, 1)
        sheet.autofilter(0, 0, max(len(out), 1), max(len(columns) - 1, 0))
        for sheet_obj in writer.sheets.values():
            sheet_obj.set_footer(
                "&LSource hashes, commit, timestamp and model version: see Metadata sheet"
            )
    restored = pd.read_excel(BytesIO(stream.getvalue()), sheet_name="Parts", dtype=str)
    if len(restored) != len(out):
        raise ContractViolation("classification export row count failed round-trip")
    name = "part_classification" + (
        "_" + "_".join(str(v) for v in applied.values()) if applied else ""
    )
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:80]
    return Response(
        stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"'},
    )
