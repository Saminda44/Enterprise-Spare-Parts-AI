"""Pydantic response models. No endpoint returns a raw dataframe dump."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Page(BaseModel):
    total: int = Field(description="Rows available before pagination")
    limit: int
    offset: int
    rows: list[dict[str, Any]]


class TableFreshness(BaseModel):
    table: str
    layer: str
    present: bool
    age_hours: float | None


class Health(BaseModel):
    status: str
    as_of: str | None = None
    tables: list[TableFreshness]


class SupersessionHit(BaseModel):
    part_no: str
    label: str = Field(description="QUERIED | CURRENT | OLDER | RELATED")
    description: str | None = None
    active_sku_id: str | None = None


class SupersessionResponse(BaseModel):
    query: str
    found: bool
    hits: list[SupersessionHit]


class ExplainResponse(BaseModel):
    """The full derivation for one part: forecast to sigma to z to SS to policy to q."""

    active_sku_id: str
    forecast: dict[str, Any]
    lead_time: dict[str, Any]
    safety_stock: dict[str, Any]
    policy: dict[str, Any]
    inventory_position: dict[str, Any]
    order: dict[str, Any]


class RunAccepted(BaseModel):
    run_id: str
    status: str
    detail: str


class RunStatus(BaseModel):
    run_id: str
    status: str
    report: dict[str, Any] | None = None
