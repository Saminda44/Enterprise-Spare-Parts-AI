"""Pure, auditable merge rules for uploaded source workbooks.

How each workbook is kept up to date (owner, 2026-10-01):

* ``MCSI.xlsx``, ``orders.xlsx``, ``sales.xlsx`` — new lines are appended to the end.
* ``dealers.xlsx`` — new dealers are appended; a changed dealer replaces its row only
  when the reviewer asks for it.
* ``current_stock.xlsx`` — ``Unrestricted`` is updated per Material (else via its
  Latest SS) at its plant and storage location; rows not in the upload keep their
  quantity, materials with no row are appended.
* ``On_Orders.xlsx`` — the upload is Material + one quantity; it becomes the next
  arrival-month column, matched by Material, else via Latest SS.
* ``PN_Yamaha.xlsx`` — new materials are appended; a new supersede number goes into
  the next empty Supersede column and becomes the Latest SS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from src.core.contracts import validate
from src.core.errors import SourceDataError
from src.parts.supersession import normalise, resolve_chains, supersede_columns

APPEND_KEYS: dict[str, tuple[str, ...]] = {
    "MCSI.xlsx": ("Billing Document", "Item"),
    "orders.xlsx": ("Sales Document", "Sales Document Item", "Schedule Line Number"),
    "sales.xlsx": ("Billing Document", "Item"),
    "dealers.xlsx": ("Dealer Code",),
}
#: Workbooks updated in place per material: the business key each upload row carries.
UPDATE_KEYS: dict[str, tuple[str, ...]] = {
    "current_stock.xlsx": ("Material", "Plant", "Storage Location"),
    "On_Orders.xlsx": ("Material",),
}
UPLOADABLE = (*APPEND_KEYS, *UPDATE_KEYS, "PN_Yamaha.xlsx")
_MONTH = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20\d{2}$")
#: Accepted headers for the On_Orders upload's single quantity column (case-insensitive).
ON_ORDER_QTY_HEADERS = (
    "quantity",
    "qty",
    "on order",
    "on order qty",
    "on order quantity",
    "order quantity",
    "order qty",
    "open quantity",
    "open qty",
)
#: PN_Yamaha upload columns that carry a new supersede number besides numbered ones.
PN_NEW_NUMBER_HEADERS = ("New Supersede", "Supersede", "Latest SS")
#: PN_Yamaha descriptive columns an upload may fill or correct.
PN_DESCRIPTIVE = ("Material description", "Material Type", "Material Group", "Brand")


@dataclass
class MergeResult:
    """Proposed complete active source and its row-level reconciliation."""

    frame: pd.DataFrame
    incoming: int
    added: int = 0
    replaced: int = 0
    unchanged: int = 0
    conflicts: int = 0
    warnings: list[str] = field(default_factory=list)
    #: What the merge will do, for the reviewer (target month, how rows matched).
    notes: list[str] = field(default_factory=list)


def _key_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _code_text(value: object) -> str:
    """A plant or storage-location code compared the same however Excel typed it.

    SAP writes storage location "0001" as text; a re-saved sheet often turns it into the
    number 1. Purely numeric codes are compared without leading zeros.
    """
    text = _key_text(value).upper()
    return (text.lstrip("0") or "0") if text.isdigit() else text


def _keys(frame: pd.DataFrame, columns: tuple[str, ...], *, dealers: bool = False) -> pd.Series:
    values = frame[list(columns)].map(_key_text)
    if dealers:
        code = values["Dealer Code"]
        name = frame["Dealer Name"].map(_key_text)
        values.loc[code.str.casefold() == "no code", "Dealer Code"] = "No Code|" + name
    return values.astype(str).agg("\x1f".join, axis=1)


def _validate(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Reject a malformed upload before any source can be published."""
    if name not in UPLOADABLE:
        raise SourceDataError(f"unsupported workbook: {name}")
    if frame.empty:
        raise SourceDataError(f"{name}: upload has no data rows")
    if frame.columns.duplicated().any():
        raise SourceDataError(f"{name}: duplicate column headers")
    required = APPEND_KEYS.get(name, UPDATE_KEYS.get(name, ("Material",)))
    missing = [column for column in required if column not in frame]
    if missing:
        raise SourceDataError(f"{name}: missing required columns: {', '.join(missing)}")
    if name == "dealers.xlsx" and "Dealer Name" not in frame:
        raise SourceDataError("dealers.xlsx: missing Dealer Name")
    if name == "current_stock.xlsx":
        if "Unrestricted" not in frame:
            raise SourceDataError("current_stock.xlsx: missing Unrestricted")
        frame = validate(
            frame,
            pa.DataFrameSchema({"Unrestricted": pa.Column(float, pa.Check.ge(0), coerce=True)}),
            stage="source_upload",
            table=name,
        )
    if name == "On_Orders.xlsx":
        quantity = _quantity_column(frame)
        frame = validate(
            frame,
            pa.DataFrameSchema(
                {quantity: pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True)}
            ),
            stage="source_upload",
            table=name,
        )
    if name == "PN_Yamaha.xlsx" and not (
        supersede_columns(frame.columns)
        or any(c in frame for c in (*PN_NEW_NUMBER_HEADERS, *PN_DESCRIPTIVE))
    ):
        raise SourceDataError(
            "PN_Yamaha.xlsx needs a supersede number (New Supersede, Latest SS or a numbered "
            "Supersede column) or a material description"
        )
    key = _keys(frame, required, dealers=name == "dealers.xlsx")
    required_key_parts = 2 if name == "orders.xlsx" else len(required)
    if (
        key.str.split("\x1f")
        .map(lambda parts: any(not part for part in parts[:required_key_parts]))
        .any()
    ):
        raise SourceDataError(f"{name}: upload contains a blank business key")
    if name == "dealers.xlsx":
        no_code = frame["Dealer Code"].map(_key_text).str.casefold() == "no code"
        if (no_code & frame["Dealer Name"].map(_key_text).eq("")).any():
            raise SourceDataError("dealers.xlsx: No Code rows need a Dealer Name")
    return frame


