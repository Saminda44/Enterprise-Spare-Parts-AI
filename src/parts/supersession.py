"""Resolve the supersession chain to one identity per physical part.

Business meaning: ``active_sku_id`` is the identifier every later step aggregates on.
Aggregate on the raw material number instead and one physical part's demand splits
across its old and new numbers, understating every forecast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING

from src.core.errors import PipelineError

if TYPE_CHECKING:
    import pandas as pd

SUPERSEDE_COLUMNS = tuple(
    f"{n}{suffix} Supersede"
    for n, suffix in [
        (1, "st"),
        (2, "nd"),
        (3, "rd"),
        (4, "th"),
        (5, "th"),
        (6, "th"),
        (7, "th"),
        (8, "th"),
        (9, "th"),
        (10, "th"),
    ]
)

_MAX_DEPTH = 20
_NON_ALNUM = re.compile(r"[^0-9A-Z]")
_SUPERSEDE_NAME = re.compile(r"^(\d+)(?:st|nd|rd|th) Supersede$", re.IGNORECASE)


def supersede_columns(columns: object) -> list[str]:
    """Find every numbered supersede column, including 11th and later."""
    found = []
    for column in columns:
        match = _SUPERSEDE_NAME.fullmatch(str(column).strip())
        if match:
            found.append((int(match.group(1)), str(column)))
    found.sort()
    return [column for _, column in found]


class SupersessionCycleError(PipelineError):
    """A chain loops back on itself (A→B→A); walking it would never terminate."""


def normalise(part_no: object) -> str:
    """Dash-insensitive key: ``5VL-F341E-00`` and ``5VLF341E00`` compare equal."""
    if part_no is None:
        return ""
    value = str(part_no).strip()
    if value in {"", "nan", "NaN", "None", "<NA>", "NaT"}:
        return ""
    return _NON_ALNUM.sub("", value.upper())


@dataclass
class ChainResolution:
    """One part's resolved identity."""

    material: str
    active_sku_id: str
    latest_ss: str
    depth: int
    agrees_with_latest_ss: bool
    chain: list[str] = field(default_factory=list)


def build_successor_map(frame: pd.DataFrame) -> dict[str, str]:
    """``normalised predecessor -> successor`` from each row's ordered chain.

    Business meaning: PN_Yamaha's numbered columns are successive replacements of its
    Material. The last populated column equals Latest SS in the supplied workbook.
    """
    successor: dict[str, str] = {}
    present = supersede_columns(frame.columns)
    for material, *supersedes in zip(frame["Material"], *(frame[c] for c in present), strict=True):
        chain = [str(material).strip()]
        for value in supersedes:
            if not normalise(value):
                continue
            chain.append(str(value).strip())
        for older, newer in pairwise(chain):
            if normalise(older) and normalise(older) != normalise(newer):
                successor.setdefault(normalise(older), newer)
    return successor


def walk(part_no: str, successor: dict[str, str]) -> tuple[str, list[str], int]:
    """Follow the chain to its terminal node, guarding cycles and runaway depth."""
    chain = [part_no]
    seen = {normalise(part_no)}
    current = part_no
    for depth in range(1, _MAX_DEPTH + 1):
        nxt = successor.get(normalise(current))
        if nxt is None:
            return current, chain, depth - 1
        if normalise(nxt) in seen:
            raise SupersessionCycleError(f"supersession cycle: {' -> '.join([*chain, nxt])}")
        seen.add(normalise(nxt))
        chain.append(nxt)
        current = nxt
    raise SupersessionCycleError(
        f"chain from {part_no!r} exceeded {_MAX_DEPTH} hops: {' -> '.join(chain)}"
    )


