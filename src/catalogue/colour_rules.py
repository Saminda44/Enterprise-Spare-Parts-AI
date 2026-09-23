"""Resolve which colour variant each catalogue part belongs to.

The rules are specified, not inferred. Each resolved row records which rule fired, so a
wrong extraction can be audited rather than merely disbelieved.

Rule B  remark carries an abbreviation      ``YB`` / ``UR YB`` / ``FOR YB``
        ``EXCEPT YB`` inverts — against the **confirmed** set, never the FOREWORD table
        ``YB, DPBMC`` belongs to each listed colour
Rule C  remark carries a number             suffix after the final ``-`` is the variant
Rule D  colour appears in the description   suffix after ``-`` or inside brackets
Rule E  multimodal catalogues               a colour shown for exactly one model is that
                                            model's variant
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.catalogue.pdf_reader import CataloguePart, ColourEntry

_UR_FOR = re.compile(r"\b(?:UR|FOR)\b", re.I)
_EXCEPT = re.compile(r"\bEXCEPT\b", re.I)
_TRAILING_NUMBER = re.compile(r"-(\d{1,2})\s*$")
_BRACKETED = re.compile(r"[(\[]([^)\]]{1,30})[)\]]")


@dataclass
class ColourAssignment:
    """One part's colour resolution."""

    part_no: str
    model_code: str | None
    part_kind: str  # "coloured" | "shared"
    colour_abbr: str | None
    colour_name: str | None
    colour_code: str | None
    rule_applied: str
    confidence: float


@dataclass
class ResolutionReport:
    confirmed_variants: list[str] = field(default_factory=list)
    rule_counts: dict[str, int] = field(default_factory=dict)
    exceptions: list[dict[str, str]] = field(default_factory=list)

    def count(self, rule: str) -> None:
        self.rule_counts[rule] = self.rule_counts.get(rule, 0) + 1


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", text.upper()) if t]


def confirm_variants(parts: list[CataloguePart], colours: list[ColourEntry]) -> list[ColourEntry]:
    """Keep only colours actually observed in the parts table.

    Business meaning: the FOREWORD table is the universe of *possible* colours. Real
    variants are equal to or fewer than it. Promoting the table wholesale invents
    variants that do not exist in the PDF, and then ``EXCEPT`` inverts against the wrong
    set.
    """
    if not colours:
        return []
    by_abbr = {c.abbreviation.upper(): c for c in colours}
    seen: set[str] = set()
    for part in parts:
        haystack = f"{part.remark_raw or ''} {part.description or ''}"
        for token in _tokens(haystack):
            if token in by_abbr:
                seen.add(token)
        upper = haystack.upper()
        for abbr, entry in by_abbr.items():
            if entry.name and entry.name.upper() in upper:
                seen.add(abbr)
    return [by_abbr[a] for a in sorted(seen)]


def _entry_for(abbr: str, confirmed: list[ColourEntry]) -> ColourEntry | None:
    return next((c for c in confirmed if c.abbreviation.upper() == abbr.upper()), None)