def _append(
    name: str, current: pd.DataFrame, incoming: pd.DataFrame, *, replace_dealers: bool
) -> MergeResult:
    columns = list(dict.fromkeys([*current.columns, *incoming.columns]))
    base = current.reindex(columns=columns)
    candidates = incoming.reindex(columns=columns)
    combined = pd.concat([base, candidates], ignore_index=True)
    exact_duplicate = combined.duplicated(keep="first").iloc[len(base) :].to_numpy()
    remaining = candidates.loc[~exact_duplicate].copy()
    unchanged = int(exact_duplicate.sum())
    keys = APPEND_KEYS[name]
    dealer = name == "dealers.xlsx"
    base_key = _keys(base, keys, dealers=dealer)
    new_key = _keys(remaining, keys, dealers=dealer)
    duplicate_new_key = new_key.duplicated(keep=False)
    conflict = new_key.isin(set(base_key)) | duplicate_new_key
    conflicted = remaining.loc[conflict]
    safe = remaining.loc[~conflict]
    replaced = 0
    if dealer and replace_dealers and not conflicted.empty:
        if duplicate_new_key.any():
            raise SourceDataError(
                "dealers.xlsx: uploaded rows repeat a dealer key with different values"
            )
        replacing_keys = set(new_key.loc[conflict])
        base = base.loc[~base_key.isin(replacing_keys)]
        replaced = len(replacing_keys)
        safe = pd.concat([safe, conflicted], ignore_index=True)
        conflicted = conflicted.iloc[0:0]
    merged = pd.concat([base, safe], ignore_index=True)
    return MergeResult(
        frame=merged,
        incoming=len(incoming),
        added=len(safe) - replaced,
        replaced=replaced,
        unchanged=unchanged,
        conflicts=len(conflicted),
        warnings=[f"{len(conflicted)} changed-key row(s) held for review"]
        if len(conflicted)
        else [],
    )


def _quantity_column(frame: pd.DataFrame) -> str:
    """The On_Orders upload's one quantity column."""
    found = [c for c in frame.columns if str(c).strip().casefold() in ON_ORDER_QTY_HEADERS]
    if len(found) != 1:
        raise SourceDataError(
            "On_Orders.xlsx upload needs exactly one quantity column, headed e.g. 'Quantity'"
        )
    return str(found[0])


