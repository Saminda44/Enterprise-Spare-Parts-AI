"""Per-catalogue extraction policy, declared rather than inferred.

Most extraction rules are general and live in the reader. A handful of catalogues need
an instruction the reader cannot safely infer from the page — which column holds the
real part number, which column is noise, whether a book is excluded outright. Those
instructions come from the catalogue owner and are recorded here, one entry per file,
so every exception is visible in one place and nothing is special-cased inline.

Two rules apply to every catalogue and so are not listed per file:

* ``9 Digit Part No.``, ``Escort 12 Digit Part No.`` and ``Superseded Part No.`` are
  never extracted. They are alternative numbering for the same part, not parts.
* A remarks column headed ``Remarks (9 Digit)`` holds a truncated part number, not a
  remark, and is discarded.

Keys are paths relative to ``data/raw/pdf_catalogues``, with forward slashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DeclaredColour:
    """One row of an applicable-colour table that is printed as an image.

    Transcribed by hand from the rendered page, since no text layer exists to read.
    """

    code: str
    name: str
    abbreviation: str


@dataclass(frozen=True)
class CatalogueOverride:
    """What the owner has said about one catalogue."""

    #: Fields to blank on every row. "remarks" drops the remarks column's content; the
    #: column itself survives if the reader later writes a colour remark into it.
    drop_fields: frozenset[str] = field(default_factory=frozenset)
    #: The book covers one model. Any "variant" the reader finds is a mis-read column
    #: header, and the cover type code is the only model.
    single_model: bool = False
    #: The applicable-colour table, transcribed, when the PDF prints it as an image.
    #: Used only when no table can be read from the page text.
    colour_table: tuple[DeclaredColour, ...] = ()
    #: Page (1-based) the transcribed table was read from, for provenance.
    colour_table_page: int | None = None
    #: Sections whose rows are not extracted, with the reason. Matched exactly.
    excluded_sections: tuple[tuple[str, str], ...] = ()
    #: Kit rows are not extracted: a ref of "*" (a kit's listed components) or "KIT"
    #: in the description.
    drop_kit_rows: bool = False
    #: Exclude the catalogue from batch extraction and the database, with this reason.
    excluded_reason: str | None = None


#: The owner's instructions, 2026-09-25.
CATALOGUE_OVERRIDES: dict[str, CatalogueOverride] = {
    # India-market layout. "Existing Part No." is the part number and "Part Name" the
    # description — the reader already maps those — and the remarks column carries
    # nothing wanted. Colour comes from the description instead.
    #
    # ENTICER 5US1's foreword (page 2, rotated image) names three colours and gives no
    # code or abbreviation. The body abbreviates them CNM (8 rows), LYNM9 (8) and BG
    # (6); the pairing below follows the initials and was confirmed by the owner.
    "ENTICER/ENTICER 5US1.pdf": CatalogueOverride(
        drop_fields=frozenset({"remarks"}),
        colour_table=(
            DeclaredColour("", "CANDY MAROON", "CNM"),
            DeclaredColour("", "LIGHT YELLOW METALLIC GREY", "LYNM9"),
            DeclaredColour("", "BLACK", "BG"),
        ),
        colour_table_page=2,
    ),
    "YBX/YBX125.pdf": CatalogueOverride(
        drop_fields=frozenset({"remarks"}),
        colour_table=(
            DeclaredColour("00", "BLACK GOLD", "BG"),
            DeclaredColour("10", "DARK PURPLISH RED COCKTAIL 3", "DPRC3"),
            DeclaredColour("20", "DEEP PURPLISH BLUE METALLIC C", "DPBMC"),
        ),
        colour_table_page=3,
    ),
    # The owner's instructions, 2026-09-26.
    # Includes "TOOL KIT" and "* CHAIN PULLER ASSY. 2 (CONSISTING OF SR. NOS. 42, 43,
    # 44)", confirmed by the owner as kit rows to drop.
    "LIBERO/LIBERO  G5.pdf": CatalogueOverride(drop_kit_rows=True),
    "R 15/R15 1CK5.pdf": CatalogueOverride(
        excluded_reason=(
            "byte-identical copy of R 15/YZF R15 1CK5 Catalogue.pdf; one is kept, by the "
            "owner's instruction"
        ),
    ),
    # Page 58 lists parts exclusive to CRUX 5KA2, a model this book does not cover.
    "CRUX/Crux_ Crux R Parts Catalogue_New 5ka1.pdf": CatalogueOverride(
        excluded_sections=(
            (
                "PARTS EXCLUSIVE TO CRUX (5KA2)",
                "parts exclusive to 5KA2, which this catalogue does not cover; not added "
                "by the owner's instruction",
            ),
        ),
    ),
    # One model each; their quantity-column headers are colour codes, not models.
    "FAZER/2WS3.pdf": CatalogueOverride(single_model=True),
    "FZ & FZS/PC 2GS6.pdf": CatalogueOverride(single_model=True),
    "SALUTO/Saluto RX B441.pdf": CatalogueOverride(single_model=True),
    # Columns collapse into the description on this file; not recoverable.
    "RAY/RAY 1GC1 WHITE.pdf": CatalogueOverride(
        excluded_reason=(
            "column boundaries collapse on this file: part name, colour, quantity and "
            "remark arrive as one field on 29 of its 108 rows; excluded by the owner"
        ),
    ),
}

#: Fields no catalogue has extracted, by the owner's instruction.
NEVER_EXTRACTED: frozenset[str] = frozenset(
    {"nine_digit_part_no", "escort_part_no", "superseded_part_no"}
)

#: Column-layout labels for those fields, removed from what the page displays.
NEVER_EXTRACTED_LABELS: frozenset[str] = frozenset(
    {"9 Digit Part No.", "Escort Part No.", "Escort 12 Digit Part No.", "Superseded Part No."}
)

_NONE = CatalogueOverride()


def relative_key(pdf_path: Path) -> str:
    """The override key for a PDF: ``<model folder>/<file name>``.

    Every catalogue sits exactly one folder below the catalogue root, so the folder and
    file name identify it without needing to know where the root is.
    """
    return f"{pdf_path.parent.name}/{pdf_path.name}"


def override_for(pdf_path: Path) -> CatalogueOverride:
    """The owner's instruction for this catalogue, or the empty default."""
    return CATALOGUE_OVERRIDES.get(relative_key(pdf_path), _NONE)


def excluded() -> dict[str, str]:
    """Every excluded catalogue and why, keyed by relative path."""
    return {
        key: rule.excluded_reason
        for key, rule in CATALOGUE_OVERRIDES.items()
        if rule.excluded_reason
    }
