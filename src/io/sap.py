"""The one SAP glued-column parser.

Several columns in these exports pack a code and a label into a single string::

    Payer               "26198      Yamaha Sales Center"
    Material            "676-42115-00       SHAFT STEERING YAMAHA 40 HP"
    Sales Organization  "2501 Associated Motorways"
    Sales Office        "W1B1 Seeduwa - PDC"
    Sales Employee      "00171976 Arosha Edirisinghe"

Business meaning: the raw glued string never matches anything on the other side of a
join. Split it, emit ``*_code`` and ``*_name``, and join on the code.

The parser is applied **per column, per file** from :data:`GLUED_COLUMNS` — never blanket
across a dataframe, because a description column would be split on its first token.
``orders.xlsx`` does not use this encoding at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.errors import SourceDataError

if TYPE_CHECKING:
    import pandas as pd

#: A run of two or more spaces — the primary separator.
_MULTI_SPACE = re.compile(r"\s{2,}")

#: What a leading code token looks like: upper-case alphanumeric, containing at least one
#: digit, optionally dashed. Matches 26198, 2501, W1B1, 00171976, 676-42115-00.
#: Does not match SHAFT, Yamaha, or any word-leading description.
_CODE_TOKEN = re.compile(r"^(?=[^\W_]*\d)[0-9A-Z][0-9A-Z\-./]{0,23}$")


def split_code_label(value: object) -> tuple[str | None, str | None]:
    """Split ``"26198      Yamaha Sales Center"`` into ``("26198", "Yamaha Sales Center")``.

    Rules, in order:

    1. Split on the first run of two or more spaces.
    2. Otherwise split on the first single space when the leading token looks like a code.
    3. Otherwise, a bare code-shaped string is a code with no label; anything else is a
       label with no code (an MCSI ``Payer`` holding a retail customer name, say).

    Returns ``(None, None)`` for null or empty input — never raises.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None, None

    match = _MULTI_SPACE.search(text)
    if match:
        code = text[: match.start()].strip()
        label = text[match.end() :].strip()
        return (code or None), (label or None)

    head, _, tail = text.partition(" ")
    if tail and _CODE_TOKEN.match(head):
        return head, tail.strip() or None

    if _CODE_TOKEN.match(text):
        return text, None
    return None, text


@dataclass(frozen=True)
class GluedColumn:
    """One column to split, and the two columns it produces."""

    source: str
    code: str
    label: str


#: Declared per file. An empty tuple states positively that a file carries no glued
#: columns — ``orders.xlsx`` has separate ``Sold-to Party`` and ``Sold-To Party Name``.
#:
#: MCSI's ``Payer`` is deliberately absent: it holds a retail customer name, not a
#: dealer, and must never be joined to ``dealers.xlsx``.
GLUED_COLUMNS: Mapping[str, tuple[GluedColumn, ...]] = {
    "orders.xlsx": (),
    "sales.xlsx": (
        GluedColumn("Payer", "payer_code", "payer_name"),
        GluedColumn("Material", "material_code", "material_description"),
    ),
    "MCSI.xlsx": (
        GluedColumn("Sales Organization", "sales_org_code", "sales_org_name"),
        GluedColumn("Sales Office", "sales_office_code", "sales_office_name"),
        GluedColumn("Sales Employee", "sales_employee_code", "sales_employee_name"),
        GluedColumn("Material", "material_code", "material_description"),
    ),
}


def split_columns(
    df: pd.DataFrame,
    columns: Iterable[GluedColumn],
    *,
    keep_raw: bool = True,
) -> pd.DataFrame:
    """Return a copy of ``df`` with each declared column split into code and label.

    Raises :class:`SourceDataError` if a declared column is absent — fail closed, because
    a silently missing split produces a join that matches nothing.
    """
    out = df.copy()
    for spec in columns:
        if spec.source not in out.columns:
            raise SourceDataError(
                f"declared glued column {spec.source!r} is not in the dataframe; "
                f"columns present: {list(out.columns)[:20]}"
            )
        parsed = out[spec.source].map(split_code_label)
        out[spec.code] = [p[0] for p in parsed]
        out[spec.label] = [p[1] for p in parsed]
        if not keep_raw:
            out = out.drop(columns=[spec.source])
    return out


def split_for_source(df: pd.DataFrame, source: str, *, keep_raw: bool = True) -> pd.DataFrame:
    """Apply the declared map for ``source`` (e.g. ``"sales.xlsx"``).

    An undeclared source raises rather than defaulting to "split nothing" — a new file
    must have its columns declared deliberately.
    """
    if source not in GLUED_COLUMNS:
        raise SourceDataError(
            f"no glued-column map declared for {source!r}; "
            f"declare one in GLUED_COLUMNS (an empty tuple means 'not glued')"
        )
    return split_columns(df, GLUED_COLUMNS[source], keep_raw=keep_raw)
