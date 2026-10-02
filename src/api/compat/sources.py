"""Preview and publish managed source workbook uploads."""

from __future__ import annotations

import hashlib
import hmac
import io
import threading
from datetime import date
from typing import Annotated
from zipfile import BadZipFile, ZipFile

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pandera.errors import SchemaError, SchemaErrors
from src.core.errors import SourceDataError
from src.core.settings import get_settings
from src.ingestion.merge import UPDATE_KEYS, UPLOADABLE, MergeResult, merge_upload
from src.ingestion.store import source_store
from src.ingestion.summary import SummaryResult, rebuild_sales_summary

router = APIRouter(tags=["sources"])
_APPLY_LOCK = threading.Lock()
MAX_UPLOAD_BYTES = 120 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1200 * 1024 * 1024


def _authorize(request: Request) -> None:
    key = get_settings().upload_api_key.get_secret_value()
    if key:
        if not hmac.compare_digest(request.headers.get("X-Upload-Key", ""), key):
            raise HTTPException(403, "upload key required")
    elif not request.client or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "uploads are local-only until SPI_UPLOAD_API_KEY is configured")


def _read_upload(data: bytes) -> pd.DataFrame:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Excel upload is empty or exceeds 120 MB")
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if not members or sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(413, "Excel workbook expands beyond the upload limit")
            if any(item.flag_bits & 1 for item in members):
                raise HTTPException(422, "encrypted Excel workbooks are not supported")
            if "xl/workbook.xml" not in archive.namelist():
                raise HTTPException(422, "not an .xlsx workbook")
        return pd.read_excel(io.BytesIO(data), sheet_name=0)
    except BadZipFile as exc:
        raise HTTPException(422, "not a valid .xlsx workbook") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "Excel workbook could not be read") from exc


def _preview_payload(
    name: str, result: MergeResult, version: str, summary: SummaryResult | None
) -> dict:
    warnings = list(result.warnings)
    if summary:
        if summary.unknown_models:
            warnings.append(f"{summary.unknown_models} model(s) need classification review")
        if summary.unknown_colors:
            warnings.append(f"{summary.unknown_colors} color(s) need mapping review")
    return {
        "name": name,
        "version": version,
        "incoming": result.incoming,
        "added": result.added,
        "replaced": result.replaced,
        "unchanged": result.unchanged,
        "conflicts": result.conflicts,
        "result_rows": len(result.frame),
        "warnings": warnings,
        "notes": list(result.notes),
        "summary_updated": summary is not None,
    }


def _snapshot_metadata_changed(
    name: str, snapshot_as_of: date | None, metadata: dict
) -> bool:
    """Return whether a stock-date confirmation changes the active source metadata.

    Business meaning: the owner may confirm the snapshot date after the workbook was
    already supplied; that confirmation must not be discarded just because no stock
    quantity changed.
    """
    return (
        name == "current_stock.xlsx"
        and snapshot_as_of is not None
        and metadata.get("stock_snapshot_as_of") != snapshot_as_of.isoformat()
    )


def _prepare(
    name: str, data: bytes, replace_dealers: bool
) -> tuple[dict, MergeResult, SummaryResult | None]:
    if name not in UPLOADABLE:
        raise HTTPException(422, "unsupported source workbook")
    store = source_store()
    version = store.version(name)
    incoming = _read_upload(data)
    current = next(iter(store.read(name).values()))
    # Stock and on-order lines find their row through the supersession chain too.
    pn_yamaha = next(iter(store.read("PN_Yamaha.xlsx").values())) if name in UPDATE_KEYS else None
    try:
        merged = merge_upload(
            name, current, incoming, replace_dealers=replace_dealers, pn_yamaha=pn_yamaha
        )
        summary = (
            rebuild_sales_summary(store.read("Sales_Summery.xlsx"), merged.frame)
            if name == "MCSI.xlsx" and merged.added > 0
            else None
        )
    except (SchemaError, SchemaErrors) as exc:
        raise HTTPException(
            422, "source schema validation failed; check required numeric columns"
        ) from exc
    except SourceDataError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _preview_payload(name, merged, version["version_id"], summary), merged, summary


