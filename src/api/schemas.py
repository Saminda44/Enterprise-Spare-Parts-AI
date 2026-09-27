"""Pydantic response models. No endpoint returns a raw dataframe dump."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Page(BaseModel):
    total: int = Field(description="Rows available before pagination")
    limit: int
    offset: int
    rows: list[dict[str, Any]]


class TableInfo(BaseModel):
    table: str
    layer: str
    present: bool
    rows: int
    columns: list[str]


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


# --------------------------------------------------------------- catalogue browser
# The original dashboard's Catalogues page speaks these shapes. They are carried over
# unchanged from the previous build so the page behaves exactly as it did.


class CatalogFile(BaseModel):
    filename: str
    rel_path: str
    size_kb: float


class CatalogModel(BaseModel):
    model: str
    pdf_count: int
    files: list[CatalogFile]


class CatalogResponse(BaseModel):
    models: list[CatalogModel]
    total_pdfs: int


class CatalogCoverageRow(BaseModel):
    model: str
    pdf_count: int
    distinct_parts: int
    ocr_pages: int


class CatalogCoverageResponse(BaseModel):
    extracted: bool
    total_part_references: int
    distinct_parts: int
    distinct_models: int
    rows: list[CatalogCoverageRow]


class CatalogPartRow(BaseModel):
    part_number: str
    source_file: str
    ocr_used: bool
