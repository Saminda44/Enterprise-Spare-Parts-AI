"""The ``/api/v1`` contract the React dashboard speaks, served from the new marts.

Every handler here does three things and no more: filter published rows, sum additive
measures, and rename to the UI's vocabulary. Ratios are quotients of those sums and
distinct counts are row counts on a table whose grain already is that entity, so no
business rule is re-applied in a request. Anything that needed deriving was derived in
``src/dashboard`` and written to a mart.

Where the new design genuinely has no equivalent for a legacy field — the RL agent, SSOP
membership, motorcycle colour — the field is returned empty or zero with the reason
recorded in ``NOT_MODELLED`` rather than filled with a plausible-looking number.
"""

from __future__ import annotations

from fastapi import APIRouter
from src.api.compat import bikes, catalog, eda, exports, parts, pipeline
from src.api.compat.overview import router as overview_router

#: Legacy fields the new design does not produce, and why. Served at /api/v1/not-modelled
#: so the gap is discoverable rather than folklore.
NOT_MODELLED: dict[str, str] = {
    "rl_*": "the RL agent is out of scope in this design (CLAUDE.md section 7)",
    "in_ssop": "SSOP.xlsx is out of scope; supersession comes from PN_Yamaha.xlsx",
    "mcsi.by_color": "this MCSI vintage carries no colour column, so no colour cut exists",
    "bikes.geo_color": "same — colour is absent from the vehicle registration extract",
    "on_order": "On_Orders months carry no year or arrival flag, so it resolves to zero",
    "container_utilization": "no container or shipment dimension exists in the sources",
    "movements": "stock movements are out of scope; stock is a snapshot from current_stock.xlsx",
}

router = APIRouter(prefix="/api/v1")
router.include_router(overview_router)
router.include_router(parts.router)
router.include_router(exports.router)
router.include_router(eda.router)
router.include_router(bikes.router)
router.include_router(catalog.router)
router.include_router(pipeline.router)


@router.get("/not-modelled", tags=["compat"])
def not_modelled() -> dict[str, str]:
    """Legacy fields with no equivalent in the new pipeline, and the reason for each."""
    return NOT_MODELLED