def chain_heads(pn_yamaha: pd.DataFrame | None) -> dict[str, str]:
    """Every PN_Yamaha number -> the Latest SS of its chain (normalised).

    Business meaning: an old number and its replacement are one physical part, so a
    stock or on-order line under either finds the other's row.
    """
    heads: dict[str, str] = {}
    if pn_yamaha is None or "Material" not in pn_yamaha:
        return heads
    numbered = supersede_columns(pn_yamaha.columns)
    latest = (
        pn_yamaha["Latest SS"] if "Latest SS" in pn_yamaha else pd.Series("", index=pn_yamaha.index)
    )
    for idx, material in pn_yamaha["Material"].items():
        own = normalise(material)
        if not own:
            continue
        head = normalise(latest.at[idx]) or own
        heads[own] = head
        for column in numbered:
            heads.setdefault(normalise(pn_yamaha.at[idx, column]), head)
    heads.pop("", None)
    return heads


def _match(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    heads: dict[str, str],
    scope: tuple[str, ...] = (),
) -> tuple[dict[int, int], list[int], list[int], int]:
    """Pair upload rows with existing rows by Material, else via the chain's Latest SS.

    ``scope`` columns (plant, storage location) must also agree. An exact Material match
    always wins; a Latest SS match only takes a row no exact match has claimed, and only
    when it is unambiguous.

    Returns:
        upload index -> existing index, unmatched upload indexes (to append), ambiguous
        upload indexes (held for review), and how many matched via Latest SS.
    """
    own = existing["Material"].map(normalise)
    head = own.map(lambda m: heads.get(m, m))
    where = pd.Series("", index=existing.index)
    for column in scope:
        where = where + "\x1f" + existing[column].map(_code_text)
    exact_index: dict[tuple[str, str], list[int]] = {}
    head_index: dict[tuple[str, str], list[int]] = {}
    for idx in existing.index:
        exact_index.setdefault((own.at[idx], where.at[idx]), []).append(idx)
        head_index.setdefault((head.at[idx], where.at[idx]), []).append(idx)

    pairs: dict[int, int] = {}
    deferred: list[tuple[int, str, str]] = []
    ambiguous: list[int] = []
    for idx, material in incoming["Material"].items():
        m = normalise(material)
        loc = "".join("\x1f" + _code_text(incoming.at[idx, c]) for c in scope)
        rows = exact_index.get((m, loc), [])
        if len(rows) == 1:
            pairs[idx] = rows[0]
        elif len(rows) > 1:
            ambiguous.append(idx)
        else:
            deferred.append((idx, m, loc))
    claimed = set(pairs.values())
    unmatched: list[int] = []
    via_head = 0
    for idx, m, loc in deferred:
        rows = [r for r in head_index.get((heads.get(m, m), loc), []) if r not in claimed]
        if len(rows) == 1:
            pairs[idx] = rows[0]
            claimed.add(rows[0])
            via_head += 1
        elif len(rows) > 1:
            ambiguous.append(idx)
        else:
            unmatched.append(idx)
    return pairs, unmatched, ambiguous, via_head


