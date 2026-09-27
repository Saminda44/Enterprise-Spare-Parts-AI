"""Yamaha catalogue remark grammar parser.

Resolves colour applicability from a remarks string using the grammar defined
in the catalogue foreword. Used by the CatalogueAgent assembly engine.

Grammar (formal-ish):
    remark        := clause (";" clause)*
    clause        := EXCEPT_clause | FOR_clause | ABBR_clause | standalone_token*
    EXCEPT_clause := ("EXCEPT" | "EXCEPT FOR") colourlist
    FOR_clause    := token* "FOR" colourlist   -- "FOR" may be at clause start
    ABBR_clause   := ABBR colourlist           -- e.g. "UR BWC1"
    colourlist    := CODE ("," CODE)*
    CODE          := token present in foreword colour legend
    EXCEPT        := "EXCEPT" | "EXCEPT FOR"
    ABBR          := "UR" | "UN" | "AP" | "LM" | "OPT" | "STD"

Three patterns produce motorcycle-colour restrictions:
  - "FOR [ABBR]" (at clause start or after a prefix like "UR FOR [ABBR]")
  - "EXCEPT [ABBR]" / "EXCEPT FOR [ABBR]"
  - "UR [ABBR]" — a colour list introduced by a catalogue abbreviation token, with
    no "FOR". "UR MPBM1,MDPBM1" on a GRAPHIC is one of three versions of that decal,
    one per colour group.

A colour may be a multi-word name rather than an abbreviation — "FOR YAMAHA BLACK",
written from a description colour the foreword table does not list. A known colour
containing spaces is matched as one phrase before the remark is split into tokens.

A colour code standing alone with no keyword at all (e.g. "YB" on a cast wheel whose
part number already ends -33 for Yamaha Black) indicates the PART'S OWN paint finish.
It does NOT say which motorcycle colour variant the part belongs to, and is treated as
universal — no restriction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Catalogue abbreviation tokens that prefix colour clauses — not colour codes
_ABBR_TOKENS = frozenset({"UR", "UN", "AP", "LM", "OPT", "STD"})

# Joins the words of a multi-word colour name into one token while parsing.
_PHRASE_JOIN = "_"

# Tokeniser: split on whitespace and commas, keep meaningful tokens
_SPLIT_PAT = re.compile(r"[\s,]+")


@dataclass
class ApplicabilityResult:
    """Colour applicability for a single parts-table row.

    Business meaning:
    - ``is_universal=True``  → part applies to ALL colours (no colour restriction).
    - ``is_except_mode=True`` → part applies to all colours EXCEPT those in ``applies_to``.
    - otherwise              → part applies only to the colours in ``applies_to``.
    """

    is_universal: bool
    applies_to: set[str] = field(default_factory=set)
    is_except_mode: bool = False
    #: The same codes in the order the remark lists them. Multimodal attribution needs
    #: that order: "FOR YB,MS1" over two models pairs the first colour with the first
    #: model, and a set would have thrown the pairing away.
    ordered: list[str] = field(default_factory=list)

    def matches(self, colour: str) -> bool:
        """Return True if this row belongs to the given colour variant."""
        if self.is_universal:
            return True
        colour = colour.upper()
        if self.is_except_mode:
            return colour not in self.applies_to
        return colour in self.applies_to


_UNIVERSAL = ApplicabilityResult(is_universal=True)


def parse_applicability(remarks: str, colour_abbrs: set[str]) -> ApplicabilityResult:
    """Parse a remarks string and return its colour applicability.

    Args:
        remarks:      Raw remarks text from the parts table (e.g. ``"LLGS6 FOR DBNM8"``).
        colour_abbrs: Set of known colour abbreviations from the foreword legend
                      (upper-case, e.g. ``{"DBNM8", "MBL2", "YB", ...}``).

    Returns:
        ApplicabilityResult describing which colours this part applies to.
    """
    colour_abbrs = {c.upper() for c in colour_abbrs}

    if not remarks or not remarks.strip():
        return _UNIVERSAL

    upper = remarks.upper().strip()

    # Join each known multi-word colour into one token, longest first so "DEEP PURPLE
    # BLUE" is not split by a shorter "PURPLE BLUE"; mapped back before returning.
    phrases = {c.replace(" ", _PHRASE_JOIN): c for c in colour_abbrs if " " in c}
    for joined, phrase in sorted(phrases.items(), key=lambda kv: -len(kv[1])):
        upper = re.sub(rf"(?<![A-Z0-9]){re.escape(phrase)}(?![A-Z0-9])", joined, upper)
    colour_abbrs = (colour_abbrs - set(phrases.values())) | set(phrases)

    applies_codes: set[str] = set()
    except_codes: set[str] = set()
    ordered: list[str] = []
    has_restriction = False

    def _record(codes: list[str]) -> None:
        for code in codes:
            if code not in ordered:
                ordered.append(code)

    # Process each semicolon-delimited clause independently
    for clause in upper.split(";"):
        clause = clause.strip()
        if not clause:
            continue

        # --- EXCEPT FOR / EXCEPT pattern ---
        m = re.match(r"EXCEPT(?:\s+FOR)?\s+(.*)", clause)
        if m:
            tokens = [t for t in _SPLIT_PAT.split(m.group(1).strip()) if t]
            codes = [t for t in tokens if t in colour_abbrs]
            if codes:
                except_codes.update(codes)
                has_restriction = True
            continue

        # --- FOR pattern ---
        # "[PREFIX] FOR [ABBR]" — space before FOR (e.g. "UR FOR SMX")
        for_pos = clause.find(" FOR ")
        if for_pos >= 0:
            after_for = clause[for_pos + 5 :].strip()
            tokens = [t for t in _SPLIT_PAT.split(after_for) if t]
            codes = [t for t in tokens if t in colour_abbrs]
            if codes:
                applies_codes.update(codes)
                _record(codes)
                has_restriction = True
            continue

        # "FOR [ABBR]" — clause starts with FOR (no prefix, e.g. "FOR YB")
        if clause.startswith("FOR "):
            after_for = clause[4:].strip()
            tokens = [t for t in _SPLIT_PAT.split(after_for) if t]
            codes = [t for t in tokens if t in colour_abbrs]
            if codes:
                applies_codes.update(codes)
                _record(codes)
                has_restriction = True
            continue

        # --- Catalogue-abbreviation clause, e.g. "UR BWC1", "UR MPBM1,MDPBM1" ---
        # A colour list introduced by one of the catalogue's own abbreviation tokens
        # restricts the part, exactly as "FOR" does. "UR MPBM1,MDPBM1" on a GRAPHIC is
        # one of three versions of that decal, one per colour group.
        tokens = [t for t in _SPLIT_PAT.split(clause) if t]
        if tokens and tokens[0] in _ABBR_TOKENS:
            codes = [t for t in tokens[1:] if t in colour_abbrs]
            if codes:
                applies_codes.update(codes)
                _record(codes)
                has_restriction = True
            continue

        # --- Standalone token (no keyword at all) ---
        # A bare colour code (e.g. "YB" on a cast wheel whose part number already ends
        # -33 for Yamaha Black) marks the PART'S OWN paint finish, not which motorcycle
        # colour variant it belongs to. Treat as universal — no restriction recorded.

    if not has_restriction:
        return _UNIVERSAL

    def _plain(code: str) -> str:
        return phrases.get(code, code)

    if except_codes and not applies_codes:
        return ApplicabilityResult(
            is_universal=False,
            applies_to={_plain(c) for c in except_codes},
            is_except_mode=True,
            ordered=sorted(_plain(c) for c in except_codes),
        )

    # If both except and applies (unusual), treat as direct inclusion
    return ApplicabilityResult(
        is_universal=False,
        applies_to={_plain(c) for c in applies_codes},
        is_except_mode=False,
        ordered=[_plain(c) for c in ordered],
    )
