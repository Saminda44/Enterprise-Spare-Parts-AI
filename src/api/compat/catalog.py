"""Catalogue endpoints — browse and serve the PDF parts catalogues.

Carried over from the previous build, deliberately and close to unchanged: this reads
each PDF live with ``YamahaCatalogueExtractor`` and resolves per-colour builds with
``CatalogueAgent``, rather than answering from Step 01's published facts. Step 01 is a
pipeline extraction tuned for feeding part compatibility downstream; this is the
interactive reader the Catalogues page was built against, and the two are kept separate
on purpose.

Only the wiring changed: module paths, settings-derived directories, and the browser's
own cache moved out of the retired ``data/interim`` and ``data/outputs`` trees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from src.api.schemas import (
    CatalogCoverageResponse,
    CatalogCoverageRow,
    CatalogFile,
    CatalogModel,
    CatalogPartRow,
    CatalogResponse,
)
from src.catalogue.browser.agent import CatalogueAgent
from src.catalogue.browser.overrides import PRODUCT_TYPES, model_folder_of, model_folders
from src.catalogue.browser.overrides import excluded as excluded_catalogues
from src.catalogue.browser.part_master import build_part_master
from src.catalogue.browser.pdf_extractor import DISPLAY_HEADERS, YamahaCatalogueExtractor
from src.catalogue.store import (
    StoredCatalogueReader,
    compatible_models,
    connect,
    ensure_schema,
    file_sha256,
    load_catalogues,
    load_pn_yamaha,
    pn_yamaha_compatibility,
    read_catalogue,
    record_excluded,
    refresh_compatibility,
    save_extraction,
    source_key,
    stored_state,
)
from src.core.errors import CatalogueStoreError, SourceDataError
from src.core.settings import get_settings

_SETTINGS = get_settings()
PDF_ROOT = (_SETTINGS.raw_dir / "pdf_catalogues").resolve()
PDF_EXTS = {".pdf", ".PDF"}
RAW_ROOT = _SETTINGS.raw_dir.resolve()
XLSX_EXTS = {".xlsx", ".xls"}

#: Upload cap. PDFs are untrusted input, so the size is bounded before anything reads it.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: The browser's own cache and exports. Not published marts — a re-read of a PDF is a
#: convenience for whoever is looking at it, not a pipeline fact.
BROWSER_DIR = (_SETTINGS.marts_dir.parent / "catalogue_browser").resolve()
AGENT_CACHE = (BROWSER_DIR / "agent_builds").resolve()

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _identical_copies() -> set[str]:
    """PDFs stored as a byte-identical copy of another, which the page lists once.

    The files stay on disk (``data/raw`` is never modified); the database records each
    as excluded with the file it copies. Empty when the database cannot be reached, so
    nothing is hidden on a guess.
    """
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT source_file FROM catalogues "
                "WHERE status = 'excluded' AND excluded_reason LIKE 'byte-identical copy of %'"
            ).fetchall()
    except CatalogueStoreError:
        return set()
    return {r[0] for r in rows}


@router.get("", response_model=CatalogResponse)
def list_catalog() -> CatalogResponse:
    models: list[CatalogModel] = []
    total = 0

    if not PDF_ROOT.exists():
        return CatalogResponse(models=[], total_pdfs=0)
    hidden = _identical_copies()

    # Model folders sit inside a product folder: pdf_catalogues/MC/AEROX, OBM/F40.
    for product_type, folder in model_folders(PDF_ROOT):
        files: list[CatalogFile] = []
        for pdf in sorted(folder.rglob("*"), key=lambda p: p.name.upper()):
            if pdf.suffix in PDF_EXTS and pdf.is_file():
                rel = pdf.relative_to(PDF_ROOT)
                if rel.as_posix() in hidden:
                    continue  # the same file as another listed PDF
                files.append(
                    CatalogFile(
                        filename=pdf.name,
                        rel_path=rel.as_posix(),
                        size_kb=round(pdf.stat().st_size / 1024, 1),
                    )
                )
        if files:
            total += len(files)
            models.append(
                CatalogModel(
                    model=folder.name,
                    product_type=product_type,
                    pdf_count=len(files),
                    files=files,
                )
            )

    return CatalogResponse(models=models, total_pdfs=total, product_types=list(PRODUCT_TYPES))


@router.get("/file/{file_path:path}")
def serve_pdf(file_path: str) -> FileResponse:
    target = (PDF_ROOT / file_path).resolve()
    # Path traversal guard
    if not str(target).startswith(str(PDF_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists() or target.suffix not in PDF_EXTS:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        str(target), media_type="application/pdf", headers={"Content-Disposition": "inline"}
    )


@router.get("/folders")
def list_folders(product_type: str = Query("MC")) -> list[str]:
    """Model folders of one product type (for the upload folder picker)."""
    product = product_type.strip().upper()
    return [f.name for p, f in model_folders(PDF_ROOT) if p == product]


@router.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),  # noqa: B008
    folder: str = Form(...),
    product_type: str = Form("MC"),
) -> dict[str, str]:
    """Upload a PDF catalogue into pdf_catalogues/{product_type}/{folder}/.

    The model folder is created if needed; the product type (MC or OBM) must be one of
    the product folders.

    Two guards the previous build did not have, because ``data/raw`` is immutable and
    PDFs are untrusted input: an upload only ever *adds* — a name that already exists is
    refused rather than overwritten — and the payload is size-capped before anything
    reads it.
    """
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    folder_clean = folder.strip().strip("/\\")
    if not folder_clean or ".." in folder_clean or "/" in folder_clean or "\\" in folder_clean:
        raise HTTPException(status_code=400, detail="Invalid folder name")

    product = product_type.strip().upper()
    if product not in PRODUCT_TYPES:
        raise HTTPException(status_code=400, detail=f"product_type must be one of {PRODUCT_TYPES}")

    target_dir = (PDF_ROOT / product / folder_clean).resolve()
    if not str(target_dir).startswith(str(PDF_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")

    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / Path(file.filename).name
    if dest.exists():
        raise HTTPException(
            status_code=409,
            detail=f"{dest.name} already exists — catalogue sources are never overwritten",
        )

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"catalogue exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB cap",
        )
    dest.write_bytes(payload)

    return {
        "rel_path": dest.relative_to(PDF_ROOT).as_posix(),
        "filename": dest.name,
        "folder": folder_clean,
        "product_type": product,
    }


_EXTRACTOR = YamahaCatalogueExtractor(max_pages=500)
_PARTS_OUT = BROWSER_DIR / "catalog_parts.parquet"
_PARTS_XLSX = BROWSER_DIR / "catalog_parts.xlsx"


def get_catalog_parts() -> pd.DataFrame:
    """The browser's own batch extraction, empty until /run-extraction has been used."""
    if not _PARTS_OUT.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(str(_PARTS_OUT))
    except (OSError, ValueError):
        return pd.DataFrame()