def _stock(current: pd.DataFrame, incoming: pd.DataFrame, heads: dict[str, str]) -> MergeResult:
    """Update Unrestricted per material and location; leave every other row as it was."""
    keys = _keys(incoming, UPDATE_KEYS["current_stock.xlsx"])
    if keys.duplicated().any():
        raise SourceDataError(
            "current_stock.xlsx: the upload repeats a Material / Plant / Storage Location"
        )
    columns = list(dict.fromkeys([*current.columns, *incoming.columns]))
    base = current.reindex(columns=columns).reset_index(drop=True)
    upload = incoming.reindex(columns=columns).reset_index(drop=True)
    base["Unrestricted"] = pd.to_numeric(base["Unrestricted"], errors="coerce")
    pairs, unmatched, ambiguous, via_head = _match(
        base, upload, heads, scope=("Plant", "Storage Location")
    )
    replaced = unchanged = 0
    for up, row in pairs.items():
        new = float(upload.at[up, "Unrestricted"])
        old = base.at[row, "Unrestricted"]
        if pd.notna(old) and float(old) == new:
            unchanged += 1
            continue
        base.at[row, "Unrestricted"] = new
        replaced += 1
    merged = pd.concat([base, upload.loc[unmatched]], ignore_index=True)
    notes = [
        f"{len(pairs):,} row(s) matched ({via_head:,} through their Latest SS); rows not in "
        "the upload keep their quantity"
    ]
    warnings = (
        [f"{len(ambiguous):,} row(s) held for review: more than one existing row could take them"]
        if ambiguous
        else []
    )
    return MergeResult(
        frame=merged,
        incoming=len(incoming),
        added=len(unmatched),
        replaced=replaced,
        unchanged=unchanged,
        conflicts=len(ambiguous),
        warnings=warnings,
        notes=notes,
    )


def next_on_order_month(current: pd.DataFrame) -> str:
    """The arrival-month column an On_Orders upload is written into: after the last one."""
    months = [
        pd.Period(pd.to_datetime(str(c), format="%b %Y"), freq="M")
        for c in current.columns
        if _MONTH.fullmatch(str(c).strip())
    ]
    if not months:
        raise SourceDataError("On_Orders.xlsx has no dated arrival columns to extend")
    return (max(months) + 1).strftime("%b %Y")


def _on_orders(
    current: pd.DataFrame,
    incoming: pd.DataFrame,
    heads: dict[str, str],
    pn_yamaha: pd.DataFrame | None,
) -> MergeResult:
    """Write the upload's quantity into a new month column after the last one."""
    quantity = _quantity_column(incoming)
    target = next_on_order_month(current)
    upload = incoming.copy()
    upload[quantity] = pd.to_numeric(upload[quantity], errors="coerce").fillna(0.0)
    # Several lines for one material (several POs) arrive together: one quantity.
    upload["_key"] = upload["Material"].map(normalise)
    repeated = int(upload["_key"].duplicated().sum())
    first = upload.groupby("_key", sort=False).first()
    first[quantity] = upload.groupby("_key", sort=False)[quantity].sum()
    upload = first.reset_index(drop=True)

    # The file's own Latest SS column also names each row's chain.
    file_heads = dict(heads)
    if "Latest SS" in current:
        for material, latest in zip(current["Material"], current["Latest SS"], strict=True):
            own, head = normalise(material), normalise(latest)
            if own and head:
                file_heads.setdefault(own, head)
    base = current.reset_index(drop=True).copy()
    base[target] = pd.NA
    pairs, unmatched, ambiguous, via_head = _match(base, upload, file_heads)
    totals: dict[int, float] = {}
    for up, row in pairs.items():
        totals[row] = totals.get(row, 0.0) + float(upload.at[up, quantity])
    for row, qty in totals.items():
        base.at[row, target] = qty

    new_rows = upload.loc[unmatched].drop(columns=[quantity]).reindex(columns=base.columns)
    new_rows[target] = upload.loc[unmatched, quantity].to_numpy()
    if pn_yamaha is not None and not new_rows.empty:
        reference = (
            pn_yamaha.assign(_key=pn_yamaha["Material"].map(normalise))
            .drop_duplicates("_key")
            .set_index("_key")
        )
        for idx in new_rows.index:
            key = normalise(new_rows.at[idx, "Material"])
            if key not in reference.index:
                continue
            for column in ("Latest SS", "Material Type", "Material Group", "Brand"):
                if column in new_rows and pd.isna(new_rows.at[idx, column]):
                    new_rows.at[idx, column] = reference.at[key, column]
            if "Description" in new_rows and pd.isna(new_rows.at[idx, "Description"]):
                new_rows.at[idx, "Description"] = reference.at[key, "Material description"]
    merged = pd.concat([base, new_rows], ignore_index=True)
    notes = [
        f"quantities are written to a new arrival month: {target}",
        f"{len(pairs):,} material(s) matched ({via_head:,} through their Latest SS), "
        f"{len(unmatched):,} added as new rows",
    ]
    if repeated:
        notes.append(f"{repeated:,} repeated material line(s) in the upload were summed")
    warnings = (
        [
            f"{len(ambiguous):,} material(s) held for review: more than one row shares their "
            "Latest SS"
        ]
        if ambiguous
        else []
    )
    return MergeResult(
        frame=merged,
        incoming=len(incoming),
        added=len(unmatched),
        replaced=len(totals),
        conflicts=len(ambiguous),
        warnings=warnings,
        notes=notes,
    )


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} Supersede"


