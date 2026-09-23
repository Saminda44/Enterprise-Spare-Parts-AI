"""Step 01 — read every catalogue PDF, resolve colour variants, publish the tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from src.catalogue.colour_rules import resolve_catalogue
from src.catalogue.pdf_reader import read_catalogue
from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.core.settings import get_settings
from src.io.parquet import write_table


def catalogue_dir() -> Path:
    return get_settings().raw_dir / "pdf_catalogues"


def extract_all(
    pdf_paths: list[Path], result: StageResult
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Extract, resolve and flatten every PDF into four tables."""
    part_rows: list[dict[str, Any]] = []
    variant_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    layout_rows: list[dict[str, Any]] = []

    for path in pdf_paths:
        try:
            extraction = read_catalogue(path)
        except Exception as exc:  # noqa: BLE001 — one bad PDF must not stop the corpus
            result.reject(f"pdf unreadable: {type(exc).__name__}", 1)
            exception_rows.append(
                {
                    "pdf_file": path.name,
                    "part_no": None,
                    "remark": None,
                    "reason": f"unreadable: {type(exc).__name__}: {exc}",
                }
            )
            layout_rows.append(
                {
                    "pdf_file": path.name,
                    "folder": path.parent.name,
                    "pages": 0,
                    "layout": "unreadable",
                    "model_codes": "",
                    "colours": 0,
                    "parts": 0,
                    "confirmed_variants": "",
                    "warnings": str(exc)[:200],
                }
            )
            continue

        assignments, report = resolve_catalogue(extraction.parts, extraction.colours)
        by_part: dict[str, list] = {}
        for assignment in assignments:
            by_part.setdefault(assignment.part_no, []).append(assignment)

        for part in extraction.parts:
            for assignment in by_part.get(part.part_no, []):
                part_rows.append(
                    {
                        "pdf_file": extraction.pdf_file,
                        "folder": path.parent.name,
                        "model_code": part.model_code
                        or (extraction.model_codes[0] if extraction.model_codes else None),
                        "part_no": part.part_no,
                        "description": part.description,
                        "qty": part.qty,
                        "remark_raw": part.remark_raw,
                        "part_kind": assignment.part_kind,
                        "colour_abbr": assignment.colour_abbr,
                        "colour_name": assignment.colour_name,
                        "colour_code": assignment.colour_code,
                        "rule_applied": assignment.rule_applied,
                        "confidence": assignment.confidence,
                        "page": part.page,
                    }
                )

        for entry in extraction.colours:
            variant_rows.append(
                {
                    "pdf_file": extraction.pdf_file,
                    "model_code": extraction.model_codes[0] if extraction.model_codes else None,
                    "colour_abbr": entry.abbreviation,
                    "colour_name": entry.name,
                    "colour_code": entry.code,
                    "is_model_colour": entry.is_model_colour,
                    "confirmed": entry.abbreviation in report.confirmed_variants,
                }
            )

        for exception in report.exceptions:
            exception_rows.append({"pdf_file": extraction.pdf_file, **exception})

        layout_rows.append(
            {
                "pdf_file": extraction.pdf_file,
                "folder": path.parent.name,
                "pages": extraction.pages,
                "layout": extraction.layout,
                "model_codes": ",".join(extraction.model_codes),
                "colours": len(extraction.colours),
                "parts": len(extraction.parts),
                "confirmed_variants": ",".join(report.confirmed_variants),
                "warnings": "; ".join(extraction.warnings),
            }
        )

    return (
        pd.DataFrame(part_rows),
        pd.DataFrame(variant_rows),
        pd.DataFrame(exception_rows),
        pd.DataFrame(layout_rows),
    )


@REGISTRY.register("01_catalogue", description="PDF catalogue reader and colour variants")
def run(ctx: PlanningContext) -> StageResult:  # noqa: ARG001 — ctx unused, contract requires it
    result = StageResult(stage="01_catalogue")
    root = catalogue_dir()
    pdfs = sorted(root.glob("**/*.pdf"))
    result.rows_in = len(pdfs)
    if not pdfs:
        result.status = StageStatus.FAILED
        result.error = f"no PDFs under {root}"
        return result

    logger.info(f"reading {len(pdfs)} catalogue PDFs")
    parts, variants, exceptions, layouts = extract_all(pdfs, result)
    result.rows_out = len(parts)

    if parts.empty:
        result.status = StageStatus.FAILED
        result.error = "no parts extracted from any PDF"
        return result

    for name, frame in (
        ("catalogue_parts", parts),
        ("model_colour_variants", variants),
        ("catalogue_exceptions", exceptions),
        ("catalogue_layouts", layouts),
    ):
        if not frame.empty:
            result.artifact(name, write_table(frame, "facts", name))

    unreadable = int((layouts["layout"] == "unreadable").sum())
    unrecognised = int((layouts["layout"] == "unrecognised").sum())
    if unreadable:
        result.warn(f"{unreadable} PDF(s) could not be opened")
    if unrecognised:
        result.warn(f"{unrecognised} PDF(s) yielded no parts — layout not recognised")
    no_colour = int((layouts["colours"] == 0).sum())
    if no_colour:
        result.warn(f"{no_colour} PDF(s) had no applicable-colour table")
    if not exceptions.empty:
        result.warn(f"{len(exceptions)} unresolved remark(s) routed to exceptions")

    coloured = int((parts["part_kind"] == "coloured").sum())
    result.warn(
        f"{coloured:,} coloured rows, {len(parts) - coloured:,} shared, "
        f"across {layouts['pdf_file'].nunique()} PDFs"
    )
    return result
