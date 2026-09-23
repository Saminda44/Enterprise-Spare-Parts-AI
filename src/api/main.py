"""Step 15 — the FastAPI service.

The API serves published marts and computes nothing. Every figure it returns was
computed in a step, tested, and written to a table. There is no endpoint that submits a
purchase order to SAP: the proposal is a recommendation and a human sends the order.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from loguru import logger
from src.api.deps import freshness
from src.api.routers import parts, runs
from src.api.routers.planning import demand, inventory, orders, parc
from src.api.schemas import Health, TableFreshness
from src.core.settings import get_settings
from src.stages import load_stages

load_stages()

app = FastAPI(
    title="Yamaha Spare Parts Planning",
    version="1.0.0",
    description=(
        "Parts search, demand, parc, policy and the monthly order proposal. "
        "Serves published marts; computes nothing in a request handler."
    ),
)

app.include_router(parts.router)
app.include_router(demand)
app.include_router(parc)
app.include_router(inventory)
app.include_router(orders)
app.include_router(runs.router)


@app.middleware("http")
async def attach_run_id(request: Request, call_next):  # noqa: ANN001, ANN201 - ASGI signature
    """A request id threaded through every log line."""
    request_id = uuid.uuid4().hex[:8]
    with logger.contextualize(request_id=request_id):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health", response_model=Health, tags=["ops"])
def health() -> Health:
    """Liveness plus data freshness, so a stale pipeline is visible rather than silently
    serving last month's numbers."""
    tables = freshness()
    present = [t for t in tables if t["present"]]
    newest = min((t["age_hours"] for t in present if t["age_hours"] is not None), default=None)
    return Health(
        status="ok" if present else "no data",
        as_of=f"{newest:.1f}h since the most recent mart" if newest is not None else None,
        tables=[TableFreshness(**t) for t in tables],
    )


@app.get("/", tags=["ops"])
def index() -> dict[str, object]:
    settings = get_settings()
    return {
        "service": "Yamaha Spare Parts Planning",
        "docs": "/docs",
        "plant": settings.plant,
        "lead_time_months": settings.lead_time_months,
        "protection_interval_months": settings.lead_time_months + settings.review_period_months,
        "on_order_interpretation": settings.on_order_interpretation,
        "note": "The order proposal is a recommendation. No endpoint writes to SAP.",
    }