def resolve_chains(frame: pd.DataFrame) -> tuple[list[ChainResolution], list[str]]:
    """Resolve every row to an ``active_sku_id``.

    ``Latest SS`` is already resolved in the source, so it is trusted as the identifier
    but **verified** against the derived chain; disagreements are returned, not hidden.
    """
    successor = build_successor_map(frame)
    resolutions: list[ChainResolution] = []
    cycles: list[str] = []

    for material, latest in zip(frame["Material"], frame["Latest SS"], strict=True):
        material_s = str(material).strip()
        latest_s = str(latest).strip() if normalise(latest) else ""
        try:
            derived, chain, depth = walk(material_s, successor)
        except SupersessionCycleError as exc:
            cycles.append(str(exc))
            derived, chain, depth = (latest_s or material_s), [material_s], 0

        active = latest_s or derived
        resolutions.append(
            ChainResolution(
                material=material_s,
                active_sku_id=active,
                latest_ss=latest_s,
                depth=depth,
                agrees_with_latest_ss=normalise(derived) == normalise(latest_s),
                chain=chain,
            )
        )
    return resolutions, cycles


# ── lookup ──────────────────────────────────────────────────────────────────────
@dataclass
class LookupHit:
    part_no: str
    label: str  # QUERIED | CURRENT | OLDER | RELATED
    description: str | None = None
    active_sku_id: str | None = None


class SupersessionLookup:
    """Accept any number in a chain and return every related part, each labelled.

    Accepts numbers with or without dashes, and partial numbers. An unknown number
    returns nothing — never a fuzzy guess, because a wrong supersession merge corrupts
    every downstream demand series.
    """

    def __init__(self, frame: pd.DataFrame) -> None:
        self._descriptions: dict[str, str] = {}
        self._active: dict[str, str] = {}
        self._members: dict[str, set[str]] = {}  # active_sku_id -> member numbers
        self._index: dict[str, str] = {}  # normalised any-number -> active_sku_id

        # Column access by name, not itertuples attributes: "1st Supersede" is not a
        # valid identifier and arrives as _11, and part_master lowercases Material.
        material_col = "Material" if "Material" in frame.columns else "material"
        desc_col = next(
            (c for c in ("Material description", "description") if c in frame.columns), None
        )
        supersede_cols = supersede_columns(frame.columns)

        for record in frame.to_dict("records"):
            material = str(record.get(material_col, "")).strip()
            if not material or material == "nan":
                continue
            active = str(record.get("active_sku_id") or material).strip() or material
            numbers = {material, active}
            for column in supersede_cols:
                value = record.get(column)
                if value is not None and str(value).strip() not in {"", "None", "nan"}:
                    numbers.add(str(value).strip())

            self._members.setdefault(active, set()).update(numbers)
            self._active[normalise(material)] = active
            for number in numbers:
                self._index.setdefault(normalise(number), active)
            if desc_col:
                description = record.get(desc_col)
                if description is not None and str(description) != "nan":
                    self._descriptions[normalise(material)] = str(description)

    def lookup(self, query: str) -> list[LookupHit]:
        """Exact, dash-insensitive, then prefix (partial) match."""
        key = normalise(query)
        if not key:
            return []

        active = self._index.get(key)
        if active is None:
            prefixed = sorted({a for n, a in self._index.items() if n.startswith(key)})
            if not prefixed:
                return []
            hits: list[LookupHit] = []
            for candidate in prefixed:
                hits.extend(self._chain_hits(candidate, key))
            return hits
        return self._chain_hits(active, key)

    def _chain_hits(self, active: str, queried_key: str) -> list[LookupHit]:
        hits: list[LookupHit] = []
        for number in sorted(self._members.get(active, {active})):
            normalised = normalise(number)
            if normalised == queried_key:
                label = "QUERIED"
            elif normalised == normalise(active):
                label = "CURRENT"
            elif normalised in self._active:
                label = "OLDER"
            else:
                label = "RELATED"
            hits.append(
                LookupHit(
                    part_no=number,
                    label=label,
                    description=self._descriptions.get(normalised),
                    active_sku_id=active,
                )
            )
        # the queried number itself always wins its label
        return sorted(hits, key=lambda h: (h.label != "QUERIED", h.label, h.part_no))
