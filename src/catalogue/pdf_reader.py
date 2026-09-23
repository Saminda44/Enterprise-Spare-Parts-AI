"""Extract the parts table from Yamaha catalogue PDFs.

The text layer is reliable; the table layer is not — pdfplumber merges cells on these
layouts. So rows are rebuilt from word x-positions against the column header, which is
the only thing that separates a description ending in a digit ("PIPE, DRAIN 3") from a
quantity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

#: extract_text() renders the catalogue's dash as U+FFFD on most of these files.
DASHES = "-‐‑‒–—―�­−"
_DASH_RE = re.compile(f"[{DASHES}]")

PART_NO_RE = re.compile(
    rf"^[0-9A-Z]{{2,5}}[{DASHES}][0-9A-Z]{{3,6}}(?:[{DASHES}][0-9A-Z]{{2,5}})?$"
)
#: Model codes are four upper-case alphanumerics containing at least one digit —
#: 2XB3, 3BX2, 21C8, B441, 5YY8. The digit requirement is what keeps ASSY, HEAD, FORK
#: and REAR out of the model list.
MODEL_CODE_RE = re.compile(r"^(?=[0-9A-Z]*\d)[0-9A-Z]{4}$")
_PAREN_CODE_RE = re.compile(r"\(\s*((?=[0-9A-Z]*\d)[0-9A-Z]{4})\s*\)")

#: "0033 YAMAHA BLACK YB" / "HO DEEP RED METALLIC K DRMK"
_COLOUR_ROW_RE = re.compile(
    r"^(?P<code>[0-9A-Z]{2,4})\s+"
    r"(?P<name>[A-Z][A-Z0-9 /\-]{3,40}?)\s+"
    r"(?P<abbr>[A-Z][A-Z0-9\-]{1,7})$"
)

_ROW_TOLERANCE = 2.5


def normalise_part_no(value: str) -> str:
    """Catalogue dashes vary; PN_Yamaha uses a plain hyphen. Normalise to compare."""
    return _DASH_RE.sub("-", str(value)).strip().upper()


@dataclass
class ColourEntry:
    abbreviation: str
    name: str
    code: str | None = None
    is_model_colour: bool = False


@dataclass
class CataloguePart:
    pdf_file: str
    model_code: str | None
    ref_no: str | None
    part_no: str
    description: str
    qty: str | None
    remark_raw: str | None
    page: int
    qty_by_model: dict[str, str] = field(default_factory=dict)


@dataclass
class PdfExtraction:
    pdf_file: str
    model_codes: list[str]
    colours: list[ColourEntry]
    parts: list[CataloguePart]
    pages: int
    layout: str
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "pdf_file": self.pdf_file,
            "pages": self.pages,
            "layout": self.layout,
            "model_codes": self.model_codes,
            "colours": len(self.colours),
            "parts": len(self.parts),
            "warnings": self.warnings,
        }


# ── page geometry ───────────────────────────────────────────────────────────────
def _rows(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Cluster words into visual rows by their top coordinate."""
    out: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if out and abs(out[-1][0]["top"] - word["top"]) <= _ROW_TOLERANCE:
            out[-1].append(word)
        else:
            out.append([word])
    return [sorted(row, key=lambda w: w["x0"]) for row in out]


@dataclass
class PageHeader:
    """Where each column starts, taken from the header row of a parts page."""

    description_x: float
    remarks_x: float | None
    model_columns: list[tuple[str, float]]  # (model code, x0), left to right


def _find_header(rows: list[list[dict[str, Any]]]) -> PageHeader | None:
    """Locate the column header. Layouts label the description column either
    ``DESCRIPTION`` or ``PART NAME`` — both appear across these catalogues."""
    description_x = remarks_x = None
    for row in rows[:12]:
        for index, word in enumerate(row):
            text = word["text"].upper().strip(".")
            if (
                text == "DESCRIPTION"
                and description_x is None
                or (
                    text == "PART"
                    and description_x is None
                    and index + 1 < len(row)
                    and row[index + 1]["text"].upper().strip(".") == "NAME"
                )
            ):
                description_x = word["x0"]
            elif text == "REMARKS" and remarks_x is None:
                remarks_x = word["x0"]
    if description_x is None:
        return None

    #: model-code headers sit between DESCRIPTION and REMARKS
    model_columns: list[tuple[str, float]] = []
    for row in rows[:12]:
        for word in row:
            text = word["text"].upper()
            if not MODEL_CODE_RE.match(text):
                continue
            if word["x0"] <= description_x:
                continue
            if remarks_x is not None and word["x0"] >= remarks_x:
                continue
            model_columns.append((text, word["x0"]))
    model_columns.sort(key=lambda pair: pair[1])
    return PageHeader(description_x, remarks_x, model_columns)


