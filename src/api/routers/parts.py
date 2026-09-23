"""Parts search, supersession lookup and the per-part explanation."""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from src.api.deps import load, paginate
from src.api.schemas import ExplainResponse, Page, SupersessionHit, SupersessionResponse
from src.parts.supersession import SupersessionLookup, normalise

router = APIRouter(prefix="/parts", tags=["parts"])

_lookup: SupersessionLookup | None = None


def _get_lookup() -> SupersessionLookup:
    global _lookup  # noqa: PLW0603 — process-wide index built once
    if _lookup is None:
        _lookup = SupersessionLookup(load("part_master"))
    return _lookup


@router.get("/search", response_model=Page)
def search(
    q: str = Query("", description="Description or part number, typo tolerant"),
    brand: str | None = None,
    group: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> Page:
    """Search the part master.

    Chroma holds the vector index for this endpoint; until Step 02's embedding pass has
    run, this falls back to a case-insensitive substring match over the same fields.
    """
    frame = load("part_master")
    if brand:
        frame = frame[frame["brand"].astype(str).str.upper() == brand.upper()]
    if group:
        frame = frame[frame["material_group"].astype(str).str.upper() == group.upper()]
    if q:
        needle = q.strip().lower()
        key = normalise(q)
        mask = frame["description"].astype(str).str.lower().str.contains(needle, na=False)
        mask |= frame["material"].map(lambda m: key in normalise(m) if key else False)
        frame = frame[mask]
    rows, total = paginate(frame, limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)


@router.get("/{part_no}/supersession", response_model=SupersessionResponse)
def supersession(part_no: str) -> SupersessionResponse:
    """Every number in the chain, each labelled QUERIED / CURRENT / OLDER / RELATED.

    An unknown number returns not-found rather than a fuzzy guess: a wrong supersession
    merge corrupts every downstream demand series.
    """
    hits = _get_lookup().lookup(part_no)
    return SupersessionResponse(
        query=part_no,
        found=bool(hits),
        hits=[
            SupersessionHit(
                part_no=h.part_no,
                label=h.label,
                description=h.description,
                active_sku_id=h.active_sku_id,
            )
            for h in hits
        ],
    )


def _row(table: str, sku: str) -> dict[str, Any]:
    frame = load(table)
    if "active_sku_id" not in frame.columns:
        return {}
    match = frame[frame["active_sku_id"] == sku]
    if match.empty:
        return {}
    record = match.iloc[0].to_dict()
    return {k: (None if pd.isna(v) else v) for k, v in record.items()}


@router.get("/{sku}/explain", response_model=ExplainResponse)
def explain(sku: str) -> ExplainResponse:
    """The whole derivation for one part, reconciled to the order proposal."""
    order = _row("monthly_order_proposal", sku)
    if not order:
        raise HTTPException(404, f"no order proposal line for {sku!r}")
    forecast = _row("forecast_protection", sku)
    policy = _row("policy_params", sku)
    position = _row("stock_position", sku)

    return ExplainResponse(
        active_sku_id=sku,
        forecast={
            "model": forecast.get("model"),
            "quadrant": forecast.get("quadrant"),
            "mu_month": forecast.get("mu_month"),
            "mu_p": forecast.get("mu_p"),
            "sigma_p": forecast.get("sigma_p"),
            "uncertainty_method": forecast.get("method"),
            "baseline_weight": forecast.get("baseline_weight"),
            "parc_only": forecast.get("parc_only"),
        },
        lead_time={
            "lead_time_months": order.get("lead_time_months"),
            "expected_arrival": order.get("expected_arrival"),
        },
        safety_stock={
            "fill_target": policy.get("fill_target"),
            "z": policy.get("z"),
            "bracketing": policy.get("ss_bracketing"),
            "normal": policy.get("ss_normal"),
            "empirical": policy.get("ss_empirical"),
            "selected": policy.get("safety_stock"),
            "strategy": policy.get("ss_strategy"),
        },
        policy={
            "policy": order.get("policy"),
            "s": order.get("s"),
            "S": order.get("S"),
            "rol": order.get("rol"),
            "trigger_reason": order.get("trigger_reason"),
        },
        inventory_position={
            "on_hand": position.get("on_hand"),
            "on_order": position.get("on_order"),
            "backorders": position.get("backorders"),
            "ip": position.get("ip"),
        },
        order={
            "q_raw": order.get("q_raw"),
            "eoq": order.get("eoq"),
            "q_econ": order.get("q_econ"),
            "q_moq": order.get("q_moq"),
            "q_pack": order.get("q_pack"),
            "q_final": order.get("q_final"),
            "unit_cost": order.get("unit_cost"),
            "value": order.get("value"),
        },
    )