def _chain(row: pd.Series, columns: list[str]) -> list[str]:
    """A material's supersede numbers, oldest replacement first, as written."""
    return [str(row[c]).strip() for c in columns if normalise(row.get(c))]


def _new_numbers(row: pd.Series, material: str) -> list[str]:
    """The supersede numbers an upload row brings, in order, without repeats or itself."""
    found: list[str] = []
    for column in (*supersede_columns(row.index), *PN_NEW_NUMBER_HEADERS):
        value = row.get(column)
        key = normalise(value)
        if key and key != normalise(material) and key not in {normalise(v) for v in found}:
            found.append(str(value).strip())
    return found


def _pn_yamaha(current: pd.DataFrame, incoming: pd.DataFrame) -> MergeResult:
    """Append new materials; extend chains into the next empty Supersede column.

    Business meaning: PN_Yamaha keeps each material's full replacement history, oldest
    first, with Latest SS the newest number. A new supersede never overwrites history;
    it extends the chain, and every older number in the same chain is extended with it,
    so all of them keep pointing at the same current part.
    """
    keys = incoming["Material"].map(normalise)
    if keys.duplicated().any():
        raise SourceDataError("PN_Yamaha.xlsx: duplicate Material in upload")
    base = current.copy().reset_index(drop=True)
    numbered = supersede_columns(base.columns)
    for column in ("Latest SS", *numbered):
        if column in base:
            base[column] = base[column].astype(object)
    # One number can be written more than once ("21CF3-18110-00" / "21C-F3181-10-00"):
    # an update applies to every row that writes it.
    position: dict[str, list[int]] = {}
    for i, m in enumerate(base["Material"]):
        position.setdefault(normalise(m), []).append(i)
    repeated = sum(1 for rows in position.values() if len(rows) > 1)
    chains: dict[int, list[str]] = {i: _chain(base.loc[i], numbered) for i in base.index}
    touched: set[int] = set()
    extended: dict[str, list[str]] = {}
    new_rows: list[dict[str, object]] = []

    for _, row in incoming.iterrows():
        material = str(row["Material"]).strip()
        numbers = _new_numbers(row, material)
        rows = position.get(normalise(material))
        if rows is None:
            record: dict[str, object] = {"Material": material}
            for column in PN_DESCRIPTIVE:
                if column in row and normalise(row[column]):
                    record[column] = row[column]
            record["_chain"] = numbers
            new_rows.append(record)
            continue
        for idx in rows:
            for column in PN_DESCRIPTIVE:
                if column in row and normalise(row[column]) and row[column] != base.at[idx, column]:
                    base.at[idx, column] = row[column]
                    touched.add(idx)
            have = {normalise(n) for n in chains[idx]}
            added = [n for n in numbers if normalise(n) not in have]
            if added:
                chains[idx] = chains[idx] + added
                extended.setdefault(normalise(material), added)
                touched.add(idx)

    # Older numbers whose chain ends at an extended material take the same extension.
    for idx in base.index:
        if normalise(base.at[idx, "Material"]) in extended:
            continue
        tail = normalise(base.at[idx, "Latest SS"]) or (
            normalise(chains[idx][-1]) if chains[idx] else ""
        )
        if tail in extended:
            have = {normalise(n) for n in chains[idx]}
            more = [n for n in extended[tail] if normalise(n) not in have]
            if more:
                chains[idx] = chains[idx] + more
                touched.add(idx)

    longest = max([len(c) for c in chains.values()] + [len(r["_chain"]) for r in new_rows] + [0])
    columns = list(numbered)
    while len(columns) < longest:
        columns.append(_ordinal(len(columns) + 1))
    for column in columns:
        if column not in base:
            base[column] = pd.Series([None] * len(base), dtype=object)
    for idx in touched:
        chain = chains[idx]
        for i, column in enumerate(columns):
            base.at[idx, column] = chain[i] if i < len(chain) else None
        if chain:
            base.at[idx, "Latest SS"] = chain[-1]
    appended = []
    for record in new_rows:
        chain = record.pop("_chain")
        for i, column in enumerate(columns):
            record[column] = chain[i] if i < len(chain) else None
        record["Latest SS"] = chain[-1] if chain else record["Material"]
        appended.append(record)
    merged = pd.concat(
        [base, pd.DataFrame(appended).reindex(columns=base.columns)], ignore_index=True
    )
    original = current.reset_index(drop=True)
    changed = [i for i in touched if not _same_row(original.iloc[i], merged.iloc[i])]

    current_resolved, current_cycles = resolve_chains(current)
    proposed_resolved, proposed_cycles = resolve_chains(merged)
    new_cycles = set(proposed_cycles) - set(current_cycles)
    if new_cycles:
        raise SourceDataError(
            f"PN_Yamaha.xlsx introduces {len(new_cycles)} new supersession cycle(s)"
        )
    old_disagreements = {
        normalise(r.material) for r in current_resolved if r.depth and not r.agrees_with_latest_ss
    }
    new_disagreements = {
        normalise(r.material) for r in proposed_resolved if r.depth and not r.agrees_with_latest_ss
    } - old_disagreements
    if new_disagreements:
        raise SourceDataError(
            f"PN_Yamaha.xlsx introduces {len(new_disagreements)} new Latest SS disagreement(s)"
        )
    named = {k: position[k] for k in keys if k in position}
    direct = {i for rows in named.values() for i in rows}
    propagated = len(touched - direct)
    notes = []
    if extended:
        notes.append(
            f"{len(extended):,} chain(s) extended into the next empty Supersede column; "
            f"{max(propagated, 0):,} older number(s) in those chains extended with them"
        )
    if len(columns) > len(numbered):
        notes.append(f"supersede columns added: {', '.join(columns[len(numbered) :])}")
    warnings = (
        [
            f"Existing source retains {len(current_cycles)} cycle(s) and "
            f"{len(old_disagreements)} chain disagreement(s) for review"
        ]
        if current_cycles or old_disagreements
        else []
    )
    if repeated:
        warnings.append(
            f"{repeated:,} material number(s) are written more than once in PN_Yamaha "
            "(different dash placement); an update applies to every copy"
        )
    changed_rows = set(changed)
    return MergeResult(
        frame=merged,
        incoming=len(incoming),
        added=len(appended),
        replaced=len(changed),
        unchanged=sum(1 for rows in named.values() if not changed_rows & set(rows)),
        warnings=warnings,
        notes=notes,
    )


def _same_row(a: pd.Series, b: pd.Series) -> bool:
    for column in b.index:
        x, y = a.get(column), b.get(column)
        if normalise(x) != normalise(y) and not (pd.isna(x) and pd.isna(y)):
            return False
    return True


def merge_upload(
    name: str,
    current: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    replace_dealers: bool = False,
    pn_yamaha: pd.DataFrame | None = None,
) -> MergeResult:
    """Preview an upload without mutating either input.

    Business meaning: histories only gain new document lines; dealer changes require
    explicit review; stock quantities and the next on-order month are updated per
    material, matched through the supersession chain (``pn_yamaha``) when the number
    differs; PN changes extend chains and keep Latest SS the newest number.
    """
    candidate = _validate(name, incoming.dropna(how="all").copy())
    if name in APPEND_KEYS:
        return _append(name, current.copy(), candidate, replace_dealers=replace_dealers)
    if name == "current_stock.xlsx":
        return _stock(current.copy(), candidate, chain_heads(pn_yamaha))
    if name == "On_Orders.xlsx":
        return _on_orders(current.copy(), candidate, chain_heads(pn_yamaha), pn_yamaha)
    return _pn_yamaha(current.copy(), candidate)