@router.get("/sources")
def list_sources(request: Request) -> dict:
    """Show each active source version, without exposing source rows."""
    _authorize(request)
    store = source_store()
    items = []
    for name in UPLOADABLE:
        version = store.version(name)
        items.append(
            {
                "name": name,
                "version": version["version_id"],
                "source_modified": version["source_modified"],
                "metadata": version["metadata"],
                "managed": not version.get("path") or "working_sources" in str(version["path"]),
            }
        )
    return {"backend": get_settings().data_backend, "sources": items}


@router.post("/sources/preview")
async def preview_source(
    request: Request,
    name: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    replace_dealers: Annotated[bool, Form()] = False,
) -> dict:
    """Parse and reconcile an upload without changing a source version."""
    _authorize(request)
    payload, _, _ = _prepare(name, await file.read(MAX_UPLOAD_BYTES + 1), replace_dealers)
    return payload


@router.post("/sources/apply")
async def apply_source(
    request: Request,
    name: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    expected_version: Annotated[str, Form()],
    replace_dealers: Annotated[bool, Form()] = False,
    confirm_snapshot: Annotated[bool, Form()] = False,
    stock_snapshot_as_of: Annotated[date | None, Form()] = None,
) -> dict:
    """Publish an approved version and refresh the dependent planning stages."""
    _authorize(request)
    # Stock and open orders are updated per material, so no complete-snapshot
    # confirmation is needed (confirm_snapshot is accepted for older clients).
    del confirm_snapshot
    if name == "current_stock.xlsx" and stock_snapshot_as_of is None:
        raise HTTPException(422, "stock snapshot date is required")
    if name == "current_stock.xlsx" and stock_snapshot_as_of > date.today():
        raise HTTPException(422, "stock snapshot date cannot be in the future")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not _APPLY_LOCK.acquire(blocking=False):
        raise HTTPException(409, "another source upload is being applied")
    try:
        from src.refresh import _LOCK as refresh_lock
        from src.refresh import refresh_in_background

        if refresh_lock.locked():
            raise HTTPException(409, "a pipeline refresh is running; retry when it finishes")
        payload, merged, summary = _prepare(name, data, replace_dealers)
        if payload["version"] != expected_version:
            raise HTTPException(409, "source changed after preview; preview this upload again")
        store = source_store()
        active_version = store.version(name)
        metadata_changed = _snapshot_metadata_changed(
            name, stock_snapshot_as_of, active_version["metadata"]
        )
        if merged.added == 0 and merged.replaced == 0 and not metadata_changed:
            return {**payload, "applied": False, "refresh_started": False}
        metadata = {
            **active_version["metadata"],
            "incoming": merged.incoming,
            "added": merged.added,
            "replaced": merged.replaced,
            "unchanged": merged.unchanged,
            "conflicts": merged.conflicts,
            "warnings": payload["warnings"],
            "notes": payload["notes"],
        }
        if stock_snapshot_as_of and name == "current_stock.xlsx":
            metadata["stock_snapshot_as_of"] = stock_snapshot_as_of.isoformat()
        digest = hashlib.sha256(data).hexdigest()
        sheet_name = next(iter(store.read(name)))
        store.publish(name, {sheet_name: merged.frame}, upload_sha256=digest, metadata=metadata)
        if summary:
            store.publish(
                "Sales_Summery.xlsx",
                summary.sheets,
                upload_sha256=digest,
                metadata={
                    "derived_from": "MCSI.xlsx",
                    "mcsi_version": store.version(name)["version_id"],
                    "unknown_models": summary.unknown_models,
                    "unknown_colors": summary.unknown_colors,
                },
            )
        started = refresh_in_background(f"{name} uploaded")
        return {**payload, "applied": True, "refresh_started": started}
    finally:
        _APPLY_LOCK.release()
