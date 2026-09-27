"""Stage 6.1 — Yamaha PDF Catalogue Extractor.

Extracts the seven-column parts table from Yamaha motorcycle PDF catalogues:
    Section | Fig. No. | Ref. No. | Part No. | Description | Q'ty | Remarks

Output matches the structure of GPD155D-A_Parts_Catalogue.xlsx exactly.

Strategy
--------
Primary: word-position clustering.
  pdfplumber extracts each word with its (x, y) coordinates.  Words on the
  same Y band are grouped into a logical row, then each word is assigned to a
  column by its X position relative to auto-detected column boundaries.

Fallback: text-line regex.
  If a page yields no positioned words (image-based) the page is flagged;
  a plain-text regex pass is attempted and, if still empty, the page is
  logged as requiring OCR (not implemented here — flag only).

Column boundary detection
--------------------------
Each "parts page" starts with a header band containing the words
  "PART NO." (or "12 DIGIT") and "REMARKS".
The extractor reads the first 25 word-rows of every page to locate these
anchors and derive the five column X-ranges:
    [ref_start, pn_start, desc_start, qty_start, rem_start]

If the header isn't found (e.g., continuation pages), the previous page's
bounds are re-used.

Part-number pattern
-------------------
Yamaha standard:  XYZ-ABCDE-NN  or  XYZ-ABCDE-NN-CC  (last two-char segment
always digits for the revision, optional two-char colour/variant suffix).
The regex is strict enough to avoid matching model-version stamps (e.g. 1BV2).
"""

from __future__ import annotations

import re
from collections import Counter as _Counter
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher as _SequenceMatcher
from pathlib import Path  # noqa: TCH003
from typing import Any

import pandas as pd
from loguru import logger
from src.catalogue.browser.overrides import (
    NEVER_EXTRACTED,
    NEVER_EXTRACTED_LABELS,
    override_for,
)
from src.catalogue.browser.remark_parser import parse_applicability

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLUMNS: list[str] = [
    "section",
    "fig_no",
    "ref_no",
    "part_no",
    "description",
    "qty",
    "nine_digit_part_no",
    "escort_part_no",
    "superseded_part_no",
    "remarks",
]
DISPLAY_HEADERS: list[str] = [
    "Section",
    "Ref. No.",
    "Part No.",
    "Description",
    "Q'ty",
    "9 Digit Part No.",
    "Escort Part No.",
    "Superseded Part No.",
    "Remarks",
]

# Yamaha part numbers.  Some PDFs encode hyphens as U+2013 (en-dash) instead
# of U+002D (ASCII hyphen), so both are accepted as separators.
# Formats supported:
#   3-part: XXX-XXXXX-NN         e.g. 5HK-14147-00
#   4-part: XXX-XXXXX-NN-XX      e.g. 5HK-14147-00-P0
#   2-part all-digit: NNNNN-NNNNN    e.g. 93210-29800 (standard Yamaha OEM)
#   2-part alphanumeric second seg:  e.g. 93306-302YP, 93306-255X5
#       (bearing/seal codes where the suffix encodes type+size with letters)
#   2-part mixed first seg:          e.g. 95E32-06010 (Yamaha fastener series)
#   10–12-char nodash: XXXXXXXXXX    e.g. 2LPWE11100 (Saluto 2LP2), 5DGE35860100 (ENTICER/YBX125)
_DASH = r"[-–]"
_PN_PAT = re.compile(
    # Every Yamaha part number contains a digit; without this "FRONT-CALM" (FZS21C2's
    # "CAST WHEEL, FRONT-CALM YELLOW") matched the 5-and-4 shape and cut the name.
    r"\b(?=[A-Z0-9\-–]*\d)("
    # 3- or 4-segment: XXX-XXXXX-NN[-XX]
    # Third segment is [A-Z0-9]{2} (not [0-9]{2}) because Yamaha graphic/decal parts
    # use letter-prefixed revision codes: B65-F174G-C0, B65-F174H-D0, etc.
    r"[A-Z0-9]{2,5}"
    + _DASH
    + r"[A-Z0-9]{3,8}"
    + _DASH
    + r"[A-Z0-9]{2}(?:"
    + _DASH
    + r"[A-Z0-9]{2})?"
    # 2-segment with 5-char alphanumeric first segment, 3-8 char alphanumeric second
    # covers: NNNNN-NNNNN, NNNNN-NNNYX, XNNNN-NNNNN, etc.
    # The first segment carries a digit ("93306-20215", "95E32-06010"), which keeps a
    # description's "FRONT-VRC1" from reading as a part number.
    r"|(?=[A-Z]{0,4}\d)[A-Z0-9]{5}" + _DASH + r"[A-Z0-9]{3,8}"
    r"|(?=[A-Z0-9]*\d)[A-Z0-9]{10,12}"
    r")\b"
)
# A four-segment part number printed flush against the first word of its description,
# e.g. "5TS-WF151-00-00FRONT". Requires three or more letters after the part number so a
# real part number is never split: no Yamaha segment is three letters long.
_PN_RUN_TOGETHER = re.compile(
    r"^([A-Z0-9]{2,5}"
    + _DASH
    + r"[A-Z0-9]{3,8}"
    + _DASH
    + r"[A-Z0-9]{2}"
    + _DASH
    + r"[A-Z0-9]{2})([A-Z]{3,}.*)$"
)
# Three letters in a row: enough to call a word part of a description rather than a
# code or a number. Used to tell a real part row from a stray 9-digit value.
_DESCRIPTION_WORD = re.compile(r"[A-Za-z]{3,}")
# A reference glued to the front of a part number: "1a)5KA-H3500-00-00", "b)5KA-F7411-00-00",
# and LIBERO 5TS1's dot-terminated references, "10.5TS-E4710-00-00".
_REF_GLUED = re.compile(r"^((?:\d{1,3}[a-z]?|[a-z])\)|\d{1,3}\.)(\S+)$")
# A kit-composition footnote line ends its text before the part number with
# "* NAME -": "* BRAKE SHOE 1 (LOWER)-5YY-F5130-00-00". Captures the name.
_KIT_NOTE = re.compile(r"\*\s*([^*]*[A-Za-z][^*]*?)\s*[-–]?\s*$")
# Page title of a model's exclusive-parts list: "PARTS EXCLUSIVE TO MODEL - CRUX (5KA2)".
_EXCLUSIVE_PAGE_PAT = re.compile(
    r"PARTS\s+EXCLUSIVE\s+TO\s+MODEL\s*[-–]\s*([A-Z][A-Z0-9 \-]*?)\s*\(([A-Z0-9]{4})\)",
    re.IGNORECASE,
)
# A full 12-digit part number, the only shape that anchors a parts table's own column.
_TWELVE_DIGIT = re.compile(
    r"^(?:[A-Z0-9]{3}[-–][A-Z0-9]{5}[-–][A-Z0-9]{2}[-–][A-Z0-9]{2}|\d{5}[-–][A-Z0-9]{5}[-–][A-Z0-9]{2})$"
)
# Side-by-side tables: part-number columns this far apart are two tables, each needing
# at least this many rows, most with a reference number printed just left of the part.
_TABLE_GAP = 200.0
_TABLE_MIN_ROWS = 3
_REF_MAX_GAP = 30.0
_REF_SHARE = 0.6
_REF_TOKEN = re.compile(r"^\d{1,3}[a-z]?[.)]?$")
# A Yamaha catalogue's publication number: "1UB9E-470EA", "1SB62-470EA". On the cover
# with its hyphen; in a file name sometimes without ("1UB65460EV-AEROX.pdf").
_CATALOGUE_NO = re.compile(r"\b(\d[A-Z][0-9A-Z]{3})\s*-\s*(\d{3}[0-9A-Z]{2})\b")
_CATALOGUE_NO_GLUED = re.compile(r"\b(\d[A-Z][0-9A-Z]{3})-?(\d{3}[A-Z][0-9A-Z])(?=[^0-9A-Z]|$)")
# Yamaha standard hardware — bolts, nuts, washers, bearings: "95307-06700",
# "953070670000". A colour in its description is a plating, not a vehicle colour.
_STANDARD_HARDWARE = re.compile(r"^9\d{4}")
# A colour code printed just before a bracketed colour name that spells it out:
# "PANEL 1 - S8 (Silver)", "COVER, TOP MNM3-(mat grey metallic)", "COMP.SMX(Black".
_COLOUR_GLOSS = re.compile(r"[\s\-.]([A-Z]{1,5}\d{0,2})\s*-?\s*\([^()]*\)?\s*$")
# Description words that can sit before a bracketed colour and are never a colour code:
# "COVER, SIDE ASSY1(YAMAHA BLACK)".
_NOT_CODES = frozenset({"ASSY", "COMP", "SIDE", "TAIL", "SUB", "COVER", "PANEL", "PLATE"})


def _strip_colour_suffix(desc: str, text: str, code: str) -> str:
    """Cut a colour the description ends with, once that colour is in remarks.

    Handles "FRONT-CALM YELLOW", "FRONT FENDER (YAMAHA BLACK)", "(LIGHT YELLOW" cut
    at the column edge, and a code with its gloss, "PANEL 1 - S8 (Silver)" or
    "COVER, TOP MNM3-(mat grey metallic)". Returns the description unchanged when
    the colour is not at its end.
    """
    if not text.strip():
        return desc
    gloss = rf"(?:[-–.]?\s*{re.escape(code)}\s*)?" if code else ""
    m = re.search(
        rf"\s*{gloss}[-–.]?\s*\(?\s*{re.escape(text.strip())}\s*\)?\s*$", desc, re.IGNORECASE
    )
    if not m or m.start() == 0:
        return desc
    return desc[: m.start()].rstrip(" -–,")


# A misprinted separator: "5YY.F6331-00-00", "4LS--F5355-00-00", "5TS-F2211.00-00".
# Only when the four segments have the lengths of a real part number; any run-on
# description is kept as a tail for ``_PN_RUN_TOGETHER`` to split off.
_PN_BAD_SEPARATOR = re.compile(
    r"^([A-Z0-9]{3})(?:\.|[-–]{1,2})([A-Z0-9]{5})(?:\.|[-–]{1,2})([A-Z0-9]{2})"
    r"(?:\.|[-–]{1,2})([A-Z0-9]{2})(.*)$"
)
# A third segment printed with one zero: "4LS-F3118-0-00" for "4LS-F3118-00-00".
_PN_SHORT_ZERO = re.compile(r"^([A-Z0-9]{3}[-–][A-Z0-9]{5})[-–]0([-–][A-Z0-9]{2})$")
# A label glued to a part number that lost its first hyphen: "KIT-5YYWF514-00-00" is
# "KIT" and "5YY-WF514-00-00". A real second segment is five characters, never eight.
_PN_LABEL_GLUED = re.compile(
    r"^([A-Z]{3,})[-–]([0-9][A-Z0-9]{2})([A-Z0-9]{5}[-–][A-Z0-9]{2}[-–][A-Z0-9]{2})$"
)
# A stray letter after a two-digit third segment: "4LS-E3451-00X-00" for
# "4LS-E3451-00-00". No Yamaha segment is three characters long.
_PN_STRAY_LETTER = re.compile(r"^([A-Z0-9]{3}[-–][A-Z0-9]{5}[-–]\d{2})[A-Z]([-–][A-Z0-9]{2})$")
# A misprinted part number with a stray hyphen splitting its second segment:
# "4LS-E-111F-00-00" for "4LS-E111F-00-00". Only when the two halves rejoin to the
# five-character second segment every Yamaha part number has.
_PN_EXTRA_HYPHEN = re.compile(
    r"^([A-Z0-9]{2,5})[-–]([A-Z])[-–]([A-Z0-9]{4})[-–]([A-Z0-9]{2})[-–]([A-Z0-9]{2})$"
)
# FIG. section header — "FIG. 1 (1D0) CYLINDER HEAD" or "FIG.1 CYLINDER" (no space after dot)
_FIG_PAT = re.compile(r"^FIG\.\s*(\d+[A-Z]?)\s*(?:\([^)]+\)\s*)?(.+)$", re.IGNORECASE)
# Lines to skip (header labels, noise)
_SKIP_PAT = re.compile(
    r"^(REF\.?|PART\s+NO\.?|PART\s+NAME|DESCRIPTION|REMARKS|NO\.?|"
    r"CONTENTS?|Q\'?TY\.?|12\s+DIGITS?|9\s+DIGITS?)$",
    re.IGNORECASE,
)
# Model-code stamps at top of page, e.g. "1BV2", "21C1", "5AK5"
_MODEL_STAMP_PAT = re.compile(r"^[A-Z0-9]{2,5}\d[A-Z]?$")
# Copyright line injected by some PDFs
_COPYRIGHT_PAT = re.compile(r"\s*No part of this Publication.*", re.IGNORECASE)
# Page-type skips — these page formats are not FIG parts tables
# KITS pages: "KITS-5YY6", "KITS 5YY6" — kit assembly lists
_KITS_PAGE_PAT = re.compile(r"\bKITS[-\s]\S", re.IGNORECASE)
# Cross-reference index pages: "PART NO." appears 3+ times, NOT necessarily consecutive —
# the numerical index layout is "PART NO. | REF. NO. | PART NO. | REF. NO. | …" so the
# old consecutive pattern never matched (REF. NO. broke the run).
_XREF_PAGE_PAT = re.compile(
    r"PART\s+NO.{0,60}PART\s+NO.{0,60}PART\s+NO",
    re.IGNORECASE | re.DOTALL,
)
# Index-page title guard: catches "NUMERICAL INDEX", "ALPHABETICAL INDEX", etc.
_INDEX_PAGE_PAT = re.compile(
    r"(?:NUMERICAL|ALPHABETICAL|COLOUR|GENERAL)\s+INDEX",
    re.IGNORECASE,
)
# Foreword / intro pages: always front matter, never genuine parts pages.
# These pages may contain a mini "Applicable Serial No. and Color Code" parts table
# in a side column that leaks into extraction if not skipped.
_FOREWORD_PAGE_PAT = re.compile(r"\bFOREWORD\b", re.IGNORECASE)
# Bilingual (Spanish/English) catalogues use "DESCRIPCION" (Spanish, no T) as the
# first header row for the description column. English "DESCRIPTION" follows below.
_BILINGUAL_HDR_PAT = re.compile(r"\bDESCRIPCION\b", re.IGNORECASE)
#: Words that mark a bracketed description suffix as a colour name rather than a size,
#: side or spec ("(STD)", "(LH)", "(NGK DPR7EA)"). Used only to decide whether a
#: description *names* a colour the foreword table does not list.
_COLOUR_NAME_WORDS = frozenset(
    {
        "BLACK",
        "WHITE",
        "RED",
        "BLUE",
        "GREEN",
        "YELLOW",
        "SILVER",
        "GREY",
        "GRAY",
        "GOLD",
        "MAROON",
        "CYAN",
        "PURPLE",
        "ORANGE",
        "BROWN",
        "PINK",
        "NAVY",
        "MATT",
        "MATTE",
        "METALLIC",
        "VIOLET",
        "BEIGE",
        "BRONZE",
        "TITAN",
        "TITANIUM",
    }
)

#: How far left of a single "Q'TY" header a right-aligned quantity may start. Descriptions
#: end around 100pt short of the column in these catalogues, so this cannot reach one.
_QTY_HEADER_OVERHANG = 6.0
# A digit ending the description this close left of the quantity column is the quantity:
# R15 2FB6 prints "GASKET, HEAD COVER 1 1" with the quantity at x=608 against a column
# at 616, too far left for the header overhang.
_QTY_TRAILING_REACH = 30.0
# Inferring a quantity column from where digits line up: at least this many rows, and
# this share of the page's part rows, with a digit ending at the same x.
_QTY_INFER_MIN_ROWS = 3
_QTY_INFER_SHARE = 0.4
_QTY_DIGITS = re.compile(r"^\d{1,3}$")

#: Similarity at which two long words in a colour name count as the same word despite a
#: one-letter slip in the PDF ("METALIC" for "METALLIC" scores 0.93).
_NAME_SPELLING_RATIO = 0.85

#: How near a digit's centre must sit to a quantity column's centre to be read as a
#: quantity rather than a description footnote. Columns in these catalogues are about
#: 10pt apart, so half that spacing separates the two cases cleanly.
_QTY_COLUMN_TOLERANCE = 4.0

# CID glyph fallback artifact from pdfplumber font decoding (e.g. "(cid:2)")
_CID_PAT = re.compile(r"\s*\(cid:\d+\)", re.IGNORECASE)
# Trailing colour-variant annotation on description text, e.g. " -YB(black)", " -DBNM8(gray)".
# Yamaha bodywork catalogues append a paint-code abbreviation + lowercase colour name in parens.
# Lowercase inside parens distinguishes colour names from structural qualifiers like "(STD)".
_COLOUR_SUFFIX_PAT = re.compile(r"\s*[-.]?\s*[A-Z][A-Z0-9]{0,7}\([a-z][^)]*\)\s*$")

# Cover-page variant code pattern: Yamaha writes each variant as "( B65J )"
# on the title page listing all models covered by the catalogue.
_COVER_VARIANT_PAT = re.compile(r"\(\s*([A-Z0-9]{3,5})\s*\)")
# Slash-separated pair pattern for catalogues that list two variants as
# "B811/B821" or "(B9E1 / B9E2)" without separate paren wrapping.
_SLASH_VARIANT_PAT = re.compile(r"\b([A-Z0-9]{3,5})\s*/\s*([A-Z0-9]{3,5})\b")

# Leading model/variant stamp that may precede "FIG." on the same pdfplumber
# word-row, e.g. "B65J FIG. 14 FRAME" or "21C1 FIG. 1 CYLINDER HEAD".
_STAMP_PREFIX_PAT = re.compile(r"^[A-Z0-9]{2,6}\s+", re.IGNORECASE)

# Partial FIG line — just the number, section name absent or on the next row.
_FIG_PARTIAL_PAT = re.compile(r"(?:^|.*\s)(FIG\.?\s*(\d+[A-Z]?))\s*$", re.IGNORECASE)

# Option-section page header: "PARTS OPTION (KICK STARTER)" — no FIG. prefix.
# Captures the label inside the parentheses as the section name.
_PARTS_OPTION_PAT = re.compile(r"^PARTS?\s+OPTION\s*\(([^)]+)\)", re.IGNORECASE)

# "AVAILABLE COLOUR" page header — these pages list bike colour variants as image captions,
# e.g. "Yamaha Alpha Cygnus Black" / "Yamaha Alpha Cygnus Cyan".
_AVAIL_COLOUR_PAT = re.compile(r"AVAILABLE\s+COLOU?RS?", re.IGNORECASE)
# Colour nouns used to validate caption lines on available-colour pages.
_CAPTION_COLOUR_NOUNS: frozenset[str] = frozenset(
    {
        "black",
        "white",
        "blue",
        "red",
        "green",
        "yellow",
        "silver",
        "gray",
        "grey",
        "orange",
        "gold",
        "cyan",
        "brown",
        "purple",
        "violet",
        "pink",
        "cream",
        "champagne",
        "magenta",
        "maroon",
        "metallic",
        "matte",
        "matt",
        "mat",
        "vivid",
        "racing",
        "bright",
        "dull",
        "bluish",
        "purplish",
        "reddish",
        "greenish",
        "cocktail",
        "rally",
        "navy",
        "cobalt",
        "candy",
        "sparkle",
        "pearl",
        # "dark", "deep", "light" intentionally omitted — too generic;
        # colours that use them (Dark Grey, Deep Blue) also have a specific colour noun.
    }
)
# Subset of colour nouns valid as standalone single-word colour names.
# Modifiers ("metallic", "mat", "vivid", ...) must be accompanied by a named colour.
_STANDALONE_COLOUR_NOUNS: frozenset[str] = frozenset(
    {
        "black",
        "white",
        "blue",
        "red",
        "green",
        "yellow",
        "silver",
        "gray",
        "grey",
        "orange",
        "gold",
        "cyan",
        "brown",
        "purple",
        "violet",
        "pink",
        "cream",
        "champagne",
        "magenta",
        "maroon",
        "cobalt",
        "navy",
    }
)
# Variant-code prefix that some catalogues use in colour captions:
# "2SP3-Gold", "BP16-Cyan", "BP16-Black Metallic" etc.
_VARIANT_CODE_PREFIX_PAT = re.compile(r"^([A-Z0-9]{2,6})-(.*)", re.IGNORECASE)


def _bilingual_fig_section(
    ws: list[dict],
    fallback: str,
    bounds: ColBounds,
) -> str:
    """Return the English-only section name from a bilingual FIG header row.

    In Spanish/English catalogues the FIG line is "FIG. N SpanishName EnglishName".
    The English words always start at x ≈ desc_start + 79 (consistently x ≥ 613
    for the SZ series), while Spanish section words cluster at x ≤ desc_start + 36.
    A fixed offset of +70 from desc_start gives a reliable split threshold that
    keeps all English words and discards all Spanish words.
    """
    thresh = (bounds.desc_start + 70.0) if bounds.desc_start < 9000 else 460.0
    eng_ws = sorted([w for w in ws if w["x0"] >= thresh], key=lambda w: w["x0"])
    if not eng_ws:
        return fallback
    return _CID_PAT.sub("", " ".join(w["text"] for w in eng_ws)).strip() or fallback


def _try_fig_match(
    joined: str,
    word_rows: list[tuple[float, list[dict]]],
    row_idx: int,
) -> re.Match | None:
    """Try all FIG-header matching strategies, returning the first hit.

    Three strategies in order:
    1. Direct ``_FIG_PAT.match`` — the normal case.
    2. Strip a leading model/variant-stamp prefix then ``_FIG_PAT.match`` —
       handles lines like "B65J FIG. 14 FRAME" that pdfplumber combines.
    3. Two-row match — the current row is "FIG. N" only (section name absent),
       and the very next word-row contains the section name.  The returned
       match object's group(2) will be the section name from the next row.
    """
    # Strategy 1: standard match
    m = _FIG_PAT.match(joined)
    if m:
        return m

    # Strategy 2: strip stamp prefix
    stripped = _STAMP_PREFIX_PAT.sub("", joined)
    m = _FIG_PAT.match(stripped)
    if m:
        return m

    # Strategy 3: "FIG. N" only on this row — peek at the next for section name
    partial = _FIG_PARTIAL_PAT.match(joined)
    if partial and row_idx + 1 < len(word_rows):
        next_text = " ".join(w["text"] for w in word_rows[row_idx + 1][1]).strip()
        if next_text and not _PN_PAT.search(next_text) and not _SKIP_PAT.match(next_text):
            combined = f"FIG. {partial.group(2)} {next_text}"
            m = _FIG_PAT.match(combined)
            if m:
                return m

    return None


