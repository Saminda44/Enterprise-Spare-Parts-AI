"""Catalogue Agent — assembles complete parts builds per (variant, colour).

Pipeline:
    Stage 1+2  existing YamahaCatalogueExtractor → rows, variants, colour_codes
    Stage 3    colour roster per variant (which colours appear for each variant)
    Stage 5    assembly engine — per (variant, colour): shared + colour-specific parts
    Stage 6    serialize to AgentResult / JSON

The assembly logic implements the remark grammar from remark_parser.py so that
each colour build is a *complete motorcycle* — shared parts plus the correct
colour-specific parts for that colour, with no duplicates by REF.NO.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from src.catalogue.browser.pdf_extractor import YamahaCatalogueExtractor
from src.catalogue.browser.remark_parser import parse_applicability

# ---------------------------------------------------------------------------
# Web colour extraction helpers (module-level, compiled once)
# ---------------------------------------------------------------------------

# Colour words that anchor a phrase as a "colour name"
_WEB_COLOUR_NOUNS = frozenset(
    [
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
        "vermillion",
        "champagne",
        "magenta",
        "maroon",
        "indigo",
    ]
)
_WEB_COLOUR_MODIFIERS = frozenset(
    [
        "metallic",
        "matte",
        "matt",
        "mat",
        "vivid",
        "deep",
        "light",
        "dark",
        "solid",
        "bright",
        "pearl",
        "candy",
        "flat",
        "grayish",
        "greyish",
        "purplish",
        "bluish",
        "reddish",
        "greenish",
        "leaf",
        "ice",
        "racing",
        "fluo",
        "neon",
        "chromatic",
        "luminous",
    ]
)
# A "colour phrase" is 2-6 capitalized-or-all-caps tokens that contain at
# least one colour noun
_WEB_PHRASE_PAT = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:[\s\-][A-Z][A-Za-z0-9]+){1,5})\b")
# Stopwords to strip when normalising colour names for fuzzy comparison
_NORM_STOP = frozenset({"the", "a", "an", "and", "or", "of", "for", "with", "no", "new"})

# ---------------------------------------------------------------------------
# Colour-name normalisation + synonym helpers (module-level)
# ---------------------------------------------------------------------------

# Canonical spelling: map variant spellings → canonical form used for overlap
_COLOUR_SPELLING: dict[str, str] = {
    "grey": "gray",
    "greyish": "grayish",
    "matt": "mat",
    "matte": "mat",
}


def _norm_colour_word(w: str) -> str:
    return _COLOUR_SPELLING.get(w.lower(), w.lower())


def _norm_colour_words(text: str) -> set[str]:
    """Split text into normalised colour words, filtering stop words & short tokens."""
    return {
        _norm_colour_word(w)
        for w in re.split(r"[\s\-_]+", text)
        if len(w) > 2 and w.lower() not in _NORM_STOP
    }


# Colour-name synonyms: when matching an available-colour label to a legend name,
# expand available-colour words with these synonyms so semantic neighbours match.
# e.g. "Gold" expands to include "yellowish", so "LIGHT YELLOWISH GRAY" matches.
_COLOUR_SYNONYMS: dict[str, frozenset[str]] = {
    "gold": frozenset({"yellowish", "golden", "champagne", "sand"}),
    "navy": frozenset({"dark", "darkish", "deep"}),
    "silver": frozenset({"gray", "metallic"}),
    "champagne": frozenset({"gold", "beige", "yellowish"}),
    "cream": frozenset({"ivory", "beige"}),
    "coral": frozenset({"red", "orange"}),
    "violet": frozenset({"purple"}),
    "turquoise": frozenset({"cyan", "teal"}),
}


def _expand_colour_words(words: set[str]) -> set[str]:
    """Return the union of *words* and their colour synonyms."""
    expanded = set(words)
    for w in words:
        expanded.update(_COLOUR_SYNONYMS.get(w, frozenset()))
    return expanded


# ---------------------------------------------------------------------------
# Cross-PDF colour-code cache (module-level, file-backed)
# ---------------------------------------------------------------------------

# Seed dictionary of well-known Yamaha colour abbreviations → human-readable names.
# Populated from PDFs in this project whose filenames or forewords explicitly name
# the codes.  Extended at runtime via _update_colour_cache() for every valid extraction.
_YAMAHA_COLOUR_SEED: dict[str, str] = {
    "SMX": "Black Metallic X",
    "CM6": "Cyan Metallic 6",
    "YB": "Yamaha Black",
    "BWC1": "Bluish White Cocktail 1",
    "MNM3": "Mat Gray Metallic 3",
    "MPBM1": "Mat Purplish Blue Metallic 1",
    "MDPBM1": "Mat Dark Purplish Blue Metallic 1",
    "LYNM9": "Light Yellowish Gray Metallic 9",
    "MBL2": "Mat Black 2",
    "S8": "Silver 8",
    "VRC1": "Vivid Red",
    "DBNM8": "Dull Blue Navy Metallic 8",
}


def _browser_dir() -> Path:
    """Where the catalogue browser keeps its own artefacts, beside the marts."""
    from src.core.settings import get_settings  # noqa: PLC0415 — avoids an import cycle

    directory = get_settings().marts_dir.parent / "catalogue_browser"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


_COLOUR_CACHE_PATH = _browser_dir() / "colour_code_cache.json"
_colour_cache: dict[str, str] | None = None  # module-level singleton


def _load_colour_cache() -> dict[str, str]:
    """Load the cross-PDF colour code cache (seed + file-backed entries)."""
    global _colour_cache  # noqa: PLW0603
    if _colour_cache is not None:
        return _colour_cache
    cache = dict(_YAMAHA_COLOUR_SEED)
    if _COLOUR_CACHE_PATH.exists():
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            cache.update(json.loads(_COLOUR_CACHE_PATH.read_text(encoding="utf-8")))
    _colour_cache = cache
    return cache


def _update_colour_cache(legend: dict[str, dict]) -> None:
    """Persist any new abbreviation → name entries to the colour code cache."""
    cache = _load_colour_cache()
    changed = False
    for abbr, entry in legend.items():
        name = entry.get("name", "")
        if name and abbr not in cache:
            cache[abbr] = name
            changed = True
    if changed:
        try:
            _COLOUR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _COLOUR_CACHE_PATH.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Garbage-legend detection (module-level)
# ---------------------------------------------------------------------------

# Tokens that indicate a copyright / legal table was mistakenly parsed as colours
_GARBAGE_ABBR_TOKENS = frozenset(
    {
        "YAMAHA",
        "HONDA",
        "SUZUKI",
        "KAWASAKI",
        "TVSL",
        "1ST",
        "2ND",
        "3RD",
        "COPYRIGHT",
        "EDITION",
        "PRINTING",
        "ANY",
        "ALL",
        "RIGHTS",
        "RESERVED",
        "USE",
        "THIS",
        "CATALOGUE",
        "PROPERTY",
        "REPRINTING",
        "UNAUTHORIZED",
        "REVISED",
        "ISSUED",
    }
)


def _is_garbage_legend(legend: dict[str, dict]) -> bool:
    """Return True if the colour legend looks like copyright text, not paint codes."""
    if not legend:
        return True
    garbage = sum(1 for abbr in legend if abbr.upper() in _GARBAGE_ABBR_TOKENS)
    return garbage / len(legend) > 0.40


# ---------------------------------------------------------------------------
# Remarks-based colour-code discovery (module-level)
# ---------------------------------------------------------------------------

# "FOR XYZ" or "FOR XYZ, ABC" in the remarks column; only all-caps alphanumeric tokens
_FOR_CODE_PAT = re.compile(
    r"\bFOR\s+((?:[A-Z][A-Z0-9]{1,7})(?:[,\s]+[A-Z][A-Z0-9]{1,7})*)",
    re.IGNORECASE,
)
# Tokens that appear after FOR but are NOT colour codes (catalogue abbreviations,
# tyre brands, common words)
_REMARK_SKIP_TOKENS = frozenset(
    {
        "NEW",
        "OLD",
        "STD",
        "OPT",
        "UR",
        "UN",
        "AP",
        "LM",
        "MRF",
        "TVS",
        "IRF",
        "CEAT",
        "METRO",
        "BRIDGESTONE",
        "APPLICABLE",
        "REFERENCE",
        "ONLY",
        "ALL",
        "MODELS",
    }
)


def _discover_remarks_codes(rows: list[dict]) -> set[str]:
    """Scan 'FOR XYZ' patterns in all row remarks to find colour abbreviations.

    Returns the set of all candidate abbreviations (2–8 uppercase chars) that
    appear as colour applicability targets in the remarks column.
    """
    found: set[str] = set()
    for row in rows:
        rem = (row.get("remarks", "") or "").upper()
        for m in _FOR_CODE_PAT.finditer(rem):
            for tok in re.split(r"[,\s]+", m.group(1).strip()):
                tok = tok.strip()
                if tok and 2 <= len(tok) <= 8 and tok not in _REMARK_SKIP_TOKENS:
                    found.add(tok)
    return found


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ColourEntry:
    abbreviation: str
    name: str
    code: str  # paint code e.g. "0903"
    is_model_colour: bool


@dataclass
class PartRow:
    figure: str
    ref_no: str
    part_no: str
    description: str
    qty: str
    remarks: str
    kind: str  # "shared" | "colour_specific"


@dataclass
class VariantBuild:
    variant: str
    colour: str
    colour_name: str
    colour_code: str
    part_count: int
    parts: list[PartRow] = field(default_factory=list)


@dataclass
class AgentResult:
    source_pdf: str
    extracted_at: str
    model: str
    model_no: str | None  # Yamaha type code from cover page, e.g. "5YY8", "BP16"
    manufacture_year: str | None
    variants: list[str]
    colour_legend: dict[
        str, dict
    ]  # abbr → {name, code, is_model_colour, web_confirmed, has_external_parts}
    rosters: dict[str, list[str]]  # variant → [colour_abbrs]
    builds: list[VariantBuild]
    # Abbreviations confirmed by web search AND having ≥1 external (colour-specific) part.
    # The colour strip in the UI shows ONLY these. Empty = web search unavailable → show all.
    validated_colours: list[str]
    web_colour_names: list[str]  # raw colour names returned by web search
    warnings: list[str]
    # Server-computed mapping: available_colour_name → colour_abbreviation.
    # Populated when the PDF has an "AVAILABLE COLOUR" page.  The frontend uses
    # this directly so it doesn't have to re-derive the mapping client-side.
    available_colour_map: dict[str, str] = field(default_factory=dict)
    # Per-variant ordered colour list, derived from rosters + colour_legend.
    # Key = variant code (e.g. "B65J"), value = ordered list of colour dicts
    # [{abbreviation, name, code, is_model_colour}] in foreword-table order.
    # Empty list means no colour variants found for that model.
    variant_colour_map: dict[str, list[dict]] = field(default_factory=dict)
    # How variant_colour_map was resolved: "roster" | "cyclic" | "web" | "fallback"
    variant_colour_source: str = "fallback"
    # Parts that have different part numbers per colour (same ref_no, ≥2 colours).
    # Each entry: {section, ref_no, description, per_colour: {abbr: part_no}}.
    colour_changing_parts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert VariantBuild list explicitly so PartRow dataclasses serialize
        d["builds"] = [
            {
                **{k: v for k, v in asdict(b).items() if k != "parts"},
                "parts": [asdict(p) for p in b.parts],
            }
            for b in self.builds
        ]
        return d


# ---------------------------------------------------------------------------
# Qty helpers (mirrors the frontend variantQty function)
# ---------------------------------------------------------------------------


def _variant_qty(qty: str, idx: int, num_variants: int) -> str:
    """Extract per-variant qty from slash-encoded string.

    For single-variant PDFs qty is a plain string (e.g. "1").
    For multi-variant PDFs qty is slash-encoded: "1//1/" where each slot
    corresponds to one variant column, padded from the right.
    """
    parts = qty.split("/")
    if len(parts) == 1:
        return qty.strip()
    offset = max(0, len(parts) - num_variants)
    raw = parts[offset + idx] if (offset + idx) < len(parts) else ""
    return raw.strip()


def _has_qty(qty_val: str) -> bool:
    return bool(qty_val and qty_val.strip() not in ("", "0"))


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------


class CatalogueAgent:
    """Run the six-stage catalogue pipeline and return an AgentResult."""

    def __init__(self, max_pages: int = 500) -> None:
        self._extractor = YamahaCatalogueExtractor(max_pages=max_pages)
        self._last_colour_matches: dict[str, dict] = {}  # For debugging colour matching

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, pdf_path: Path) -> AgentResult:
        """Extract and assemble a complete AgentResult for one PDF.

        Args:
            pdf_path: Absolute path to the Yamaha parts catalogue PDF.

        Returns:
            AgentResult with model, variants, colour legend, rosters, and builds.
        """
        logger.info(f"CatalogueAgent: starting {pdf_path.name}")

        # ── Stage 1 + 2 ── existing extractor ──────────────────────────
        result = self._extractor.extract(pdf_path, model=pdf_path.parent.name)
        if result.error:
            raise RuntimeError(f"Extraction failed: {result.error}")

        variants: list[str] = result.variants or []
        colour_codes: list[dict] = result.colour_codes or []
        rows: list[dict] = result.rows or []

        # When no variant code was found on the cover page or in the filename,
        # the _assemble_builds loop has nothing to iterate over and produces 0
        # builds — even though the extractor found real rows.  Synthesise a
        # single empty-string variant so the loop runs and all extracted parts
        # get indexed as shared parts for this model.
        _variant_synthesised = not variants and bool(rows)
        if _variant_synthesised:
            # Use the Yamaha type code (model_no) as the synthetic variant key so the
            # frontend can display a meaningful chip (e.g. "5YY8") instead of nothing.
            # Validity rules for a Yamaha type code:
            #   • 3-8 chars, purely alphanumeric, no spaces
            #   • Does NOT contain 4+ consecutive digits (rejects "JAN2019")
            _raw_mn = result.model_no or ""
            _valid_code = bool(re.match(r"^[A-Z0-9]{3,8}$", _raw_mn)) and not bool(
                re.search(r"\d{4}", _raw_mn)
            )
            _synth_code = _raw_mn if _valid_code else ""
            variants = [_synth_code]
            logger.info(
                f"{pdf_path.name}: no variant code detected — "
                f"synthesising variant '{_synth_code}' so {len(rows)} rows can be indexed"
            )

        colour_abbrs: set[str] = {c["abbreviation"].upper() for c in colour_codes}
        colour_legend: dict[str, dict] = {c["abbreviation"].upper(): c for c in colour_codes}

        logger.info(
            f"{pdf_path.name}: {len(rows)} rows, "
            f"{len(variants)} variants, {len(colour_codes)} colours"
        )

        # ── Update cross-PDF colour code cache from valid legends ──────
        # Every time we see a clean colour table, persist its code→name
        # entries so they can be reused when other PDFs have garbage tables.
        if not _is_garbage_legend(colour_legend) and colour_legend:
            _update_colour_cache(colour_legend)

        # ── Garbage-legend fallback ─────────────────────────────────────
        # Some PDFs have their colour table mis-extracted (e.g. copyright
        # notice parsed as abbreviations → YAMAHA, 1ST, ANY).  Detect this
        # and replace with codes discovered from the remarks column itself.
        if _is_garbage_legend(colour_legend):
            discovered = _discover_remarks_codes(rows)
            if discovered:
                logger.warning(
                    f"{pdf_path.name}: colour legend appears to be garbage "
                    f"({list(colour_legend.keys())}); rebuilding from "
                    f"remarks-discovered codes: {sorted(discovered)}"
                )
                warnings = list(result.warnings)
                warnings.append(
                    f"Colour table extraction failed; "
                    f"rebuilt from remarks: {', '.join(sorted(discovered))}"
                )
                # Look up a human-readable name for each discovered code via
                # a targeted web search (one search per code, cached in-process).
                new_legend: dict[str, dict] = {}
                for code in sorted(discovered):
                    code_name = self._search_colour_code_name(code)
                    new_legend[code] = {
                        "abbreviation": code,
                        "name": code_name,
                        "code": "",
                        "is_model_colour": True,
                    }
                colour_legend = new_legend
                colour_abbrs = set(colour_legend.keys())
            else:
                logger.warning(
                    f"{pdf_path.name}: colour legend garbage and no 'FOR XYZ' "
                    f"codes found in remarks — no colour builds possible"
                )
                warnings = list(result.warnings)
                warnings.append(
                    "Colour table extraction failed and remarks contain no colour codes."
                )
                colour_legend = {}
                colour_abbrs = set()
        else:
            warnings = list(result.warnings)

        if not colour_codes and not colour_abbrs:
            warnings.append("No colour table found in foreword; colour builds unavailable.")

        if _variant_synthesised:
            warnings.append(
                "No variant code found in PDF; all parts indexed under a single unnamed variant."
            )

        # ── Stage 3 ── colour roster per variant ───────────────────────
        rosters = self._build_rosters(rows, variants, colour_abbrs)

        # ── Colour validation ── check for orphaned/inconsistent colours ─
        self._check_orphaned_colours(colour_legend, rosters, variants, warnings)

        # ── Roster validation ── check completeness and correctness ─────
        self._validate_rosters(rosters, variants, colour_legend, warnings)

        # ── Stage 5 ── assemble builds ─────────────────────────────────
        builds = self._assemble_builds(rows, variants, colour_legend, rosters, colour_abbrs)

        # ── Stage 4 ── web validation + external-parts check ───────────
        # If the PDF has an "AVAILABLE COLOUR" page, use those captions as the
        # reference colour-name list (no web search needed).
        pdf_available_colours = result.available_colours or []
        if pdf_available_colours:
            web_colour_names = pdf_available_colours
            logger.info(
                f"{pdf_path.name}: using {len(web_colour_names)} colour(s) "
                f"from PDF available-colour page"
            )
        else:
            web_colour_names = self._search_web_colours(result.model, result.manufacture_year)
            if not web_colour_names:
                warnings.append("Web colour search returned no results; showing all PDF colours.")
                logger.warning(f"{pdf_path.name}: web colour search empty")
            else:
                logger.info(f"{pdf_path.name}: web found {len(web_colour_names)} colour name(s)")

        # Which colour abbreviations have ≥1 external (colour_specific) part
        colours_with_external: set[str] = {
            b.colour for b in builds if any(p.kind == "colour_specific" for p in b.parts)
        }

        # Annotate the colour legend with web_confirmed + has_external_parts
        validated_colours: list[str] = []
        for abbr, entry in colour_legend.items():
            pdf_name = entry.get("name", "")
            web_ok = not web_colour_names or self._web_confirms_colour(pdf_name, web_colour_names)
            ext_ok = abbr in colours_with_external
            colour_legend[abbr] = {
                **entry,
                "web_confirmed": web_ok,
                "has_external_parts": ext_ok,
            }
            if web_ok and ext_ok:
                validated_colours.append(abbr)

        # ── Server-side available-colour → abbreviation mapping ─────────
        available_colour_map: dict[str, str] = {}
        if pdf_available_colours and colour_legend:
            available_colour_map = self._map_available_colours_to_abbrs(
                pdf_available_colours, colour_legend
            )
            logger.info(f"{pdf_path.name}: available-colour map: {available_colour_map}")

        # ── variant_colour_map: ordered colour list per variant ──────────
        # Preserves foreword colour-table order so the UI tabs match PDF order.
        abbr_order: dict[str, int] = {
            c["abbreviation"].upper(): i for i, c in enumerate(colour_codes)
        }

        # Model colours from foreword (those marked with (*))
        model_colour_list: list[dict] = [c for c in colour_codes if c.get("is_model_colour")]
        num_variants = len(variants)

        # Determine if all variants share identical roster sets.
        # When they do the roster cannot differentiate which colours belong to
        # which variant — fall back to cyclic distribution of the foreword's
        # model colours (Yamaha lists them in cyclic order: var0-col0, var1-col0,
        # …, varN-col0, var0-col1, var1-col1, …).
        roster_frozen = {v: frozenset(cs) for v, cs in rosters.items()}
        rosters_differ = len(set(roster_frozen.values())) > 1

        variant_colour_map: dict[str, list[dict]] = {}
        variant_colour_source: str = "fallback"

        if num_variants == 1:
            # Single-variant PDF — cyclic distribution is meaningless with one variant.
            # Use every colour seen in remarks (roster), ordered by foreword table.
            # Colours absent from remarks but present in colour_legend are still
            # surfaced via the frontend colour_legend merge (they are universal parts).
            only_v = variants[0]
            roster_abbrs = sorted(rosters.get(only_v, set()), key=lambda a: abbr_order.get(a, 999))
            variant_colour_map[only_v] = [
                {
                    "abbreviation": abbr,
                    "name": colour_legend.get(abbr, {}).get("name", abbr),
                    "code": colour_legend.get(abbr, {}).get("code", ""),
                    "is_model_colour": colour_legend.get(abbr, {}).get("is_model_colour", False),
                }
                for abbr in roster_abbrs
                if abbr in colour_legend
            ]
            variant_colour_source = "roster"
        elif rosters_differ:
            # Variants have distinct colour sets in remarks → use roster directly.
            for v, roster_set in rosters.items():
                ordered = sorted(roster_set, key=lambda a: abbr_order.get(a, 999))
                variant_colour_map[v] = [
                    {
                        "abbreviation": abbr,
                        "name": colour_legend.get(abbr, {}).get("name", abbr),
                        "code": colour_legend.get(abbr, {}).get("code", ""),
                        "is_model_colour": colour_legend.get(abbr, {}).get(
                            "is_model_colour", False
                        ),
                    }
                    for abbr in ordered
                    if abbr in colour_legend
                ]
            variant_colour_source = "roster"
        elif model_colour_list and num_variants > 0 and len(model_colour_list) % num_variants == 0:
            # All variants share the same roster (remarks-based colours can't
            # differentiate them) AND the foreword model-colour count divides
            # evenly by the variant count.  Apply cyclic distribution: each
            # variant gets every N-th model colour starting at its own index.
            for idx, variant in enumerate(variants):
                variant_colour_map[variant] = [
                    {
                        "abbreviation": model_colour_list[j]["abbreviation"],
                        "name": model_colour_list[j]["name"],
                        "code": model_colour_list[j]["code"],
                        "is_model_colour": True,
                    }
                    for j in range(idx, len(model_colour_list), num_variants)
                ]
            variant_colour_source = "cyclic"
        else:
            # Cyclic distribution failed — try web search per variant code.
            if result.model and variants and colour_legend:
                web_map = self._enrich_variant_colours_via_web(
                    result.model, result.manufacture_year, variants, colour_legend
                )
            else:
                web_map = None

            if web_map and any(web_map.values()):
                for v in variants:
                    abbrs = web_map.get(v, [])
                    variant_colour_map[v] = [
                        {
                            "abbreviation": abbr,
                            "name": colour_legend.get(abbr, {}).get("name", abbr),
                            "code": colour_legend.get(abbr, {}).get("code", ""),
                            "is_model_colour": colour_legend.get(abbr, {}).get(
                                "is_model_colour", False
                            ),
                        }
                        for abbr in abbrs
                        if abbr in colour_legend
                    ]
                variant_colour_source = "web"
                warnings.append(
                    "Colour variant assignment determined by web search "
                    "(PDF data insufficient for cyclic distribution)."
                )
            else:
                # Final fallback: show all known colours for every variant.
                all_abbrs = sorted(colour_legend.keys(), key=lambda a: abbr_order.get(a, 999))
                fallback_colours = [
                    {
                        "abbreviation": abbr,
                        "name": colour_legend[abbr].get("name", abbr),
                        "code": colour_legend[abbr].get("code", ""),
                        "is_model_colour": colour_legend[abbr].get("is_model_colour", False),
                    }
                    for abbr in all_abbrs
                ]
                for v in variants:
                    variant_colour_map[v] = fallback_colours
                variant_colour_source = "fallback"

        logger.info(
            f"{pdf_path.name}: variant_colour_map keys={list(variant_colour_map)} "
            f"sizes={[len(v) for v in variant_colour_map.values()]} "
            f"source={variant_colour_source} rosters_differ={rosters_differ} "
            f"model_colours={len(model_colour_list)}"
        )

        # ── Colour-changing parts: same ref_no, ≥2 colour-specific versions ──
        colour_changing_parts = self._identify_colour_changing_parts(rows, colour_abbrs)
        logger.info(f"{pdf_path.name}: {len(colour_changing_parts)} colour-changing part(s)")

        return AgentResult(
            source_pdf=pdf_path.name,
            extracted_at=datetime.now(tz=UTC).isoformat(),
            model=result.model,
            model_no=result.model_no,
            manufacture_year=result.manufacture_year,
            variants=variants,
            colour_legend=colour_legend,
            rosters={v: list(cs) for v, cs in rosters.items()},
            builds=builds,
            validated_colours=validated_colours,
            web_colour_names=web_colour_names,
            warnings=warnings,
            available_colour_map=available_colour_map,
            variant_colour_map=variant_colour_map,
            variant_colour_source=variant_colour_source,
            colour_changing_parts=colour_changing_parts,
        )

    # ------------------------------------------------------------------
    # Stage 3 — colour roster per variant
    # ------------------------------------------------------------------

    def _build_rosters(
        self,
        rows: list[dict],
        variants: list[str],
        colour_abbrs: set[str],
    ) -> dict[str, set[str]]:
        """Return {variant_code: set(colour_abbrs)}: which colours each model comes in.

        Business meaning: a multimodal catalogue covers several model variants at once
        and prices every part per variant, so which colours belong to *which* model has
        to be read out of the quantity columns, not just the remark.

        Two passes, because a row that names one model is evidence and a row that names
        several is not:

        1. A row whose quantity lands on exactly **one** variant proves that variant
           comes in the colours its remark names. A side cover carrying ``UR FOR RSH``
           with quantity only under B65J says B65J is built in RSH.
        2. A row spanning **several** variants is then distributed rather than copied:
           each colour goes to the variant pass 1 already showed holds it. Only a colour
           nothing has claimed falls back to position — Yamaha lists colours in the same
           order as the quantity columns, so ``FOR YB,MS1`` over two live variants pairs
           the first with the first.

        Copying every named colour onto every live variant, which is what this used to
        do, inflates the rosters badly: on AEROX it gave B65J six colours and B65N five,
        where the catalogue actually has three and one.
        """
        rosters: dict[str, set[str]] = {v: set() for v in variants}
        num_v = len(variants)

        def live_variants(qty_raw: str) -> list[str]:
            """Variants this row is actually priced for."""
            out = []
            for idx, variant in enumerate(variants):
                v_qty = _variant_qty(qty_raw, idx, num_v) if num_v > 1 else qty_raw
                if _has_qty(v_qty):
                    out.append(variant)
            return out

        # Colours each row names, in the order the catalogue lists them.
        claims: list[tuple[list[str], list[str]]] = []
        for row in rows:
            qty_raw = row.get("qty", "") or ""

            # Desc-colour PDFs: colour membership is stored in colour_hint (the
            # extractor found colours in description parentheses and left the
            # description and remarks unchanged). It may be comma-separated, e.g.
            # "BWC1,SMX" produced by the EXCEPT complement logic.
            hint = (row.get("colour_hint") or "").upper()
            named = [t for t in (t.strip() for t in hint.split(",")) if t in colour_abbrs]

            if not named:
                appl = parse_applicability(row.get("remarks", "") or "", colour_abbrs)
                if appl.is_universal:
                    continue  # shared row — says nothing about which colours exist
                if appl.is_except_mode:
                    # "EXCEPT C" names what the part is *not* for. The full colour set
                    # is not known yet, so it contributes no positive evidence here;
                    # the complement is resolved once the rosters are built.
                    continue
                named = [c for c in appl.ordered if c in colour_abbrs]

            live = live_variants(qty_raw)
            if named and live:
                claims.append((live, named))

        # Pass 1 — rows that name a single variant.
        for live, named in claims:
            if len(live) == 1:
                rosters[live[0]].update(named)

        confirmed = {v: set(cs) for v, cs in rosters.items()}

        # Pass 2 — distribute the rows that span several variants.
        for live, named in claims:
            if len(live) < 2:
                continue
            unplaced: list[str] = []
            for colour in named:
                holders = [v for v in live if colour in confirmed[v]]
                if holders:
                    for variant in holders:
                        rosters[variant].add(colour)
                else:
                    unplaced.append(colour)
            for position, colour in enumerate(unplaced):
                if position < len(live):
                    rosters[live[position]].add(colour)

        return rosters

    # ------------------------------------------------------------------
    # Stage 5 — assemble complete builds per (variant, colour)
    # ------------------------------------------------------------------

    def _assemble_builds(
        self,
        rows: list[dict],
        variants: list[str],
        colour_legend: dict[str, dict],
        rosters: dict[str, set[str]],
        colour_abbrs: set[str],
    ) -> list[VariantBuild]:
        """Build complete parts list per (variant, colour).

        For each variant, for each colour in that variant's roster:
        1. Shared parts     — rows where the variant has qty and no colour code
                              in remarks → always included.
        2. Colour-specific  — rows where remarks resolves to include THIS colour.
        3. Dedup by REF.NO  — when several rows share one ref_no (same balloon
                              number, different colour options) pick exactly the
                              one matching the selected colour.
        """
        num_v = len(variants)
        builds: list[VariantBuild] = []

        for idx, variant in enumerate(variants):
            colours = rosters.get(variant, set())
            if not colours:
                # Roster empty — remarks either absent or use column codes rather
                # than colour abbreviations.  Build a single _ALL catalogue so the
                # user still gets the complete shared parts list for this variant.
                colours = {"_ALL"}

            for colour in sorted(colours):
                legend_entry = colour_legend.get(colour, {})
                colour_name = legend_entry.get("name", colour)
                colour_code = legend_entry.get("code", "")

                parts: list[PartRow] = []
                # Track ref_no → list[PartRow] for dedup
                by_ref: dict[str, list[PartRow]] = {}

                for row in rows:
                    qty_raw = row.get("qty", "") or ""
                    v_qty = _variant_qty(qty_raw, idx, num_v) if num_v > 1 else qty_raw
                    if not _has_qty(v_qty):
                        continue  # this variant has no qty for this row

                    # Desc-colour PDFs: membership comes from colour_hint, not remarks.
                    # colour_hint may be comma-separated (e.g. "BWC1,SMX" from
                    # EXCEPT complement) — split and check membership.
                    hint = (row.get("colour_hint") or "").upper()
                    hint_tokens = (
                        {t.strip() for t in hint.split(",") if t.strip() in colour_abbrs}
                        if hint
                        else set()
                    )
                    if hint_tokens:
                        kind = "colour_specific"
                        matches = colour == "_ALL" or colour in hint_tokens
                    else:
                        remarks = row.get("remarks", "") or ""
                        appl = parse_applicability(remarks, colour_abbrs)

                        if colour == "_ALL" or appl.is_universal:
                            kind = "shared"
                            matches = True
                        else:
                            kind = "colour_specific"
                            matches = appl.matches(colour)

                    if not matches:
                        continue

                    pr = PartRow(
                        figure=row.get("section", "") or "",
                        ref_no=row.get("ref_no", "") or "",
                        part_no=row.get("part_no", "") or "",
                        description=row.get("description", "") or "",
                        qty=v_qty,
                        remarks=remarks,
                        kind=kind,
                    )

                    # Key by (section, ref_no) so colour-specific parts from
                    # different sections with the same ref number (FENDER ref=1,
                    # FUEL TANK ref=1 etc.) are never collapsed together.
                    ref = (pr.figure, pr.ref_no) if pr.ref_no else pr.part_no
                    by_ref.setdefault(ref, []).append(pr)

                # Dedup: for rows that share a ref_no, prefer colour_specific
                # over shared; among colour_specific rows pick the one that
                # exactly matches (already filtered above, so all are valid).
                seen_refs: set[str] = set()
                for ref, candidates in by_ref.items():
                    # Prefer colour_specific over shared if both exist
                    specific = [p for p in candidates if p.kind == "colour_specific"]
                    chosen = specific[0] if specific else candidates[0]
                    parts.append(chosen)
                    seen_refs.add(ref)

                builds.append(
                    VariantBuild(
                        variant=variant,
                        colour=colour if colour != "_ALL" else "",
                        colour_name=colour_name if colour != "_ALL" else "All colours",
                        colour_code=colour_code,
                        part_count=len(parts),
                        parts=parts,
                    )
                )

        return builds

    # ------------------------------------------------------------------
    # Server-side available-colour → abbreviation mapping
    # ------------------------------------------------------------------

    def _map_available_colours_to_abbrs(
        self,
        available_colours: list[str],
        colour_legend: dict[str, dict],
    ) -> dict[str, str]:
        """Map each available-colour caption to the best-matching colour abbreviation.

        Uses normalised word-overlap between the caption and the legend colour
        name, expanded with colour synonyms so semantic neighbours match
        (e.g. "Gold" → "LIGHT YELLOWISH GRAY ME 9" via "yellowish"↔"gold").

        Dynamic thresholds based on caption length:
        - Single-word captions: 0.15 threshold
          (short captions like "Black" match "BLACK METALLIC X")
        - Multi-word captions: 0.50 threshold (avoid spurious matches)
        - Captions >5 words: rejected as likely foreword text, not captions

        Returns:
            dict mapping caption (e.g. "Matt Grey") → abbreviation (e.g. "MNM3").
            Entries are omitted when no match exceeds the dynamic threshold.

        Also returns available_colour_match_scores: dict[str, float] for debugging.
        """
        if not available_colours or not colour_legend:
            return {}

        model_abbrs = [
            abbr for abbr, entry in colour_legend.items() if entry.get("is_model_colour", True)
        ]
        if not model_abbrs:
            model_abbrs = list(colour_legend.keys())

        # Pre-normalize and expand all legend names (done once, reused for all captions)
        legend_words_expanded: dict[str, set[str]] = {}
        for abbr in model_abbrs:
            legend_name = colour_legend[abbr].get("name", "")
            legend_words = _norm_colour_words(legend_name)
            legend_words_expanded[abbr] = _expand_colour_words(legend_words)

        # Score every (caption, abbreviation) pair
        scores: list[tuple[float, str, str]] = []
        for caption in available_colours:
            # Reject very long captions (likely foreword text, not image captions)
            caption_words_count = len(caption.split())
            if caption_words_count > 5:
                logger.debug(f"Skipping long caption: {caption!r} ({caption_words_count} words)")
                continue

            avail_words = _expand_colour_words(_norm_colour_words(caption))
            if not avail_words:
                logger.debug(f"Caption {caption!r} has no colour words after normalization")
                continue

            # Dynamic threshold based on caption length
            threshold = 0.15 if caption_words_count == 1 else 0.50

            for abbr in model_abbrs:
                legend_words = legend_words_expanded[abbr]
                if not legend_words:
                    continue

                overlap = avail_words & legend_words
                # Score relative to the shorter word set → short captions like
                # "Cyan" score high against "CYAN METALLIC 6" (1/1 min).
                score = len(overlap) / min(len(avail_words), len(legend_words))
                if score >= threshold:
                    scores.append((score, caption, abbr))

        # Bipartite matching: highest scores first, but avoid greedy early-binding
        # Use a more sophisticated assignment to avoid forcing poor matches
        scores.sort(key=lambda t: t[0], reverse=True)

        result: dict[str, str] = {}
        used_captions: set[str] = set()
        used_abbrs: set[str] = set()
        unmatched_captions: list[str] = []

        for score, caption, abbr in scores:
            if caption not in used_captions and abbr not in used_abbrs:
                result[caption] = abbr
                logger.debug(f"Matched caption {caption!r} → {abbr} (score={score:.2f})")
                used_captions.add(caption)
                used_abbrs.add(abbr)
            elif caption not in used_captions:
                # Caption not yet matched, but this abbr is taken
                # Could improve with Hungarian algorithm, but greedy works for most cases
                pass

        # Track unmatched captions for warning
        for caption in available_colours:
            if caption not in result:
                unmatched_captions.append(caption)
                logger.warning(f"Colour caption not matched: {caption!r}")

        # Store match scores on self for later use in API response (if implemented)
        if unmatched_captions and len(available_colours) > 0:
            unmapped_pct = len(unmatched_captions) / len(available_colours)
            if unmapped_pct > 0.2:
                logger.warning(
                    f"High unmapped colour rate: "
                    f"{len(unmatched_captions)}/{len(available_colours)} "
                    f"({unmapped_pct:.1%}) captions could not be matched"
                )

        # Store match data on instance for debugging (optional)
        self._last_colour_matches: dict[str, dict] = {}
        for caption in available_colours:
            if caption in result:
                # Look up the best score for this caption
                best_score = next(
                    (s for s, c, a in scores if c == caption and a == result[caption]), 0.0
                )
                self._last_colour_matches[caption] = {
                    "abbr": result[caption],
                    "score": best_score,
                }
            else:
                self._last_colour_matches[caption] = {
                    "abbr": None,
                    "score": 0.0,
                }

        return result

    # ------------------------------------------------------------------
    # Colour-code name lookup (supplemental web search for discovered codes)
    # ------------------------------------------------------------------

    def _search_colour_code_name(self, code: str) -> str:
        """Look up a Yamaha colour abbreviation (e.g. "SMX") → human-readable name.

        Priority:
          1. Cross-PDF colour code cache (seeded with known codes + accumulated from
             all successfully extracted colour tables in this session/file).
          2. Web search as a last resort.

        Returns the code itself when no name can be established.
        """
        # 1. Cache lookup (cheap, reliable)
        cache = _load_colour_cache()
        if code in cache:
            name = cache[code]
            logger.debug(f"Colour code {code!r} → {name!r} (from cache)")
            return name

        # 2. Web search (slow, may be wrong — last resort)
        q = urllib.parse.urlencode({"q": f'Yamaha "{code}" colour paint motorcycle', "ia": "web"})
        url = f"https://html.duckduckgo.com/html/?{q}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Colour code name lookup failed for {code!r}: {exc}")
            return code

        text = re.sub(r"<[^>]+>", " ", html)
        names = self._extract_colour_names_from_text(text)
        for name in names[:8]:
            words_lower = [w.lower() for w in name.split()]
            if any(w in _WEB_COLOUR_NOUNS for w in words_lower):
                logger.debug(f"Colour code {code!r} → {name!r} (from web)")
                # Persist to cache for next time
                cache[code] = name
                _update_colour_cache({code: {"name": name}})
                return name

        logger.debug(f"Colour code {code!r}: no name found, using code as name")
        return code

    # ------------------------------------------------------------------
    # Web colour validation helpers
    # ------------------------------------------------------------------

    def _search_web_colours(self, model: str, year: str | None) -> list[str]:
        """DuckDuckGo HTML search → colour names mentioned for this model/year.

        Uses only stdlib (urllib) — no external dependencies.
        Returns a list of candidate colour-name strings (may be empty if the
        request fails or no colour phrases are found).
        """
        query_parts = [model, "color", "colour", "variant"]
        if year:
            query_parts.insert(1, year)
        q = urllib.parse.urlencode({"q": " ".join(query_parts), "ia": "web"})
        url = f"https://html.duckduckgo.com/html/?{q}"

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Web colour search failed for {model!r}: {exc}")
            return []

        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        return self._extract_colour_names_from_text(text)

    @staticmethod
    def _extract_colour_names_from_text(text: str) -> list[str]:
        """Extract colour-name phrases from a block of text.

        A phrase qualifies when it contains at least one word from
        _WEB_COLOUR_NOUNS (with optional _WEB_COLOUR_MODIFIERS).
        Returns deduplicated names in discovery order.
        """
        seen: set[str] = set()
        results: list[str] = []
        for m in _WEB_PHRASE_PAT.finditer(text):
            phrase = m.group(1).strip()
            words_lower = [w.lower() for w in re.split(r"[\s\-]+", phrase)]
            # Must contain at least one colour noun
            if not any(w in _WEB_COLOUR_NOUNS for w in words_lower):
                continue
            # All words must be colour nouns, modifiers, or short (≤2 char) tokens
            meaningful = [w for w in words_lower if w not in _NORM_STOP and len(w) > 2]
            if not meaningful:
                continue
            key = phrase.lower()
            if key not in seen:
                seen.add(key)
                results.append(phrase)
        return results

    # ------------------------------------------------------------------
    # Variant colour enrichment via web search (fallback path)
    # ------------------------------------------------------------------

    def _enrich_variant_colours_via_web(
        self,
        model: str,
        year: str | None,
        variants: list[str],
        colour_legend: dict[str, dict],
    ) -> dict[str, list[str]] | None:
        """Search the web for each variant code to find its colour assignment.

        For every variant code (e.g. "B65J") performs a targeted DuckDuckGo
        search: ``"B65J" Aerox 2024 colour``.  Colour-name phrases found in the
        results are matched back to the foreword legend via word-overlap.

        Returns dict[variant_code → list[colour_abbreviation]] when at least
        one variant yields a match, otherwise None.
        """
        result: dict[str, list[str]] = {}

        for variant in variants:
            query_parts = [f'"{variant}"', model, "colour"]
            if year:
                query_parts.append(year)
            q = urllib.parse.urlencode({"q": " ".join(query_parts), "ia": "web"})
            url = f"https://html.duckduckgo.com/html/?{q}"

            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
                    html = resp.read().decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Variant colour web search failed for {variant!r}: {exc}")
                continue

            text = re.sub(r"<[^>]+>", " ", html)
            colour_names = self._extract_colour_names_from_text(text)

            # Match each found colour name to the closest legend abbreviation
            matched: list[str] = []
            for name in colour_names[:30]:
                name_words = _expand_colour_words(_norm_colour_words(name))
                if not name_words:
                    continue
                best_score = 0.0
                best_abbr: str | None = None
                for abbr, entry in colour_legend.items():
                    legend_words = _norm_colour_words(entry.get("name", ""))
                    if not legend_words:
                        continue
                    overlap = len(name_words & legend_words)
                    score = overlap / len(legend_words)
                    if score > best_score and score >= 0.4:
                        best_score = score
                        best_abbr = abbr
                if best_abbr and best_abbr not in matched:
                    matched.append(best_abbr)

            if matched:
                result[variant] = matched
                logger.info(
                    f"Variant {variant!r}: web-matched colours {matched} "
                    f"(model={model!r} year={year!r})"
                )
            else:
                logger.debug(f"Variant {variant!r}: no colour match from web search")

        return result if any(result.values()) else None

    # ------------------------------------------------------------------
    # Colour validation — orphaned and inconsistent colours
    # ------------------------------------------------------------------

    def _check_orphaned_colours(
        self,
        colour_legend: dict[str, dict],
        rosters: dict[str, set[str]],
        variants: list[str],
        warnings: list[str],
    ) -> None:
        """Check for orphaned colours and roster inconsistencies.

        Detects:
        1. Colours in legend but never appear in any variant's roster
        2. Rosters with inconsistent colour counts across variants
        3. Colour count mismatches

        Updates warnings list in-place.
        """
        if not colour_legend or not variants:
            return

        # Collect all colours used across all variants
        all_roster_colours: set[str] = set()
        for variant in variants:
            all_roster_colours.update(rosters.get(variant, set()))

        # Colours in legend but not in any roster (orphaned)
        legend_abbrs = set(colour_legend.keys())
        orphaned = legend_abbrs - all_roster_colours
        if orphaned:
            orphaned_list = ", ".join(sorted(orphaned))
            warnings.append(
                f"Orphaned colours in legend (not in parts): {orphaned_list}. "
                f"These may be special-order or discontinued colours."
            )
            logger.warning(f"Orphaned colours detected: {orphaned} not found in remarks/rosters")

        # Roster consistency check: variant colour counts should be similar
        if variants and len(variants) > 1:
            roster_sizes = [len(rosters.get(v, set())) for v in variants]
            if roster_sizes:
                avg_size = sum(roster_sizes) / len(roster_sizes)
                max_size = max(roster_sizes)
                # Flag if one variant has significantly more colours (>50% difference)
                if max_size > 0 and (max_size - avg_size) / avg_size > 0.5:
                    warnings.append(
                        f"Variant colour rosters inconsistent: sizes={roster_sizes}. "
                        f"May indicate incomplete remarks or multi-region variants."
                    )
                    logger.warning(
                        f"Roster inconsistency: variant colour counts {roster_sizes} "
                        f"differ significantly (avg={avg_size:.1f})"
                    )

    def _validate_rosters(
        self,
        rosters: dict[str, set[str]],
        variants: list[str],
        colour_legend: dict[str, dict],
        warnings: list[str],
    ) -> None:
        """Validate colour rosters for reasonableness and completeness.

        Checks:
        1. Empty rosters (no colours detected for variant)
        2. Roster size consistency
        3. All colours in rosters exist in legend

        Updates warnings list in-place.
        """
        if not variants or not rosters:
            return

        # Check for empty rosters
        empty_variants = [v for v in variants if not rosters.get(v, set())]
        if empty_variants:
            warnings.append(
                f"No colours detected for variant(s): {', '.join(empty_variants)}. "
                f"Remarks may be incomplete or remarks grammar not matching legend codes."
            )
            logger.warning(f"Empty rosters for variants: {empty_variants}")

        # Check for colours in roster that don't exist in legend
        legend_abbrs = set(colour_legend.keys())
        for variant, colours in rosters.items():
            unknown = colours - legend_abbrs
            if unknown:
                unknown_list = ", ".join(sorted(unknown))
                warnings.append(
                    f"Variant {variant} has unknown colour codes not in legend: {unknown_list}. "
                    f"May indicate typos in remarks or legend extraction failure."
                )
                logger.warning(f"Unknown colour codes in roster {variant}: {unknown}")

    # ------------------------------------------------------------------
    # Colour-changing parts identification (PDF-data only)
    # ------------------------------------------------------------------

    def _identify_colour_changing_parts(
        self,
        rows: list[dict],
        colour_abbrs: set[str],
    ) -> list[dict]:
        """Find parts whose part number varies by colour.

        Scans all rows for entries that share the same ref_no but carry
        different colour-applicability restrictions in their remarks.  These
        are the physical parts (body panels, seat covers, etc.) that need to
        be ordered in the bike's specific colour.

        Returns:
            List of dicts sorted by section then ref_no.  Each entry:
                {section, ref_no, description, per_colour: {abbr: part_no}}
            Only entries with ≥2 distinct colour→part_no pairs are included.
        """
        # Group colour-specific rows by ref_no
        by_ref: dict[str, list[dict]] = {}
        for row in rows:
            ref = (row.get("ref_no", "") or "").strip()
            if not ref:
                continue
            hint = (row.get("colour_hint") or "").upper()
            hint_tokens_fc = (
                {t.strip() for t in hint.split(",") if t.strip() in colour_abbrs} if hint else set()
            )
            if hint_tokens_fc:
                by_ref.setdefault(ref, []).append(row)
                continue
            remarks = row.get("remarks", "") or ""
            appl = parse_applicability(remarks, colour_abbrs)
            if not appl.is_universal and appl.applies_to:
                by_ref.setdefault(ref, []).append(row)

        colour_parts: list[dict] = []
        for ref, ref_rows in by_ref.items():
            per_colour: dict[str, str] = {}
            for row in ref_rows:
                hint = (row.get("colour_hint") or "").upper()
                hint_tokens_fc = (
                    {t.strip() for t in hint.split(",") if t.strip() in colour_abbrs}
                    if hint
                    else set()
                )
                if hint_tokens_fc:
                    pn = row.get("part_no", "")
                    for tok in hint_tokens_fc:
                        per_colour[tok] = pn
                    continue
                remarks = row.get("remarks", "") or ""
                appl = parse_applicability(remarks, colour_abbrs)
                part_no = (row.get("part_no", "") or "").strip()
                for abbr in appl.applies_to:
                    if abbr not in per_colour:
                        per_colour[abbr] = part_no

            # Only include when part_no actually differs across colours
            unique_part_nos = set(per_colour.values())
            if len(per_colour) >= 2 and len(unique_part_nos) >= 2:
                first = ref_rows[0]
                colour_parts.append(
                    {
                        "section": (first.get("section", "") or "").strip(),
                        "ref_no": ref,
                        "description": (first.get("description", "") or "").strip(),
                        "per_colour": per_colour,
                    }
                )

        # Sort by section then ref_no for stable display
        colour_parts.sort(key=lambda e: (e["section"], e["ref_no"]))
        return colour_parts

    @staticmethod
    def _web_confirms_colour(pdf_colour_name: str, web_names: list[str]) -> bool:
        """Return True if the PDF colour name overlaps sufficiently with any web name.

        Uses normalised word-overlap (grey↔gray, mat/matt) plus synonym expansion
        so "MAT GRAY METALLIC 3" confirms against "Matt Grey" correctly.
        ≥40% of the PDF colour's meaningful words must appear in a web name.
        """
        if not web_names:
            return True

        pdf_words = _expand_colour_words(_norm_colour_words(pdf_colour_name))
        if not pdf_words:
            return True

        for web_name in web_names:
            web_words = _expand_colour_words(_norm_colour_words(web_name))
            overlap = pdf_words & web_words
            ratio = len(overlap) / len(pdf_words)
            if ratio >= 0.40:
                return True
        return False


# ---------------------------------------------------------------------------
# Cross-model compatibility — new classes
# ---------------------------------------------------------------------------

# Yamaha part-number patterns (mirrors pdf_catalogue_extractor.py constants)
_PART_NO_PAT = re.compile(
    r"\b([A-Z0-9]{2,4}-[A-Z0-9]{4,6}-\d{2}(?:-[A-Z0-9]{2})?|"  # 3- or 4-part
    r"\d{5}-\d{5}|"  # 2-part numeric
    r"[A-Z0-9]{10,12})\b"  # no-dash long
)


@dataclass
class ModelCompatibilityResult:
    """One deduped part with every model it appears in."""

    part_no: str
    description: str
    compatible_models: list[str]
    model_years: dict[str, str]  # model → manufacture_year (may be empty string)
    source_catalogs: list[str]  # PDF filenames


class LLMFallbackExtractor:
    """Claude-powered extractor for PDFs below the word-position yield threshold.

    Business meaning: some Yamaha PDFs (image-based or unusual layouts) produce
    very few rows via the word-position clusterer.  This class sends the raw page
    text to Claude and asks it to parse part_no + description directly, using the
    same Yamaha part-number grammar the extractor knows.
    """

    # Rows-per-page ratio below which LLM fallback is triggered
    YIELD_THRESHOLD: float = 0.70

    _SYSTEM = (
        "You are a Yamaha spare-parts catalogue parser. "
        "Extract every spare part row from the catalogue page text provided. "
        "Return ONLY a JSON array — no prose, no markdown fences. "
        "Each element must have exactly two string fields: "
        '{"part_no": "...", "description": "..."}. '
        "Skip rows with no recognisable Yamaha part number. "
        "Part numbers look like: 5HK-14147-00, 2FS-E1111-10, 93210-29800, 2LPWE11100."
    )

    def __init__(self, llm_model: str = "claude-sonnet-4-6") -> None:
        self._llm_model = llm_model
        self._client: Any = None  # lazy-init on first use

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic  # noqa: PLC0415

            self._client = anthropic.Anthropic()
        except ImportError:
            raise RuntimeError("anthropic package not installed — run: uv add anthropic") from None
        return self._client

    def extract(self, pdf_path: Path, model_name: str) -> list[dict[str, str]]:
        """Return [{part_no, description}] extracted by Claude from all PDF pages."""
        import pdfplumber  # noqa: PLC0415

        rows: list[dict[str, str]] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    if len(text.strip()) < 30:
                        continue
                    page_rows = self._extract_page(text, page_num + 1, pdf_path.name)
                    rows.extend(page_rows)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"LLMFallbackExtractor: failed to open {pdf_path.name}: {exc}")
        logger.info(
            f"LLMFallbackExtractor [{model_name}] {pdf_path.name}: {len(rows)} rows via Claude"
        )
        return rows

    def _extract_page(self, text: str, page_num: int, filename: str) -> list[dict[str, str]]:
        client = self._get_client()
        # Truncate very long pages to avoid token overflow
        page_text = text[:4000]
        try:
            msg = client.messages.create(
                model=self._llm_model,
                max_tokens=2048,
                system=self._SYSTEM,
                messages=[{"role": "user", "content": page_text}],
            )
            raw = msg.content[0].text.strip()
            # Strip accidental markdown fences
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            result = []
            for item in data:
                pn = str(item.get("part_no", "")).strip()
                desc = str(item.get("description", "")).strip()
                if pn and _PART_NO_PAT.match(pn):
                    result.append({"part_no": pn, "description": desc})
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"LLMFallbackExtractor: page {page_num} of {filename} failed: {exc}")
            return []


class CrossModelCompatibilityAgent:
    """Batch agent: extract every PDF, roll up part_no → compatible models + years.

    Business meaning: a spare part may appear in multiple Yamaha models.  This
    agent processes every PDF catalogue under a root folder, merges the results
    by part_no, and produces a single lookup table so procurement can identify
    which models share a part.

    Usage::

        agent = CrossModelCompatibilityAgent()
        df = agent.run_all(Path("data/raw/pdf_catalogues"))
        agent.save(df, _browser_dir() / "model_compatibility.xlsx")
    """

    def __init__(
        self,
        max_pages: int = 500,
        llm_model: str = "claude-sonnet-4-6",
        yield_threshold: float = LLMFallbackExtractor.YIELD_THRESHOLD,
    ) -> None:
        self._extractor = YamahaCatalogueExtractor(max_pages=max_pages)
        self._llm = LLMFallbackExtractor(llm_model=llm_model)
        self._threshold = yield_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(
        self,
        pdf_root: Path,
        max_workers: int = 4,
    ) -> pd.DataFrame:
        """Process every PDF under pdf_root and return the compatibility table.

        Returns:
            DataFrame with columns:
                part_no, description, compatible_models (list),
                model_years (dict[model→year]), source_catalogs (list)
        """
        pdf_files = sorted(
            {f for f in pdf_root.rglob("*") if f.suffix.lower() == ".pdf"},
            key=lambda p: (p.parent.name.upper(), p.name.upper()),
        )
        if not pdf_files:
            logger.warning(f"CrossModelCompatibilityAgent: no PDFs found under {pdf_root}")
            return self._empty_df()

        logger.info(
            f"CrossModelCompatibilityAgent: {len(pdf_files)} PDFs, "
            f"{max_workers} workers, threshold={self._threshold:.0%}"
        )

        records: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self._process_one, f): f for f in pdf_files}
            for future in as_completed(futures):
                pdf_file = futures[future]
                try:
                    records.extend(future.result())
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        f"CrossModelCompatibilityAgent: unhandled error for {pdf_file.name}: {exc}"
                    )

        logger.info(f"CrossModelCompatibilityAgent: {len(records)} total rows — rolling up")
        return self._rollup(records)

    def save(self, df: pd.DataFrame, out_path: Path) -> None:
        """Write compatibility table to Excel (+ sibling .parquet).

        The Excel sheet has list/dict columns flattened to comma-separated strings
        for readability.  The parquet retains native Python types for downstream use.
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Excel — flatten collections to strings
        excel_df = df.copy()
        excel_df["compatible_models"] = excel_df["compatible_models"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else str(x)
        )
        excel_df["model_years"] = excel_df["model_years"].apply(
            lambda x: (
                "; ".join(f"{m}: {y}" for m, y in x.items()) if isinstance(x, dict) else str(x)
            )
        )
        excel_df["source_catalogs"] = excel_df["source_catalogs"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else str(x)
        )
        with pd.ExcelWriter(str(out_path), engine="xlsxwriter") as writer:
            excel_df.to_excel(writer, sheet_name="Model Compatibility", index=False)  # noqa: E501
            ws = writer.sheets["Model Compatibility"]
            ws.set_column(0, 0, 20)  # part_no
            ws.set_column(1, 1, 40)  # description
            ws.set_column(2, 2, 50)  # compatible_models
            ws.set_column(3, 3, 40)  # model_years
            ws.set_column(4, 4, 60)  # source_catalogs

        # Parquet: serialize model_years dict → JSON string (pyarrow can't write
        # a struct type with no child fields when all dicts are empty).
        parquet_df = df.copy()
        parquet_df["model_years"] = parquet_df["model_years"].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
        )
        parquet_path = out_path.with_suffix(".parquet")
        parquet_df.to_parquet(parquet_path, index=False)
        logger.info(f"Saved: {out_path} ({len(df):,} unique parts) + {parquet_path.name}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_one(self, pdf_file: Path) -> list[dict[str, str]]:
        """Extract one PDF; fall back to LLM when word-position yield is low."""
        model_name = pdf_file.parent.name
        result = self._extractor.extract(pdf_file, model=model_name)

        if result.error:
            logger.error(f"{pdf_file.name}: extraction error — {result.error}")
            return []

        yield_score = len(result.rows) / result.pages_scanned if result.pages_scanned > 0 else 0.0

        if result.pages_scanned > 0 and yield_score < self._threshold:
            logger.warning(
                f"{pdf_file.name}: yield={yield_score:.2f} < {self._threshold:.2f} "
                f"({len(result.rows)} rows / {result.pages_scanned} pages) "
                f"— using LLM fallback"
            )
            rows = self._llm.extract(pdf_file, model_name)
        else:
            rows = result.rows
            logger.debug(
                f"{pdf_file.name}: yield={yield_score:.2f} "
                f"({len(rows)} rows / {result.pages_scanned} pages)"
            )

        year = result.manufacture_year or ""
        return [
            {
                "part_no": r.get("part_no", "").strip(),
                "description": r.get("description", "").strip(),
                "model": model_name,
                "manufacture_year": year,
                "source_file": pdf_file.name,
            }
            for r in rows
            if r.get("part_no", "").strip()
        ]

    @staticmethod
    def _rollup(records: list[dict[str, str]]) -> pd.DataFrame:
        """Aggregate per-PDF rows into one row per unique part_no."""
        if not records:
            return CrossModelCompatibilityAgent._empty_df()

        df = pd.DataFrame(records)
        df = df[df["part_no"].str.len() > 0].copy()

        def agg(grp: pd.DataFrame) -> pd.Series:
            # Best description: longest non-empty string
            descs = grp["description"].dropna()
            descs = descs[descs.str.len() > 0]
            best_desc = (
                descs.sort_values(key=lambda s: s.str.len(), ascending=False).iloc[0]
                if not descs.empty
                else ""
            )
            models = sorted(grp["model"].dropna().unique().tolist())
            year_map: dict[str, str] = (
                grp[grp["manufacture_year"].str.len() > 0]
                .groupby("model")["manufacture_year"]
                .first()
                .to_dict()
            )
            sources = sorted(grp["source_file"].dropna().unique().tolist())
            return pd.Series(
                {
                    "description": best_desc,
                    "compatible_models": models,
                    "model_years": year_map,
                    "source_catalogs": sources,
                }
            )

        result = df.groupby("part_no", sort=True).apply(agg).reset_index()
        logger.info(
            f"Rollup complete: {len(result):,} unique parts "
            f"from {df['model'].nunique()} models / {df['source_file'].nunique()} PDFs"
        )
        return result

    @staticmethod
    def _empty_df() -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "part_no",
                "description",
                "compatible_models",
                "model_years",
                "source_catalogs",
            ]
        )
