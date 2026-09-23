"""Demand, parc, inventory and the order proposal — all served straight from marts."""

from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from src.api.deps import load, paginate
from src.api.schemas import Page

demand = APIRouter(prefix="/demand", tags=["demand"])
parc = APIRouter(prefix="/parc", tags=["parc"])
inventory = APIRouter(prefix="/inventory", tags=["inventory"])
orders = APIRouter(prefix="/orders", tags=["orders"])


@demand.get("/{sku}/history", response_model=Page)
def history(sku: str, limit: int = Query(200, le=1000), offset: int = 0) -> Page:
    """Monthly ordered, confirmed and lost quantity for one part."""
    frame = load("demand_history")
    frame = frame[frame["active_sku_id"] == sku].sort_values("month")
    if frame.empty:
        raise HTTPException(404, f"no demand history for {sku!r}")
    rows, total = paginate(frame, limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)


@demand.get("/{sku}/forecast", response_model=Page)
def forecast(sku: str) -> Page:
    """mu, sigma, quantiles and the method that produced them."""
    frame = load("forecast_protection")
    frame = frame[frame["active_sku_id"] == sku]
    if frame.empty:
        raise HTTPException(404, f"no forecast for {sku!r}")
    rows, total = paginate(frame, 1, 0)
    return Page(total=total, limit=1, offset=0, rows=rows)


@parc.get("/uio", response_model=Page)
def uio(
    model: str | None = None,
    year: int | None = None,
    scenario: str = "base",
    limit: int = Query(200, le=2000),
    offset: int = 0,
) -> Page:
    """Units in operation by model, year and age bucket."""
    frame = load("uio_age_matrix")
    frame = frame[frame["scenario"] == scenario]
    if model:
        frame = frame[frame["enterprise_model_id"].astype(str).str.upper() == model.upper()]
    if year:
        frame = frame[frame["year"] == year]
    rows, total = paginate(frame, limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)


@parc.get("/scenarios", response_model=Page)
def scenarios(limit: int = Query(50, le=200), offset: int = 0) -> Page:
    """The scenario definitions Step 11 published.

    Running a new scenario is a pipeline job, not a request handler — see POST /runs.
    """
    rows, total = paginate(load("scenarios"), limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)


@inventory.get("/{sku}/position", response_model=Page)
def position(sku: str) -> Page:
    """on_hand, on_order and IP for one part."""
    frame = load("stock_position")
    frame = frame[frame["active_sku_id"] == sku]
    if frame.empty:
        raise HTTPException(404, f"no stock position for {sku!r}")
    rows, total = paginate(frame, 1, 0)
    return Page(total=total, limit=1, offset=0, rows=rows)


@inventory.get("/policy/{sku}", response_model=Page)
def policy(sku: str) -> Page:
    """Safety stock, ROL, ROQ, the chosen policy and the parameters behind it."""
    params = load("policy_params")
    params = params[params["active_sku_id"] == sku]
    if params.empty:
        raise HTTPException(404, f"no policy for {sku!r}")
    selection = load("policy_selection")
    merged = params.merge(selection[["active_sku_id", "policy"]], on="active_sku_id", how="left")
    rows, total = paginate(merged, 1, 0)
    return Page(total=total, limit=1, offset=0, rows=rows)


def _proposal(cycle: str | None, triggered_only: bool) -> pd.DataFrame:
    frame = load("mart_monthly_order")
    if cycle:
        frame = frame[frame["cycle_month"] == cycle]
    if triggered_only:
        frame = frame[frame["q_final"] > 0]
    return frame.sort_values("value", ascending=False)


@orders.get("/proposal", response_model=Page)
def proposal(
    cycle: str | None = Query(None, description="YYYY-MM"),
    abc: str | None = None,
    policy: str | None = None,
    limit: int = Query(100, le=2000),
    offset: int = 0,
) -> Page:
    """The monthly order proposal.

    This is a **recommendation**. There is no endpoint that submits a purchase order to
    SAP — a human sends the order.
    """
    frame = _proposal(cycle, triggered_only=True)
    if abc:
        frame = frame[frame["abc_class"].astype(str).str.upper() == abc.upper()]
    if policy:
        frame = frame[frame["policy"].astype(str).str.upper() == policy.upper()]
    rows, total = paginate(frame, limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)


@orders.get("/proposal.csv")
def proposal_csv(cycle: str | None = None) -> StreamingResponse:
    """Buyer-ready export of the same recommendation."""
    frame = _proposal(cycle, triggered_only=True)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    name = f"order_proposal_{cycle or 'latest'}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