# Y-tolerance for grouping words into the same logical row (points).
# Using a sequential-window approach (not fixed buckets) so small baseline
# variations (e.g. BB8-E1392-00 rendered 4 pts above its description text)
# don't silently split one visual row into two word-rows.
_Y_TOL = 5
# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ColBounds:
    """X-coordinate boundaries for ALL columns of a Yamaha parts page.

    The extractor first identifies columns from the header row, then uses
    these positions to classify each word into the correct column.

    pn_start          — x-start of the PART NO. (or PART NAME) column.
    desc_start        — x-start of the DESCRIPTION column.
    qty_start         — x-start of the Q'TY column (single-variant PDFs only;
                        multi-variant PDFs use qty_col_xs instead).
    rem_start         — x-start of the REMARKS column.
    qty_col_xs        — x-centre of each variant Q'ty column, left-to-right.
                        Empty for single-variant PDFs.
    nine_digit_start  — x-start of the "9 DIGIT PART NO." column present in
                        some India-market PDFs (e.g. YBX125).  9999.0 when absent.
    superseded_start  — x-start of the "SUPERSEDED PART NO." column.  9999.0 when absent.
    header_detected   — True when a column-header row was found and all
                        positions above come from it (more reliable).
    """

    pn_start: float = 9999.0
    desc_start: float = 9999.0
    qty_start: float = 9999.0
    rem_start: float = 9999.0
    qty_col_xs: list[float] = field(default_factory=list)
    nine_digit_start: float = 9999.0
    escort_start: float = 9999.0  # "ESCORT 12 DIGIT PART NO." column (ENTICER-family)
    superseded_start: float = 9999.0
    header_detected: bool = False
    # True when "REMARKS (9 DIGIT)" header means the REMARKS column IS the 9-digit part column.
    # In this layout nine_digit_start is cleared (9999) so content routes via rem_start → remarks.
    remarks_is_nine_digit: bool = False
    # True when the catalogue is bilingual (Spanish first, English second).
    # Each data row's Spanish description is immediately followed by an English
    # description on the next Y row; extraction should take the English row.
    is_bilingual: bool = False
    # Maps logical column name → the PDF's actual header label for that column.
    # e.g. {"part_no": "Existing Part No.", "description": "Part Name"}
    # Only populated for columns whose PDF label differs from the default.
    col_labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Output of extracting one PDF file."""

    pdf_path: Path
    model: str
    rows: list[dict[str, str]]
    pages_scanned: int
    sections_found: int
    ocr_flagged: int  # pages that needed OCR but couldn't be handled
    variants: list[str] = field(default_factory=list)  # e.g. ["B65J","B65L","B65M","B65N"]
    # colour_codes: [{abbreviation, name, code, is_model_colour}] from the PDF's colour table
    colour_codes: list[dict] = field(default_factory=list)
    # model_colour_source: how is_model_colour was decided - "marked" when the table's
    # abbreviation column carries (*), "parts"/"listed" when it does not and the colours
    # had to be resolved from the document, "none" when there is no colour table at all.
    model_colour_source: str = "none"
    # available_colours: captions from "AVAILABLE COLOUR" page, e.g.
    # ["Yamaha Alpha Cygnus Black", "Yamaha Alpha Cygnus Cyan"]
    available_colours: list[str] = field(default_factory=list)
    # available_colour_map: populated by CatalogueAgent after web/PDF colour matching;
    # empty when result comes directly from the extractor without agent post-processing.
    available_colour_map: dict[str, str] = field(default_factory=dict)
    manufacture_year: str | None = None  # e.g. "2019" from ©2019 on the cover page
    model_no: str | None = None  # Yamaha type code from cover page, e.g. "5YY8", "BP16"
    catalogue_no: str | None = None  # publication number on the cover, e.g. "1UB65-460EV"
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # column_layout: detected column names in left-to-right order for display
    column_layout: list[str] = field(default_factory=list)
    # column_display_labels: maps logical field name → PDF's actual column header text.
    # Only populated for columns whose PDF label differs from the default DISPLAY_HEADERS.
    # e.g. {"part_no": "Existing Part No.", "description": "Part Name",
    #        "escort_part_no": "Escort 12 Digit Part No."}
    column_display_labels: dict[str, str] = field(default_factory=dict)

    @property
    def df(self) -> pd.DataFrame:
        if not self.rows:
            return pd.DataFrame(columns=COLUMNS)
        return pd.DataFrame(self.rows, columns=COLUMNS)

    def summary(self) -> str:
        return (
            f"{self.pdf_path.name}: "
            f"{len(self.rows)} rows | {self.sections_found} sections | "
            f"{self.pages_scanned} pages | "
            f"ocr_flagged={self.ocr_flagged}"
            + (f" | WARN: {self.warnings[0]}" if self.warnings else "")
        )


# ---------------------------------------------------------------------------
# Core extractor
# ---------------------------------------------------------------------------


class YamahaCatalogueExtractor:
    """Extract parts tables from Yamaha PDF catalogues.

    Business meaning: turns unstructured PDF text into the same seven-column
    table produced by hand in GPD155D-A_Parts_Catalogue.xlsx so that all
    Yamaha model catalogues can be searched, filtered, and joined uniformly.

    Usage::

        ex = YamahaCatalogueExtractor()
        result = ex.extract(
            Path("data/raw/pdf_catalogues/FZ & FZS/FZ16 21C1.pdf"), model="FZ & FZS"
        )
        df = result.df  # pandas DataFrame with COLUMNS

        all_df = ex.extract_all(Path("data/raw/pdf_catalogues"))
    """

    def __init__(self, max_pages: int = 500) -> None:
        self.max_pages = max_pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, pdf_path: Path, model: str = "") -> ExtractionResult:
        """Extract parts table from a single PDF catalogue."""
        import pdfplumber  # lazy — not needed at import time

        rows: list[dict[str, str]] = []
        sections_seen: set[str] = set()
        ocr_flagged = 0
        warnings: list[str] = []
        pages_scanned = 0

        current_section = ""
        current_fig = ""
        last_bounds: ColBounds | None = None
        variant_counter: _Counter[tuple[str, ...]] = _Counter()

        # Pre-detect variant count from cover page so _split_after pops exactly
        # N qty digits per row (preventing trailing description digits from being
        # consumed, e.g. "GUIDE, VALVE 1" kept intact instead of "GUIDE, VALVE").
        pre_variants = self._resolve_variants(pdf_path, _Counter())
        num_variants = len(pre_variants)

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[: self.max_pages]:
                    pages_scanned += 1
                    words = page.extract_words(
                        x_tolerance=4,
                        y_tolerance=4,
                        keep_blank_chars=False,
                        use_text_flow=False,
                    )

                    if not words:
                        ocr_flagged += 1
                        continue

                    words = self._split_run_together_part_numbers(words)
                    # A page printing two parts tables side by side is parsed as two pages,
                    # each with its own column bounds; see _side_by_side_tables.
                    # A "PARTS EXCLUSIVE TO MODEL" page has no FIG header, so its rows
                    # were filed under whatever section the previous page ended on.
                    exclusive = _EXCLUSIVE_PAGE_PAT.search(
                        " ".join(
                            " ".join(w["text"] for w in ws) for _, ws in self._group_by_y(words)[:8]
                        )
                    )
                    if exclusive:
                        name, code = exclusive.group(1).strip(), exclusive.group(2)
                        current_section = f"PARTS EXCLUSIVE TO {name} ({code})"
                        current_fig = ""
                    for table_words in self._side_by_side_tables(words):
                        word_rows = self._group_by_y(table_words)

                        # Skip KITS pages, cross-reference index pages, and named index pages.
                        # Guard _XREF_PAGE_PAT with a FIG-header check: some catalogues
                        # (e.g. ENTICER 5US1) have "PART NO. … PART NO. … PART NO." in
                        # their column-header row, which is NOT an index page.  Genuine
                        # cross-reference index pages never contain "FIG." section markers.
                        page_header = " ".join(
                            " ".join(w["text"] for w in ws) for _, ws in word_rows[:8]
                        )
                        _has_fig = bool(_FIG_PAT.search(page_header))
                        if (
                            _KITS_PAGE_PAT.search(page_header)
                            or (_XREF_PAGE_PAT.search(page_header) and not _has_fig)
                            or _INDEX_PAGE_PAT.search(page_header)
                            or _FOREWORD_PAGE_PAT.search(page_header)
                        ):
                            continue

                        # Collect variant codes from column-header rows on this page
                        self._collect_variant_row(word_rows, variant_counter)

                        # Merge newly-detected bounds with last_bounds rather than
                        # replacing.  Without this, a continuation page that has
                        # variant column-header rows (→ qty_col_xs) but no REMARKS
                        # keyword returns ColBounds(rem_start=9999, qty_col_xs=[…])
                        # which overwrites the rem_start found on the header page,
                        # silently killing remark extraction for all later pages.
                        new_bounds = self._detect_col_bounds(word_rows)
                        if new_bounds is None:
                            bounds = last_bounds
                        else:
                            if last_bounds is not None:
                                # Propagate remarks_is_nine_digit: once a page establishes
                                # that REMARKS == 9-digit column, all subsequent pages must
                                # respect that layout even if their partial header row only
                                # has the REMARKS keyword (not the "(9 DIGIT)" qualifier).
                                if not new_bounds.remarks_is_nine_digit:
                                    new_bounds.remarks_is_nine_digit = (
                                        last_bounds.remarks_is_nine_digit
                                    )
                                if new_bounds.rem_start >= 9000:
                                    new_bounds.rem_start = last_bounds.rem_start
                                # Only inherit qty_col_xs when this page has no column layout
                                # of its own.  A detected desc_start (<9000) means the page
                                # is a real data page; don't let a spurious qty_col_xs from a
                                # foreword page (e.g. "21C 1CK" example text passing
                                # _is_variant_code) corrupt the single-variant positional mode.
                                if not new_bounds.qty_col_xs and new_bounds.desc_start >= 9000:
                                    new_bounds.qty_col_xs = last_bounds.qty_col_xs
                                if new_bounds.nine_digit_start >= 9000:
                                    new_bounds.nine_digit_start = last_bounds.nine_digit_start
                                if new_bounds.escort_start >= 9000:
                                    new_bounds.escort_start = last_bounds.escort_start
                                if new_bounds.superseded_start >= 9000:
                                    new_bounds.superseded_start = last_bounds.superseded_start
                                if not new_bounds.col_labels:
                                    new_bounds.col_labels = last_bounds.col_labels
                                if not new_bounds.is_bilingual:
                                    new_bounds.is_bilingual = last_bounds.is_bilingual
                            bounds = new_bounds

                        page_rows, new_section, new_fig, page_sects = self._parse_word_rows(
                            word_rows, bounds, current_section, current_fig, num_variants
                        )
                        for page_row in page_rows:
                            page_row["page"] = pages_scanned
                        rows.extend(page_rows)
                        sections_seen.update(page_sects)

                        if new_section:
                            current_section = new_section
                        if new_fig:
                            current_fig = new_fig
                        if bounds:
                            last_bounds = bounds

        except Exception as exc:  # noqa: BLE001
            logger.error(f"Extraction failed for {pdf_path}: {exc}")
            return ExtractionResult(
                pdf_path=pdf_path,
                model=model,
                rows=rows,
                pages_scanned=pages_scanned,
                sections_found=len(sections_seen),
                ocr_flagged=ocr_flagged,
                warnings=warnings,
                error=str(exc),
            )

        # Fallback: if positional extraction found nothing, try text-line parser
        if not rows:
            logger.warning(f"{pdf_path.name}: positional pass empty — trying text fallback")
            warnings.append("positional extraction empty; used text fallback")
            rows, sections_seen = self._text_fallback(pdf_path)

        # Post-extraction reroute: when the PDF has NO Remarks column
        # (rem_start stays at the 9999 sentinel), any value that landed in
        # 'remarks' was misrouted — either by the text-line fallback inside
        # _split_after (which puts trailing tokens into remarks) or by
        # positional ambiguity when a page's column layout differed slightly
        # from last_bounds.  Move those values to nine_digit_part_no instead.
        if last_bounds is not None and last_bounds.rem_start >= 9000:
            rerouted = 0
            for row in rows:
                rem = (row.get("remarks") or "").strip()
                if not rem:
                    continue
                if not (row.get("nine_digit_part_no") or "").strip():
                    row["nine_digit_part_no"] = rem
                row["remarks"] = ""
                rerouted += 1
            if rerouted:
                logger.debug(
                    f"{pdf_path.name}: rerouted {rerouted} misplaced"
                    f" remarks→nine_digit (no remarks column in PDF)"
                )

        # Column policy. Runs before any colour parsing so a discarded column can never
        # be read as a colour remark. See overrides.py for the owner's instructions.
        policy = override_for(pdf_path)
        if policy.excluded_reason:
            warnings.append(f"excluded by the owner: {policy.excluded_reason}")
        # A note line, not a table row: the part name printed before the part number
        # lands in the ref column and nothing is left for the description (GLADIATOR's
        # "SEAL AIR CLEANER ASSY. - 5TS-WE445-00-00 (CONSISTING OF ...)" read as ref
        # "CLEANE", description "("). Dropped by the owner's instruction.
        notes = [
            r
            for r in rows
            if re.search(r"[A-Za-z]{3,}", r.get("ref_no") or "")
            and not re.search(r"[A-Za-z]{3,}", r.get("description") or "")
        ]
        if notes:
            rows = [r for r in rows if r not in notes]
            warnings.append(
                f"{len(notes)} note line(s) not extracted (part name in the ref column): "
                + ", ".join(r.get("part_no", "") for r in notes)
            )
        if policy.drop_kit_rows:
            kits = [
                r
                for r in rows
                if (r.get("ref_no") or "").strip() == "*"
                or re.search(r"\bKIT\b", r.get("description") or "", re.IGNORECASE)
            ]
            if kits:
                rows = [r for r in rows if r not in kits]
                warnings.append(
                    f"{len(kits)} kit row(s) not extracted by the owner's instruction: "
                    + ", ".join(r.get("part_no", "") for r in kits)
                )
        for section, reason in policy.excluded_sections:
            kept_rows = [r for r in rows if r.get("section") != section]
            if len(kept_rows) != len(rows):
                warnings.append(
                    f"{len(rows) - len(kept_rows)} row(s) in section {section!r} not "
                    f"extracted: {reason}"
                )
                rows = kept_rows
        remarks_are_part_numbers = bool(last_bounds and last_bounds.remarks_is_nine_digit)
        blank = set(NEVER_EXTRACTED) | set(policy.drop_fields)
        if remarks_are_part_numbers:
            blank.add("remarks")
        blanked = 0
        for row in rows:
            for field_name in blank:
                if (row.get(field_name) or "").strip():
                    row[field_name] = ""
                    blanked += 1
        if blanked:
            reasons = []
            if remarks_are_part_numbers:
                reasons.append("the Remarks (9 Digit) column holds a truncated part number")
            if policy.drop_fields:
                reasons.append(f"owner drops {sorted(policy.drop_fields)}")
            reasons.append("9-digit / escort / superseded numbers are never extracted")
            logger.debug(f"{pdf_path.name}: blanked {blanked} value(s) — {'; '.join(reasons)}")

        # Resolve model variants: prefer cover-page pattern, fall back to column headers
        variants = self._resolve_variants(pdf_path, variant_counter)
        if variants:
            logger.info(f"{pdf_path.name}: detected variants {variants}")

        # Extract colour code table from PDF intro pages
        colour_codes = self._extract_colour_codes(pdf_path)
        if colour_codes:
            logger.info(f"{pdf_path.name}: found {len(colour_codes)} colour codes")
        elif policy.colour_table:
            # The table is printed as an image; the owner-approved transcription stands
            # in for it. It carries no (*) marks, so model colours are resolved later.
            colour_codes = [
                {
                    "code": c.code,
                    "name": c.name,
                    "abbreviation": c.abbreviation,
                    "is_model_colour": False,
                }
                for c in policy.colour_table
            ]
            warnings.append(
                f"colour table transcribed from page {policy.colour_table_page} "
                "(printed as an image)"
            )

        # A token cannot be both a model code and a colour code in the same catalogue, so
        # a "variant" the colour table also lists is a mis-read column header: FAZER 2WS3
        # comes out with variants VRC1 and BWC1, which are Vivid Red and Bluish White.
        # Corrected once the cover type code is known, further down.
        table_abbrs_all = {c["abbreviation"].upper() for c in colour_codes}
        mis_read_variants = [v for v in variants if v.upper() in table_abbrs_all]

        # For PDFs whose colour table uses 2-digit numeric codes (e.g. CRUX-S
        # where 70=YAMAHA BLACK, 80=CANDY MAROON, 90=SILVER 3), identify
        # colour-specific rows by the third segment of the part number instead
        # of description brackets.  This is more reliable than bracket parsing
        # and avoids false-positive colours like "BLACK GOLD" / "SILVER" that
        # appear in model-variant description brackets but not in the paint table.
        _suffix_map: dict[str, str] = {
            c["code"]: c["abbreviation"].upper()
            for c in colour_codes
            if re.match(r"^[A-Z0-9]{2}$", c.get("code", ""))
        }
        if _suffix_map:
            # Find base parts (first two hyphen-segments, e.g. "5KA-F4100")
            # that appear in ≥2 rows with *different* suffix codes from the
            # map.  Only those bases are genuine colour-variant parts — e.g.
            # CRUX-S has "5KA-F4100-70-00", "5KA-F4100-80-00", "5KA-F4100-
            # 90-00" (three colour variants of the same fender).  FAZER has
            # "5YY-F1510-00-00" through "5YY-F1510-40-00" (fuel tank in five
            # colours) alongside thousands of standard parts like "5YY-E1111-
            # 00-00" where the "00" is just the Yamaha version field, NOT a
            # colour code.  Passing only the discriminating bases to
            # _lift_suffix_colours prevents those standard parts from being
            # falsely tagged as "DPBM1".
            _base_codes: dict[str, set[str]] = {}
            for _r in rows:
                _pn = (_r.get("part_no") or "").strip()
                _segs = _pn.split("-")
                if len(_segs) >= 3 and _segs[2] in _suffix_map:
                    _b = f"{_segs[0]}-{_segs[1]}"
                    _base_codes.setdefault(_b, set()).add(_segs[2])
            _discriminating = {_b for _b, _v in _base_codes.items() if len(_v) >= 2}
            if _discriminating:
                rows = self._lift_suffix_colours(rows, _suffix_map, _discriminating)
                _tagged = sum(1 for r in rows if r.get("colour_hint"))
                logger.debug(
                    f"{pdf_path.name}: suffix-tagged {_tagged} rows"
                    f" via codes {list(_suffix_map)}"
                    f" ({len(_discriminating)} discriminating bases)"
                )
            else:
                logger.debug(
                    f"{pdf_path.name}: suffix codes {list(_suffix_map)} present but "
                    "no base part has ≥2 distinct codes — skipping suffix-colour tagging"
                )

        # Lift colour names from description parentheses (older-format PDFs that
        # encode variants as 'DESCRIPTION (COLOUR NAME)' instead of a foreword
        # colour table + FOR/EXCEPT remarks).  Only activates when colour_codes
        # is empty — never overwrites a proper foreword-extracted colour table.
        if not colour_codes:
            rows, colour_codes = self._lift_desc_colours(rows)
            if colour_codes:
                logger.info(
                    f"{pdf_path.name}: lifted {len(colour_codes)} desc-colour(s): "
                    f"{[c['abbreviation'] for c in colour_codes]}"
                )
        else:
            # Foreword colour table is present.
            # Step 1 — Remarks column (highest priority): FOR/UR/EXCEPT patterns
            # and bare colour abbreviations in the Remarks field are the canonical
            # way Yamaha India catalogues indicate colour membership.
            rows = self._extract_remark_colour_hints(rows, colour_codes)
            rem_hinted = sum(1 for r in rows if r.get("colour_hint"))
            if rem_hinted:
                logger.info(f"{pdf_path.name}: tagged {rem_hinted} rows via remarks colour hints")
            # Step 2 — Description fallback: parenthetical / dash-suffix / FOR
            # patterns in the Description column, for PDFs that embed colour in
            # descriptions instead of (or in addition to) remarks.  Rows already
            # hinted by Step 1 are counted for group confirmation but not overwritten.
            rows = self._extract_foreword_colour_hints(rows, colour_codes)
            rows, colour_codes = self._adopt_unlisted_desc_colours(rows, colour_codes)
            dropped = self._drop_unreliable_suffix_hints(rows, _suffix_map)
            if dropped:
                warnings.append(dropped)
            hinted = sum(1 for r in rows if r.get("colour_hint"))
            if hinted:
                logger.info(
                    f"{pdf_path.name}: tagged {hinted} rows with foreword colour hints"
                    f" ({rem_hinted} from remarks, {hinted - rem_hinted} from descriptions)"
                )

        # Extract available colour captions from the "AVAILABLE COLOUR" page
        available_colours = self._extract_available_colours(pdf_path)
        if available_colours:
            logger.info(
                f"{pdf_path.name}: found {len(available_colours)} available colour(s) from page"
            )

        # Extract manufacture year from cover page (©YYYY / "1st edition, May YYYY")
        manufacture_year = self._extract_manufacture_year(pdf_path)
        if manufacture_year:
            logger.info(f"{pdf_path.name}: manufacture year {manufacture_year}")

        # Extract Yamaha type/model code from cover page (e.g. "5YY8", "BP16")
        model_no = self._extract_model_no(pdf_path)

        # Replace colour codes read as model variants with the cover type code. Safe
        # only when the quantity column is single: then the "variants" are a label and
        # no quantity is attributed through them. Where quantities are split per column
        # the headers decide which model each quantity belongs to, so they are flagged
        # rather than rewritten. The owner has confirmed some books are single-model.
        if policy.single_model or mis_read_variants:
            per_column_qty = any("/" in (r.get("qty") or "") for r in rows)
            if policy.single_model or not per_column_qty:
                kept = (
                    []
                    if policy.single_model
                    else [v for v in variants if v.upper() not in table_abbrs_all]
                )
                corrected = kept or ([model_no] if model_no else [])
                warnings.append(
                    f"variants {variants} replaced by {corrected}: "
                    + (
                        "the owner confirms a single model"
                        if policy.single_model
                        else f"{mis_read_variants} are colour codes in this book's own table"
                    )
                )
                logger.info(f"{pdf_path.name}: variants {variants} -> {corrected}")
                variants = corrected
            else:
                warnings.append(
                    f"quantity columns are headed by colour codes {mis_read_variants}; "
                    f"quantities are split per column, so they are left as variants and "
                    f"per-model colours for this catalogue should not be trusted"
                )
        if model_no:
            logger.info(f"{pdf_path.name}: model_no {model_no}")

        # Build column_layout: ordered list of detected column names (left → right)
        # for display in the catalogue viewer.
        column_layout: list[str] = []
        if last_bounds is not None:
            b = last_bounds
            # Collect (x_start, display_name) pairs for every detected column
            _detected: list[tuple[float, str]] = [
                (0.0, "Ref. No."),  # ref is always present, starts at 0
                (b.pn_start if b.pn_start < 9000 else 50.0, "Part No."),
                (b.desc_start if b.desc_start < 9000 else 150.0, "Description"),
            ]
            if b.qty_col_xs:
                _detected.append((min(b.qty_col_xs), "Q'ty (per variant)"))
            elif b.qty_start < 9000:
                _detected.append((b.qty_start, "Q'ty"))
            if b.nine_digit_start < 9000:
                _detected.append((b.nine_digit_start, "9 Digit Part No."))
            if b.escort_start < 9000:
                escort_label = b.col_labels.get("escort_part_no", "Escort Part No.")
                _detected.append((b.escort_start, escort_label))
            if b.superseded_start < 9000:
                _detected.append((b.superseded_start, "Superseded Part No."))
            if b.rem_start < 9000:
                label = "Remarks (9 Digit)" if b.remarks_is_nine_digit else "Remarks"
                _detected.append((b.rem_start, label))

            # Override display names with PDF-native labels for part_no / description
            _label_overrides = b.col_labels
            _display_map: dict[str, str] = {}
            for _x, _name in _detected:
                _display_map[_x] = _name
            if "part_no" in _label_overrides:
                for i, (_x, _n) in enumerate(_detected):
                    if _n == "Part No.":
                        _detected[i] = (_x, _label_overrides["part_no"])
                        break
            if "description" in _label_overrides:
                for i, (_x, _n) in enumerate(_detected):
                    if _n == "Description":
                        _detected[i] = (_x, _label_overrides["description"])
                        break

            column_layout = [name for _, name in sorted(_detected, key=lambda t: t[0])]
            column_display_labels = dict(b.col_labels)
        else:
            column_display_labels = {}

        # The page shows only what is extracted. The discarded numbering columns go, and
        # a "Remarks (9 Digit)" column becomes a plain Remarks column: its part numbers
        # were blanked above, and it now carries the colour remarks written below.
        column_layout = [
            "Remarks" if name == "Remarks (9 Digit)" else name
            for name in column_layout
            if name not in NEVER_EXTRACTED_LABELS
        ]
        column_display_labels = {
            k: v for k, v in column_display_labels.items() if k not in NEVER_EXTRACTED
        }

        # A colour the description states, verified against the foreword table, goes
        # into remarks as "FOR <ABBR>" — the grammar every catalogue's remarks already
        # use, so one parser reads them all. The original remark is kept in front of
        # it. A remark that already restricts the part to a colour is left alone: it
        # is the catalogue's own statement and outranks anything read from a
        # description. Colours the table does not list are not written; they are
        # recorded on the row as colour_name_unmatched instead.
        #
        # The colour moves: it is cut from the description once it is in remarks
        # (FZS21C2 "CAST WHEEL, FRONT-CALM YELLOW" -> "CAST WHEEL, FRONT", remark
        # "CALM YELLOW"). Where the remark already carries a restriction the description
        # is left exactly as printed (FZS 21C8 "SCOOP & GUIDE AIR 1 -VRC1 FOR BWC1").
        # A colour nothing verifies (one part only, not in the table) is written bare,
        # without FOR: recorded, but restricting nothing, so no build loses the part.
        table_abbrs = {c["abbreviation"].upper() for c in colour_codes if c.get("abbreviation")}
        remarks_written = 0
        for row in rows:
            original = (row.get("remarks") or "").strip()
            abbr = (row.get("desc_colour") or "").upper()
            if not abbr and row.get("colour_hint_source") == "description":
                abbr = (row.get("colour_hint") or "").upper()
            if abbr in table_abbrs:
                remark = f"FOR {abbr}"
            elif row.get("colour_unverified"):
                abbr, remark = row["colour_unverified"], row["colour_unverified"]
                # A bracketed gloss of a code the remark already carries is redundant:
                # R15 2YS1 "CAST WHEEL, FRONT -LGB/DRSC (low gloss black/deep red
                # stripe)" with remark "UR LGB/DRSC". The gloss goes; remarks stay.
                desc = row.get("description") or ""
                glossed = re.search(r"[-–]\s*(\S+)\s*\([^()]*\)?\s*$", desc)
                if original and glossed and glossed.group(1).upper() in original.upper():
                    row["description"] = desc[: desc.rfind("(")].rstrip()
                    continue
            else:
                continue
            if not parse_applicability(original, table_abbrs).is_universal:
                continue
            row["remarks"] = f"{original} {remark}".strip()
            row["description"] = _strip_colour_suffix(
                row.get("description") or "", row.get("desc_colour_text") or "", abbr
            )
            remarks_written += 1
        if remarks_written:
            if not any("Remarks" in name for name in column_layout):
                column_layout.append("Remarks")
            logger.debug(
                f"{pdf_path.name}: wrote {remarks_written} colour remark(s) from descriptions"
            )

        # A colour code with the quantity glued on, "-YB FOR LGM61" for LGM6 and 1, or
        # with a stray letter, "-VRC1 FOR BWCQ11" for BWC1 and 1 (FZS 21C8).
        split = self._split_glued_colour_qty(rows, table_abbrs)
        if split:
            logger.debug(f"{pdf_path.name}: split {split} colour code(s) glued to a quantity")

        # A part row with no quantity printed at all takes 1, by the owner's instruction
        # (CRUX 5KA1 "LEVER, COCK", FZ S 21C6 "COVER, SIDE 3 -S3"). Marked on the row.
        assumed = self._assume_missing_qty(rows)
        if assumed:
            warnings.append(f"{assumed} row(s) print no quantity; taken as 1 (qty_assumed)")

        # Prune phantom colour codes: after all colour_hint assignment is complete,
        # remove from colour_codes any colour whose abbreviation never appears in
        # even one row's colour_hint.  These "phantom" entries come from multi-year
        # foreword tables that list all variants ever produced (e.g. SMX, YB for
        # earlier model years) but the current PDF's body pages only contain parts
        # for a subset of those colours.  Keeping phantoms pollutes the UI with
        # colour chips that match 0 rows.
        #
        # Guard: only prune when at least one row actually has a hint (active_abbrs
        # non-empty).  For single-colour PDFs where NO rows carry a colour_hint,
        # the entire colour_codes list is left intact.
        active_abbrs: set[str] = set()
        for _row in rows:
            _hint = _row.get("colour_hint") or ""
            for _tok in _hint.split(","):
                _tok = _tok.strip()
                if _tok:
                    active_abbrs.add(_tok.upper())
        # A table's only colour is never a phantom: it is the model's colour.
        single_table_colour = (
            len([c for c in colour_codes if c.get("source") != "description"]) == 1
        )
        if active_abbrs and not single_table_colour:
            before_count = len(colour_codes)
            colour_codes = [c for c in colour_codes if c["abbreviation"].upper() in active_abbrs]
            pruned_count = before_count - len(colour_codes)
            if pruned_count:
                logger.debug(
                    f"{pdf_path.name}: pruned {pruned_count} phantom colour code(s) "
                    f"(0 body rows matched); kept {len(colour_codes)}"
                )

        colour_codes, model_colour_source, colour_warning = self._resolve_model_colours(
            colour_codes, active_abbrs
        )
        # A row colour outside the final colour list is a stray reading (CRUX 5KA1's
        # "HANDLE SEAT (CRUX-R)" came out coloured "CRUXR"), not a colour.
        valid = {c["abbreviation"].upper() for c in colour_codes}
        for row in rows:
            hint = row.get("colour_hint") or ""
            if hint:
                kept = [t.strip() for t in hint.split(",") if t.strip().upper() in valid]
                if kept:
                    row["colour_hint"] = ",".join(kept)
                else:
                    row.pop("colour_hint", None)
                    row.pop("colour_hint_source", None)
        if colour_warning:
            warnings.append(colour_warning)
        logger.debug(
            f"{pdf_path.name}: model colours resolved from {model_colour_source} "
            f"({sum(1 for c in colour_codes if c['is_model_colour'])}/{len(colour_codes)})"
        )

        return ExtractionResult(
            pdf_path=pdf_path,
            model=model,
            rows=rows,
            pages_scanned=pages_scanned,
            sections_found=len(sections_seen),
            ocr_flagged=ocr_flagged,
            variants=variants,
            colour_codes=colour_codes,
            model_colour_source=model_colour_source,
            available_colours=available_colours,
            manufacture_year=manufacture_year,
            model_no=model_no,
            catalogue_no=self._extract_catalogue_no(pdf_path),
            warnings=warnings,
            column_layout=column_layout,
            column_display_labels=column_display_labels,
        )

    @staticmethod
    def _extract_catalogue_no(pdf_path: Path) -> str | None:
        """The Yamaha publication number printed on the cover, e.g. "1UB9E-470EA".

        Yamaha numbers its parts catalogues as five characters, a hyphen, and five more
        (``1SB62-470EA``, ``1UB65-460EV``). 39 of the 107 covers print one; AEROX carries
        it only in its file name ("1UB65460EV-AEROX.pdf"), which is read second. None
        when neither has it — most India-market books do not.
        """
        import pdfplumber

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                text = " ".join(
                    (pdf.pages[i].extract_text() or "") for i in range(min(2, len(pdf.pages)))
                ).upper()
        except Exception:  # noqa: BLE001 - untrusted input; the number is optional
            text = ""
        m = _CATALOGUE_NO.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = _CATALOGUE_NO_GLUED.search(pdf_path.stem.upper())
        return f"{m.group(1)}-{m.group(2)}" if m else None

    def extract_all(
        self,
        pdf_root: Path,
        save_path: Path | None = None,
        max_workers: int = 4,
    ) -> pd.DataFrame:
        """Batch-extract every PDF under pdf_root and return a merged DataFrame.

        Uses parallel extraction (ThreadPoolExecutor) to process multiple PDFs
        concurrently, improving throughput for large batches.

        Args:
            pdf_root:    Root folder containing model sub-directories.
            save_path:   Optional path to write the result as Parquet.
            max_workers: Maximum concurrent workers for parallel extraction (default 4).

        Returns:
            DataFrame with COLUMNS + ["model", "source_file"] columns.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        all_dfs: list[pd.DataFrame] = []

        # Use case-insensitive .pdf suffix to avoid double-counting on Windows
        pdf_files = sorted(
            {f for f in pdf_root.rglob("*") if f.suffix.lower() == ".pdf"},
            key=lambda p: (p.parent.name.upper(), p.name.upper()),
        )
        # Catalogues the owner has excluded are not extracted in batch. Each is logged
        # with its reason so its absence from the output is explained, not silent.
        kept = []
        for f in pdf_files:
            reason = override_for(f).excluded_reason
            if reason:
                logger.info(f"extract_all: excluded {f.parent.name}/{f.name} — {reason}")
            else:
                kept.append(f)
        pdf_files = kept

        if not pdf_files:
            empty = pd.DataFrame(columns=COLUMNS + ["model", "source_file", "ocr_used"])
            if save_path:
                empty.to_parquet(save_path, index=False)
            return empty

        logger.info(f"extract_all: {len(pdf_files)} PDFs, {max_workers} workers")

        def extract_one(pdf_file: Path) -> tuple[Path, str, pd.DataFrame | None]:
            """Extract one PDF, returning (path, model_name, dataframe or None)."""
            model_name = pdf_file.parent.name
            try:
                logger.info(f"Extracting [{model_name}] {pdf_file.name}")
                result = self.extract(pdf_file, model=model_name)
                logger.debug(result.summary())

                if result.error:
                    logger.error(f"  → skipped: {result.error}")
                    return (pdf_file, model_name, None)

                if not result.rows:
                    logger.warning("  → no rows extracted")
                    return (pdf_file, model_name, None)

                df = result.df.copy()
                df["model"] = model_name
                df["source_file"] = pdf_file.name
                df["ocr_used"] = False
                return (pdf_file, model_name, df)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Extract failed for {pdf_file}: {exc}")
                return (pdf_file, model_name, None)

        # Parallel extraction using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(extract_one, pf): pf for pf in pdf_files}
            for completed, future in enumerate(as_completed(futures), start=1):
                try:
                    pdf_file, model_name, df = future.result()
                    if df is not None:
                        all_dfs.append(df)
                    logger.debug(f"Completed {completed}/{len(pdf_files)}: {pdf_file.name}")
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Future failed: {exc}")

        if not all_dfs:
            empty = pd.DataFrame(columns=COLUMNS + ["model", "source_file", "ocr_used"])
            if save_path:
                empty.to_parquet(save_path, index=False)
            return empty

        merged = pd.concat(all_dfs, ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["model", "source_file", "part_no", "ref_no", "fig_no"],
        )

        logger.info(
            f"Extraction complete: {len(merged)} total rows | "
            f"{merged['part_no'].nunique()} distinct part numbers | "
            f"{merged['model'].nunique()} models"
        )

        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(save_path, index=False)
            logger.info(f"Saved → {save_path}")

        return merged

        if not all_dfs:
            empty = pd.DataFrame(columns=COLUMNS + ["model", "source_file", "ocr_used"])
            if save_path:
                empty.to_parquet(save_path, index=False)
            return empty

        merged = pd.concat(all_dfs, ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["model", "source_file", "part_no", "ref_no", "fig_no"],
        )

        logger.info(
            f"Extraction complete: {len(merged)} total rows | "
            f"{merged['part_no'].nunique()} distinct part numbers | "
            f"{merged['model'].nunique()} models"
        )

        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(save_path, index=False)
            logger.info(f"Saved → {save_path}")

        return merged

    # ------------------------------------------------------------------
    # Word-position helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_run_together_part_numbers(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Split a part number that the PDF prints flush against its description.

        Some catalogues typeset ``5TS-WF151-00-00FRONT FENDER`` with no gap, so the
        whole thing arrives as one word. ``_PN_PAT`` ends in a word boundary, which
        fails before the ``F``; the regex then backtracks to the three-segment
        ``5TS-WF151-00`` and the row is stored under a part number that does not exist,
        with ``-00`` and ``FRONT`` silently gone. Splitting the token first gives the
        pattern a clean part number and the description its first word back.

        The two halves share the original box, divided in proportion to their length,
        which is accurate enough for the column router: only the split point's x
        matters, and it falls well inside the part-number column.
        """
        out: list[dict[str, Any]] = []
        for word in words:
            text = word["text"]
            # A reference glued to the front, "1a)5KA-H3500-00-00": split it off so the
            # part number stands alone. Without this the row's only readable part number
            # was the 9-digit column's, and the real one was lost with its description.
            glued = _REF_GLUED.match(text)
            if glued and (_PN_PAT.match(glued.group(2)) or _PN_BAD_SEPARATOR.match(glued.group(2))):
                ref, rest = glued.group(1), glued.group(2)
                split_x = word["x0"] + (word["x1"] - word["x0"]) * len(ref) / len(text)
                out.append({**word, "text": ref, "x1": split_x})
                word = {**word, "text": rest, "x0": split_x}
                text = rest
            # A stray hyphen inside the second segment, "4LS-E-111F-00-00" for
            # "4LS-E111F-00-00": five segments match no part-number shape.
            misprint = _PN_EXTRA_HYPHEN.match(text)
            if misprint:
                word = {**word, "text": "{}-{}{}-{}-{}".format(*misprint.groups())}
                text = word["text"]
            # A dot or doubled hyphen for the first separator, "5YY.F6331-00-00": the
            # reader otherwise skips it and takes the row's 9-digit number as the part.
            separator = _PN_BAD_SEPARATOR.match(text)
            if separator and ("." in text[:15] or "--" in text or "–-" in text):
                word = {**word, "text": "{}-{}-{}-{}{}".format(*separator.groups())}
                text = word["text"]
            short = _PN_SHORT_ZERO.match(text)
            if short:
                word = {**word, "text": "{}-00{}".format(*short.groups())}
                text = word["text"]
            label = _PN_LABEL_GLUED.match(text)
            if label:
                split_x = word["x0"] + (word["x1"] - word["x0"]) * (len(label.group(1)) + 1) / len(
                    text
                )
                out.append({**word, "text": label.group(1), "x1": split_x})
                word = {
                    **word,
                    "text": f"{label.group(2)}-{label.group(3)}",
                    "x0": split_x,
                }
                text = word["text"]
            stray = _PN_STRAY_LETTER.match(text)
            if stray:
                word = {**word, "text": "{}{}".format(*stray.groups())}
                text = word["text"]
            match = _PN_RUN_TOGETHER.match(text)
            if not match:
                out.append(word)
                continue
            pn, rest = match.group(1), match.group(2)
            width = word["x1"] - word["x0"]
            split_x = word["x0"] + width * len(pn) / len(word["text"])
            out.append({**word, "text": pn, "x1": split_x})
            out.append({**word, "text": rest, "x0": split_x})
        return out

    @staticmethod
    def _side_by_side_tables(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Split a page that prints two parts tables side by side into one list per table.

        CRUX 5KA1 page 58 lays its exclusive-parts list out in two tables, left and
        right. Read as one table, the column bounds come from the left one, so every
        right-hand part lost its description and quantity, and a right-hand part that
        shared a line with a left-hand one was dropped outright.

        A second table is recognised only when two columns of 12-digit part numbers
        stand at least ``_TABLE_GAP`` apart, each with a reference number printed just
        to its left on most rows. An Escort or Superseded 12-digit column fails that
        last test: what sits to its left is a 9-digit number or a quantity, not a ref.

        Business meaning: every part on a two-table page is extracted with its own
        description and quantity instead of a third of them being silently lost.
        """
        anchors = sorted(
            (w for w in words if _TWELVE_DIGIT.match(w["text"])), key=lambda w: w["x0"]
        )
        clusters: list[list[dict[str, Any]]] = []
        for word in anchors:
            if clusters and word["x0"] - clusters[-1][-1]["x0"] <= _TABLE_GAP / 4:
                clusters[-1].append(word)
            else:
                clusters.append([word])
        tables = [c for c in clusters if len(c) >= _TABLE_MIN_ROWS]
        if len(tables) != 2 or tables[1][0]["x0"] - tables[0][-1]["x0"] < _TABLE_GAP:
            return [words]

        def ref_share(column: list[dict[str, Any]]) -> float:
            with_ref = 0
            for pn in column:
                with_ref += any(
                    _REF_TOKEN.match(w["text"])
                    and abs(w["top"] - pn["top"]) <= _Y_TOL
                    and 0 <= pn["x0"] - w["x1"] <= _REF_MAX_GAP
                    for w in words
                )
            return with_ref / len(column)

        if min(ref_share(tables[0]), ref_share(tables[1])) < _REF_SHARE:
            return [words]
        split_x = tables[1][0]["x0"] - _REF_MAX_GAP - 10
        return [
            [w for w in words if w["x0"] < split_x],
            [w for w in words if w["x0"] >= split_x],
        ]

    @staticmethod
    def _drop_unreliable_suffix_hints(
        rows: list[dict[str, Any]], suffix_map: dict[str, str]
    ) -> str | None:
        """Remove colours read from part-number suffixes where the book contradicts them.

        CRUX 5KA1's table maps 00/10/20 to BG/CNM/DCC2, and every part whose number
        differs only in that segment was coloured by it: "METER ASSY (PRICOL)" -00 as
        BG and "(JNS INST LTD)" -10 as CNM, though those are two suppliers. Even its
        painted CRUX-R parts disagree: "COWLING ASSY" -10 is printed SILVER.

        * Where a description names a colour and the suffix implies another more often
          than the two agree, the suffix code does not mean colour in this book, and no
          row keeps a colour taken from it.
        * A row whose description carries its own qualifier — "(PRICOL)", "-CRUX-R",
          "(12V 2.0W)" — differs from its siblings by that, not by colour.

        Business meaning: a part is tied to a paint colour only on the catalogue's word,
        never because its number resembles a coloured part's.
        """
        if not suffix_map:
            return None
        agree = disagree = 0
        for row in rows:
            segs = (row.get("part_no") or "").split("-")
            named = (row.get("desc_colour") or "").upper()
            if len(segs) >= 3 and segs[2] in suffix_map and named:
                if suffix_map[segs[2]] == named:
                    agree += 1
                else:
                    disagree += 1
        book_wide = disagree > agree
        dropped = 0
        for row in rows:
            if row.get("colour_hint_source") != "suffix":
                continue
            if row.get("desc_colour"):
                # The description states the colour itself; it stands on its own word.
                row["colour_hint"] = row["desc_colour"]
                row["colour_hint_source"] = "description"
                continue
            desc = (row.get("description") or "").upper()
            tail = re.search(r"(?:\(([^()]*)\)?|[-–]\s*([A-Z0-9][A-Z0-9 \-]*))\s*$", desc)
            qualifier = tail and (tail.group(1) or tail.group(2) or "").strip()
            qualified = bool(qualifier) and not (
                set(re.split(r"[\s\-/]+", qualifier)) & _COLOUR_NAME_WORDS
            )
            if book_wide or qualified:
                row.pop("colour_hint", None)
                row.pop("colour_hint_source", None)
                dropped += 1
        if not dropped:
            return None
        if book_wide:
            return (
                f"part-number suffix colours dropped on {dropped} row(s): descriptions "
                f"contradict them ({disagree} against, {agree} for)"
            )
        return None

    @staticmethod
    def _split_glued_colour_qty(rows: list[dict[str, Any]], abbrs: set[str]) -> int:
        """Split a quantity off a colour code it is printed flush against.

        FZS 21C8 prints "CAST WHEEL, REAR -YB FOR LGM61": LGM6 is the colour and 1 the
        quantity, and the row had no quantity. "SCOOP & GUIDE AIR 1 -VRC1 FOR BWCQ11"
        is BWC1 and 1 with a stray letter. Only a row with no quantity is touched, and
        only when the remainder is a colour in the book's own table.
        """
        split = 0
        for row in rows:
            if re.search(r"\d", row.get("qty") or ""):
                continue
            desc = (row.get("description") or "").rstrip()
            m = re.search(r"[A-Z0-9]+$", desc.upper())
            if not m or not abbrs or m.group() in abbrs:
                continue
            token = m.group()
            for cut in (1, 2):
                head, qty = token[:-cut], token[-cut:]
                if not head or not qty.isdigit():
                    continue
                code = head if head in abbrs else None
                if code is None and head[-1:].isdigit():
                    # One stray character inside the code: "BWCQ1" is "BWC1".
                    code = next(
                        (
                            a
                            for a in sorted(abbrs)
                            if len(a) == len(head) - 1
                            and any(head[:i] + head[i + 1 :] == a for i in range(len(head)))
                        ),
                        None,
                    )
                if code is not None:
                    row["description"] = f"{desc[: m.start()]}{code}"
                    row["qty"] = qty
                    split += 1
                    break
        return split

    @staticmethod
    def _assume_missing_qty(rows: list[dict[str, Any]]) -> int:
        """Give a part row that prints no quantity a quantity of 1, and mark it.

        By the owner's instruction: CRUX 5KA1's "LEVER, COCK" and "TIRE (2.75 X 8)
        TVS", FZ S 21C6's "COVER, SIDE 3 -S3" print a part number and a name but leave
        the quantity cell blank. Kit footnotes and kit headers ("BRAKE PAD KIT",
        "(CONSISTING OF REF. NOS. 8 & 10)") name a set rather than a fitted part and
        keep no quantity. On a multi-model page the 1 applies to every model.
        """
        assumed = 0
        for row in rows:
            if re.search(r"\d", row.get("qty") or "") or row.get("kit_note"):
                continue
            desc = (row.get("description") or "").upper()
            if not re.search(r"[A-Z]{3,}", desc) or re.search(r"\bKIT\b|CONSISTING", desc):
                continue
            row["qty"] = "1"
            row["qty_assumed"] = True
            assumed += 1
        return assumed

    @staticmethod
    def _has_qty_word(words: list[dict[str, Any]], bounds: ColBounds | None) -> bool:
        """Whether any of these words sits in a quantity column as a quantity."""
        if bounds is None:
            return False
        for w in words:
            if not _QTY_DIGITS.match(w["text"]):
                continue
            centre = (w["x0"] + w["x1"]) / 2
            if bounds.qty_col_xs and any(abs(centre - x) <= 8 for x in bounds.qty_col_xs):
                return True
            if (
                not bounds.qty_col_xs
                and bounds.qty_start < 9000
                and w["x0"] >= bounds.qty_start - _QTY_HEADER_OVERHANG
                and (bounds.rem_start >= 9000 or w["x0"] < bounds.rem_start)
            ):
                return True
        return False

    @staticmethod
    def _infer_qty_column(
        word_rows: list[tuple[float, list[dict]]], bounds: ColBounds | None
    ) -> ColBounds | None:
        """Place the quantity column from the page's digits when no header names it.

        FZS21C2 heads its table "PART NO. PART NAME REMARKS" with no Q'TY label, so the
        column was unknown and the reader fell back to guessing from text: "CAST WHEEL,
        FRONT-CALM YELLOW 1" came out as description "CAST", remark "WHEEL,". The
        quantities still stand in a column — right-aligned digits ending at one x — and
        that column is used when enough of the page's part rows agree on it.
        """
        if (
            bounds is None
            or bounds.qty_start < 9000
            or bounds.qty_col_xs
            or bounds.desc_start >= 9000
        ):
            return bounds
        limit = min(
            bounds.rem_start,
            bounds.nine_digit_start,
            bounds.escort_start,
            bounds.superseded_start,
        )
        ends: _Counter[int] = _Counter()
        lefts: dict[int, float] = {}
        part_rows = 0
        for _y, ws in word_rows:
            pn = next((w for w in ws if _PN_PAT.match(w["text"])), None)
            if pn is None:
                continue
            part_rows += 1
            digits = [
                w for w in ws if _QTY_DIGITS.match(w["text"]) and pn["x1"] + 40 < w["x0"] < limit
            ]
            if digits:
                last = max(digits, key=lambda w: w["x0"])
                key = round(last["x1"] / 3)
                ends[key] += 1
                lefts[key] = min(lefts.get(key, last["x0"]), last["x0"])
        if not ends:
            return bounds
        key, count = ends.most_common(1)[0]
        if count < _QTY_INFER_MIN_ROWS or count < _QTY_INFER_SHARE * part_rows:
            return bounds
        return replace(bounds, qty_start=lefts[key] - 2)

    @staticmethod
    def _group_by_y(words: list[dict[str, Any]]) -> list[tuple[float, list[dict]]]:
        """Group words into rows by Y coordinate using a sequential sliding window.

        Words are sorted by `top`, then each word joins the current row if its
        `top` is within _Y_TOL pts of the row's representative Y.  This avoids
        the fixed-bucket rounding artifact where two words 4 pts apart can fall
        into different buckets even though they're on the same visual line.
        """
        if not words:
            return []
        sorted_w = sorted(words, key=lambda w: w["top"])
        groups: list[tuple[float, list[dict]]] = []
        row_y = sorted_w[0]["top"]
        row_ws: list[dict] = [sorted_w[0]]
        for w in sorted_w[1:]:
            if abs(w["top"] - row_y) <= _Y_TOL:
                row_ws.append(w)
            else:
                groups.append((row_y, sorted(row_ws, key=lambda ww: ww["x0"])))
                row_y = w["top"]
                row_ws = [w]
        groups.append((row_y, sorted(row_ws, key=lambda ww: ww["x0"])))
        return groups

    @staticmethod
    def _detect_col_bounds(
        word_rows: list[tuple[float, list[dict]]],
    ) -> ColBounds | None:
        """Detect all column boundaries from the page header rows.

        Pass 1 — explicit header identification (_detect_header_row):
          Scans for the header row (containing ≥3 column keywords such as PART,
          DESCRIPTION, REMARKS, QTY) and records the x-start of every column
          found there.  This gives us pn_start, desc_start, and qty_start which
          the old code never detected.

        Pass 2 — specialised detection (existing logic, unchanged):
          - "REMARKS" keyword  → rem_start (rightmost column anchor)
          - Variant-code tokens on header rows → qty_col_xs (multi-variant)
          - "9 DIGIT PART NO." / "SUPERSEDED PART NO." → extra column starts

        Pass-2 results take precedence over Pass-1 for the columns they cover
        (rem_start, nine_digit_start, superseded_start) because the existing
        detection is tuned for split-row headers and CRUX-style double-headers.
        """
        # A column header sits above the data it heads, never below it. Rows after the
        # page's last part-number row are footers, and some catalogues print a column
        # legend there ("Part No. … existing part … 9 digit … remarks"). Left in, that
        # legend was taken as the header: on YBX125's continuation pages it set the
        # Remarks column to start at x=219, so every description and quantity to its
        # right was filed as a remark — 221 rows lost their quantities that way.
        last_data_row = max(
            (
                i
                for i, (_y, ws) in enumerate(word_rows)
                if _PN_PAT.search(" ".join(w["text"].upper() for w in ws))
            ),
            default=None,
        )
        if last_data_row is not None:
            word_rows = word_rows[: last_data_row + 1]

        # ── Pass 1: full header row scan ──────────────────────────────────────
        header = YamahaCatalogueExtractor._detect_header_row(word_rows)
        # Unpack col_labels injected under the "_labels" sentinel key.
        col_labels: dict[str, str] = header.pop("_labels", {})  # type: ignore[arg-type]
        pn_start = header.get("part_no", 9999.0)
        desc_start = header.get("description", 9999.0)
        qty_start = header.get("qty", 9999.0)
        escort_start = header.get("escort", 9999.0)
        # Seed from header; Pass 2 may refine these three below.
        rem_start = header.get("remarks", 9999.0)
        nine_digit_start = header.get("nine_digit", 9999.0)
        superseded_start = header.get("superseded", 9999.0)

        # ── Pass 2: specialised detection (original logic) ────────────────────
        raw_vc_xs: list[float] = []  # accumulate variant-code x-centres

        for _y, ws in word_rows[:25]:
            texts = [w["text"].upper() for w in ws]
            joined_up = " ".join(texts)

            # REMARKS anchor
            rem_idx = next((i for i, t in enumerate(texts) if t == "REMARKS"), None)
            if rem_idx is not None:
                rem_start = ws[rem_idx]["x0"]

            # CRUX-style "12 DIGIT" + "9 DIGIT" double-header — both show "DIGIT".
            # Strip parentheses so "(9 DIGIT)" also counts (India-market catalogues).
            # NOTE: do NOT set rem_start here.  CRUX has no REMARKS column; the 9 DIGIT
            # column is correctly detected via the flat-scan nine_digit_start path below.
            # Setting rem_start from the "9" token caused remarks_is_nine_digit=True, which
            # cleared nine_digit_start and routed 9-digit values into the remarks field.
            # Skip data rows (contain part numbers) — only collect codes from
            # column-header rows.  Remark qualifiers (DBNM8, MBL2, etc.) appear
            # on data rows and would otherwise pollute qty_col_xs.
            if _PN_PAT.search(joined_up):
                continue

            # Accumulate variant-code column headers from every header row.
            # Require ≥2 variant codes on the same row: a model stamp (e.g. "1SU5")
            # satisfies _is_variant_code on its own and would create a spurious
            # single-entry qty_col_xs, forcing multi-variant positional mode
            # with the wrong column positions (root cause for ENTICER 5US1).
            row_vcs = [
                w for w in ws if YamahaCatalogueExtractor._is_variant_code(w["text"].upper())
            ]
            if len(row_vcs) >= 2:
                # Deduplicate by code text within a single row.  Some PDFs (e.g.
                # FASINO foreword) print the same variant code in BOTH a "Q'ty
                # Column" cell and a "Model Code" cell on the same row, giving two
                # x-positions for one variant.  Keep only the leftmost occurrence
                # so we don't create a phantom second qty-column slot.
                seen_in_row: set[str] = set()
                for w in row_vcs:
                    code = w["text"].upper()
                    if code not in seen_in_row:
                        seen_in_row.add(code)
                        raw_vc_xs.append((w["x0"] + w["x1"]) / 2)

        # Sort and deduplicate near-identical x-centres (within 8 px)
        qty_col_xs: list[float] = []
        for cx in sorted(raw_vc_xs):
            if not qty_col_xs or cx - qty_col_xs[-1] > 8.0:
                qty_col_xs.append(cx)

        # ── India-market extra column detection ───────────────────────────────
        # "9 DIGIT PART NO." and "SUPERSEDED PART NO." headers may be split
        # across different Y-rows (pdfplumber groups words by Y-band, so "9" at
        # y=40 and "DIGIT" at y=44 land in separate word-rows).  A flat x-proximity
        # scan across header-only rows handles this reliably: we pair each "DIGIT"
        # token with any "9" token whose x0 is within 50 pts to its left.
        #
        # IMPORTANT: exclude data rows.  A part-list row with ref_no=9 (e.g.
        # "9@441") would pair with the "DIGIT@470" from the "12 DIGIT" column
        # header (gap=29 px < 50 threshold), falsely setting nine_digit_start to
        # the ref-no column (~441 px) and routing ALL content into nine_digit.
        flat_words: list[dict] = []
        for _, ws in word_rows[:25]:
            if not _PN_PAT.search(" ".join(w["text"] for w in ws)):
                flat_words.extend(ws)
        # Strip parentheses so "(9" matches "9" and "DIGIT)" matches "DIGIT".
        # Handles "REMARKS (9 DIGIT)" column headers in India-market catalogues.
        digit_x_list = [
            w["x0"] for w in flat_words if w["text"].upper().strip("()") in ("DIGIT", "DIGITS")
        ]
        nine_x_list = [w["x0"] for w in flat_words if w["text"].strip("()") == "9"]
        sup_words = [w for w in flat_words if w["text"].upper() == "SUPERSEDED"]

        for dig_x in digit_x_list:
            near_nines = [x for x in nine_x_list if x < dig_x and dig_x - x < 50]
            if near_nines and nine_digit_start >= 9000:
                nine_digit_start = max(near_nines)  # nearest "9" left of "DIGIT"
                break

        if sup_words and superseded_start >= 9000:
            superseded_start = min(w["x0"] for w in sup_words)

        # Right-aligned column data sits to the left of the header word's left edge.
        # Shift nine_digit_start inward so data values that start just left of the
        # detected header x-position are routed correctly.
        # Observed offsets: 6 px in ENTICER 5US1, ~9 px in CRUX-S PC5KA5.
        # Use 15 px to cover both catalogues with margin.
        if nine_digit_start < 9000:
            nine_digit_start = max(0.0, nine_digit_start - 15.0)

        # Detect "REMARKS (9 DIGIT)" layout: rem_start and nine_digit_start land at
        # the same physical column (within 40 pts).  In this layout the REMARKS
        # column IS the 9-digit part number column — content routes to rem_start
        # (the remarks field) so nine_digit_start is cleared to avoid double-routing.
        remarks_is_nine_digit = False
        if nine_digit_start < 9000 and rem_start < 9000 and abs(nine_digit_start - rem_start) < 40:
            remarks_is_nine_digit = True
            # Use the leftmost anchor of the merged "REMARKS (9 DIGIT)" column header
            # so data values aligned with either token are captured.
            rem_start = min(rem_start, nine_digit_start)
            nine_digit_start = 9999.0  # content routes via rem_start → remarks field

        # ── India-market single-variant qty column (e.g. GLADIATOR 5 SPEED) ──
        # India-market PDFs (remarks_is_nine_digit=True) have one variant-code
        # column header (e.g. "5YY8") between description and REMARKS columns.
        # The ≥2-variant guard skips single-code rows, leaving qty_col_xs empty.
        # Without a qty zone, _split_after in greedy mode pops description-suffix
        # digits ("COVER, CYLINDER HEAD SIDE 3 1" → qty="3/1") instead of the
        # actual qty "1".  Re-scan header rows for a single variant code in the
        # desc–rem gap; enabling multi-variant positional mode then lets the
        # existing footnote-marker guard route the trailing "3" back to desc.
        if remarks_is_nine_digit and not qty_col_xs and desc_start < 9000 and rem_start < 9000:
            for _, _ws_india in word_rows[:25]:
                if _PN_PAT.search(" ".join(w["text"] for w in _ws_india)):
                    continue  # data row — skip
                _india_vcs = [
                    w
                    for w in _ws_india
                    if YamahaCatalogueExtractor._is_variant_code(w["text"].upper())
                    and w["x0"] > desc_start  # must be past description column
                    and w["x0"] < rem_start  # must be before REMARKS column
                ]
                if _india_vcs:
                    qty_col_xs = [(w["x0"] + w["x1"]) / 2 for w in _india_vcs]
                    break

        # ── Single-variant-code qty_start detection (CRUX-style and 45SB-style) ──
        # When a PDF has exactly ONE variant-code token as a column header (e.g.
        # "IAK5" for CRUX, "BS54" for 45SB Final), that token sits on a row above
        # the main anchor row so _detect_header_row misses it.  Scan the first 25
        # word-rows here to find it and record its x-position as qty_start.
        # Guard: skip India-market layouts (remarks_is_nine_digit=True) because
        # their nine_digit_start was intentionally cleared to 9999 and a leftover
        # variant-like token could create a spurious qty_start.
        # Upper bound: use the smaller of nine_digit_start and rem_start so we
        # don't accidentally absorb a 9-digit or remarks column as the qty column.
        if not qty_col_xs and qty_start >= 9000 and desc_start < 9000 and not remarks_is_nine_digit:
            _qty_upper = min(nine_digit_start, rem_start) + 30.0
            for _y2, ws2 in word_rows[:25]:
                if _PN_PAT.search(" ".join(w["text"] for w in ws2)):
                    continue  # data row — skip
                sv_vcs = [
                    w
                    for w in ws2
                    if YamahaCatalogueExtractor._is_variant_code(w["text"].upper())
                    and w["x0"] > desc_start + 15.0  # clearly past description zone
                    and w["x0"] < _qty_upper
                ]
                if len(sv_vcs) == 1:
                    # Subtract a margin for right-aligned data: qty digit x0 can
                    # sit a few px left of the column-header word's x0 (same
                    # right-alignment offset seen in nine_digit_start, fixed with -15).
                    qty_start = max(0.0, sv_vcs[0]["x0"] - 10.0)
                    break

        if nine_digit_start < 9000 or superseded_start < 9000:
            logger.debug(
                "Extra columns detected: nine_digit_start={:.1f} "
                "superseded_start={:.1f} rem_start={:.1f} remarks_is_nine_digit={}",
                nine_digit_start,
                superseded_start,
                rem_start,
                remarks_is_nine_digit,
            )

        any_detected = (
            rem_start < 9000
            or qty_col_xs
            or nine_digit_start < 9000
            or superseded_start < 9000
            or pn_start < 9000
            or desc_start < 9000
            or qty_start < 9000
        )
        # Detect bilingual (Spanish/English) catalogue: "DESCRIPCION" (Spanish, no T)
        # appears in the header block alongside the standard English "DESCRIPTION".
        # These catalogues have two header rows per column — Spanish then English —
        # and two description rows per data row — Spanish then English.
        is_bilingual = any(
            _BILINGUAL_HDR_PAT.search(" ".join(w["text"] for w in ws))
            for _, ws in word_rows[:15]
            if not _PN_PAT.search(" ".join(w["text"] for w in ws))
        )

        if any_detected:
            return ColBounds(
                pn_start=pn_start,
                desc_start=desc_start,
                qty_start=qty_start,
                rem_start=rem_start,
                qty_col_xs=qty_col_xs,
                nine_digit_start=nine_digit_start,
                escort_start=escort_start,
                superseded_start=superseded_start,
                header_detected=bool(header),
                remarks_is_nine_digit=remarks_is_nine_digit,
                is_bilingual=is_bilingual,
                col_labels=col_labels,
            )
        return None

    @staticmethod
    def _detect_header_row(
        word_rows: list[tuple[float, list[dict]]],
    ) -> dict[str, float]:
        """Find the column-header BLOCK and return {logical_col: x_start}.

        Yamaha PDFs frequently split column headers across two Y-rows, e.g.:

            Row A:  REF.   PART NO.   DESCRIPTION   REMARKS
            Row B:  NO.               Q'TY

        The old "first row with ≥3 hits" approach missed Q'TY on Row B,
        causing QTY values to be classified as description.

        New approach — scan the header BLOCK:
        1. Find the first non-data row containing both a part-label keyword
           ("PART" or "DESCRIPTION") and a column-anchor keyword
           ("DESCRIPTION", "REMARKS", or "Q'TY"/"QTY").
        2. From that row onward accumulate column x-positions across every
           subsequent non-data row (up to 6 more rows).
        3. Return the merged column map.

        Returned keys (only present for detected columns):
          "ref_no", "part_no", "description", "qty", "remarks",
          "nine_digit", "superseded"
        """

        def _classify(
            norms: list[str],
            ws_: list[dict],
            col_starts: dict[str, float],
            col_labels: dict[str, str],
        ) -> None:
            """Classify words on one row into col_starts (in-place).

            Also records the PDF's actual header text in col_labels so the UI
            can show "Existing Part No." instead of the generic "Part No." label.
            """
            bare = [n.replace("'", "") for n in norms]
            # Strip parentheses so "(9" matches "9" and "DIGIT)" matches "DIGIT".
            # This handles "REMARKS (9 DIGIT)" headers in India-market catalogues.
            stripped = [n.strip("()") for n in norms]
            for i, (norm, br, w) in enumerate(zip(norms, bare, ws_, strict=False)):
                if norm == "REF" and "ref_no" not in col_starts:
                    col_starts["ref_no"] = w["x0"]
                elif norm == "EXISTING" and "part_no" not in col_starts:
                    # "EXISTING PART NO." — the 12-digit column in ENTICER catalogues.
                    # Mark the label so the UI shows "Existing Part No." not "Part No."
                    col_starts["part_no"] = w["x0"]
                    col_labels["part_no"] = "Existing Part No."
                elif norm == "ESCORT" and "escort" not in col_starts:
                    # "ESCORT 12 DIGIT PART NO." — alternate part number column in ENTICER.
                    col_starts["escort"] = w["x0"]
                    col_labels["escort_part_no"] = "Escort 12 Digit Part No."
                elif norm == "PART" and "part_no" not in col_starts:
                    col_starts["part_no"] = w["x0"]
                elif norm in ("DESCRIPTION", "DESC") and "description" not in col_starts:
                    col_starts["description"] = w["x0"]
                elif norm == "NAME" and "description" not in col_starts:
                    # "PART NAME" header (ENTICER, SZ-old-format): map to description field.
                    # Guard: only accept "NAME" if the previous token was "PART" or it
                    # follows immediately after "EXISTING", to avoid misclassifying lone
                    # "NAME" tokens in foreword sentences.
                    prev_norm = norms[i - 1] if i > 0 else ""
                    if prev_norm in ("PART", "EXISTING"):
                        col_starts["description"] = w["x0"]
                        col_labels["description"] = "Part Name"
                elif br in ("QTY", "QUANTITY") and "qty" not in col_starts:
                    col_starts["qty"] = w["x0"]
                elif (
                    YamahaCatalogueExtractor._is_variant_code(norm)
                    and "qty" not in col_starts
                    and "description" in col_starts
                    and w["x0"] > col_starts.get("description", 0.0)
                ):
                    # Variant-code column header (e.g. "5US1" in ENTICER catalogues)
                    # used in place of "QTY" — record its x-position as qty_start.
                    col_starts["qty"] = w["x0"]
                elif norm == "REMARKS" and "remarks" not in col_starts:
                    col_starts["remarks"] = w["x0"]
                elif norm == "SUPERSEDED" and "superseded" not in col_starts:
                    col_starts["superseded"] = w["x0"]
                elif stripped[i] == "9" and "nine_digit" not in col_starts:
                    for look in range(i + 1, min(i + 3, len(norms))):
                        if stripped[look] in ("DIGIT", "DIGITS"):  # handle both singular and plural
                            col_starts["nine_digit"] = w["x0"]
                            break

        # ── Step 1: find the first row that anchors the header block ──────────
        header_start: int | None = None
        for idx, (_y, ws) in enumerate(word_rows[:30]):
            joined_raw = " ".join(w["text"] for w in ws)
            if _PN_PAT.search(joined_raw):
                continue  # skip data rows

            nset = {w["text"].upper().strip().rstrip(".") for w in ws}
            bare_set = {n.replace("'", "") for n in nset}

            # Standard anchor: row has a part-label AND a column anchor
            has_part_label = "PART" in nset or "DESCRIPTION" in nset or "EXISTING" in nset
            has_col_anchor = (
                "DESCRIPTION" in nset
                or "REMARKS" in nset
                or "QTY" in bare_set
                or "ESCORT" in nset  # ENTICER-family: ESCORT column is a reliable anchor
                or "SUPERSEDED" in nset  # ENTICER-family: SUPERSEDED appears in header
            )

            if has_part_label and has_col_anchor:
                header_start = idx
                break

        if header_start is None:
            return {}

        # ── Step 2: collect from the full header block ────────────────────────
        col_starts: dict[str, float] = {}
        col_labels: dict[str, str] = {}
        for _y, ws in word_rows[header_start : min(header_start + 6, 30)]:
            joined_raw = " ".join(w["text"] for w in ws)
            if _PN_PAT.search(joined_raw):
                break  # data row — header block ended

            norms = [w["text"].upper().strip().rstrip(".") for w in ws]
            _classify(norms, ws, col_starts, col_labels)

        if col_starts:
            logger.debug(
                "Header block (start={}): {}",
                header_start,
                ", ".join(f"{k}={v:.1f}" for k, v in sorted(col_starts.items())),
            )
        # Return col_starts merged with col_labels under a special "_labels" key.
        # The caller (_detect_col_bounds) unpacks them separately.
        if col_labels:
            col_starts["_labels"] = col_labels  # type: ignore[assignment]
        return col_starts

    @staticmethod
    def _is_variant_code(s: str) -> bool:
        """True for short alphanumeric tokens that mix letters and digits (variant codes)."""
        return (
            3 <= len(s) <= 5
            and s.isalnum()
            and any(c.isdigit() for c in s)
            and any(c.isalpha() for c in s)
        )

    @staticmethod
    def _collect_variant_row(
        word_rows: list[tuple[float, list[dict]]],
        counter: _Counter,
    ) -> None:
        """Scan word-rows for a QTY column-header row containing 3+ variant codes.

        In multi-variant catalogues Yamaha prints the variant codes as rotated
        column headers (e.g. J56B L56B M56B N56B for AEROX variants B65J–B65N).
        The rotated rendering means pdfplumber may read the chars bottom-to-top,
        but the tokens are still short mixed alphanumeric strings — same shape as
        real variant codes.  We count co-occurring tuples across pages so the most
        frequent combination wins.
        """
        for _y, ws in word_rows:
            texts = [w["text"].upper() for w in ws]
            vc = [t for t in texts if YamahaCatalogueExtractor._is_variant_code(t)]
            if len(vc) >= 3:
                counter[tuple(vc)] += 1

    # Colour words that MUST appear in a parenthetical description suffix for
    # it to be treated as a colour name (not a size, spec, or functional label).
    # Deliberately excludes "LIGHT", "DARK", "DEEP" etc. which appear in
    # non-colour contexts ("LIGHT ON/OFF", "DEEP BORE").
    _DESC_COLOUR_WORDS: frozenset[str] = frozenset(
        {
            "BLACK",
            "WHITE",
            "BLUE",
            "RED",
            "GREEN",
            "YELLOW",
            "ORANGE",
            "PURPLE",
            "PINK",
            "BROWN",
            "GREY",
            "GRAY",
            "SILVER",
            "GOLD",
            "CYAN",
            "MAGENTA",
            "TEAL",
            "NAVY",
            "MAROON",
            "BEIGE",
            "CREAM",
            "BRONZE",
            "COPPER",
            "TURQUOISE",
            "CANDY",
            "METALLIC",
            "MATTE",
            "MAT",
            "GLOSSY",
            "PEARL",
            "LUMINOUS",
            "VIVID",
        }
    )

    @staticmethod
    def _lift_suffix_colours(
        rows: list[dict],
        code_suffix_map: dict[str, str],
        discriminating_bases: set[str] | None = None,
    ) -> list[dict]:
        """Tag rows with colour_hint using part-number third-segment colour codes.

        Business meaning: Yamaha catalogues that carry a colour code table with
        2-digit numeric codes (e.g. CRUX-S PC5KA5: 70=YAMAHA BLACK, 80=CANDY
        MAROON, 90=SILVER 3) encode the colour in the *third segment* of the
        12-digit part number — e.g. '5KA-F4100-**70**-00'.  This method maps
        that segment to the official colour abbreviation so the agent and
        frontend can treat these rows identically to FOR/EXCEPT-remarks rows.

        ``discriminating_bases``: when provided, only rows whose base part
        (first two hyphen-segments, e.g. "5YY-F1510") is in this set are
        tagged.  Parts whose base appears with only one suffix code across the
        whole PDF (e.g. standard version-field "00" on every engine part) are
        left untagged — they are shared parts, not colour-specific variants.

        Only the invisible ``colour_hint`` key is added; description, remarks,
        and nine_digit_part_no are left unchanged.
        """
        updated: list[dict] = []
        for row in rows:
            pn = (row.get("part_no") or "").strip()
            segments = pn.split("-")
            code = segments[2] if len(segments) >= 3 else ""
            abbr = code_suffix_map.get(code, "")
            if abbr:
                if discriminating_bases is not None:
                    base = f"{segments[0]}-{segments[1]}" if len(segments) >= 2 else ""
                    if base not in discriminating_bases:
                        updated.append(row)
                        continue
                new_row = dict(row)
                new_row["colour_hint"] = abbr
                new_row["colour_hint_source"] = "suffix"
                updated.append(new_row)
            else:
                updated.append(row)
        return updated

    @staticmethod
    def _extract_remark_colour_hints(
        rows: list[dict],
        colour_codes: list[dict],
    ) -> list[dict]:
        """Tag rows using the Remarks column as the primary colour source.

        Business meaning: Yamaha India catalogues use the Remarks column to
        indicate which colour variant a part belongs to, via five forms:

          • Bare abbreviation:   "YB"              → colour_hint = "YB"
          • FOR/UR + abbr:       "FOR YB"          → colour_hint = "YB"
          • [Part] FOR [Bike]:   "LLGS6 FOR DBNM8" → colour_hint = "DBNM8"
                                 "YB FOR YB,RSH"   → colour_hint = "YB,RSH"
          • EXCEPT + abbr:       "EXCEPT YB"       → colour_hint = all other colours
          • Number suffix:       "A-2" / "14-2"    → colour_hint = foreword colour[index 2]
                                 Used when the foreword table assigns a number to each colour
                                 and the remark encodes the colour as the number after "-".
                                 Only fires when none of the above patterns matched AND the
                                 suffix number is within the foreword colour count.

        "UR" (Use specified parts number) is treated identically to "FOR" when
        the referenced token is a known foreword colour abbreviation.

        Only tokens that resolve to known foreword abbreviations are accepted.
        Remarks containing solely non-colour content (e.g. "UN", "AP") produce
        no hint, leaving the row as Shared.  Comma-separated colour_hint is
        used when a part belongs to multiple colours.

        Called before _extract_foreword_colour_hints so that remark-based
        hints have priority over description-based ones.
        """
        known_abbrs: set[str] = {
            c["abbreviation"].upper() for c in colour_codes if c.get("abbreviation")
        }
        # Preserve foreword order for EXCEPT complement and index lookup
        all_abbrs_ordered: list[str] = [
            c["abbreviation"].upper() for c in colour_codes if c.get("abbreviation")
        ]
        # 1-based index → abbreviation (foreword row position = colour index)
        index_to_abbr: dict[int, str] = {i + 1: abbr for i, abbr in enumerate(all_abbrs_ordered)}
        if not known_abbrs:
            return rows

        def _norm(s: str) -> str:
            return re.sub(r"[\s\-]", "", s)

        norm_to_abbr: dict[str, str] = {_norm(a): a for a in known_abbrs}
        name_to_abbr: dict[str, str] = {
            c["name"].upper(): c["abbreviation"].upper()
            for c in colour_codes
            if c.get("name") and c.get("abbreviation")
        }
        norm_name_to_abbr: dict[str, str] = {_norm(k): v for k, v in name_to_abbr.items()}

        def _resolve_one(token: str) -> str | None:
            cu = token.strip().upper().rstrip(".!?,;:")  # strip trailing punctuation (PDF artefact)
            if cu in known_abbrs:
                return cu
            n = _norm(cu)
            if n in norm_to_abbr:
                return norm_to_abbr[n]
            if cu in name_to_abbr:
                return name_to_abbr[cu]
            if n in norm_name_to_abbr:
                return norm_name_to_abbr[n]
            # Fuzzy: swap digit 1 ↔ letter I — a common PDF rendering artefact
            # where the foreword has "BWCI" but remarks say "BWC1" (or vice versa).
            for src, dst in (("1", "I"), ("I", "1")):
                if src in cu:
                    alt = cu.replace(src, dst)
                    if alt in known_abbrs:
                        return alt
                    alt_n = _norm(alt)
                    if alt_n in norm_to_abbr:
                        return norm_to_abbr[alt_n]
            return None

        def _split_tokens(text: str) -> list[str]:
            return [t.strip() for t in re.split(r"[,/]+", text) if t.strip()]

        _FOR_UR_RE = re.compile(r"^\s*(?:FOR|UR)\s+(.+)$", re.IGNORECASE)
        # "EXCEPT FOR YB" and "EXCEPT YB" both exclude YB from the hint set.
        _EXCEPT_RE = re.compile(r"^\s*EXCEPT\s+(?:FOR\s+)?(.+)$", re.IGNORECASE)
        _EXCEPT_INNER_RE = re.compile(r"^EXCEPT\s+(?:FOR\s+)?(.+)$", re.IGNORECASE)
        # Embedded FOR anywhere in remark text — catches "UR FOR YB", "UR S3 FOR YB"
        _INNER_FOR_RE = re.compile(r"\bFOR\s+([A-Z0-9][A-Z0-9,/\s-]*?)\s*$", re.IGNORECASE)
        # Number-suffix: remark ends with "-<digit(s)>" or IS just "<digit(s)>"
        # e.g. "A-2" → index 2, "14-3" → index 3, "2" → index 2
        # Only valid when the suffix number is within the foreword colour count.
        _NUM_SUFFIX_RE = re.compile(r"(?:^|-)(\d+)\s*$")

        def _parse_remark(rem: str) -> str | None:
            rem = rem.strip()
            if not rem:
                return None
            # EXCEPT: tag with every foreword colour NOT mentioned
            m = _EXCEPT_RE.match(rem)
            if m:
                excluded: set[str] = set()
                for tok in _split_tokens(m.group(1)):
                    a = _resolve_one(tok)
                    if a:
                        excluded.add(a)
                if excluded:
                    included = [a for a in all_abbrs_ordered if a not in excluded]
                    return ",".join(included) if included else None
                return None
            # FOR / UR prefix + colour(s)
            # Handles "FOR YB", "UR YB", "FOR YB,DRMK"
            m = _FOR_UR_RE.match(rem)
            if m:
                # Strip parenthetical descriptive notes like "(for blue scooter)"
                # appended by some catalogues after the colour code:
                # "FOR DPBML (for blue scooter)" → content = "DPBML"
                _content = re.sub(r"\s*\([^)]*\)\s*", " ", m.group(1)).strip().rstrip(".!?,;:")
                # "UR EXCEPT BWC1" → treat EXCEPT content as exclusion list
                _exc_inner = _EXCEPT_INNER_RE.match(_content)
                if _exc_inner:
                    _excluded: set[str] = set()
                    for tok in _split_tokens(_exc_inner.group(1)):
                        a = _resolve_one(tok)
                        if a:
                            _excluded.add(a)
                    if _excluded:
                        _included = [a for a in all_abbrs_ordered if a not in _excluded]
                        return ",".join(_included) if _included else None
                    return None
                resolved: list[str] = []
                for tok in _split_tokens(_content):
                    a = _resolve_one(tok)
                    if a:
                        resolved.append(a)
                # Fallback: search for embedded "FOR [colour]" within the content.
                # Handles "UR FOR YB" (outer=UR, content="FOR YB") and
                # "UR S3 FOR YB" (outer=UR, content="S3 FOR YB").
                if not resolved:
                    m_inner = _INNER_FOR_RE.search(_content)
                    if m_inner:
                        for tok in _split_tokens(m_inner.group(1)):
                            a = _resolve_one(tok)
                            if a:
                                resolved.append(a)
                return ",".join(dict.fromkeys(resolved)) if resolved else None
            # General "[part_colour] FOR [bike_colours]" — FOR anywhere in remark.
            # "LLGS6 FOR DBNM8"           → colour_hint = "DBNM8"
            # "YB FOR YB,RSH,SM12,MBM3"   → colour_hint = "YB,RSH,SM12,MBM3"
            # "LNYM9 FOR MBL2,MDRM3"      → colour_hint = "MBL2,MDRM3"
            # The colour(s) BEFORE FOR are the part's own paint code and are ignored
            # for filtering; only colours AFTER FOR are the bike-variant selectors.
            m_any_for = _INNER_FOR_RE.search(rem)
            if m_any_for:
                resolved_for: list[str] = []
                for tok in _split_tokens(m_any_for.group(1)):
                    a = _resolve_one(tok)
                    if a:
                        resolved_for.append(a)
                if resolved_for:
                    return ",".join(dict.fromkeys(resolved_for))
            # Bare form: remark consists SOLELY of colour abbreviations/names.
            # A bare colour code (e.g. "YB" on a cast wheel) marks the PART'S
            # OWN paint finish, NOT which motorcycle colour variant it belongs to.
            # Treat as universal → return None, consistent with remark_parser.py.
            # If ANY token fails to resolve, fall through to the number-suffix
            # path below so "A-2" can still reach number-suffix.
            tokens = _split_tokens(rem)
            if tokens:
                all_resolved = True
                for tok in tokens:
                    if _resolve_one(tok) is None:
                        all_resolved = False
                        break
                if all_resolved:
                    return None  # bare colour code = own paint finish = universal
            # Number-suffix fallback (last resort): "A-2", "14-2", "2" etc.
            # The foreword assigns a sequential index to each colour; the number
            # after the last "-" (or the whole remark if purely numeric) is that
            # index.  Only fires when nothing above matched AND the suffix number
            # is within the valid range [1, len(colour_codes)].
            # Guard: reject numbers with leading zeros.
            #   Yamaha colour indices are plain integers (1, 2, 3 …) — never "01".
            #   Yamaha part-number cross-references in remarks end in "-01", "-02"
            #   etc. — always with a leading zero.  This stops "4S-E1310-01"
            #   (a part-number reference) from mapping to colour index 1 (YB).
            # Remark "SL-3" never reaches here: bare form resolves "SL-3" first.
            # Remark "90387-10848" never fires: 10848 > colour count.
            m_num = _NUM_SUFFIX_RE.search(rem)
            if m_num and index_to_abbr:
                num_str = m_num.group(1)
                if not num_str.startswith("0"):  # reject "01", "02", etc.
                    idx = int(num_str)
                    abbr = index_to_abbr.get(idx)
                    if abbr:
                        return abbr
            return None

        updated: list[dict] = []
        for row in rows:
            # A remark states the colour outright; a part-number suffix only implies
            # it, and suffix codes are not stable across part families in every book.
            if row.get("colour_hint") and row.get("colour_hint_source") != "suffix":
                updated.append(row)
                continue
            rem = (row.get("remarks") or "").strip()
            hint = _parse_remark(rem)
            if hint:
                new_row = dict(row)
                new_row["colour_hint"] = hint
                new_row["colour_hint_source"] = "remarks"
                updated.append(new_row)
            else:
                updated.append(row)
        return updated

    @staticmethod
    def _extract_foreword_colour_hints(
        rows: list[dict],
        colour_codes: list[dict],
    ) -> list[dict]:
        """Tag rows whose description ends with a foreword colour abbreviation or name.

        Business meaning: some Yamaha PDFs have a proper foreword colour table
        AND embed the colour in the Description column as a trailing parenthetical.
        Two sub-formats are handled:
          • Abbreviation form: "FRONT FENDER COMP (YB)" — YB is a foreword abbreviation.
          • Name form: "FRONT FENDER (YAMAHA BLACK)" — full colour name that maps to YB.
          • Unknown-code form: "FRONT FENDER (DPBMV)" — abbreviation-shaped code not in the
            foreword table but a sibling of confirmed colour-variant rows in the same group.

        Each colour variant is a separate row with a different part number.  This method
        sets colour_hint on these rows so that _build_rosters and _assemble_builds handle
        them like standard FOR/EXCEPT remark rows.

        Only tags rows in (section, ref_no) groups that have ≥2 different part
        numbers with confirmed colour parentheticals — a lone parenthetical like
        "HOLDER (INNER)" is never tagged even if it accidentally matches.
        """
        known_abbrs: set[str] = {
            c["abbreviation"].upper() for c in colour_codes if c.get("abbreviation")
        }

        # Normalized lookup: strip hyphens and spaces for fuzzy matching.
        # Handles PDF extraction artifacts like "SL 3" → "SL3" → "SL-3",
        # or "DRM K" → "DRMK" → "DRMK".
        def _norm(s: str) -> str:
            return re.sub(r"[\s\-]", "", s)

        norm_to_abbr: dict[str, str] = {_norm(a): a for a in known_abbrs}
        # Name → abbreviation: "(YAMAHA BLACK)" maps to abbreviation "YB" etc.
        name_to_abbr: dict[str, str] = {
            c["name"].upper(): c["abbreviation"].upper()
            for c in colour_codes
            if c.get("name") and c.get("abbreviation")
        }
        abbr_to_name: dict[str, str] = {v: k for k, v in name_to_abbr.items()}
        if not known_abbrs:
            return rows

        def _words(text: str) -> list[str]:
            return [w for w in re.split(r"[\s\-]+", text) if w]

        def _word_fits(word: str, name_words: list[str]) -> bool:
            """One description word against a table name's words.

            Equal; or one a prefix of the other (a name cut off at the column edge,
            "NON M" for "NON-METALLIC"); or near-identical spelling ("METALIC" for
            "METALLIC") on words long enough that a one-letter slip is not a
            different colour.
            """
            for nw in name_words:
                if word == nw:
                    return True
                shorter, longer = sorted((word, nw), key=len)
                if (
                    len(shorter) >= 1
                    and longer.startswith(shorter)
                    and (shorter is word or len(shorter) >= 3)
                ):
                    return True
                if min(len(word), len(nw)) >= 5 and (
                    _SequenceMatcher(None, word, nw).ratio() >= _NAME_SPELLING_RATIO
                ):
                    return True
            return False

        def _words_fit(words: list[str], name_words: list[str]) -> bool:
            return bool(words) and all(_word_fits(w, name_words) for w in words)

        # Match descriptions whose suffix is a known foreword abbreviation or name.
        # Forms seen in Yamaha India catalogues:
        #   "(ABBR)"      — paren form:       "FRONT FENDER COMP (YB)"
        #   "- ABBR"      — dash-suffix form: "COVER SIDE 1 (LH)- YB", "FUEL TANK - SL-3"
        #   "(SUB)-DRM K" — dash after paren: colour has a space ("DRM K" not just "DRMK")
        #   "(SUB)YB"     — no separator:     colour appended directly after closing paren
        #   "BASE SL-3"   — no paren at all:  OCR artifact or format-B PDFs
        # _DASH allows spaces in group 2 to capture "DRM K", "SL 3", etc.
        _PAREN = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")
        # Same, with the closing bracket lost where the PDF cut the name at the column
        # edge: "FRONT FENDER (LIGHT YELLOW".
        _PAREN_OPEN = re.compile(r"^(.+?)\s*\(([^()]+)$")
        _DASH = re.compile(r"^(.+?)\s*[-–]\s*([A-Z0-9][A-Z0-9\s-]*)\s*$")
        _ABBR_LIKE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")

        def _resolve_abbr(content: str) -> str | None:
            """Return the canonical abbreviation for parenthetical content, or None."""
            cu = content.strip().upper()
            if cu in known_abbrs:
                return cu
            normed = _norm(cu)
            if normed in norm_to_abbr:
                return norm_to_abbr[normed]
            if cu in name_to_abbr:
                return name_to_abbr[cu]
            normed_name = _norm(cu)
            if normed_name in {_norm(k): v for k, v in name_to_abbr.items()}:
                return {_norm(k): v for k, v in name_to_abbr.items()}[normed_name]
            # A shortened, cut-off or misspelt name. The table says "LIGHT YELLOW GREY
            # NON-METALLIC"; descriptions say "(LIGHT YELLOW NON METALIC)", or stop at
            # the column edge as "(LIGHT YELLOW". Two words at least, and exactly one
            # table name may fit — so "(RED" can never guess between two reds.
            words = _words(cu)
            if len(words) >= 2:
                candidates = {
                    abbr for name, abbr in name_to_abbr.items() if _words_fit(words, _words(name))
                }
                if len(candidates) == 1:
                    return candidates.pop()
            return None

        def _compatible(raw_name: str, abbr: str) -> bool:
            """Does a description's colour name describe the colour ``abbr`` stands for?

            Looser than a fresh match, because it only has to avoid a false
            contradiction: "(SILVER)" is consistent with the table's "SILVER 3", even
            though a lone "SILVER" is too little to assign a colour on its own.
            """
            name = abbr_to_name.get(abbr.upper())
            return bool(name) and _words_fit(_words(raw_name.upper()), _words(name))

        def _detect_known_abbr(desc: str) -> str | None:
            """Try all extraction patterns; return a colour abbreviation or None.

            Returns known foreword abbreviations (via _resolve_abbr) for patterns
            1-3, or an unknown-but-abbreviation-shaped code for pattern 4 (FOR).
            """
            # Pattern 1: paren form — "(YAMAHA BLACK)", "(YB)"
            # Pattern 1b: dash-suffix — "COVER (LH)-YB", "FUEL TANK - SL-3"
            m = _PAREN.match(desc) or _DASH.match(desc) or _PAREN_OPEN.match(desc)
            if m:
                a = _resolve_abbr(m.group(2))
                if a is not None:
                    return a
            # Pattern 2: colour appended after closing paren with optional separator
            # Handles "(LH)YB", "(LH)-YB", "(LH) SL-3"
            if ")" in desc:
                after = desc[desc.rfind(")") + 1 :].strip().lstrip("-").strip()
                if after:
                    a = _resolve_abbr(after)
                    if a is not None:
                        return a
            # Pattern 3: description ends with a known colour abbreviation (normalised)
            # Catches "SC00P & GUIDE AIR1 SL-3" (OCR typo, no paren/dash separator)
            norm_d = _norm(desc.upper())
            for ka in sorted(known_abbrs, key=len, reverse=True):
                ka_n = _norm(ka)
                if ka_n and norm_d.endswith(ka_n) and len(norm_d) > len(ka_n):
                    return ka
            # Pattern 4: "FOR COLOUR" or "UR COLOUR" at end of description.
            # "CAST WHEEL -YB FOR CMY"    → CMY (the part is FOR the CMY colour variant).
            # "COVER SIDE -UR YB"         → YB  (UR = Use specified parts number for YB).
            # FOR is prioritised first; UR is checked separately below.
            # Even when CMY is not in the foreword table, extract it as a synthetic hint
            # so rows appear under CMY colour in the viewer.
            m_for = re.search(r"\b(?:FOR|UR)\s+([A-Z0-9][A-Z0-9\s-]*)\s*$", desc, re.IGNORECASE)
            if m_for:
                target = m_for.group(1).strip()
                a = _resolve_abbr(target)
                if a is not None:
                    return a
                unk = _norm(target.upper())
                if len(unk) >= 2:
                    # OCR prefix: unk starts with a known abbr and is only slightly longer
                    # e.g. "LGM61" → starts with "LGM6", extra "1" is OCR noise.
                    for ka in sorted(known_abbrs, key=len, reverse=True):
                        ka_n = _norm(ka)
                        if ka_n and unk.startswith(ka_n) and len(unk) <= len(ka_n) + 3:
                            return ka
                    # OCR truncation: a unique known abbr starts with unk
                    # e.g. "BWC" → "BWC1" (OCR dropped the trailing digit).
                    prefix_matches = [
                        ka
                        for ka in known_abbrs
                        if _norm(ka).startswith(unk) and len(_norm(ka)) <= len(unk) + 3
                    ]
                    if len(prefix_matches) == 1:
                        return prefix_matches[0]
                    if _ABBR_LIKE.match(unk):
                        return unk
            return None

        groups: dict[tuple[str, str], list[int]] = {}
        parsed: dict[int, str] = {}

        def _named_colour(desc: str) -> tuple[str | None, str | None]:
            """The colour a description names outright: (table abbreviation, raw name).

            Only the bracket/dash forms count — the description has to *state* a colour
            for it to overrule anything. Returns (None, raw) when a colour word is named
            that the foreword table does not list, so the caller can refuse to guess.
            """
            m = _PAREN.match(desc) or _PAREN_OPEN.match(desc) or _DASH.match(desc)
            if not m:
                return None, None
            content = m.group(2).strip()
            abbr = _resolve_abbr(content)
            if abbr is not None:
                return abbr, content
            if set(re.split(r"[\s\-]+", content.upper())) & _COLOUR_NAME_WORDS:
                return None, content
            return None, None

        for idx, row in enumerate(rows):
            key = (row.get("section", ""), row.get("ref_no", ""))
            existing = (row.get("colour_hint") or "").strip()

            # Record every colour the description names that the foreword table does
            # not list, whatever else happens to the row — these are the catalogue's
            # colours the table forgot, and the owner has to decide what they are.
            _named, _raw = _named_colour((row.get("description") or "").strip())
            if (
                _named is None
                and _raw is not None
                and not (existing and _compatible(_raw, existing.split(",")[0].strip()))
            ):
                row = {**row, "colour_name_unmatched": _raw, "desc_colour_text": _raw}
                rows[idx] = row
            elif _named is not None:
                # Kept so the colour the description itself states can be written into
                # remarks later, even when another step reached the same answer first.
                row = {**row, "desc_colour": _named, "desc_colour_text": _raw}
                rows[idx] = row

            # A part-number suffix only implies a colour, and in some books the same
            # suffix code means different colours in different part families: LIBERO
            # 5TS1's "-00-" is Yamaha Black on the front fender but Black Gold on the
            # side cover. Where the description names the colour, the description wins.
            if existing and row.get("colour_hint_source") == "suffix":
                named, raw_name = _named_colour((row.get("description") or "").strip())
                if named is not None and named != existing:
                    row = {**row, "colour_hint": named, "colour_hint_source": "description"}
                    rows[idx] = row
                    existing = named
                elif named is None and raw_name is not None and not _compatible(raw_name, existing):
                    # Names a colour that contradicts the suffix's colour and that the
                    # foreword table does not list. Asserting the suffix's colour would be
                    # wrong; leave it unattributed and say so. A name that merely shortens
                    # or misspells the suffix's colour ("SILVER" for "SILVER 3") is not a
                    # contradiction and keeps it.
                    row = {
                        k: v
                        for k, v in row.items()
                        if k not in ("colour_hint", "colour_hint_source")
                    }
                    row["colour_name_unmatched"] = raw_name
                    row["desc_colour_text"] = raw_name
                    rows[idx] = row
                    continue

            # Rows already hinted by remarks count toward group confirmation.
            # Use the first listed colour for the ≥2-distinct-colours check.
            if existing:
                primary = existing.split(",")[0].strip()
                groups.setdefault(key, []).append(idx)
                parsed[idx] = primary
                continue
            desc = (row.get("description") or "").strip()
            abbr = _detect_known_abbr(desc)
            if abbr is None:
                continue
            groups.setdefault(key, []).append(idx)
            parsed[idx] = abbr

        # Confirm groups by ≥2 distinct colour abbreviations (not part_nos).
        # Using abbreviations handles the case where the same part_no appears for
        # multiple colours (e.g. "TANK (YAMAHA BLACK)" and "TANK (SL-3)" sharing
        # part_no 5TS-XF41A-40) — distinct colours are the real confirmation signal.
        variant_idxs: set[int] = set()
        confirmed_keys: set[tuple[str, str]] = set()
        for key, idxs in groups.items():
            abbrs = {parsed[i] for i in idxs}
            if len(abbrs) >= 2:
                variant_idxs.update(idxs)
                confirmed_keys.add(key)

        if not variant_idxs:
            return rows

        # Second pass: within confirmed colour-variant groups, tag any untagged
        # sibling rows.  First tries to resolve the parenthetical to a known
        # abbreviation (handles "SL 3" → "SL-3", "DRM K" → "DRMK").
        # Falls back to using an abbreviation-shaped raw token for codes not in
        # the foreword table (e.g. "DPBMV").
        all_group_members: dict[tuple[str, str], list[int]] = {}
        for idx, row in enumerate(rows):
            key = (row.get("section", ""), row.get("ref_no", ""))
            if key in confirmed_keys:
                all_group_members.setdefault(key, []).append(idx)

        # Applicability notes ("YB FOR CMY", "SR FOR BMC") look like colour codes after
        # normalisation but are NOT colour names — they mean "use part X for colour Y".
        # Reject any raw token whose source content contains FOR/EXCEPT as a word.
        _FOR_EXCEPT_RE = re.compile(r"\bFOR\b|\bEXCEPT\b", re.IGNORECASE)

        for key in confirmed_keys:
            for idx in all_group_members.get(key, []):
                if idx in variant_idxs:
                    continue
                # Skip rows already hinted by remarks — don't overwrite
                if rows[idx].get("colour_hint"):
                    variant_idxs.add(idx)
                    continue
                desc = (rows[idx].get("description") or "").strip()
                # Try to resolve to a known abbreviation via all patterns
                abbr: str | None = _detect_known_abbr(desc)
                if abbr is None:
                    # Unknown code (e.g. "DPBMV"): fall back to abbreviation-shaped
                    # raw token from paren/dash/after-paren extraction.
                    # Reject if the source content is an applicability note like
                    # "YB FOR CMY" or "SR FOR BMC" — those are cross-colour references,
                    # not colour names, and CMY/BMC may not be in this PDF's colour table.
                    raw: str | None = None
                    raw_src: str = ""
                    m = _PAREN.match(desc) or _DASH.match(desc)
                    if m:
                        raw_src = m.group(2).strip()
                        raw = _norm(raw_src.upper())
                    elif ")" in desc:
                        after = desc[desc.rfind(")") + 1 :].strip().lstrip("-").strip()
                        if after:
                            raw_src = after
                            raw = _norm(after.upper())
                    if (
                        raw
                        and len(raw) >= 2
                        and _ABBR_LIKE.match(raw)
                        and not _FOR_EXCEPT_RE.search(raw_src)
                    ):
                        abbr = raw
                if abbr is not None:
                    parsed[idx] = abbr
                    variant_idxs.add(idx)

        updated: list[dict] = []
        for idx, row in enumerate(rows):
            if idx in variant_idxs:
                if row.get("colour_hint"):
                    # Preserve the remark-based hint; do not overwrite with description
                    updated.append(row)
                else:
                    new_row = dict(row)
                    new_row["colour_hint"] = parsed[idx]
                    new_row["colour_hint_source"] = "description"
                    updated.append(new_row)
            else:
                updated.append(row)

        return updated

    @staticmethod
    def _adopt_unlisted_desc_colours(
        rows: list[dict[str, Any]], colour_codes: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Use a colour the description names even when the foreword table omits it.

        LIBERO 5TS1 prints its fenders, tanks and covers in YAMAHA BLACK, SILVER and
        DEEP PURPLE BLUE METALLIC; CRUX-S in YAMAHA GOLD and BLACK GOLD. None is in the
        book's table. By the owner's instruction the description is used, in order:

        1. A marking is not a colour: "(blue paint mark)" on a bearing is its fit grade.
        2. A name glossing a code printed just before it — "S8 (Silver)",
           "-DBNM8 (Grey)", "- YB(BLACK)" — is that code.
        3. A shortened name whose words all belong to exactly one table colour is that
           colour: ENTICER 5US1's "(MAROON)" is Candy Maroon, CNM.
        4. Standard hardware (``9xxxx``) is left unrestricted: "NUT HEX(YELLOW)" is a
           plating, and restricting it would drop the nut from every other build.
        5. Any other name is a vehicle colour only when the same part comes in at least
           two colours — same section and ref, or same part-number base. A lone
           "PLATE, CAP -SILVER" is the part's finish; tying it to a colour the bike is
           not sold in would drop it from every real build. Confirmed names join the
           colour list as their own abbreviation with ``source`` ``description``, and
           truncated printings ("DEEP PURPLE") take the longest printed form.

        Every name not used is recorded on the row as ``colour_ignored`` with the
        reason. A colour from the row's own remark outranks the description.

        Business meaning: a body part the catalogue prints in several colours is
        attributed per colour, and nothing is tied to a colour no build carries.
        """

        def words(text: str) -> tuple[str, ...]:
            return tuple(w for w in re.split(r"[\s\-]+", text.upper()) if w)

        def family(row: dict[str, Any]) -> list[tuple[str, ...]]:
            pn = (row.get("part_no") or "").strip().upper()
            base = "-".join(pn.split("-")[:2]) if "-" in pn else pn[:8]
            keys: list[tuple[str, ...]] = [("base", base)]
            if (row.get("ref_no") or "").strip():
                keys.append(("ref", row.get("section") or "", row["ref_no"].strip()))
            return keys

        table = [
            (c["abbreviation"].upper(), set(words(c.get("name") or "")))
            for c in colour_codes
            if c.get("abbreviation") and c.get("source") != "description"
        ]
        table_abbrs = {abbr for abbr, _ in table}
        to_table: dict[tuple[str, ...], str] = {}
        pending: list[tuple[int, tuple[str, ...], str]] = []
        out: list[dict[str, Any]] = []
        for row in rows:
            raw = row.get("colour_name_unmatched")
            if not raw or row.get("colour_hint_source") == "remarks":
                out.append(row)
                continue
            row = {k: v for k, v in row.items() if k != "colour_name_unmatched"}
            name_words = words(raw)
            gloss = _COLOUR_GLOSS.search((row.get("description") or "").upper())
            code = gloss.group(1) if gloss else ""
            if "MARK" in name_words:
                row["colour_ignored"] = f"{raw} (a marking, not a vehicle colour)"
            elif code and (
                code in table_abbrs
                or gloss.group(0)[0] in "-."
                or (
                    any(ch.isdigit() for ch in code) and code.rstrip("0123456789") not in _NOT_CODES
                )
            ):
                pending.append((len(out), (code,), raw.upper()))
            elif _STANDARD_HARDWARE.match((row.get("part_no") or "").strip()):
                row["colour_ignored"] = f"{raw} (standard hardware finish)"
            else:
                owners = [abbr for abbr, tw in table if set(name_words) <= tw]
                # A name whose initials and number spell a table code is that colour:
                # CRUX 5KA1's "DEEP CYAN COCKTAIL 2" is DCC2 ("Dark Cyan Cocktail2").
                initials = "".join(w[0] for w in name_words if w.isalpha()) + "".join(
                    w for w in name_words if w.isdigit()
                )
                if not owners and initials in table_abbrs:
                    owners = [initials]
                if len(owners) == 1:
                    row.update(
                        colour_hint=owners[0],
                        colour_hint_source="description",
                        desc_colour=owners[0],
                    )
                    to_table[name_words] = owners[0]
                else:
                    pending.append((len(out), name_words, " ".join(name_words)))
            out.append(row)

        # A truncated printing of a name already resolved to a table colour is that
        # colour: "DEEP CYAN" cut from "DEEP CYAN COCKTAIL 2" is DCC2.
        still_pending = []
        for idx, name_words, label in pending:
            target = next(
                (
                    abbr
                    for full, abbr in to_table.items()
                    if len(name_words) < len(full) and full[: len(name_words)] == name_words
                ),
                None,
            )
            if target:
                out[idx].update(
                    colour_hint=target, colour_hint_source="description", desc_colour=target
                )
            else:
                still_pending.append((idx, name_words, label))
        pending = still_pending

        # Each truncated printing resolves to the longest name it begins.
        printed = {name for _, name, _ in pending}
        canonical = {
            name: max((o for o in printed if o[: len(name)] == name), key=len) for name in printed
        }

        def resolved(name: tuple[str, ...]) -> str:
            return " ".join(canonical.get(name, name))

        # Colours per part family, counting table colours already on rows.
        colours_of: dict[tuple[str, ...], set[str]] = {}
        pending_at = {idx: resolved(name) for idx, name, _ in pending}
        for idx, row in enumerate(out):
            colour = pending_at.get(idx) or (row.get("colour_hint") or "").split(",")[0].strip()
            if colour:
                for key in family(row):
                    colours_of.setdefault(key, set()).add(colour.upper())

        known = {c["abbreviation"].upper() for c in colour_codes if c.get("abbreviation")}
        added: list[dict[str, Any]] = []
        for idx, name_words, label in pending:
            name = resolved(name_words)
            row = out[idx]
            in_table = name in table_abbrs
            if not in_table and max(len(colours_of.get(k, ())) for k in family(row)) < 2:
                row["colour_ignored"] = f"{label} (one colour only: the part's finish)"
                row["colour_unverified"] = label
                continue
            row.update(
                colour_hint=name,
                colour_hint_source="description",
                desc_colour=name,
            )
            if in_table:
                continue
            row["colour_not_in_table"] = True
            if name not in known:
                known.add(name)
                added.append(
                    {
                        "code": "",
                        "name": label,
                        "abbreviation": name,
                        "is_model_colour": False,
                        "source": "description",
                    }
                )
        return out, colour_codes + added

    @classmethod
    def _lift_desc_colours(cls: type, rows: list[dict]) -> tuple[list[dict], list[dict]]:
        """Lift colour names and abbreviations from description parentheses.

        Business meaning: some older Yamaha catalogues (e.g. CRUX-S PC5KA5)
        encode colour variants as 'DESCRIPTION (COLOUR NAME OR ABBR)' in the
        Description column rather than via a foreword colour table plus
        FOR/EXCEPT remarks.  This method normalises those rows so the rest of
        the pipeline (roster-builder, frontend filter) can treat them
        identically to the standard FOR/EXCEPT format.

        Three detection passes:

        Pass 1 — colour-vocabulary match:
          The parenthetical content contains at least one word from
          _DESC_COLOUR_WORDS (e.g. "YAMAHA BLACK", "SILVER-3").
          Groups with ≥2 different part_nos are confirmed colour-variant groups.

        Pass 2 — sibling abbreviation tagging:
          Within confirmed groups from Pass 1, any untagged sibling row whose
          parenthetical looks like a Yamaha abbreviation (≥2 uppercase chars,
          starts with a letter) is also tagged.  Catches "(DRMK)", "(DPBMV)"
          etc. that don't contain colour vocabulary but coexist with named
          colour siblings.

        Pass 3 — cross-group frequency (fallback when Pass 1 finds nothing):
          If zero groups were confirmed in Pass 1, look for abbreviations that
          appear as parenthetical suffixes across ≥3 different (section, ref_no)
          groups, each with ≥2 different part_nos.  Requires ≥3 alphanumeric
          characters to exclude 2-char side codes like "LH", "RH".

        Side-effect on each affected row:
          • colour_hint → set to the colour abbreviation (e.g. 'YB').
            description, remarks, nine_digit_part_no are left UNCHANGED so
            the user sees the original PDF text in the table display.
            The agent and API use colour_hint for roster/filter logic.

        Returns:
            (updated_rows, synthetic_colour_codes)
            synthetic_colour_codes: [{abbreviation, name, code='',
                                       is_model_colour=False}, ...]
        """
        import re
        from collections import defaultdict

        # Matches 'BASE(COLOUR)' or 'BASE (COLOUR)' with an optional trailing
        # ' -MODEL' suffix.  Space before '(' is optional to handle cases like
        # 'COVER TAIL ASSY.(SILVER-3)' where PDF extraction omits the space.
        # Group 1 = base description, group 2 = parenthetical content.
        _PAT = re.compile(r"^(.+?)\s*\(([^)]+)\)(?:\s*[-–]\s*\S+)?$")
        # Abbreviation-shaped content: uppercase, 2-8 alphanumeric chars (+ hyphens),
        # starts with a letter.  Matches "DRMK", "DPBMV", "YB", "SL-3", etc.
        _ABBR_LIKE = re.compile(r"^[A-Z][A-Z0-9-]{1,7}$")
        # Direction/position qualifiers that appear in paren but are NOT colour codes.
        # When paren content is one of these, look at after-paren content for colour.
        _DIR_CODES = frozenset(
            {
                "LH",
                "RH",
                "L",
                "R",
                "LEFT",
                "RIGHT",
                "FRONT",
                "REAR",
                "UPPER",
                "LOWER",
                "INNER",
                "OUTER",
                "TOP",
                "BOTTOM",
            }
        )

        def _is_colour_content(content: str) -> bool:
            # Normalise hyphens/digits around colour words before checking
            words = set(re.sub(r"[-/]", " ", content).upper().split())
            return bool(words & cls._DESC_COLOUR_WORDS)

        def _normalise_colour(content: str) -> str:
            """Canonical form: hyphens → spaces, collapse whitespace, uppercase."""
            return re.sub(r"\s+", " ", re.sub(r"-", " ", content).strip()).upper()

        # Pass 1: parse descriptions; only keep colour-word-containing content
        groups: dict[tuple, list[int]] = defaultdict(list)
        parsed: dict[int, tuple[str, str]] = {}  # idx → (base_desc, normalised_colour)

        for idx, row in enumerate(rows):
            desc = row.get("description", "")
            m = _PAT.match(desc)
            if not m:
                continue
            # Strip trailing periods/spaces from base for stable group key
            # (e.g. "COVER TAIL 1." and "COVER TAIL 1" group together).
            base = m.group(1).strip().rstrip(". ")
            content = m.group(2).strip()

            if not _is_colour_content(content):
                # Paren holds a direction/position qualifier (LH, RH, etc.) —
                # check for colour vocabulary in the content after the closing paren.
                # Handles "SCOOP (LH) YAMAHA BLACK" and "(LH)-SILVER 3" formats.
                if ")" in desc:
                    after = desc[desc.rfind(")") + 1 :].strip().lstrip("-").strip()
                    if after and _is_colour_content(after):
                        content = after
                    else:
                        continue
                else:
                    continue  # size spec / functional label — skip

            norm = _normalise_colour(content)
            # Group by (section, ref_no) only — NOT by base description.
            # Yamaha sometimes writes descriptions inconsistently between
            # colour variants (e.g. "COVER, SIDE ASSY 1 (CANDY MAROON)"
            # vs "COVER SIDE ASSY 1 (SILVER-3)" — comma differs).
            # Same ref_no in the same section always means the same part.
            key = (row.get("section", ""), row.get("ref_no", ""))
            groups[key].append(idx)
            parsed[idx] = (base, norm)

        # Confirmed colour-variant groups: ≥2 different part_nos
        variant_idxs: set[int] = set()
        confirmed_keys: set[tuple] = set()
        for _key, idxs in groups.items():
            pns = {rows[i].get("part_no", "") for i in idxs}
            if len(pns) >= 2:
                variant_idxs.update(idxs)
                confirmed_keys.add(_key)

        # Pass 2: within confirmed groups, tag any untagged sibling rows whose
        # parenthetical looks like a Yamaha abbreviation code.  Catches colour
        # abbreviations like "(DRMK)" or "(DPBMV)" that coexist with named
        # colour rows ("(YAMAHA BLACK)") in the same (section, ref_no) group.
        if confirmed_keys:
            all_grp: dict[tuple, list[int]] = defaultdict(list)
            for idx2, row2 in enumerate(rows):
                key2 = (row2.get("section", ""), row2.get("ref_no", ""))
                if key2 in confirmed_keys:
                    all_grp[key2].append(idx2)

            for key2 in confirmed_keys:
                for idx2 in all_grp[key2]:
                    if idx2 in variant_idxs:
                        continue
                    desc2 = rows[idx2].get("description", "")
                    m2 = _PAT.match(desc2)
                    if not m2:
                        continue
                    content2 = m2.group(2).strip().upper()
                    base2 = m2.group(1).strip().rstrip(". ")

                    if content2 in _DIR_CODES and ")" in desc2:
                        # Paren holds a direction code — the colour is after the paren.
                        # "SCOOP (LH)-DRM K" → colour token = "DRMK" (spaces stripped).
                        after2 = desc2[desc2.rfind(")") + 1 :].strip().lstrip("-").strip()
                        if after2:
                            # Normalise: strip spaces so "DRM K" → "DRMK" for ABBR_LIKE check
                            tok2 = re.sub(r"\s", "", after2.upper())
                            if tok2 and _ABBR_LIKE.match(tok2) and tok2 not in _DIR_CODES:
                                parsed[idx2] = (base2, tok2)
                                variant_idxs.add(idx2)
                    elif _ABBR_LIKE.match(content2) and content2 not in _DIR_CODES:
                        # Use the abbreviation directly as the colour norm key
                        parsed[idx2] = (base2, content2)
                        variant_idxs.add(idx2)

        # Pass 3 (fallback): if Pass 1 found no confirmed groups, look for
        # abbreviation-shaped parentheticals (or after-paren tokens when the paren
        # holds a direction code) that repeat across ≥3 different (section, ref_no)
        # groups.  Requires ≥3 alphanumeric chars to exclude 2-char side codes (LH, RH).
        if not confirmed_keys:
            cand_by_group: dict[tuple, list[tuple[int, str]]] = defaultdict(list)
            for idx3, row3 in enumerate(rows):
                desc3 = row3.get("description", "")
                m3 = _PAT.match(desc3)
                if not m3:
                    continue
                content3 = m3.group(2).strip().upper()
                # When paren content is a direction code, try after-paren for colour
                if content3 in _DIR_CODES and ")" in desc3:
                    after3 = desc3[desc3.rfind(")") + 1 :].strip().lstrip("-").strip()
                    if after3:
                        content3 = re.sub(r"\s", "", after3.upper())
                if not _ABBR_LIKE.match(content3):
                    continue
                if len(re.sub(r"[^A-Z0-9]", "", content3)) < 3:
                    continue  # too short (LH/RH = 2 alnum chars)
                key3 = (row3.get("section", ""), row3.get("ref_no", ""))
                cand_by_group[key3].append((idx3, content3))

            # Count groups each abbreviation appears in (only multi-part groups)
            abbr_group_sets: dict[str, set] = defaultdict(set)
            for key3, entries in cand_by_group.items():
                pns3 = {rows[i].get("part_no", "") for i, _ in entries}
                if len(pns3) >= 2:
                    for _, c3 in entries:
                        abbr_group_sets[c3].add(key3)

            multi_group = {c for c, gs in abbr_group_sets.items() if len(gs) >= 3}
            if multi_group:
                for _key3, entries in cand_by_group.items():
                    pns3 = {rows[i].get("part_no", "") for i, _ in entries}
                    if len(pns3) < 2:
                        continue
                    if not any(c3 in multi_group for _, c3 in entries):
                        continue
                    for idx3, c3 in entries:
                        if idx3 not in variant_idxs:
                            row3 = rows[idx3]
                            desc3 = row3.get("description", "")
                            m3 = _PAT.match(desc3)
                            base3 = m3.group(1).strip().rstrip(". ") if m3 else ""
                            parsed[idx3] = (base3, c3)
                            variant_idxs.add(idx3)

        if not variant_idxs:
            return rows, []

        # Collect unique normalised colour names in first-encounter order
        seen_colours: dict[str, None] = {}
        for idx in sorted(variant_idxs):
            seen_colours.setdefault(parsed[idx][1], None)

        # Generate abbreviations: abbreviation-shaped norms (e.g. "DRMK", "YB")
        # are used as-is; full colour names go through _make_abbr.
        def _make_abbr(name: str, used: set[str]) -> str:
            words = re.sub(r"[^A-Z0-9 ]", "", name).split()
            base = "".join(w[0] if w.isalpha() else w for w in words)[:6]
            if not base or not base[0].isalpha():
                base = "C" + base
            abbr = base
            n = 2
            while abbr in used:
                abbr = base[:5] + str(n)
                n += 1
            used.add(abbr)
            return abbr

        used_abbrs: set[str] = set()
        colour_abbr: dict[str, str] = {}
        # Process full-name norms first so _make_abbr can claim their abbreviations
        # before abbreviation-shaped norms do the same (avoids collisions).
        sorted_colours = sorted(
            seen_colours,
            key=lambda c: (1 if _ABBR_LIKE.match(c) else 0, c),
        )
        for cu in sorted_colours:
            if _ABBR_LIKE.match(cu):
                # Use the abbreviation directly; mark as taken
                used_abbrs.add(cu)
                colour_abbr[cu] = cu
            else:
                colour_abbr[cu] = _make_abbr(cu, used_abbrs)

        # Deduplicate by abbreviation (same abbr = same colour, different norm spelling)
        seen_abbrs: set[str] = set()
        synthetic_colour_codes = []
        for cu in seen_colours:
            abbr = colour_abbr[cu]
            if abbr not in seen_abbrs:
                seen_abbrs.add(abbr)
                synthetic_colour_codes.append(
                    {
                        "abbreviation": abbr,
                        "name": cu.title(),
                        "code": "",
                        "is_model_colour": False,
                    }
                )

        # Final pass: tag affected rows with a colour_hint field.
        # Description, remarks, and nine_digit_part_no are NEVER modified —
        # the user sees exactly what the PDF shows (e.g. "FRONT FENDER (YAMAHA BLACK)"
        # and "5A-WF151-70" remain unchanged).  Only the invisible colour_hint key
        # is added so the agent and frontend can use it for roster/filter logic.
        updated: list[dict] = []
        for idx, row in enumerate(rows):
            if idx not in variant_idxs:
                updated.append(row)
                continue

            _, norm_colour = parsed[idx]
            new_row = dict(row)
            new_row["colour_hint"] = colour_abbr[norm_colour]
            updated.append(new_row)

        return updated, synthetic_colour_codes

    @staticmethod
    def _extract_manufacture_year(pdf_path: Path) -> str | None:
        """Extract manufacture / publication year from the PDF cover page.

        Scans the first 3 pages for Yamaha copyright patterns:
          ©2019 by Yamaha ...
          1st edition, May 2019
          PARTS CATALOGUE  2019

        Business meaning: identifies the model year this parts catalogue covers.
        Returns the 4-digit year string, e.g. "2019", or None if not found.
        """
        import pdfplumber as _plumber

        # ©YYYY or ©YYYY (full-width ©)
        _COPYRIGHT = re.compile(r"[©©]\s*(\d{4})")
        # "edition, Month YYYY" or "edition YYYY"
        _EDITION = re.compile(r"edition[,\s]+\w+\s+(\d{4})", re.IGNORECASE)
        # Standalone 4-digit year that looks plausible (avoid part numbers etc.)
        _YEAR_BARE = re.compile(r"\b(19[89]\d|20[012]\d)\b")

        try:
            with _plumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[:3]:
                    text = page.extract_text() or ""
                    for pat in (_COPYRIGHT, _EDITION, _YEAR_BARE):
                        m = pat.search(text)
                        if m:
                            yr = int(m.group(1))
                            if 1990 <= yr <= 2040:
                                return str(yr)
        except Exception:  # noqa: BLE001
            pass
        return None

    @staticmethod
    def _extract_model_no(pdf_path: Path) -> str | None:
        """Extract the Yamaha type/model code from the PDF cover page.

        Business meaning: identifies the Yamaha internal type designation
        (e.g. "5YY8" for Gladiator 5 Speed, "BP16" for Alfa, "B65J" for
        Aerox) that appears on the catalogue cover.  Distinct from the folder
        model name ("GLADIATOR") and from the variant list (which may contain
        multiple codes for multi-variant catalogues).

        Tries six strategies in order, using pymupdf (handles CID-encoded
        fonts that pdfplumber cannot decode):
          S1  Isolated line on cover page that is itself a model code
          S2  Parentheses pattern: ( CODE ) — may have internal spaces
          S3  Slash pair: CODE1/CODE2 — takes first
          S4  "MODEL CODE1, ..." prefix line
          S5  Parentheses in the PDF filename
          S6  First model-code token in the PDF filename (stem)

        A model code is 3-8 alphanumeric chars containing both letters and
        digits (excludes all-digit years, all-alpha words, and part numbers).
        """
        import fitz  # pymupdf

        _PAREN = re.compile(r"\(\s*([A-Z0-9][A-Z0-9 ]{1,7}[A-Z0-9])\s*\)")
        _SLASH = re.compile(r"\b([A-Z0-9]{3,6})\s*/\s*([A-Z0-9]{3,6})\b")
        _MODEL = re.compile(r"\bMODEL\s+([A-Z0-9]{3,8})")

        def _is_code(s: str) -> bool:
            s = s.strip().replace(" ", "")
            return (
                3 <= len(s) <= 8
                and s.isalnum()
                and any(c.isdigit() for c in s)
                and any(c.isalpha() for c in s)
            )

        try:
            doc = fitz.open(str(pdf_path))
            for pg_idx in range(min(2, len(doc))):
                text = doc[pg_idx].get_text()
                # S1: isolated line
                for line in text.splitlines():
                    if _is_code(line):
                        return line.strip()
                # S2: parentheses (collapse internal spaces)
                m = _PAREN.search(text)
                if m:
                    code = m.group(1).replace(" ", "")
                    if _is_code(code):
                        return code
                # S3: slash pair — take first
                m = _SLASH.search(text)
                if m and _is_code(m.group(1)) and _is_code(m.group(2)):
                    return m.group(1)
                # S4: "MODEL CODE1, ..." prefix
                m = _MODEL.search(text)
                if m and _is_code(m.group(1)):
                    return m.group(1)
        except Exception:  # noqa: BLE001
            pass

        # S5: parentheses in filename
        m = _PAREN.search(pdf_path.stem.upper())
        if m:
            code = m.group(1).replace(" ", "")
            if _is_code(code):
                return code

        # S6: first model-code token in filename stem
        for token in re.split(r"[\s_\-,]+", pdf_path.stem):
            t = token.strip().upper()
            if _is_code(t):
                return t

        # S7: "XXXXX series" / "XXXXX SERIES" pattern in foreword pages (pdfplumber).
        # Older Yamaha catalogues (e.g. LIBERO G5) have scanned cover pages that
        # pymupdf cannot read as text, but the FOREWORD page (pages 2-5) is
        # text-layer and contains "5TSD series" or similar.
        try:
            import pdfplumber as _pp  # noqa: PLC0415

            _SERIES_PAT = re.compile(r"\b([A-Z0-9]{3,8})\s+SERIES\b")
            with _pp.open(str(pdf_path)) as _pdf:
                for _pg in _pdf.pages[1:6]:
                    _text = (_pg.extract_text() or "").upper()
                    _m = _SERIES_PAT.search(_text)
                    if _m and _is_code(_m.group(1)):
                        return _m.group(1)
        except Exception:  # noqa: BLE001
            pass

        return None

    @staticmethod
    def _resolve_model_colours(
        colour_codes: list[dict], active_abbrs: set[str]
    ) -> tuple[list[dict], str, str | None]:
        """Decide which of the listed colours are this model's own colours.

        Business meaning: the paint colours the catalogue's model is actually built in.
        A row carrying ``(*)`` in the abbreviation column of the applicable-colour table
        says so outright, and wherever any row is marked those rows are the answer.

        Only 41 of the 107 catalogues in this vintage mark anything, so the rest have to
        be resolved from the document itself. By the time this runs, phantom pruning has
        already dropped every listed colour that no part in the body references, so what
        survives is the table narrowed to colours the catalogue actually builds parts in:

        * ``parts`` — no marker, but the body corroborates the table, so every surviving
          row is a model colour. This is what the marked catalogues themselves show: in
          37 of the 41, every listed colour is starred.
        * ``listed`` — no marker and no part references any listed colour, so nothing
          corroborates the table. Those rows are **not** promoted: a table colour is
          never a colour variant until something in the catalogue verifies it. One
          catalogue lands here and its sole "colour" is a bare ``BIKE``, which is a
          mis-parsed row rather than a colour at all.

        Returns the colour codes with ``is_model_colour`` set, the rule that fired, and
        a warning where nothing could be verified.
        """
        if not colour_codes:
            return colour_codes, "none", None

        if any(c.get("is_model_colour") for c in colour_codes):
            return colour_codes, "marked", None

        listed = {c["abbreviation"].upper() for c in colour_codes}
        corroborated = active_abbrs & listed

        # A table listing a single colour with no (*) marker is that model's colour:
        # there is nothing else it could be. 2FB6 lists only DPBMY.
        table_rows = [c for c in colour_codes if c.get("source") != "description"]
        if len(table_rows) == 1:
            for code in colour_codes:
                code["is_model_colour"] = (
                    code is table_rows[0] or code["abbreviation"].upper() in corroborated
                )
            return colour_codes, "single", None
        if corroborated:
            for code in colour_codes:
                code["is_model_colour"] = code["abbreviation"].upper() in corroborated
            return colour_codes, "parts", None

        return (
            colour_codes,
            "listed",
            f"no (*) marker in the colour table and no part references any listed "
            f"colour {sorted(listed)}; none is treated as a model colour, because a "
            f"listed colour only becomes a variant once the catalogue verifies it",
        )

    @staticmethod
    def _extract_colour_codes(pdf_path: Path) -> list[dict]:
        """Extract the colour-variant table from PDF intro pages.

        Yamaha catalogues include a table mapping colour abbreviation → colour
        name → paint code, e.g. "CM6(*) | CYAN METALLIC 6 | 1344".
        The (*) suffix marks the model's primary colour variant.

        Returns list of dicts: {abbreviation, name, code, is_model_colour}.
        Empty list if not found.
        """
        import pdfplumber as _plumber

        # Abbreviation: 2-8 alphanumeric chars, optionally followed by (*) or *
        _ABBR_PAT = re.compile(r"^([A-Z0-9]{2,8})(\(\s*\*\s*\)|\*)?$")
        # Paint code: Yamaha codes always start with 2+ digits and are 4-5 chars
        # (e.g. "1344", "0390", "0033", "00AL", "00V9").  Rejects pure-letter
        # strings ("THE", "PART") and short page-numbers ("01", "12").
        # Only used for non-column-swapped rows; 2-digit codes from swapped rows
        # (e.g. CRUX-S: "70", "80", "90") bypass this check entirely.
        _CODE_PAT = re.compile(r"^\d{2}[A-Z0-9]{2,3}$")
        # Words that indicate a header row — skip these
        _HEADER_WORDS = frozenset(
            {
                "ABBREVIATION",
                "ABBR",
                "COLOUR",
                "COLOR",
                "NAME",
                "CODE",
                "COLOURNAME",
                "COLOURCODE",
            }
        )
        # Column-swap detectors (compiled once, not per-row).
        # Some PDFs (e.g. CRUX-S) use 2-digit numeric codes ("70", "80") in
        # column 0 with the abbreviation in column 2 — the standard layout is
        # the reverse. Allowing 2-digit in _NUMERIC_CODE_RE triggers the swap.
        _NUMERIC_CODE_RE = re.compile(r"^\d{2,5}$")
        _ALPHA_ABBR_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
        # LIBERO-style: paint code with slashes ("1X/33/P1", "OX/PO/P1")
        _SLASH_CODE_RE = re.compile(r"^[A-Z0-9]+(?:/[A-Z0-9]+)+$")
        # Vocabulary check: real colour names always contain at least one of these.
        # Prevents TOC/section-name rows ("CYLINDER HEAD", "FIG 1") being accepted.
        _COLOUR_WORDS = frozenset(
            {
                "BLACK",
                "WHITE",
                "BLUE",
                "RED",
                "GREEN",
                "YELLOW",
                "ORANGE",
                "PURPLE",
                "PINK",
                "BROWN",
                "GREY",
                "GRAY",
                "SILVER",
                "GOLD",
                "CYAN",
                "MAGENTA",
                "TEAL",
                "NAVY",
                "MAROON",
                "BEIGE",
                "CREAM",
                "BRONZE",
                "COPPER",
                "TURQUOISE",
                "METALLIC",
                "MATTE",
                "MAT",
                "GLOSSY",
                "PEARL",
                "LUMINOUS",
                "VIVID",
                "DARK",
                "DEEP",
                "LIGHT",
                "BRIGHT",
                "REDDISH",
                "BLUISH",
                "GRAYISH",
                "GREYISH",
                "PURPLISH",
                "YELLOWISH",
                "GREENISH",
                "BLACKISH",
                "WHITISH",
                "COCKTAIL",  # "BLUISH WHITE COCKTAIL 1"
                "YAMAHA",  # "YAMAHA BLACK"
            }
        )
        # Common English words that can never be Yamaha colour abbreviations.
        # Rejects prose false-positives like "BOTH | METALLIC SILVER | 0390".
        _STOP_WORDS = frozenset(
            {
                "TO",
                "AT",
                "BE",
                "OF",
                "IN",
                "ON",
                "BY",
                "OR",
                "SO",
                "AS",
                "IF",
                "DO",
                "GO",
                "IS",
                "AN",
                "IT",
                "NO",
                "UP",
                "FOR",
                "AND",
                "THE",
                "BUT",
                "NOT",
                "YET",
                "NOR",
                "ANY",
                "ALL",
                "BOTH",
                "FROM",
                "WITH",
                "INTO",
                "THAN",
                "THIS",
                "THAT",
                "WILL",
                "HAVE",
                "BEEN",
                "WERE",
                "MORE",
                "ALSO",
                "SUCH",
                "SOME",
                "NOTE",
                "FORE",
                "PART",
                "ONLY",
                "WHEN",
                "THEN",
                "EACH",
                "USED",
                # English pronouns / determiners that are never Yamaha colour codes.
                # "YOU" is a known false-positive: foreword prose "...When you" lands
                # on the same Y-band as the colour-table header row; the GLADIATOR
                # column-swap then promotes "you" into the abbreviation slot.
                "YOU",
                "HIM",
                "HER",
                "ITS",
                "OUR",
                "HIS",
                "WE",
            }
        )

        def _parse_row(abbr_raw: str, name: str, code_raw: str) -> dict | None:
            abbr_clean = abbr_raw.replace(" ", "").upper()
            code_clean = code_raw.replace(" ", "").upper()
            # Hyphen-stripped forms for pattern matching (handles "SL-3" → "SL3").
            abbr_norm = abbr_clean.replace("-", "")
            code_norm = code_clean.replace("-", "")

            # Pre-swap stopword guard: if the raw left token is a common English word,
            # reject immediately — do NOT attempt a column swap that could move a valid
            # colour abbreviation into the code slot and the prose word into the
            # abbreviation slot.  Root cause of the "YOU" false-positive (FZ S 21C6):
            #   foreword row "This…you" → GLADIATOR swap → abbr="YOU", code="THIS"
            #   then "YAMAHA" in the name body passes the colour-vocabulary check.
            if abbr_norm in _STOP_WORDS:
                return None

            # Some Yamaha forewords use "Colour Code | Colour Name | Abbreviation"
            # column order (numeric code on the left, text abbreviation on the right).
            # Detect by: left is purely numeric, right starts with a letter.
            # For 2-digit codes (e.g. CRUX-S: 70, 80, 90) the swap also applies.
            swapped = False
            if _NUMERIC_CODE_RE.match(abbr_norm) and _ALPHA_ABBR_RE.match(code_norm):
                abbr_clean, code_clean = code_clean, abbr_clean
                abbr_norm, code_norm = code_norm, abbr_norm
                swapped = True

            # GLADIATOR-style: left col is a short alpha paint code ("HO", "GO"),
            # right col is the colour abbreviation ("YB", "DRMK", "SL-3").
            # Detected when right col fails numeric paint-code pattern but both cols
            # are alphabetic-abbreviation-like.
            if (
                not swapped
                and not _CODE_PAT.match(code_norm)
                and _ALPHA_ABBR_RE.match(code_norm)
                and _ALPHA_ABBR_RE.match(abbr_norm)
            ):
                abbr_clean, code_clean = code_clean, abbr_clean
                abbr_norm, code_norm = code_norm, abbr_norm
                swapped = True

            # LIBERO-style: paint code contains slashes ("1X/33/P1", "OX/PO/P1"),
            # abbreviation is on the right ("YB", "DRMK").  Yamaha India forewords
            # for older models (pre-2010) used a slash-separated paint formulation
            # code instead of the standard 4-digit numeric code.
            if not swapped and _SLASH_CODE_RE.match(abbr_clean) and _ALPHA_ABBR_RE.match(code_norm):
                abbr_clean, code_clean = code_clean, abbr_clean
                abbr_norm, code_norm = code_norm, abbr_norm
                swapped = True

            # ── Clean the abbreviation ──────────────────────────────────────────────
            # 1. Detect (*) marker BEFORE stripping — marks the primary colour variant.
            is_model_colour = bool(re.search(r"\(\s*\*\s*\)|\*$", abbr_clean))
            # 2. Strip (*) or * suffix — decorative only; the real code is without it.
            #    "YB(*)" → "YB", "CM6*" → "CM6"
            abbr = re.sub(r"\s*\(\s*\*\s*\)\s*|\s*\*\s*$", "", abbr_clean).strip()
            # 3. Strip colour-word suffix from compound abbreviation+colour strings
            #    found in older Yamaha catalogues (e.g. 1GC1 2012 format):
            #    "YB-BLACK" → "YB", "DBNM8-DARKGREY" → "DBNM8".
            #    "SL-3" is left intact: digit suffix is not a colour vocabulary word.
            if "-" in abbr:
                _head, _tail = abbr.split("-", 1)
                if re.match(r"^[A-Z][A-Z0-9]{1,7}$", _head) and any(
                    cw in _tail.upper() for cw in _COLOUR_WORDS
                ):
                    abbr = _head
            # 4. Re-derive norm from the cleaned abbreviation for all downstream checks.
            abbr_norm_clean = abbr.replace("-", "")
            m = _ABBR_PAT.match(abbr_norm_clean)
            if not m or m.group(1) in _HEADER_WORDS:
                return None

            # Reject purely-numeric abbreviations (section/page numbers, quantities)
            if abbr_norm_clean.isdigit():
                return None
            # Yamaha colour abbreviations always start with a letter (YB, CM6, SMX …)
            if not abbr_norm_clean[0].isalpha():
                return None
            # Reject common English function words that can never be colour codes
            if abbr_norm_clean in _STOP_WORDS:
                return None

            # When the columns were swapped, code_clean is the original left numeric
            # (e.g. "70", "1344") — always valid as-is.  Without a swap, apply the
            # 4-5 char standard pattern so 2-digit page numbers ("46") are rejected.
            if not swapped and not _CODE_PAT.match(code_clean):
                return None

            name = name.strip()
            if len(name) < 3:
                return None
            if name.upper() in _HEADER_WORDS:
                return None

            # Colour name must contain a recognisable colour word.
            # Eliminates TOC/section rows: "CYLINDER HEAD", "FIG 1 ASSEMBLY" etc.
            # Split by spaces, hyphens, AND parentheses so "MBL2(MAT BLACK)" yields
            # {"MBL2", "MAT", "BLACK"} and "BLACK" hits the vocabulary.  Without the
            # paren split, "BLACK)" (with trailing paren) would miss the set.
            name_words = set(re.split(r"[\s\-\(\)]+", name.upper()))
            if not name_words.intersection(_COLOUR_WORDS):
                return None

            return {
                "abbreviation": abbr,
                "name": name.title(),  # "YAMAHA BLACK" → "Yamaha Black"
                "code": code_clean,
                "is_model_colour": is_model_colour,
            }

        def _read_under_header(words: list[dict]) -> list[dict]:
            """Read a colour table by the columns its header row declares."""
            # All three labels must share one line: "Colour Code" also appears in
            # prose headings ("6. Initial Serial No. and Colour Code").
            by_line = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
            pairs: list[tuple[str, dict]] = []
            abbr_labels: list[dict] = []
            for k, w in enumerate(by_line):
                text = w["text"].strip().upper()
                nxt = by_line[k + 1] if k + 1 < len(by_line) else None
                if re.match(r"^ABBREVIAT", text):
                    abbr_labels.append(w)
                elif (
                    text in ("COLOUR", "COLOR")
                    and nxt is not None
                    and nxt["text"].strip().upper() in ("CODE", "NAME")
                    and abs(nxt["top"] - w["top"]) <= 3
                ):
                    key = "code" if nxt["text"].strip().upper() == "CODE" else "name"
                    pairs.append((key, {**w, "x1": nxt["x1"]}))
            labels: dict[str, dict] = {}
            for abbr_label in abbr_labels:
                same = {k: p for k, p in pairs if abs(p["top"] - abbr_label["top"]) <= 4}
                if "code" in same and "name" in same:
                    labels = {"abbr": abbr_label, **same}
                    break
            if len(labels) < 3:
                return []
            tops = [lab["top"] for lab in labels.values()]
            if max(tops) - min(tops) > 4:
                return []
            order = sorted(labels, key=lambda key: labels[key]["x0"])
            if order not in (["code", "name", "abbr"], ["abbr", "name", "code"]):
                return []
            header_top = max(tops)
            left = min(lab["x0"] for lab in labels.values()) - 40
            right = max(lab["x1"] for lab in labels.values()) + 40
            first, last = labels[order[0]], labels[order[2]]
            below = [
                w
                for w in words
                if header_top + 4 < w["top"] < header_top + 400 and left <= w["x0"] < right
            ]
            lines: list[list[dict]] = []
            for w in sorted(below, key=lambda w: (w["top"], w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
                    lines[-1].append(w)
                else:
                    lines.append([w])
            entries: list[dict] = []
            for line in lines:
                line.sort(key=lambda w: w["x0"])
                edge_l = line[0]["x0"] <= first["x1"] + 5
                edge_r = line[-1]["x0"] >= last["x0"] - 15
                if len(line) >= 3 and edge_l and edge_r:
                    if order[0] == "code":
                        # The abbreviation cell may hold several words: RAY 1GC1
                        # prints "DBNM8-DARK GREY" there.
                        # The cell is the last word, plus the word before it when that
                        # one opens a "CODE-colour" compound ("CNM-CANDY MAROON").
                        # 2FB6's name ends in "Y" right before its "DPBMY": no hyphen.
                        cell = [line[-1]]
                        if len(line) > 3 and "-" in line[-2]["text"] and "-" not in cell[0]["text"]:
                            cell.insert(0, line[-2])
                        code = line[0]["text"].strip()
                        abbr = " ".join(w["text"] for w in cell).strip()
                        name = " ".join(w["text"] for w in line[1 : len(line) - len(cell)])
                    else:
                        abbr, code = line[0]["text"].strip(), line[-1]["text"].strip()
                        name = " ".join(w["text"] for w in line[1:-1])
                    name = name.strip()
                    # "YB-BLACK", "DBNM8-DARK GREY": the code, glossed with its colour.
                    head, _, tail = abbr.partition("-")
                    if tail and set(re.split(r"[\s\-]+", tail.upper())) & _COLOUR_WORDS:
                        abbr = head
                    # GLADIATOR prints its codes "HO", "GO": the part numbers carry
                    # "H0", "G0" (5YY-F4100-H0-20), so the letter O is a zero.
                    if re.match(r"^[A-Z]O$", code.upper()):
                        code = code[0] + "0"
                    marked = bool(re.search(r"\(\s*\*\s*\)|\*$", abbr))
                    abbr = re.sub(r"\s*\(\s*\*\s*\)\s*|\s*\*\s*$", "", abbr).upper()
                    words_up = set(re.split(r"[\s\-\(\)]+", name.upper()))
                    if (
                        re.match(r"^[A-Z][A-Z0-9\-]{0,8}$", abbr)
                        and words_up & _COLOUR_WORDS
                        # Codes may carry slashes: FAZER 5YY6 "FO/90", R15 "PI/P0".
                        and re.match(r"^[A-Z0-9]{1,5}(?:/[A-Z0-9]{1,5})*$", code.upper())
                        and len(code) >= 2
                    ):
                        entries.append(
                            {
                                "abbreviation": abbr,
                                "name": name.title(),
                                "code": code.upper(),
                                "is_model_colour": marked,
                            }
                        )
                        continue
                # A colour name wrapped onto the next line carries only name words.
                if entries and not edge_l and not edge_r:
                    entries[-1]["name"] = (
                        f"{entries[-1]['name']} {' '.join(w['text'] for w in line)}".strip()
                    )
                    continue
                if entries:
                    break
            return entries

        def _dedup(entries: list[dict]) -> list[dict]:
            seen: set[str] = set()
            out: list[dict] = []
            for e in entries:
                key = e["abbreviation"].upper()
                if key not in seen:
                    seen.add(key)
                    out.append(e)
            return out

        # Best partial result seen across all pages/strategies (handles single-colour PDFs
        # where only 1 entry exists and ">= 3" would never trigger).
        best_partial: list[dict] = []

        # --- Strategy 0: read under the table's own header ---------------------------
        # Every foreword table is headed "Colour Code | Colour Name | Abbreviation", in
        # that order or reversed. The table usually shares its lines with foreword
        # prose, so reading a whole line as one row (strategies 1-2) mixes the two and
        # loses rows: FZS 21C8's CMY, GLADIATOR's DRMK and FZS21C2's YB went missing,
        # and 2FB6 read "BIKE". Anchoring on the header clips each line to the table's
        # own x-range and fixes the column order. Some books print the foreword on the
        # last page (CRUX 5KA1), so the last pages are read too.
        try:
            with _plumber.open(str(pdf_path)) as pdf:
                n_pages = len(pdf.pages)
                scan = list(range(min(15, n_pages))) + [
                    i for i in range(max(0, n_pages - 3), n_pages) if i >= 15
                ]
                for i in scan:
                    anchored = _read_under_header(pdf.pages[i].extract_words() or [])
                    if anchored:
                        return _dedup(anchored)
        except Exception:  # noqa: BLE001
            pass

        try:
            with _plumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[:15]:
                    # --- Strategy 1: pdfplumber ruled-table extraction ---
                    # Scan ALL tables on the page; keep the one with the most valid
                    # colour entries (avoids premature return on a mixed/fake table).
                    best_page: list[dict] = []
                    for table in page.extract_tables() or []:
                        if not table or len(table) < 2:
                            continue
                        entries: list[dict] = []
                        for row in table:
                            if not row or len(row) < 3:
                                continue
                            e = _parse_row(
                                str(row[0] or ""),
                                str(row[1] or ""),
                                str(row[2] or ""),
                            )
                            if e:
                                entries.append(e)
                        if len(entries) > len(best_page):
                            best_page = entries

                    if len(best_page) >= 3:
                        return _dedup(best_page)  # Confident multi-colour result
                    if len(best_page) > len(best_partial):
                        best_partial = best_page  # Remember for single-colour fallback

                    # --- Strategy 2: word-position row clustering ---
                    words = page.extract_words() or []
                    if not words:
                        continue

                    # Group words into Y-rows (same tolerance as main extractor)
                    rows_by_y: dict[float, list[dict]] = {}
                    for w in words:
                        y_key = round(float(w.get("top", 0)) / _Y_TOL) * _Y_TOL
                        rows_by_y.setdefault(y_key, []).append(w)

                    entries2: list[dict] = []
                    for y_key in sorted(rows_by_y):
                        ws = sorted(rows_by_y[y_key], key=lambda w: w["x0"])
                        if len(ws) < 3:
                            continue

                        # Left token may be split: "CM6" + "(*)" → join if next is a marker
                        left_parts = [ws[0]["text"].strip()]
                        rest_start = 1
                        if len(ws) > 1 and ws[1]["text"].strip() in ("(*)", "*", "(*)"):
                            left_parts.append(ws[1]["text"].strip())
                            rest_start = 2

                        left = "".join(left_parts).replace(" ", "").upper()
                        right = ws[-1]["text"].strip()
                        # Middle words form the colour name
                        middle_ws = ws[rest_start:-1]
                        middle = " ".join(w["text"] for w in middle_ws).strip()
                        if not middle:
                            middle = (
                                ws[rest_start]["text"].strip() if rest_start < len(ws) - 1 else ""
                            )

                        e = _parse_row(left, middle, right)
                        if e:
                            entries2.append(e)

                    if len(entries2) >= 3:
                        # Guard: require at least 2 entries that are NOT plain English
                        # colour words.  Cover pages sometimes list "BLACK", "BLUE"
                        # as model variant labels — they pass _parse_row validation but
                        # are false positives that cause premature early-return, skipping
                        # the real foreword table on a later page.  Single-colour
                        # supplements (1 entry) are unaffected: they never reach this
                        # threshold anyway and land in best_partial correctly.
                        n_genuine = sum(
                            1 for e in entries2 if e["abbreviation"].upper() not in _COLOUR_WORDS
                        )
                        if n_genuine >= 2:
                            return _dedup(entries2)  # Confident multi-colour result
                    if len(entries2) > len(best_partial):
                        best_partial = entries2

        except Exception:  # noqa: BLE001
            pass

        # No page produced >= 3 valid entries (single-colour PDF or non-standard layout).
        # Return best partial so single-colour PDFs still show their one chip.
        return _dedup(best_partial)

    @staticmethod
    def _extract_available_colours(pdf_path: Path) -> list[str]:
        """Extract colour variant captions from a Yamaha parts catalogue cover page.

        Yamaha catalogues display bike images side-by-side on the cover (or on
        a dedicated "AVAILABLE COLOUR" page) with colour names as captions
        beneath each image.  Four caption formats are handled:

            A. "Yamaha Alpha Cygnus Black"  — Yamaha-branded (Alpha, Ray)
            B. "2SP3-Gold", "BP16-Cyan"     — VariantCode-ColourName (Fasino, XC115)
            C. "Cyan Metallic | Mat Black"  — bare colour clusters (Fasino 2SP2)
            D. "Black Metallic Bike"        — [colour] Bike (Fazer 2WS)

        Key discriminators that separate genuine captions from colour-code tables:
        - On a Y-row split by large X-gaps (≥40 pts), every sub-group must
          contain at least one colour noun.  Foreword/two-column pages have one
          sub-group that is plain sentence text (no colour nouns) — those rows
          are rejected.
        - Colour-code table rows start with a short all-caps abbreviation (e.g.
          "CM6(*)", "MBL2") in the first sub-group, which has no colour noun.
        - Paint-code abbreviation codes (2-4 char all-uppercase, e.g. "YB",
          "SMX") as the last word flag a colour-table row, not a caption.

        Returns a deduplicated list of colour name strings.  Empty if none found.
        """
        import pdfplumber as _plumber

        # Large X-gap (pts) between two side-by-side bike images / captions.
        # Normal inter-word spacing: ≤15 pts.  Image-column gap: ≥80 pts.
        _X_GAP = 40.0
        # Captions are short; sentence text in foreword pages is much longer.
        _MAX_WORDS = 8
        # 2–4 char ALL-CAPS endings that are paint-code abbreviations, not colours.
        # Common colour-word endings that are allowed even when all-caps:
        _COLOUR_ENDINGS = frozenset(
            {
                "black",
                "white",
                "blue",
                "red",
                "cyan",
                "gray",
                "grey",
                "gold",
                "pink",
                "green",
                "brown",
                "silver",
                "orange",
                "maroon",
                "purple",
            }
        )

        def _split_by_gap(row_words: list[dict]) -> list[list[dict]]:
            groups: list[list[dict]] = []
            current: list[dict] = [row_words[0]]
            for prev, cur in zip(row_words, row_words[1:], strict=False):
                gap = float(cur.get("x0", 0)) - float(prev.get("x1", 0))
                if gap > _X_GAP:
                    groups.append(current)
                    current = [cur]
                else:
                    current.append(cur)
            groups.append(current)
            return groups

        def _group_has_colour(group: list[dict]) -> bool:
            return any(w["text"].lower() in _CAPTION_COLOUR_NOUNS for w in group)

        def _caption_from_group(group: list[dict]) -> str | None:
            """Extract a colour name from one X-gap-split sub-group, or None."""
            texts = [w["text"] for w in group]

            # Sentence-length sub-groups are foreword text, not image captions.
            if len(texts) > _MAX_WORDS:
                return None

            if _COPYRIGHT_PAT.search(" ".join(texts)):
                return None

            # Format B: VariantCode-ColourName, e.g. "2SP3-Gold", "BP16-Cyan",
            # "5YY6-Dark Blue Pearl".  Also: "BP16_Cyan Metallic" (underscore),
            # "2SP3-Black-Pearl" (hyphenated colours).
            # Tried FIRST: the full token "2SP3-Gold" is a single word that isn't
            # itself a colour noun, so all downstream checks would wrongly reject it.
            m = _VARIANT_CODE_PREFIX_PAT.match(texts[0])

            # Guard: real variant codes (2SP3, BP16) always contain a digit.
            # Plain hyphenated English words (NON-METALLIC, MID-BLUE) must not
            # be mistaken for variant codes and have their suffix returned.
            if m and any(c.isdigit() for c in m.group(1)):
                colour_part = " ".join([m.group(2)] + texts[1:]).strip()
                if any(w.lower() in _CAPTION_COLOUR_NOUNS for w in colour_part.split()):
                    return colour_part
                return None  # variant-code token but no colour → not a caption

            # Format B variant: underscore instead of hyphen ("BP16_Cyan Metallic")
            # or multi-word colour after dash ("5YY6-Dark Blue Pearl").
            if "_" in texts[0] or ("-" in texts[0] and re.match(r"^[A-Z0-9]{2,6}-", texts[0])):
                # Split on underscore or dash
                variant_and_colour = re.split(r"[_-]", texts[0], maxsplit=1)
                if len(variant_and_colour) == 2:
                    variant_code, colour_start = variant_and_colour
                    if any(c.isdigit() for c in variant_code) and variant_code.upper() != "YAMAHA":
                        # Reconstruct: colour_start + remaining words
                        colour_part = " ".join([colour_start] + texts[1:]).strip()
                        if any(w.lower() in _CAPTION_COLOUR_NOUNS for w in colour_part.split()):
                            return colour_part
                        return None

            # Reject figure/code-reference prefixes: "FO/90", "1X/33/P1" etc.
            if "/" in texts[0]:
                return None

            # Reject paint-code table rows with embedded 4-digit paint-code numbers
            # e.g. "A 1124 WHITE METALLIC 6", "C 1177 VIVID PURPLISH BLUE COCKTAIL 5"
            if any(re.match(r"^\d{4,5}$", t) for t in texts):
                return None

            # Must contain at least one colour noun.
            if not any(t.lower() in _CAPTION_COLOUR_NOUNS for t in texts):
                return None

            # Single-word groups must be a named base colour, not a modifier alone.
            # "Black", "Cyan" → OK; "Metallic", "Mat", "Vivid" alone → reject.
            if len(texts) == 1 and texts[0].lower() not in _STANDALONE_COLOUR_NOUNS:
                return None

            # Reject if last word is a short paint-code abbreviation:
            # e.g. "YB", "SMX", "DRMK" — but keep "BLACK", "BLUE", etc.
            last = texts[-1]
            if (
                2 <= len(last) <= 4
                and last == last.upper()
                and last.isalpha()
                and last.lower() not in _COLOUR_ENDINGS
            ):
                return None

            # Reject colour-code-table rows: first token is a short all-caps
            # abbreviation like "MBL2", "CM6(*)", "SMX(*)", "YB".
            first = texts[0]
            if re.match(r"^[A-Z0-9]{2,8}(\([*]\)|\*)?$", first) and first.upper() != "YAMAHA":
                return None

            return " ".join(texts)

        def _page_captions(words: list[dict]) -> list[str]:
            """Extract all colour captions from one page's word list."""
            rows_by_y: dict[float, list[dict]] = {}
            for w in words:
                y_key = round(float(w.get("top", 0)) / _Y_TOL) * _Y_TOL
                rows_by_y.setdefault(y_key, []).append(w)

            found: list[str] = []
            seen_local: set[str] = set()
            for y_key in sorted(rows_by_y):
                row_ws = sorted(rows_by_y[y_key], key=lambda w: w["x0"])
                sub_groups = _split_by_gap(row_ws)

                # Row-level guard: every sub-group with ≥2 words must contain a
                # colour noun.  Foreword two-column rows have one sub-group that
                # is plain sentence text → reject the whole row.
                if any(len(g) >= 2 and not _group_has_colour(g) for g in sub_groups):
                    continue

                # Reject paint-code table rows: any sub-group starting with a
                # 4-5 digit paint-code number ("0918", "0033" etc.).
                if any(re.match(r"^\d{4,5}$", g[0]["text"]) for g in sub_groups):
                    continue

                for group in sub_groups:
                    cap = _caption_from_group(group)
                    if cap and cap not in seen_local:
                        seen_local.add(cap)
                        found.append(cap)
            return found

        captions: list[str] = []
        seen: set[str] = set()

        try:
            with _plumber.open(str(pdf_path)) as pdf:
                # ── Pass 1: dedicated "AVAILABLE COLOUR" page (pages 1-20) ────
                for page in pdf.pages[:20]:
                    text = page.extract_text() or ""
                    if not _AVAIL_COLOUR_PAT.search(text):
                        continue
                    words = page.extract_words(x_tolerance=6, y_tolerance=4) or []
                    for cap in _page_captions(words):
                        if cap not in seen:
                            seen.add(cap)
                            captions.append(cap)
                    if captions:
                        break

                # ── Pass 2: cover/intro image pages (pages 1-5) ────────────
                # Scan early pages for colour caption rows.  These pages have
                # bike images (large whitespace) between sparse caption rows.
                # Restricted to pages 1-5 so foreword text pages are excluded.
                if not captions:
                    for page in pdf.pages[:5]:
                        words = page.extract_words(x_tolerance=6, y_tolerance=4) or []
                        if not words:
                            continue
                        page_caps = _page_captions(words)
                        if page_caps:
                            for cap in page_caps:
                                if cap not in seen:
                                    seen.add(cap)
                                    captions.append(cap)
                            break  # one image page per PDF

        except Exception:  # noqa: BLE001
            pass

        return captions

    @staticmethod
    def _resolve_variants(
        pdf_path: Path,
        col_counter: _Counter,
    ) -> list[str]:
        """Return the ordered list of model variant codes for this PDF.

        Primary source: cover page text pattern ``( B65J )``.
        Fallback: most-common column-header tuple collected during extraction.
        """
        import pdfplumber  # already imported at call site, but safe to repeat

        def _is_vc(s: str) -> bool:
            return (
                3 <= len(s) <= 5
                and s.isalnum()
                and any(c.isdigit() for c in s)
                and any(c.isalpha() for c in s)
            )

        best_single: str | None = None  # single variant code found in parens across all pages
        cover_text = ""  # first two pages, to check column-header codes against

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[:8]:
                    text = page.extract_text() or ""
                    if page.page_number <= 2:
                        cover_text += " " + text.upper()

                    # Primary: explicit "( CODE )" per variant — e.g. "( B65J ) ( B65L )"
                    found = [m for m in _COVER_VARIANT_PAT.findall(text) if _is_vc(m)]
                    seen: dict[str, None] = {}
                    for v in found:
                        seen[v] = None
                    if len(seen) >= 2:
                        return list(seen)
                    # Record single parens code from cover pages only (pages 0-1).
                    # Body pages may have figure references like "(1I0)" that are not variants.
                    if len(seen) == 1 and best_single is None and page.page_number <= 2:
                        best_single = next(iter(seen))

                    # Secondary: slash-separated pair — e.g. "B811/B821" or "(B9E1 / B9E2)"
                    # Collect all unique codes that appear as either half of a slash pair.
                    slash_seen: dict[str, None] = {}
                    for m in _SLASH_VARIANT_PAT.finditer(text):
                        a, b = m.group(1), m.group(2)
                        if _is_vc(a) and _is_vc(b) and a != b:
                            slash_seen[a] = None
                            slash_seen[b] = None
                    if len(slash_seen) >= 2:
                        return list(slash_seen)

        except Exception:
            pass

        # Return single variant identified from parens (e.g. "( B627 ) INDIA")
        if best_single:
            return [best_single]

        # Scan filename tokens for first variant code — handles covers without parens.
        # Check parenthesised tokens FIRST (e.g. "SZ16 (54B2).pdf" → "54B2" not "SZ16").
        # "SZ16" is the model name; "(54B2)" is the Yamaha type code enclosed in parens.
        import re as _re

        _PAREN_STEM = _re.compile(r"\(([A-Z0-9]{2,8})\)")
        for m_ps in _PAREN_STEM.finditer(pdf_path.stem.upper()):
            tok = m_ps.group(1)
            if _is_vc(tok):
                return [tok]

        for token in _re.split(r"[\s_\-]+", pdf_path.stem):
            if _is_vc(token.upper()):
                return [token.upper()]

        # Fallback: column-header scan results (collected during extraction)
        if col_counter:
            best, _ = col_counter.most_common(1)[0]
            # Quantity-column headers are often printed rotated 90 degrees, and pdfplumber
            # reads upward text last-character-first: YBX125's "4LS1" arrives as "1SL4".
            # Un-reverse a code only when its reversal is printed on the cover and the
            # code as read is not. Column order is kept, since quantities are aligned to it.
            fixed = []
            for code in best:
                reversed_code = code[::-1]
                if (
                    code not in cover_text
                    and _is_vc(reversed_code)
                    and re.search(rf"\b{re.escape(reversed_code)}\b", cover_text)
                ):
                    fixed.append(reversed_code)
                else:
                    fixed.append(code)
            return fixed

        return []

    def _parse_word_rows(
        self,
        word_rows: list[tuple[float, list[dict]]],
        bounds: ColBounds | None,
        current_section: str,
        current_fig: str,
        num_variants: int = 0,
    ) -> tuple[list[dict], str, str, set[str]]:
        """Parse word-rows into structured dicts.

        Two extraction modes, selected automatically per page:

        Positional mode (when bounds.qty_col_xs is available):
            Every word after the part number is classified by its x-centre into
            description / qty-slot / remarks.  This correctly handles both
            partial-coverage parts (blank variant cells) and description names
            that end in a digit (e.g. "STAY 1") without confusing them with qty.

        Text-based fallback (single-variant or no column bounds):
            Uses _split_after heuristics — same behaviour as before.

        Ref-number carry-forward:
            Yamaha prints the ref number only on the first part of a shared-ref
            group.  The last seen ref is propagated to subsequent blank-ref rows
            within the same FIG section.
        """
        rows: list[dict[str, str]] = []
        sections_seen: set[str] = set()
        bounds = self._infer_qty_column(word_rows, bounds)

        # Pre-scan: find the first FIG. header on this page and use it to seed
        # new_section/new_fig before the main loop. This handles pages where data
        # rows appear above the FIG. header in Y-order (e.g. AEROX continuation
        # pages where rows 1-4 sit at a lower Y than the FIG. stamp).
        new_section = current_section
        new_fig = current_fig
        for _pi, (_y, ws) in enumerate(word_rows):
            joined_pre = " ".join(w["text"] for w in ws).strip()
            fig_m = _try_fig_match(joined_pre, word_rows, _pi)
            if fig_m:
                raw = _CID_PAT.sub("", fig_m.group(2)).strip()
                if bounds and bounds.is_bilingual:
                    raw = _bilingual_fig_section(ws, raw, bounds)
                new_section = raw if raw else f"FIG. {fig_m.group(1)}"
                new_fig = f"FIG. {fig_m.group(1)}"
                break
            opt_m = _PARTS_OPTION_PAT.match(joined_pre)
            if opt_m:
                new_section = opt_m.group(1).strip()
                break

        # last_ref_no carries the most recent non-blank ref number forward.
        # Yamaha PDFs print the ref number only on the FIRST part of a shared-ref
        # group (e.g. B65-F8356-20 and B65-F8356-30 both use ref 20, but only
        # the first row has "20" in the ref cell).
        last_ref_no = ""

        # Index-based loop so we can peek ahead when a row has a part number
        # but an empty description (e.g. BB8-E1392-00 where the PDF renders the
        # description text at a Y coordinate just outside the grouping window).
        idx = 0
        while idx < len(word_rows):
            _y, ws = word_rows[idx]
            idx += 1
            joined = " ".join(w["text"] for w in ws).strip()

            if not joined or len(joined) < 2:
                continue
            if _MODEL_STAMP_PAT.match(joined):
                continue

            # Detect FIG. header (must scan pre-filter joined).
            # _try_fig_match handles three cases:
            #   (a) standard "FIG. N SECTION" on one line
            #   (b) model-stamp prefix before FIG on same line
            #   (c) "FIG. N" alone on this row, section name on the next row
            # For case (c) the helper peeks at word_rows[idx] (already advanced).
            fig_m = _try_fig_match(joined, word_rows, idx - 1)
            if fig_m:
                # Case (c): section name came from word_rows[idx], advance past it
                partial_check = _FIG_PARTIAL_PAT.match(joined)
                if (
                    partial_check
                    and not _FIG_PAT.match(joined)
                    and not _FIG_PAT.match(_STAMP_PREFIX_PAT.sub("", joined))
                ):
                    idx += 1
                raw = _CID_PAT.sub("", fig_m.group(2)).strip()
                if bounds and bounds.is_bilingual:
                    raw = _bilingual_fig_section(ws, raw, bounds)
                new_fig = f"FIG. {fig_m.group(1)}"
                new_section = raw if raw else new_fig  # fallback for CID-corrupt names
                sections_seen.add(new_section)
                last_ref_no = ""  # reset ref carry at every new figure
                continue

            opt_m = _PARTS_OPTION_PAT.match(joined)
            if opt_m:
                new_section = opt_m.group(1).strip()
                sections_seen.add(new_section)
                last_ref_no = ""
                continue

            if _SKIP_PAT.match(joined):
                continue

            # Quick check for part number before expensive filtering
            if not _PN_PAT.search(joined):
                continue

            # ── Positional filtering ────────────────────────────────────────
            # Find the part number word's x0 to anchor the column layout.
            # Remove any words that are >80 pts to the left of it — these are
            # figure-illustration numbers printed in the margin (e.g. CRUX PDFs,
            # where illustration numbers sit 200+ pts left of the part number).
            # 80 pts (vs the old 50) lets us capture ref-number columns that sit
            # 60-70 pts left of the part number (e.g. ENTICER 5US2 at 67 pts).
            pn_word = next((w for w in ws if _PN_PAT.match(w["text"])), None)
            # A row that is nothing but a 9-digit number is not a part row: it is that
            # column's value printed on its own baseline, and it was being stored as a
            # second, empty copy of the part above it ("4S-F3144-V0" beside
            # "4LS-F3144-V0-00 SEAL, DUST"). The 9-digit number is never extracted.
            #
            # Position alone cannot decide it. CRUX 5KA1 page 58 prints two parts tables
            # side by side, so the left table's 9-digit column starts left of the right
            # table's part numbers and a position test threw away six real parts. The
            # phantom's tell is that it has no description: every real part row names
            # its part in words, and a lone 9-digit value names nothing.
            if (
                pn_word is not None
                and bounds is not None
                and bounds.nine_digit_start < 9000
                and pn_word["x0"] >= bounds.nine_digit_start
                and not any(_DESCRIPTION_WORD.search(w["text"]) for w in ws if w is not pn_word)
            ):
                continue
            if pn_word:
                x_cutoff = pn_word["x0"] - 80
                ws_filtered = [w for w in ws if w["x0"] >= x_cutoff]
                # A part row whose name wraps, with the quantity printed on the
                # continuation line: R15 2YS1's "CAST WHEEL, FRONT -LGB/DRSC" over
                # "(low gloss black/deep red stripe) 1 UR LGB/DRSC", YBX125's
                # "COVER SIDE1 WITH" over "GRAPHICS(4LS2)-BG 1". Read as one row, or the
                # row had no quantity and the next line was lost.
                if idx < len(word_rows) and not self._has_qty_word(ws_filtered, bounds):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_ws
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                        and min(w["x0"] for w in next_ws) > pn_word["x1"] - 5
                        and self._has_qty_word(next_ws, bounds)
                    ):
                        ws_filtered = ws_filtered + sorted(next_ws, key=lambda w: w["x0"])
                        idx += 1
                joined = " ".join(w["text"] for w in ws_filtered).strip()
            else:
                ws_filtered = ws

            pn_m = _PN_PAT.search(joined)
            if not pn_m:
                continue
            pn = pn_m.group(1).replace("–", "-")  # normalize en-dash to hyphen
            if pn.startswith("X") or not new_section:
                continue

            # Everything before PN = ref number text
            before = joined[: pn_m.start()].strip()

            # ── Column classification ───────────────────────────────────────
            # Two modes depending on whether variant column positions are known.
            #
            # POSITIONAL MODE (qty_col_xs available):
            #   Classify every word after the part number by its x-centre:
            #     • x0 ≥ rem_start              → remarks
            #     • x_centre ≥ qty_zone_x AND digit → qty (assigned to nearest col)
            #     • everything else              → description
            #   This is the only reliable way to keep description digits (e.g. the
            #   "1" in "STAY 1") from being confused with qty digits, because their
            #   x-positions place them firmly in the description zone.
            #
            # TEXT-BASED FALLBACK (no column bounds / single-variant):
            #   Use _split_after heuristics (existing behaviour).

            # Initialise extra-column accumulators here so they are always defined
            # regardless of which extraction mode runs below.
            nine_digit_parts: list[str] = []
            escort_parts: list[str] = []
            superseded_parts: list[str] = []

            if bounds and bounds.qty_col_xs and pn_word:
                n_cols = len(bounds.qty_col_xs)
                qty_zone_x = min(bounds.qty_col_xs) - 15.0
                max_qty_cx = max(bounds.qty_col_xs)  # x-centre of rightmost qty col
                slots: list[str] = [""] * n_cols
                desc_parts: list[str] = []
                rem_parts: list[str] = []
                # Words in the gap between the last qty column and the first extra
                # column (or REMARKS when no extra columns exist).
                pre_rem_parts: list[str] = []
                # Only use the gap-zone when the REMARKS boundary is known;
                # without rem_start we cannot define the gap reliably.
                use_gap_zone = bounds.rem_start < 9000
                # Track right edge of last description word to detect footnote markers.
                last_desc_x1 = 0.0

                for w in ws_filtered:
                    if w["x0"] < pn_word["x1"]:  # ref-no / part-number
                        continue
                    if use_gap_zone and w["x0"] >= bounds.rem_start:
                        rem_parts.append(w["text"])
                        continue
                    # Route words into extra columns by x-position (right → left priority)
                    if bounds.superseded_start < 9000 and w["x0"] >= bounds.superseded_start:
                        superseded_parts.append(w["text"])
                        continue
                    if bounds.escort_start < 9000 and w["x0"] >= bounds.escort_start:
                        escort_parts.append(w["text"])
                        continue
                    if bounds.nine_digit_start < 9000 and w["x0"] >= bounds.nine_digit_start:
                        nine_digit_parts.append(w["text"])
                        continue
                    w_cx = (w["x0"] + w["x1"]) / 2
                    # Qty slot: accept 1–5 digit strings only.  India-market PDFs
                    # have 9-char all-digit nine_digit values (e.g. "344010109") to
                    # the right of qty columns; those must NOT contaminate qty slots.
                    if w_cx >= qty_zone_x and re.match(r"^\d{1,5}$", w["text"]):
                        # Guard: Yamaha catalogues suffix descriptions with small
                        # footnote markers (e.g. "COVER, CYLINDER HEAD SIDE 3",
                        # "HEAD, CYLINDER 1") that physically sit within the qty zone
                        # but are immediately adjacent to description text (gap < 15 px).
                        # Distinguish by the x-gap from the last description word's
                        # right edge: < 15 px → footnote → route to description.
                        gap_from_desc = w["x0"] - last_desc_x1
                        # ...unless the digit sits squarely on a quantity column. A
                        # footnote marker trails the description text and lands wherever
                        # that text ends; a quantity is aligned to its column. Without
                        # this, a long description that runs close to the first column
                        # eats the row's quantities: ALFA B931's "FENDER, FRONT
                        # -VRC1(vivid red)" ends 10px short of the column and lost both
                        # its 1s, so the row vanished from the model entirely.
                        # The tolerance scales with the column spacing: ALFA's columns
                        # are 10px apart, YBX125's 17px, where a "1" sat 4.5px off
                        # centre and was kept in the description.
                        xs = sorted(bounds.qty_col_xs)
                        spacing = min(
                            (b - a for a, b in zip(xs, xs[1:], strict=False)), default=0.0
                        )
                        tolerance = min(8.0, max(_QTY_COLUMN_TOLERANCE, 0.35 * spacing))
                        on_qty_column = any(
                            abs(col_cx - w_cx) <= tolerance for col_cx in bounds.qty_col_xs
                        )
                        if (
                            last_desc_x1 > 0
                            and gap_from_desc < 15.0
                            and len(w["text"]) <= 2
                            and not on_qty_column
                        ):
                            desc_parts.append(w["text"])
                            last_desc_x1 = max(last_desc_x1, w["x1"])
                        else:
                            nearest = min(
                                range(n_cols),
                                key=lambda i: abs(bounds.qty_col_xs[i] - w_cx),
                            )
                            slots[nearest] = w["text"]
                    elif use_gap_zone and w_cx > max_qty_cx:
                        # Non-digit word past the last qty column: colour/market
                        # qualifier that belongs in remarks, not description.
                        pre_rem_parts.append(w["text"])
                    else:
                        desc_parts.append(w["text"])
                        last_desc_x1 = max(last_desc_x1, w["x1"])

                # Lookahead: pn and description on different Y-rows.
                # Only needed when the current row has no description AND no
                # gap-zone qualifiers (i.e. effectively empty after the pn).
                if not desc_parts and not pre_rem_parts and idx < len(word_rows):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_joined
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                    ):
                        desc_parts = [_COPYRIGHT_PAT.sub("", next_joined).strip()]
                        idx += 1

                # Bilingual catalogue: Spanish description is on the data row;
                # English description is on the immediately following Y row.
                # Replace Spanish with English by consuming that next row.
                elif bounds.is_bilingual and desc_parts and idx < len(word_rows):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_joined
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                    ):
                        # Only consume words in the description column zone
                        # (allow 30 pt left-margin tolerance for data alignment).
                        # Stop at the first qty column so gap-zone qualifiers
                        # like applicability codes ("UR") are not captured.
                        _d_lo = max(0.0, bounds.desc_start - 30.0)
                        _d_hi = (
                            (min(bounds.qty_col_xs) - 15.0)
                            if bounds.qty_col_xs
                            else (bounds.rem_start if bounds.rem_start < 9000 else 9999.0)
                        )
                        eng_words = [
                            w["text"] for w in next_ws if w["x0"] >= _d_lo and w["x0"] < _d_hi
                        ]
                        if eng_words:
                            desc_parts = eng_words
                            idx += 1
                            # Also replace gap-zone (pre_rem_parts) and remarks
                            # with English values, discarding Spanish words like "PARA".
                            _qty_lo = min(bounds.qty_col_xs) if bounds.qty_col_xs else 9999.0
                            _rem_hi = bounds.rem_start if bounds.rem_start < 9000 else 9999.0
                            pre_rem_parts = [
                                w["text"]
                                for w in next_ws
                                if w["x0"] >= _qty_lo
                                and w["x0"] < _rem_hi
                                and not re.match(r"^\d{1,5}$", w["text"])
                            ]
                            if bounds.rem_start < 9000:
                                rem_parts = [
                                    w["text"] for w in next_ws if w["x0"] >= bounds.rem_start
                                ]

                desc_raw = " ".join(desc_parts)
                # Truncate at any embedded PN: indicates a supersession code or
                # merged Y-row from tight typesetting (e.g. CRUX 5KA1 PDF).
                # Yamaha descriptions are plain English — they never legitimately
                # contain a part number.
                _pn_in_desc = _PN_PAT.search(desc_raw)
                desc = desc_raw[: _pn_in_desc.start()].strip() if _pn_in_desc else desc_raw
                qty = "/".join(slots)
                filled = [s for s in slots if s]
                # Collapse "1/1/1/1" → "1" only when EVERY slot is filled identically
                if filled and len(set(filled)) == 1 and len(filled) == n_cols:
                    qty = filled[0]
                # NOTE: do NOT rstrip("/") here.  Trailing slashes like "1/" are
                # semantically meaningful: they signal that this part has no qty
                # for the LAST variant(s), allowing the frontend variantQty filter
                # to hide the row when that variant is selected.  The collapse step
                # above already converts fully-filled identical slots ("1/1") to
                # plain "1", so spurious trailing slashes from genuine duplicates
                # are handled by _detect_col_bounds de-duplication instead.
                # Pattern-based fallback for India-market PDFs where header
                # detection failed to set nine_digit_start / superseded_start.
                # Nine-digit part numbers are exactly 9 alphanumeric chars.
                # Superseded part numbers are exactly 12 alphanumeric chars.
                # This is safe for standard PDFs: their gap-zone tokens (colour
                # codes like "DBNM8", qualifiers like "FOR") are never 9 or 12
                # chars of pure uppercase alphanumeric.
                if bounds.nine_digit_start >= 9000 and pre_rem_parts:
                    leftover: list[str] = []
                    for _tok in pre_rem_parts:
                        if re.match(r"^[A-Z0-9]{9}$", _tok, re.IGNORECASE):
                            nine_digit_parts.append(_tok)
                        elif re.match(r"^[A-Z0-9]{12}$", _tok, re.IGNORECASE):
                            superseded_parts.append(_tok)
                        else:
                            leftover.append(_tok)
                    pre_rem_parts = leftover

                # Combine gap-zone words with explicit-remarks words.
                # Gap-zone words (pre_rem_parts) appear to the LEFT of the
                # REMARKS column in the PDF, so they always come first.
                # e.g. gap=["DBNM8"] rem=["FOR","YB"] → "DBNM8 FOR YB"
                # e.g. gap=["FOR"]   rem=["SM12"]     → "FOR SM12"
                remarks = " ".join(pre_rem_parts + rem_parts)

            elif bounds and bounds.desc_start < 9000 and pn_word:
                # ── Single-variant positional mode ──────────────────────────
                # The header row was detected and gave us explicit column
                # x-starts for DESCRIPTION, Q'TY, and REMARKS.  Classify every
                # word after the part number by its x-position — no heuristics.
                desc_sv: list[str] = []
                desc_w: list[dict[str, Any]] = []
                qty_sv: list[str] = []
                rem_sv: list[str] = []

                for w in ws_filtered:
                    if w["x0"] < pn_word["x1"]:  # ref-no / part-no zone
                        continue
                    if bounds.rem_start < 9000 and w["x0"] >= bounds.rem_start:
                        rem_sv.append(w["text"])
                        continue
                    if bounds.superseded_start < 9000 and w["x0"] >= bounds.superseded_start:
                        superseded_parts.append(w["text"])
                        continue
                    if bounds.escort_start < 9000 and w["x0"] >= bounds.escort_start:
                        escort_parts.append(w["text"])
                        continue
                    if bounds.nine_digit_start < 9000 and w["x0"] >= bounds.nine_digit_start:
                        nine_digit_parts.append(w["text"])
                        continue
                    if bounds.qty_start < 9000 and (
                        w["x0"] >= bounds.qty_start
                        # Quantities are right-aligned under a left-aligned "Q'TY"
                        # header, so a two-digit one starts a little left of it: 2XB3's
                        # "11" sits at x=662.5 against a header at 665 and was being
                        # filed as description ("BOLT, FLANGE 11", quantity blank).
                        or (
                            _QTY_DIGITS.match(w["text"])
                            and w["x0"] >= bounds.qty_start - _QTY_HEADER_OVERHANG
                        )
                    ):
                        qty_sv.append(w["text"])
                        continue
                    desc_sv.append(w["text"])
                    desc_w.append(w)

                # A quantity printed just short of the column ends the description.
                if (
                    bounds.qty_start < 9000
                    and not qty_sv
                    and len(desc_w) >= 2
                    and _QTY_DIGITS.match(desc_w[-1]["text"])
                    and desc_w[-1]["x0"] >= bounds.qty_start - _QTY_TRAILING_REACH
                ):
                    qty_sv.append(desc_sv.pop())
                    desc_w.pop()

                # Lookahead when description zone is empty
                if not desc_sv and idx < len(word_rows):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_joined
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                    ):
                        desc_sv = [_COPYRIGHT_PAT.sub("", next_joined).strip()]
                        idx += 1

                # Bilingual catalogue: Spanish description captured in desc_sv;
                # English description is on the immediately following Y row.
                elif bounds.is_bilingual and desc_sv and idx < len(word_rows):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_joined
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                    ):
                        _d_lo = max(0.0, bounds.desc_start - 30.0)
                        # Upper bound: stop at qty_start so gap-zone qualifiers
                        # like applicability codes ("UR") are not captured.
                        _d_hi = (
                            bounds.qty_start
                            if bounds.qty_start < 9000
                            else (bounds.rem_start if bounds.rem_start < 9000 else 9999.0)
                        )
                        eng_words = [
                            w["text"] for w in next_ws if w["x0"] >= _d_lo and w["x0"] < _d_hi
                        ]
                        if eng_words:
                            desc_sv = eng_words
                            idx += 1
                            # Also replace gap-zone non-digits and remarks with
                            # English values from the same row. This discards
                            # Spanish connector words like "PARA" (= "FOR") and
                            # keeps the English equivalents ("FOR") in the remarks.
                            # Digit qty values come from the data row (correct);
                            # only the non-digit applicability codes are swapped.
                            if bounds.qty_start < 9000:
                                _rem_hi = bounds.rem_start if bounds.rem_start < 9000 else 9999.0
                                _eng_gap = [
                                    w["text"]
                                    for w in next_ws
                                    if bounds.qty_start <= w["x0"] < _rem_hi
                                    and not re.match(r"^\d{1,5}$", w["text"])
                                ]
                                qty_sv = [t for t in qty_sv if re.match(r"^\d{1,5}$", t)] + _eng_gap
                            if bounds.rem_start < 9000:
                                rem_sv = [w["text"] for w in next_ws if w["x0"] >= bounds.rem_start]

                # Recover a qty digit that pdfplumber merged into the last
                # description token (PDF text runs where the gap between ")"
                # and the adjacent qty digit is < x_tolerance, e.g. "HEAD)2"
                # stored as a single glyph sequence).  Guard: only apply when
                # the qty zone was detected but came back empty.
                # The glued token must reach the quantity column: FZS21C2's
                # "REAR-VRC1" has no quantity printed, and was split into "REAR-VRC"
                # and a quantity of 1.
                if (
                    bounds.qty_start < 9000
                    and not qty_sv
                    and desc_sv
                    and (
                        len(desc_w) != len(desc_sv)
                        or desc_w[-1]["x1"] >= bounds.qty_start - _QTY_HEADER_OVERHANG
                    )
                ):
                    _last = desc_sv[-1]
                    _mm = re.match(r"^(.+[^\d])(\d{1,2})$", _last)
                    if _mm:
                        desc_sv[-1] = _mm.group(1)
                        qty_sv.append(_mm.group(2))

                desc_raw_sv = " ".join(desc_sv)
                _pn_in_desc_sv = _PN_PAT.search(desc_raw_sv)
                desc_sv_clean = (
                    desc_raw_sv[: _pn_in_desc_sv.start()].strip() if _pn_in_desc_sv else desc_raw_sv
                )

                if bounds.qty_start < 9000:
                    # Qty zone was detected — use positional result directly.
                    # Non-digit tokens in the qty zone (e.g. applicability codes
                    # like "UR", "S3" that sit between the qty column and the
                    # REMARKS header) are routed to remarks rather than discarded.
                    qty_raw = " ".join(qty_sv)
                    qty_m = re.search(r"\d+", qty_raw)
                    desc = desc_sv_clean
                    qty = qty_m.group() if qty_m else ""
                    non_digit_qty = [t for t in qty_sv if not re.match(r"^\d+$", t)]
                    if non_digit_qty:
                        rem_sv = non_digit_qty + rem_sv
                else:
                    # Qty column not detected — apply _split_after heuristics.
                    # _split_after returns (desc, qty, trailing_remarks); capture
                    # the third value so non-digit trailing tokens reach remarks.
                    desc, qty, _sa_rem = self._split_after(desc_sv_clean, num_variants)
                    if _sa_rem:
                        rem_sv = [_sa_rem] + rem_sv

                remarks = " ".join(rem_sv)

            else:
                # ── Text-based fallback ─────────────────────────────────────
                after = _COPYRIGHT_PAT.sub("", joined[pn_m.end() :]).strip()

                # Strip remarks-zone words and save them
                positional_remarks = ""
                if bounds and bounds.rem_start < 9000:
                    rem_words = [w["text"] for w in ws_filtered if w["x0"] >= bounds.rem_start]
                    if rem_words:
                        rem_suffix = " ".join(rem_words)
                        if after.endswith(rem_suffix):
                            after = after[: -len(rem_suffix)].strip()
                            positional_remarks = rem_suffix

                # Lookahead: pn and description on different Y-rows
                if not after and idx < len(word_rows):
                    _ny, next_ws = word_rows[idx]
                    next_joined = " ".join(w["text"] for w in next_ws).strip()
                    if (
                        next_joined
                        and not _PN_PAT.search(next_joined)
                        and not _FIG_PAT.match(next_joined)
                        and not _SKIP_PAT.match(next_joined)
                    ):
                        after = _COPYRIGHT_PAT.sub("", next_joined).strip()
                        idx += 1

                desc, qty, remarks = self._split_after(after, num_variants)
                if not remarks and positional_remarks:
                    remarks = positional_remarks

            # ── Kit-composition footnote ───────────────────────────────────
            # Under some FAZER/GLADIATOR tables: "* BRAKE SHOE KIT-5YY-WF533-00-00
            # CONSISTING OF * BRAKE SHOE 1 (LOWER)-5YY-F5130-00-00 (5Y-F5130-00)". The
            # name sits before the part number, so it was being stored as the ref. It
            # is the description; the bracketed 9-digit number is never extracted, and
            # a footnote has no reference or quantity of its own.
            kit_note = _KIT_NOTE.search(before)
            if kit_note:
                rows.append(
                    {
                        "section": new_section,
                        "fig_no": new_fig,
                        "ref_no": "",
                        "part_no": pn,
                        "description": kit_note.group(1).strip(),
                        "qty": "",
                        "nine_digit_part_no": "",
                        "escort_part_no": "",
                        "superseded_part_no": "",
                        "remarks": "",
                        "kit_note": True,
                    }
                )
                continue

            # ── Ref number ─────────────────────────────────────────────────
            if re.match(r"^[\d\s]+$", before):
                last_int = re.search(r"(\d{1,3})\s*$", before)
                ref_no = last_int.group(1) if last_int else before.strip()
            else:
                ref_no = before

            # Carry forward: when the PDF leaves ref blank for the 2nd+ part
            # in a shared-ref group, reuse the last seen ref number.
            if ref_no:
                last_ref_no = ref_no
            elif last_ref_no:
                ref_no = last_ref_no

            rows.append(
                {
                    "section": new_section,
                    "fig_no": new_fig,
                    "ref_no": ref_no,
                    "part_no": pn,
                    "description": _COLOUR_SUFFIX_PAT.sub("", desc).strip(),
                    "qty": qty,
                    "nine_digit_part_no": " ".join(nine_digit_parts),
                    "escort_part_no": " ".join(escort_parts),
                    "superseded_part_no": " ".join(superseded_parts),
                    "remarks": remarks,
                }
            )

        return rows, new_section, new_fig, sections_seen

    # ------------------------------------------------------------------
    # Text-line fallback (no positional data)
    # ------------------------------------------------------------------

    def _text_fallback(self, pdf_path: Path) -> tuple[list[dict[str, str]], set[str]]:
        """Text-line regex parser used when positional extraction yields nothing."""
        import pdfplumber

        rows: list[dict[str, str]] = []
        sections_seen: set[str] = set()
        current_section = ""
        current_fig = ""

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[: self.max_pages]:
                    text = page.extract_text() or ""

                    # Skip KITS pages, cross-reference index pages, and named index pages.
                    # Same FIG-header guard as the positional pass: genuine index pages
                    # never contain "FIG." section markers.
                    page_head = text[:400]
                    _has_fig_text = bool(_FIG_PAT.search(page_head))
                    if (
                        _KITS_PAGE_PAT.search(page_head)
                        or (_XREF_PAGE_PAT.search(page_head) and not _has_fig_text)
                        or _INDEX_PAGE_PAT.search(page_head)
                        or _FOREWORD_PAGE_PAT.search(page_head)
                    ):
                        continue

                    for line in text.split("\n"):
                        line = line.strip()
                        if not line or len(line) < 3:
                            continue
                        if _MODEL_STAMP_PAT.match(line):
                            continue
                        if _SKIP_PAT.match(line):
                            continue

                        fig_m = _FIG_PAT.match(line)
                        if fig_m:
                            current_fig = f"FIG. {fig_m.group(1)}"
                            current_section = _CID_PAT.sub("", fig_m.group(2)).strip()
                            sections_seen.add(current_section)
                            continue

                        opt_m = _PARTS_OPTION_PAT.match(line)
                        if opt_m:
                            current_section = opt_m.group(1).strip()
                            sections_seen.add(current_section)
                            continue

                        pn_m = _PN_PAT.search(line)
                        if not pn_m:
                            continue
                        pn = pn_m.group(1).replace("–", "-")  # normalize en-dash
                        if pn.startswith("X") or not current_section:
                            continue

                        before = line[: pn_m.start()].strip()
                        after = _COPYRIGHT_PAT.sub("", line[pn_m.end() :]).strip()

                        ref_m = re.match(r"^(\d{1,3})\s*$", before)
                        ref_no = ref_m.group(1) if ref_m else before
                        desc, qty, remarks = self._split_after(after, num_variants=0)

                        rows.append(
                            {
                                "section": current_section,
                                "fig_no": current_fig,
                                "ref_no": ref_no,
                                "part_no": pn,
                                "description": desc,
                                "qty": qty,
                                "nine_digit_part_no": "",
                                "escort_part_no": "",
                                "superseded_part_no": "",
                                "remarks": remarks,
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Text fallback failed for {pdf_path}: {exc}")

        return rows, sections_seen

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_after(after: str, num_variants: int = 0) -> tuple[str, str, str]:
        """Split 'DESCRIPTION tokens qty... [remarks]' into (desc, qty, remarks).

        Algorithm (right-to-left):
        1. If last token is non-numeric → it is remarks; pop it.
        2. Pop qty digit tokens from the right:
           - If num_variants > 0: pop exactly num_variants digits. This prevents
             trailing description digits (e.g. "GUIDE, VALVE 1") from being
             consumed as a qty column when all variant qtys are the same value.
           - If num_variants == 0 (unknown): greedy — pop all trailing digits.
        3. Collapse identical multi-values: "1/1/1/1" → "1".
        4. Everything remaining is the description.
        """
        tokens = list(after.split())
        if not tokens:
            return "", "", ""

        # Step 1: extract optional remarks (last non-digit token)
        remarks = ""
        if not re.match(r"^\d+$", tokens[-1]):
            remarks = tokens.pop()

        if not tokens:
            return "", "", remarks

        # Step 2: collect qty tokens
        qty_vals: list[str] = []
        if num_variants > 0:
            # Known variant count — pop at most num_variants digits from the right
            count = 0
            while tokens and count < num_variants and re.match(r"^\d+$", tokens[-1]):
                qty_vals.insert(0, tokens.pop())
                count += 1
        else:
            # Unknown — greedy: pop all trailing digit tokens
            while tokens and re.match(r"^\d+$", tokens[-1]):
                qty_vals.insert(0, tokens.pop())

        qty = "/".join(qty_vals) if qty_vals else ""
        # Collapse "1/1/1/1" → "1" when all variant qtys are identical
        if qty and len(set(qty_vals)) == 1:
            qty = qty_vals[0]
        return " ".join(tokens), qty, remarks