def _parse_page(page: Any, header: PageHeader, pdf_file: str, page_no: int) -> list[CataloguePart]:
    parts: list[CataloguePart] = []
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    for row in _rows(words):
        part_word = next((w for w in row if PART_NO_RE.match(w["text"])), None)
        if part_word is None:
            continue
        if "XXXX" in part_word["text"].upper():  # printed placeholder, not a part
            continue

        ref_candidates = [w for w in row if w["x0"] < part_word["x0"]]
        ref_no = ref_candidates[0]["text"] if ref_candidates else None

        after = [w for w in row if w["x0"] > part_word["x0"]]
        first_model_x = header.model_columns[0][1] if header.model_columns else header.remarks_x

        description_words = [
            w for w in after if first_model_x is None or w["x0"] < first_model_x - 2
        ]
        description = " ".join(w["text"] for w in description_words).strip()

        qty_by_model: dict[str, str] = {}
        for index, (code, x0) in enumerate(header.model_columns):
            right = (
                header.model_columns[index + 1][1]
                if index + 1 < len(header.model_columns)
                else (header.remarks_x if header.remarks_x is not None else x0 + 40)
            )
            cell = [w for w in after if x0 - 6 <= w["x0"] < right - 2]
            if cell:
                qty_by_model[code] = " ".join(w["text"] for w in cell).strip()

        remark = None
        if header.remarks_x is not None:
            remark_words = [w for w in after if w["x0"] >= header.remarks_x - 6]
            remark = " ".join(w["text"] for w in remark_words).strip() or None

        single_qty = next(iter(qty_by_model.values()), None) if len(qty_by_model) == 1 else None

        parts.append(
            CataloguePart(
                pdf_file=pdf_file,
                model_code=None,
                ref_no=ref_no,
                part_no=normalise_part_no(part_word["text"]),
                description=description,
                qty=single_qty,
                remark_raw=remark,
                page=page_no,
                qty_by_model=qty_by_model,
            )
        )
    return parts


# ── document-level extraction ───────────────────────────────────────────────────
def extract_model_codes(pdf: Any) -> list[str]:
    """Model codes from the cover page, e.g. "(2XB3)" and "(B65J)"."""
    codes: list[str] = []
    for page in pdf.pages[:2]:
        for code in _PAREN_CODE_RE.findall(page.extract_text() or ""):
            if code not in codes:
                codes.append(code)
    return codes


def extract_colour_table(pdf: Any) -> list[ColourEntry]:
    """The applicable-colour table from the FOREWORD page.

    Business meaning: this is the *universe of possible* colours for the PDF, not the
    variant list. A variant is confirmed only once its abbreviation is observed in the
    parts table — see :mod:`src.catalogue.colour_rules`.
    """
    entries: list[ColourEntry] = []
    seen: set[str] = set()
    for page in pdf.pages[:8]:
        text = page.extract_text() or ""
        if not re.search(r"FOREWARD|FOREWORD", text, re.I):
            continue
        for line in text.splitlines():
            stripped = line.strip()
            starred = "(*)" in stripped or stripped.endswith("*")
            candidate = stripped.replace("(*)", "").strip().rstrip("*").strip()
            match = _COLOUR_ROW_RE.match(candidate)
            if not match:
                continue
            abbr = match.group("abbr").upper()
            name = match.group("name").strip()
            if abbr in seen or abbr in {"ABBR", "NAME", "CODE"}:
                continue
            if name.upper().startswith(("COLOUR", "COLOR")):
                continue
            seen.add(abbr)
            entries.append(
                ColourEntry(
                    abbreviation=abbr,
                    name=name,
                    code=match.group("code"),
                    is_model_colour=starred,
                )
            )
    return entries


def read_catalogue(path: Path) -> PdfExtraction:
    """Extract model codes, the colour table and every parts row from one PDF."""
    path = Path(path)
    parts: list[CataloguePart] = []
    warnings: list[str] = []

    with pdfplumber.open(path) as pdf:
        model_codes = extract_model_codes(pdf)
        colours = extract_colour_table(pdf)
        pages = len(pdf.pages)
        header_models: set[str] = set()

        # The foreword carries a worked example that looks exactly like a parts row.
        # Excluding it stops FRONT FLASHER LIGHT ASSY appearing in every catalogue.
        texts = [p.extract_text() or "" for p in pdf.pages]
        is_foreword = [bool(re.search(r"FOREWARD|FOREWORD", t, re.I)) for t in texts]

        # Layout is consistent within a catalogue, but the header is only printed on
        # some pages. Detect it on parts pages, then apply to pages that lack it.
        headers: list[PageHeader | None] = []
        for page_no, page in enumerate(pdf.pages):
            if is_foreword[page_no]:
                headers.append(None)
                continue
            headers.append(_find_header(_rows(page.extract_words(keep_blank_chars=False))))
        fallback = next((h for h in headers if h is not None), None)

        for page_no, page in enumerate(pdf.pages, start=1):
            if is_foreword[page_no - 1]:
                continue
            header = headers[page_no - 1] or fallback
            if header is None:
                continue
            header_models.update(code for code, _ in header.model_columns)
            parts.extend(_parse_page(page, header, path.name, page_no))

        # Single-model catalogues print the code at the top-left of each parts page.
        for page_no, text in enumerate(texts):
            if is_foreword[page_no] or not text:
                continue
            first = text.splitlines()[0].strip()
            if MODEL_CODE_RE.match(first):
                header_models.add(first)
        for text in texts[:6]:
            for code in re.findall(r"YAMAHA\s*[-–]\s*([0-9A-Z]{4})", text):
                if MODEL_CODE_RE.match(code):
                    header_models.add(code)

    colour_abbrs = {c.abbreviation for c in colours}
    for code in sorted(header_models):
        if code not in model_codes and code not in colour_abbrs:
            model_codes.append(code)

    if not model_codes:
        warnings.append("no model code found on the cover page or any parts header")
    if not colours:
        warnings.append("no applicable-colour table found on the FOREWORD page")
    if not parts:
        warnings.append("no parts rows extracted — layout not recognised")

    #: Cover-page codes are authoritative; header codes only extend them.
    multimodel = len(header_models) > 1
    layout = "multimodal" if multimodel else "single-model"
    if not parts:
        layout = "unrecognised"

    for part in parts:
        if not multimodel and model_codes:
            part.model_code = model_codes[0]

    return PdfExtraction(
        pdf_file=path.name,
        model_codes=model_codes,
        colours=colours,
        parts=parts,
        pages=pages,
        layout=layout,
        warnings=warnings,
    )
