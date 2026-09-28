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
from src.io.parquet import read_table, table_exists, table_path

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


@router.get("/policy/export.xlsx")
def export_policy(
    urgency: str | None = None,
    tier: str | None = None,
    ss_method: str | None = None,
    search: str | None = None,
) -> Response:
    """Download the same final order shown on the existing Order Plan screen."""
    if not table_exists("marts", "mart_monthly_order"):
        raise HTTPException(503, "monthly order mart unavailable")
    proposal = read_table("marts", "mart_monthly_order")
    if any((urgency, tier, ss_method, search)):
        from src.api.compat.parts import _sku

        sku = _sku(urgency=urgency, tier=tier, ss_method=ss_method, search=search)
        if sku.empty:
            raise HTTPException(503, "dashboard mart unavailable")
        keys = sku["active_sku_id"]
        proposal = proposal[proposal["active_sku_id"].isin(keys)]
    settings = get_settings()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=settings.root, capture_output=True, text=True, check=False
    )
    hashes = {
        "mart_monthly_order.parquet": hashlib.sha256(
            table_path("marts", "mart_monthly_order").read_bytes()
        ).hexdigest()
    }
    for path in sorted(settings.source_parquet_dir.glob("*.meta.json")):
        info = json.loads(path.read_text(encoding="utf-8"))
        hashes[path.name] = info.get(
            "source_sha256", info.get("sha256", info.get("source_hash", "see source metadata"))
        )
    metadata = {
        "source_file_hashes": json.dumps(hashes, sort_keys=True),
        "code_commit_sha": commit.stdout.strip() or "unavailable",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model_version": "planning-pipeline-v1",
        "currency": settings.currency,
        "assumptions": json.dumps(settings.summary(), default=str),
    }
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