_EXTRACT_STATUS: dict[str, Any] = {"running": False, "last_result": None}


@router.get("/tables/{file_path:path}")
def extract_pdf_tables(
    file_path: str,
    max_pages: int = Query(200, le=500),
) -> dict[str, Any]:
    """Extract parts from one Yamaha PDF using YamahaCatalogueExtractor.

    Returns up to nine columns depending on PDF type:
        Section | Ref. No. | Part No. | Description | Q'ty
        | 9 Digit Part No. | Superseded Part No. | Remarks
    The extra columns are only populated for India-market PDFs that carry them.
    """
    target = (PDF_ROOT / file_path).resolve()
    if not str(target).startswith(str(PDF_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists() or target.suffix not in PDF_EXTS:
        raise HTTPException(status_code=404, detail="File not found")

    # The stored copy when there is a current one; the PDF itself otherwise.
    result, source = read_catalogue(target, max_pages=max(max_pages, 500))

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    # Column order must match DISPLAY_HEADERS index-for-index:
    # 0=section 1=ref_no 2=part_no 3=description 4=qty
    # 5=nine_digit_part_no 6=escort_part_no 7=superseded_part_no 8=remarks
    _col_keys = [
        "section",
        "ref_no",
        "part_no",
        "description",
        "qty",
        "nine_digit_part_no",
        "escort_part_no",
        "superseded_part_no",
        "remarks",
    ]
    rows = [[r.get(c, "") for c in _col_keys] for r in result.rows]
    sections = sorted({r[0] for r in rows if r[0]})

    # Build desc_colour_hints: a lookup from "part_no::description" → colour_hint
    # used by the frontend to annotate rows in PDFs where colours come from
    # description parentheses (e.g. CRUX-S, LIBERO G5) or part-number suffixes.
    #
    # IMPORTANT: only include rows whose colour_hint came from description/suffix
    # patterns, NOT from FOR/EXCEPT remarks.  For remarks-based hints, the frontend's
    # getRowKind(remarks) already parses them correctly.  Including remarks-derived
    # hints here causes key-collision bugs: the same part_no (e.g. B65-F2865-00-33,
    # a Yamaha-Black-painted COVER FRONT) can appear in multiple rows with DIFFERENT
    # colour hints — e.g. one row "UR FOR YB" (hint=YB) and another "UR YB FOR MS1"
    # (hint=MS1) — and the last-write-wins dict would overwrite the earlier hints,
    # causing parts to appear under the wrong colour filter in the UI.
    #
    # Detection: if the row's remarks contain the word FOR or EXCEPT, the hint came
    # from remarks processing and getRowKind(remarks) handles it correctly → skip.
    # For rows with empty remarks or remarks that lack FOR/EXCEPT (description-based
    # or suffix-based hints), include them in the dict and merge duplicate keys.
    import re as _re

    _FOR_EXCEPT_REM_RE = _re.compile(r"\bFOR\b|\bEXCEPT\b", _re.IGNORECASE)

    desc_colour_hints: dict[str, str] = {}
    for _r in result.rows:
        if not _r.get("colour_hint") or not _r.get("part_no"):
            continue
        _rem = (_r.get("remarks") or "").strip()
        # Skip rows whose hint came from FOR/EXCEPT remarks — the frontend
        # getRowKind(remarks) handles those correctly with no key-collision risk.
        if _rem and _FOR_EXCEPT_REM_RE.search(_rem):
            continue
        _key = f"{_r['part_no']}::{_r.get('description', '')}"
        _new_hint = _r["colour_hint"]
        if _key in desc_colour_hints:
            # Merge: union of comma-separated hint tokens, deduplicated and sorted
            _existing = {h.strip() for h in desc_colour_hints[_key].split(",") if h.strip()}
            _incoming = {h.strip() for h in _new_hint.split(",") if h.strip()}
            desc_colour_hints[_key] = ",".join(sorted(_existing | _incoming))
        else:
            desc_colour_hints[_key] = _new_hint
    desc_colour_mode: bool = bool(desc_colour_hints)

    # Drop optional columns when this PDF has no data in them.
    # nine_digit_part_no=5, escort_part_no=6, superseded_part_no=7 are market-specific.
    # remarks=8 is dropped when the extractor's column recognition did NOT detect a
    # Remarks column in the PDF (e.g. CRUX-S PDFs whose last column is 9 Digit Part No.).
    # The column_layout list is the authoritative signal — it only includes "Remarks"
    # when the extractor saw rem_start < 9000 in the column-bounds scan.
    headers: list[str] = list(DISPLAY_HEADERS)
    # Apply PDF-native labels from extractor (e.g. "Existing Part No." for ENTICER family)
    _labels = result.column_display_labels or {}
    if "part_no" in _labels:
        headers[2] = _labels["part_no"]
    if "description" in _labels:
        headers[3] = _labels["description"]
    if "escort_part_no" in _labels:
        headers[6] = _labels["escort_part_no"]
    _has_remarks_col = any("Remarks" in col for col in (result.column_layout or []))
    optional_cols = [5, 6, 7] if _has_remarks_col else [5, 6, 7, 8]
    drop = [c for c in optional_cols if not any(row[c].strip() for row in rows)]
    if drop:
        keep = [i for i in range(len(headers)) if i not in drop]
        headers = [headers[i] for i in keep]
        rows = [[row[i] for i in keep] for row in rows]

    # When the PDF has no explicit variant codes but has a valid Yamaha type-code,
    # surface it as a single synthetic variant so the UI shows a meaningful chip.
    # Validity rules for a Yamaha type code:
    #   • 3-8 chars, purely alphanumeric, no spaces
    #   • Does NOT contain 4+ consecutive digits (rejects date strings like "JAN2019")
    import re as _re

    _mn = result.model_no or ""
    _valid_code = bool(_re.match(r"^[A-Z0-9]{3,8}$", _mn)) and not bool(_re.search(r"\d{4}", _mn))
    _synth_variant = _mn if _valid_code else ""
    _variants = result.variants or ([_synth_variant] if _synth_variant else [])

    return {
        # "database" for the stored copy, "pdf" when it was read live (not loaded yet,
        # changed since it was stored, or the database is unreachable).
        "source": source,
        "headers": headers,
        "rows": rows,
        "total": len(rows),
        "sections": sections,
        "variants": _variants,
        "colour_codes": result.colour_codes,
        # How is_model_colour was decided: "marked" when the table's abbreviation
        # column carries (*), "parts"/"listed" when it does not, "none" with no table.
        "model_colour_source": result.model_colour_source,
        "available_colours": result.available_colours,
        "manufacture_year": result.manufacture_year,
        "model_no": result.model_no,
        "pages_scanned": result.pages_scanned,
        "sections_found": result.sections_found,
        "ocr_flagged": result.ocr_flagged,
        "warnings": result.warnings,
        "column_layout": result.column_layout,
        "column_display_labels": result.column_display_labels,
        "desc_colour_mode": desc_colour_mode,
        "desc_colour_hints": desc_colour_hints,
        # NEW: Colour matching metadata for debugging
        "colour_extraction_metadata": {
            "source": "pdf_cover" if result.available_colours else "agent_web",
            "unmapped_count": len(result.available_colours or [])
            - len(result.available_colour_map),
            "total_available": len(result.available_colours or []),
            "matched_count": len(result.available_colour_map),
            "has_warnings": any(
                "colour" in w.lower() or "unmapped" in w.lower() for w in result.warnings
            ),
        },
    }


@router.post("/run-extraction")
def run_batch_extraction(background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Extract every PDF catalogue into the browser's own ``catalog_parts.parquet``.

    Runs in the background so the request returns immediately.
    Poll GET /catalog/extraction-status for progress.
    """
    if _EXTRACT_STATUS["running"]:
        return {"queued": False, "message": "Extraction already running"}

    def _run() -> None:
        _EXTRACT_STATUS["running"] = True
        _EXTRACT_STATUS["last_result"] = None
        try:
            BROWSER_DIR.mkdir(parents=True, exist_ok=True)
            df = _EXTRACTOR.extract_all(PDF_ROOT, save_path=_PARTS_OUT)
            # Also save Excel for easy download / business review
            if not df.empty:
                df.to_excel(_PARTS_XLSX, index=False, engine="openpyxl")
            # The legacy build also mirrored this into PostgreSQL; there is no database
            # in this design, so parquet under data/ is the store.
            _EXTRACT_STATUS["last_result"] = {
                "ok": True,
                "total_rows": len(df),
                "distinct_parts": int(df["part_no"].nunique()) if not df.empty else 0,
                "models": int(df["model"].nunique()) if not df.empty else 0,
                "parquet": str(_PARTS_OUT),
                "excel": str(_PARTS_XLSX) if not df.empty else None,
            }
        except Exception as exc:  # noqa: BLE001
            _EXTRACT_STATUS["last_result"] = {"ok": False, "error": str(exc)}
        finally:
            _EXTRACT_STATUS["running"] = False

    background_tasks.add_task(_run)
    return {"queued": True, "message": "Extraction started in background"}


@router.get("/extraction-status")
def get_extraction_status() -> dict[str, Any]:
    """Return current state of the batch extraction job."""
    return {
        "running": _EXTRACT_STATUS["running"],
        "last_result": _EXTRACT_STATUS["last_result"],
        "parquet_exists": _PARTS_OUT.exists(),
        "parquet_size_kb": (
            round(_PARTS_OUT.stat().st_size / 1024, 1) if _PARTS_OUT.exists() else 0
        ),
        "excel_exists": _PARTS_XLSX.exists(),
    }


@router.get("/download")
def download_catalog_excel() -> FileResponse:
    """Download extracted catalog parts as Excel (.xlsx).

    The file is regenerated from the current catalog_parts.parquet on each call
    so it always reflects the latest extraction run.
    Triggers a re-generate if the parquet is newer than the cached Excel.
    """
    if not _PARTS_OUT.exists():
        raise HTTPException(
            status_code=404,
            detail="No catalog data found. Run POST /catalog/run-extraction first.",
        )
    # Re-generate Excel if parquet is newer than the saved xlsx (or xlsx missing)
    if not _PARTS_XLSX.exists() or _PARTS_OUT.stat().st_mtime > _PARTS_XLSX.stat().st_mtime:
        BROWSER_DIR.mkdir(parents=True, exist_ok=True)
        pd.read_parquet(_PARTS_OUT).to_excel(_PARTS_XLSX, index=False, engine="openpyxl")
    return FileResponse(
        path=_PARTS_XLSX,
        filename="catalog_parts.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/coverage", response_model=CatalogCoverageResponse)
def get_catalog_coverage() -> CatalogCoverageResponse:
    """Stage 6.1 — Parts extracted from PDF catalogues, grouped by model.

    Returns data from catalog_parts.parquet (written by stage06 run).
    If the parquet does not exist, returns extracted=False with empty rows.
    """
    df = get_catalog_parts()

    if df.empty:
        return CatalogCoverageResponse(
            extracted=False,
            total_part_references=0,
            distinct_parts=0,
            distinct_models=0,
            rows=[],
        )

    # Count PDFs per model from the live file system (for pdf_count)
    pdf_counts: dict[str, int] = {}
    for _product, folder in model_folders(PDF_ROOT):
        pdf_counts[folder.name] = pdf_counts.get(folder.name, 0) + sum(
            1 for f in folder.rglob("*") if f.suffix in PDF_EXTS
        )

    pn_col = "part_no" if "part_no" in df.columns else "part_number"
    rows: list[CatalogCoverageRow] = []
    if "model" in df.columns and pn_col in df.columns:
        agg_dict: dict[str, Any] = {"distinct_parts": (pn_col, "nunique")}
        if "ocr_used" in df.columns:
            agg_dict["ocr_pages"] = ("ocr_used", "sum")
        grp = (
            df.groupby("model")
            .agg(**agg_dict)
            .reset_index()
            .sort_values("distinct_parts", ascending=False)
        )
        for _, r in grp.iterrows():
            model_name = str(r["model"])
            rows.append(
                CatalogCoverageRow(
                    model=model_name,
                    pdf_count=pdf_counts.get(model_name, 0),
                    distinct_parts=int(r["distinct_parts"]),
                    ocr_pages=int(r.get("ocr_pages", 0)),
                )
            )

    return CatalogCoverageResponse(
        extracted=True,
        total_part_references=len(df),
        distinct_parts=int(df[pn_col].nunique()) if pn_col in df.columns else 0,
        distinct_models=int(df["model"].nunique()) if "model" in df.columns else 0,
        rows=rows,
    )


@router.get("/excel")
def list_excel_catalogues() -> list[dict[str, Any]]:
    """List all Excel parts-catalogue files found directly in data/raw/."""
    result = []
    if RAW_ROOT.exists():
        for f in sorted(RAW_ROOT.glob("*"), key=lambda p: p.name.upper()):
            if f.is_file() and f.suffix in XLSX_EXTS and "catalogue" in f.stem.lower():
                result.append(
                    {
                        "filename": f.name,
                        "stem": f.stem,
                        "size_kb": round(f.stat().st_size / 1024, 1),
                    }
                )
    return result


@router.get("/excel/{filename}")
def get_excel_catalogue(
    filename: str,
    section: str | None = Query(None),
    search: str | None = Query(None),
) -> dict[str, Any]:
    """Return all rows from an Excel parts catalogue in data/raw/.

    Optionally filter by section and/or a search string (matched against
    Part No. and Description columns).
    """
    import openpyxl

    target = (RAW_ROOT / filename).resolve()
    if not str(target).startswith(str(RAW_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists() or target.suffix not in XLSX_EXTS:
        raise HTTPException(status_code=404, detail="File not found")

    wb = openpyxl.load_workbook(str(target), read_only=True, data_only=True)
    ws = wb.active

    headers: list[str] = []
    rows: list[list[str]] = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if not any(cells):
            continue
        if i == 0:
            headers = cells
            continue
        rows.append(cells)

    # Drop "Fig. No." column
    if "Fig. No." in headers:
        drop_idx = headers.index("Fig. No.")
        headers = [h for j, h in enumerate(headers) if j != drop_idx]
        rows = [[c for j, c in enumerate(r) if j != drop_idx] for r in rows]

    # Derive column indices for filtering
    try:
        sec_idx = headers.index("Section")
    except ValueError:
        sec_idx = 0
    try:
        pn_idx = headers.index("Part No.")
    except ValueError:
        pn_idx = 2
    try:
        desc_idx = headers.index("Description")
    except ValueError:
        desc_idx = 3

    if section:
        rows = [r for r in rows if r[sec_idx].upper() == section.upper()]
    if search:
        q = search.lower()
        rows = [r for r in rows if q in r[pn_idx].lower() or q in r[desc_idx].lower()]

    sections = sorted({r[sec_idx] for r in rows if r[sec_idx]})

    return {
        "filename": filename,
        "headers": headers,
        "rows": rows,
        "total": len(rows),
        "sections": sections,
    }


@router.get("/parts/{model}", response_model=list[CatalogPartRow])
def get_parts_for_model(
    model: str,
    limit: int = Query(500, le=5000),
) -> list[CatalogPartRow]:
    """Return part numbers extracted from PDF catalogues for a specific model."""
    df = get_catalog_parts()

    if df.empty or "model" not in df.columns:
        return []

    sub = df[df["model"].str.lower() == model.lower()].head(limit)
    pn_col = "part_no" if "part_no" in df.columns else "part_number"
    result: list[CatalogPartRow] = []
    for _, r in sub.iterrows():
        result.append(
            CatalogPartRow(
                part_number=str(r.get(pn_col, "")),
                source_file=str(r.get("source_file", "")),
                ocr_used=bool(r.get("ocr_used", False)),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Catalogue Agent endpoints
# ---------------------------------------------------------------------------

_AGENT = CatalogueAgent(max_pages=500)
# Builds are resolved from the stored extraction the parts table shows, not a re-read.
_AGENT._extractor = StoredCatalogueReader(max_pages=500)  # type: ignore[assignment]
_AGENT_STATUS: dict[str, Any] = {}  # file_path → {running, cached, error}


def _cache_path(rel: str) -> Path:
    """Return the disk-cache path for a given PDF rel_path."""
    safe = rel.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return AGENT_CACHE / f"{safe}.json"


@router.get("/agent/{file_path:path}")
def run_agent(
    file_path: str,
    refresh: bool = Query(False, description="Force re-run even if cached"),
) -> dict[str, Any]:
    """Run the CatalogueAgent on one PDF and return assembled builds.

    Results are cached to data/catalogue_browser/agent_builds/ so subsequent calls
    are instant.  Pass ?refresh=true to force re-extraction.

    Response schema (summary):
        model, variants[], colour_legend{}, rosters{}, builds[{variant, colour,
        colour_name, colour_code, part_count, parts[{figure, ref_no, part_no,
        description, qty, remarks, kind}]}], warnings[]
    """
    target = (PDF_ROOT / file_path).resolve()
    if not str(target).startswith(str(PDF_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists() or target.suffix not in PDF_EXTS:
        raise HTTPException(status_code=404, detail="File not found")

    cache = _cache_path(file_path)

    if not refresh and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        # Backfill model from the relative path when the cache was built without it.
        if not data.get("model"):
            data["model"] = model_folder_of(file_path)
        # Backfill model_no from the PDF cover page when the cache predates this field.
        if "model_no" not in data:
            data["model_no"] = YamahaCatalogueExtractor._extract_model_no(target)
        return data

    try:
        result = _AGENT.run(target)
        out = result.to_dict()
        AGENT_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        return out
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/agent/{file_path:path}")
def clear_agent_cache(file_path: str) -> dict[str, str]:
    """Delete the cached agent build for a PDF so the next GET re-runs it."""
    cache = _cache_path(file_path)
    if cache.exists():
        cache.unlink()
        return {"status": "cleared", "path": str(cache)}
    return {"status": "not_cached"}


@router.delete("/agent-cache/all")
def clear_all_agent_cache() -> dict[str, int]:
    """Delete ALL cached agent builds so every PDF is re-processed on next open."""
    deleted = 0
    for f in AGENT_CACHE.glob("*.json"):
        f.unlink()
        deleted += 1
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Part-master rebuild from agent builds
# ---------------------------------------------------------------------------

_PM_STATUS: dict[str, Any] = {
    "running": False,
    "last_result": None,
}


def _run_part_master_rebuild(run_missing_agents: bool) -> None:
    """Background task: optionally run agent on unprocessed PDFs, then build master."""
    _PM_STATUS["running"] = True
    _PM_STATUS["last_result"] = None
    processed: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    try:
        # ── 1. Run agent on PDFs that have no cached build ─────────────────
        if run_missing_agents and PDF_ROOT.exists():
            agent = CatalogueAgent(max_pages=500)
            agent._extractor = StoredCatalogueReader(max_pages=500)  # type: ignore[assignment]
            for pdf_path in sorted(PDF_ROOT.rglob("*")):
                if pdf_path.suffix not in PDF_EXTS or not pdf_path.is_file():
                    continue
                rel = pdf_path.relative_to(PDF_ROOT).as_posix()
                cache = _cache_path(rel)
                if cache.exists():
                    skipped.append(pdf_path.name)
                    continue
                try:
                    result = agent.run(pdf_path)
                    out = result.to_dict()
                    AGENT_CACHE.mkdir(parents=True, exist_ok=True)
                    cache.write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    processed.append(pdf_path.name)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{pdf_path.name}: {exc}")

        # ── 2. Build part master — agent JSONs + extractor fallback ────────
        df = build_part_master(pdf_root=PDF_ROOT)

        _PM_STATUS["last_result"] = {
            "ok": True,
            "total_parts": len(df),
            "total_pdfs": len(list(AGENT_CACHE.glob("*.json"))),
            "agents_run": len(processed),
            "agents_skipped": len(skipped),
            "agent_errors": errors,
        }
    except Exception as exc:  # noqa: BLE001
        _PM_STATUS["last_result"] = {"ok": False, "error": str(exc)}
    finally:
        _PM_STATUS["running"] = False


@router.post("/part-master/rebuild")
def rebuild_part_master(
    background_tasks: BackgroundTasks,
    run_missing_agents: bool = Query(
        True,
        description=(
            "If true, run the CatalogueAgent on any PDFs that do not yet have "
            "a cached build before aggregating."
        ),
    ),
) -> dict[str, Any]:
    """Rebuild the catalogue part master from all agent build caches.

    Scans every PDF in data/raw/pdf_catalogues/:
    - If ``run_missing_agents=true`` (default): runs CatalogueAgent on PDFs
      that have no cached JSON yet (may take several minutes per PDF).
    - Aggregates all cached build JSONs into a unified part master:
        data/catalogue_browser/catalogue_part_master.parquet
        data/catalogue_browser/catalogue_part_master.xlsx

    Poll ``GET /catalog/part-master/status`` for progress.
    """
    if _PM_STATUS["running"]:
        return {"queued": False, "message": "Rebuild already running"}

    background_tasks.add_task(_run_part_master_rebuild, run_missing_agents)
    return {
        "queued": True,
        "message": (
            "Part master rebuild started — agents will run on unprocessed PDFs "
            "then aggregate all builds."
            if run_missing_agents
            else "Aggregating existing agent builds into part master."
        ),
    }


@router.get("/part-master/status")
def part_master_status() -> dict[str, Any]:
    """Return the status of the last part master rebuild."""
    pm_parquet = (BROWSER_DIR / "catalogue_part_master.parquet").resolve()
    return {
        "running": _PM_STATUS["running"],
        "last_result": _PM_STATUS["last_result"],
        "parquet_exists": pm_parquet.exists(),
        "parquet_size_kb": (
            round(pm_parquet.stat().st_size / 1024, 1) if pm_parquet.exists() else 0
        ),
        "cached_pdfs": len(list(AGENT_CACHE.glob("*.json"))),
    }


# ---------------------------------------------------------------------------
# Catalogue database (PostgreSQL)
# ---------------------------------------------------------------------------


@router.get("/db/status")
def catalogue_db_status() -> dict[str, Any]:
    """Which catalogues are stored, which are not, and whether the database is reachable."""
    on_disk = sorted(
        p.relative_to(PDF_ROOT).as_posix()
        for p in PDF_ROOT.rglob("*")
        if p.suffix in PDF_EXTS and p.is_file()
    )
    try:
        with connect() as conn:
            ensure_schema(conn)
            state = stored_state(conn)
    except CatalogueStoreError as exc:
        return {"reachable": False, "error": str(exc), "on_disk": len(on_disk)}
    return {
        "reachable": True,
        "on_disk": len(on_disk),
        "loaded": sum(1 for v in state.values() if v["status"] == "loaded"),
        "excluded": {
            k: v["excluded_reason"] for k, v in state.items() if v["status"] == "excluded"
        },
        "not_loaded": [k for k in on_disk if k not in state],
        "pn_yamaha": _pn_yamaha_status(),
    }


def _pn_yamaha_status() -> dict[str, Any]:
    """Rows loaded from PN_Yamaha and how many matched a catalogue part."""
    try:
        with connect() as conn:
            rows, loaded_at = conn.execute(
                "SELECT count(*), max(loaded_at) FROM pn_yamaha"
            ).fetchone()
            matched = conn.execute(
                "SELECT count(*) FROM pn_yamaha_compatibility WHERE in_catalogue"
            ).fetchone()[0]
    except (CatalogueStoreError, psycopg.Error):
        return {"rows": 0, "matched": 0, "loaded_at": None}
    return {
        "rows": rows,
        "matched": matched,
        "loaded_at": loaded_at.isoformat() if loaded_at else None,
    }


@router.post("/db/load/{file_path:path}")
def load_catalogue_into_db(file_path: str) -> dict[str, Any]:
    """Extract one PDF and store it — the manual step for a newly added catalogue."""
    target = (PDF_ROOT / file_path).resolve()
    if not str(target).startswith(str(PDF_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not target.exists() or target.suffix not in PDF_EXTS:
        raise HTTPException(status_code=404, detail="File not found")
    key = source_key(target)
    try:
        with connect() as conn:
            ensure_schema(conn)
            reason = excluded_catalogues().get(key)
            if reason:
                record_excluded(conn, key, file_sha256(target), reason)
                return {"source_file": key, "status": "excluded", "reason": reason}
            result = YamahaCatalogueExtractor(max_pages=500).extract(target)
            catalogue_id = save_extraction(conn, key, file_sha256(target), result)
            refresh_compatibility(conn)
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    stale = _cache_path(file_path)
    if stale.exists():
        stale.unlink()  # its builds came from the previous extraction
    return {
        "source_file": key,
        "status": "loaded",
        "catalogue_id": catalogue_id,
        "rows": len(result.rows),
        "warnings": result.warnings,
    }


_DB_LOAD: dict[str, Any] = {"running": False}


@router.post("/db/load-all")
def load_all_catalogues_into_db(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Re-extract PDFs whose stored copy is current"),
) -> dict[str, Any]:
    """Extract every PDF catalogue and save it to the database, in the background.

    The manual step for a new installation, or after catalogues are copied in. By default
    only PDFs with no current stored copy are read; ``force`` re-reads them all. Poll
    ``GET /catalog/db/load-status`` for progress.
    """
    if _DB_LOAD.get("running"):
        return {"queued": False, "message": "a load is already running", **_DB_LOAD}
    pdfs = sorted(p for p in PDF_ROOT.rglob("*") if p.suffix in PDF_EXTS and p.is_file())
    _DB_LOAD.clear()
    _DB_LOAD.update(
        {
            "running": True,
            "force": force,
            "total": len(pdfs),
            "done": 0,
            "loaded": 0,
            "skipped": 0,
            "excluded": 0,
            "failed": [],
            "current": None,
            "error": None,
            "started_at": pd.Timestamp.now(tz="Asia/Colombo").isoformat(),
            "finished_at": None,
        }
    )

    def progress(event: dict[str, Any]) -> None:
        _DB_LOAD.update({k: v for k, v in event.items() if k in _DB_LOAD})
        _DB_LOAD["current"] = event["source_file"]

    def run() -> None:
        try:
            load_catalogues(pdfs, force=force, on_event=progress)
            # The material master is matched against the catalogues just loaded.
            _DB_LOAD["current"] = "PN_Yamaha (Brand YM)"
            with connect() as conn:
                _DB_LOAD["pn_yamaha"] = load_pn_yamaha(conn)
        except (CatalogueStoreError, SourceDataError) as exc:
            _DB_LOAD["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported to the page, not swallowed
            _DB_LOAD["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _DB_LOAD["running"] = False
            _DB_LOAD["current"] = None
            _DB_LOAD["finished_at"] = pd.Timestamp.now(tz="Asia/Colombo").isoformat()

    background_tasks.add_task(run)
    return {"queued": True, "total": len(pdfs), "force": force}


@router.get("/db/load-status")
def catalogue_db_load_status() -> dict[str, Any]:
    """Progress of the last (or running) load-all."""
    return dict(_DB_LOAD) if _DB_LOAD else {"running": False, "total": 0}


@router.get("/db/compatible-models")
def part_compatible_models(
    part_no: str | None = Query(None, description="Part number or SAP material id (exact)"),
    q: str | None = Query(None, description="Part-number prefix or description text"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Which model variants a part (material) is fitted to, from the stored catalogues.

    ``part_no`` ignores separators, so "B65E390710" finds "B65-E3907-10".
    """
    if not part_no and not q:
        raise HTTPException(status_code=400, detail="give part_no or q")
    try:
        with connect() as conn:
            ensure_schema(conn)
            rows = compatible_models(conn, part_no=part_no, q=q, limit=limit)
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"count": len(rows), "parts": rows}


@router.post("/db/pn-yamaha/load")
def load_pn_yamaha_into_db() -> dict[str, Any]:
    """Load PN_Yamaha's Yamaha-brand ("YM") materials into the database (a few seconds)."""
    try:
        with connect() as conn:
            ensure_schema(conn)
            return load_pn_yamaha(conn)
    except SourceDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/db/pn-yamaha")
def pn_yamaha_lookup(
    material: str | None = Query(None, description="Material or Latest SS (exact)"),
    q: str | None = Query(None, description="Material prefix or description text"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """PN_Yamaha materials with the catalogue part name and compatible model variants.

    A material is matched to the catalogues through its own number, its Latest SS or any
    of its ten superseded numbers; separators are ignored and the 10- and 12-digit forms
    of a part are one part.
    """
    if not material and not q:
        raise HTTPException(status_code=400, detail="give material or q")
    try:
        with connect() as conn:
            ensure_schema(conn)
            rows = pn_yamaha_compatibility(conn, material=material, q=q, limit=limit)
    except CatalogueStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"count": len(rows), "materials": rows}
