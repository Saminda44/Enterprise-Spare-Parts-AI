"""Generic read access to published tables.

The dashboard needs to render ~30 published tables. Rather than 30 bespoke endpoints,
this exposes them behind one allow-listed reader: it selects, filters, sorts and
paginates rows that a stage already computed and wrote. Nothing is derived here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from src.api.deps import SERVED_TABLES, load, paginate
from src.api.schemas import Page, TableInfo
from src.core.errors import SourceDataError

router = APIRouter(prefix="/tables", tags=["tables"])


@router.get("", response_model=list[TableInfo])
def list_tables() -> list[TableInfo]:
    """Every table the service will serve, with its row count."""
    out: list[TableInfo] = []
    for name, layer in SERVED_TABLES.items():
        try:
            frame = load(name)
        except (SourceDataError, FileNotFoundError):
            out.append(TableInfo(table=name, layer=layer, present=False, rows=0, columns=[]))
            continue
        out.append(
            TableInfo(
                table=name,
                layer=layer,
                present=True,
                rows=len(frame),
                columns=[str(c) for c in frame.columns],
            )
        )
    return out


@router.get("/{name}", response_model=Page)
def read(
    name: str,
    where: str | None = Query(None, description="column=value equality filter"),
    contains: str | None = Query(None, description="column=substring, case-insensitive"),
    sort: str | None = Query(None, description="column to sort by"),
    desc: bool = True,
    limit: int = Query(100, le=20000, description="hard cap; large tables must be paged"),
    offset: int = 0,
) -> Page:
    """Read one published table."""
    if name not in SERVED_TABLES:
        raise HTTPException(404, f"{name!r} is not a served table")
    try:
        frame = load(name)
    except (SourceDataError, FileNotFoundError) as exc:
        raise HTTPException(404, f"{name!r} has not been produced yet — run the pipeline") from exc

    if where and "=" in where:
        column, _, value = where.partition("=")
        if column not in frame.columns:
            raise HTTPException(422, f"unknown column {column!r}")
        frame = frame[frame[column].astype(str).str.upper() == value.strip().upper()]

    if contains and "=" in contains:
        column, _, value = contains.partition("=")
        if column not in frame.columns:
            raise HTTPException(422, f"unknown column {column!r}")
        frame = frame[frame[column].astype(str).str.contains(value.strip(), case=False, na=False)]

    if sort:
        if sort not in frame.columns:
            raise HTTPException(422, f"unknown sort column {sort!r}")
        frame = frame.sort_values(sort, ascending=not desc, na_position="last")

    rows, total = paginate(frame, limit, offset)
    return Page(total=total, limit=limit, offset=offset, rows=rows)