def resolve_part(
    part: CataloguePart,
    confirmed: list[ColourEntry],
    report: ResolutionReport,
    *,
    single_model_variants: dict[str, str] | None = None,
) -> list[ColourAssignment]:
    """Apply rules B → C → D → E to one part row.

    Returns one assignment per colour the part belongs to; a shared part yields one row
    with ``colour_abbr`` unset.
    """
    remark = (part.remark_raw or "").strip()
    description = part.description or ""
    abbrs = {c.abbreviation.upper() for c in confirmed}

    def shared(rule: str, confidence: float) -> list[ColourAssignment]:
        report.count(rule)
        return [
            ColourAssignment(
                part_no=part.part_no,
                model_code=part.model_code,
                part_kind="shared",
                colour_abbr=None,
                colour_name=None,
                colour_code=None,
                rule_applied=rule,
                confidence=confidence,
            )
        ]

    def coloured(
        entries: list[ColourEntry], rule: str, confidence: float
    ) -> list[ColourAssignment]:
        report.count(rule)
        return [
            ColourAssignment(
                part_no=part.part_no,
                model_code=part.model_code,
                part_kind="coloured",
                colour_abbr=entry.abbreviation,
                colour_name=entry.name,
                colour_code=entry.code,
                rule_applied=rule,
                confidence=confidence,
            )
            for entry in entries
        ]

    # ── Rule B — abbreviations in the remark ────────────────────────────────────
    if remark and abbrs:
        found = [t for t in _tokens(remark) if t in abbrs]
        if found:
            if _EXCEPT.search(remark):
                excluded = set(found)
                remaining = [c for c in confirmed if c.abbreviation.upper() not in excluded]
                if remaining:
                    return coloured(remaining, "B:EXCEPT", 0.85)
                report.exceptions.append(
                    {
                        "part_no": part.part_no,
                        "remark": remark,
                        "reason": "EXCEPT excluded every confirmed variant",
                    }
                )
                return shared("B:EXCEPT-empty", 0.3)
            entries = [e for e in (_entry_for(a, confirmed) for a in dict.fromkeys(found)) if e]
            rule = "B:UR/FOR" if _UR_FOR.search(remark) else "B:abbr"
            return coloured(entries, rule, 0.95 if len(entries) == 1 else 0.9)

    # ── Rule C — numeric suffix in the remark ───────────────────────────────────
    if remark:
        match = _TRAILING_NUMBER.search(remark)
        if match and any(c.code for c in confirmed):
            variant = match.group(1)
            entry = next((c for c in confirmed if (c.code or "").lstrip("0") == variant), None)
            if entry is not None:
                report.count("C:suffix")
                return [
                    ColourAssignment(
                        part_no=part.part_no,
                        model_code=part.model_code,
                        part_kind="shared",
                        colour_abbr=entry.abbreviation,
                        colour_name=entry.name,
                        colour_code=entry.code,
                        rule_applied="C:suffix",
                        confidence=0.75,
                    )
                ]

    # ── Rule D — colour in the description ──────────────────────────────────────
    if description and abbrs:
        candidates: list[str] = []
        for bracketed in _BRACKETED.findall(description):
            candidates.extend(t for t in _tokens(bracketed) if t in abbrs)
        tail = description.rsplit("-", 1)[-1] if "-" in description else ""
        candidates.extend(t for t in _tokens(tail) if t in abbrs)
        upper = description.upper()
        for entry in confirmed:
            if entry.name and entry.name.upper() in upper:
                candidates.append(entry.abbreviation.upper())
        if candidates:
            entries = [
                e for e in (_entry_for(a, confirmed) for a in dict.fromkeys(candidates)) if e
            ]
            if entries:
                return coloured(entries, "D:description", 0.7)

    # ── Rule E — multimodal, colour shown for exactly one model ─────────────────
    if single_model_variants and part.qty_by_model:
        owned = [code for code in part.qty_by_model if single_model_variants.get(code) is not None]
        if len(owned) == 1:
            abbr = single_model_variants[owned[0]]
            entry = _entry_for(abbr, confirmed) if abbr else None
            if entry is not None:
                return coloured([entry], "E:single-model", 0.7)

    if remark and abbrs and not any(t in abbrs for t in _tokens(remark)):
        report.exceptions.append(
            {"part_no": part.part_no, "remark": remark, "reason": "remark unresolved against table"}
        )
    return shared("shared:no-colour-signal", 0.6 if not remark else 0.4)


def resolve_catalogue(
    parts: list[CataloguePart], colours: list[ColourEntry]
) -> tuple[list[ColourAssignment], ResolutionReport]:
    """Confirm the variant set, then resolve every part against it."""
    report = ResolutionReport()
    confirmed = confirm_variants(parts, colours)
    report.confirmed_variants = [c.abbreviation for c in confirmed]

    # Rule E step 1 — a colour whose quantity appears for exactly one model belongs to
    # that model. This must run before splitting comma-separated remarks across models.
    abbrs = {c.abbreviation.upper() for c in confirmed}
    models_for_abbr: dict[str, set[str]] = {}
    for part in parts:
        found = [t for t in _tokens(part.remark_raw or "") if t in abbrs]
        for abbr in found:
            models_for_abbr.setdefault(abbr, set()).update(part.qty_by_model)
    single_model_variants = {
        next(iter(models)): abbr for abbr, models in models_for_abbr.items() if len(models) == 1
    }

    assignments: list[ColourAssignment] = []
    for part in parts:
        assignments.extend(
            resolve_part(part, confirmed, report, single_model_variants=single_model_variants)
        )
    return assignments, report
