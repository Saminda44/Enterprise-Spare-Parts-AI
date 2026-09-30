"""Step 15 — the FastAPI service.

The API serves published marts and computes nothing. Every figure it returns was
computed in a step, tested, and written to a table. There is no endpoint that submits a
purchase order to SAP: the proposal is a recommendation and a human sends the order.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from src.api.compat import router as compatibility_router
from src.api.compat.filters import REQUEST_CATEGORY, REQUEST_SEGMENT
from src.api.deps import freshness
from src.api.routers import parts, runs, tables
from src.api.routers.planning import demand, inventory, orders, parc
from src.api.schemas import Health, TableFreshness
from src.core.settings import get_settings
from src.dashboard.segments import CATEGORY_KEYS, SEGMENTS
from src.stages import load_stages

#: Serve the original dashboard against the current planning API on one origin.
DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"

load_stages()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Keep the analysis in step with the source workbooks (see ``src/refresh.py``)."""
    if get_settings().auto_refresh_sources:
        from src.refresh import start_watcher, stop_watcher  # noqa: PLC0415

        start_watcher()
        yield
        stop_watcher()
    else:
        yield


app = FastAPI(
    lifespan=lifespan,
    title="Yamaha Spare Parts Planning",
    version="1.0.0",
    description=(
        "Parts search, demand, parc, policy and the monthly order proposal. "
        "Serves published marts; computes nothing in a request handler."
    ),
)

app.include_router(compatibility_router)
app.include_router(parts.router)
app.include_router(demand)
app.include_router(parc)
app.include_router(inventory)
app.include_router(orders)
app.include_router(tables.router)
app.include_router(runs.router)


@app.middleware("http")
async def attach_run_id(request: Request, call_next):  # noqa: ANN001, ANN201 - ASGI signature
    """A request id threaded through every log line."""
    request_id = uuid.uuid4().hex[:8]
    # The MC / OBM spare-parts section the page belongs to; every mart with a segment column
    # is narrowed to it for this request (src/api/compat/filters.py).
    segment = (request.query_params.get("segment") or "").strip().upper()
    token = REQUEST_SEGMENT.set(segment if segment in SEGMENTS else None)
    category = CATEGORY_KEYS.get((request.query_params.get("category") or "").strip().lower())
    category_token = REQUEST_CATEGORY.set(category)
    try:
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)
    finally:
        REQUEST_SEGMENT.reset(token)
        REQUEST_CATEGORY.reset(category_token)
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


@app.get("/info", tags=["ops"])
def index() -> dict[str, object]:
    settings = get_settings()
    return {
        "service": "Yamaha Spare Parts Planning",
        "docs": "/docs",
        "dashboard": "/" if DASHBOARD_DIR.joinpath("index.html").exists() else None,
        "plant": settings.plant,
        "lead_time_months": settings.lead_time_months,
        "protection_interval_months": settings.lead_time_months + settings.review_period_months,
        "on_order_interpretation": settings.on_order_interpretation,
        "note": "The order proposal is a recommendation. No endpoint writes to SAP.",
    }


# --------------------------------------------------------------------- dashboard
# Registered last, so every API route above wins the match. What is left is either a
# built asset or a client-side route, and a client-side route has to return index.html
# for a deep link or a page reload to work.
if DASHBOARD_DIR.joinpath("assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def dashboard(path: str) -> FileResponse:
    """Serve the existing dashboard, or say plainly that it has not been built."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "unknown API endpoint")
    index_html = DASHBOARD_DIR / "index.html"
    if not index_html.exists():
        raise HTTPException(
            404,
            "dashboard not built — run `npm run build` in frontend/, or use /docs for the API",
        )
    # A request for a real file (favicon, a root-level asset) is served as itself; a
    # path with no file behind it is a client-side route and gets the shell.
    candidate = (DASHBOARD_DIR / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(DASHBOARD_DIR.resolve()):
        return FileResponse(candidate)
    return FileResponse(index_html)
