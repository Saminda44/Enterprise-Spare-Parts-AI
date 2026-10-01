"""Pure, auditable merge rules for uploaded source workbooks."""

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
SNAPSHOT_KEYS: dict[str, tuple[str, ...]] = {
    "current_stock.xlsx": ("Material", "Plant", "Storage Location"),
    "On_Orders.xlsx": ("Material",),
}
UPLOADABLE = (*APPEND_KEYS, *SNAPSHOT_KEYS, "PN_Yamaha.xlsx")
_MONTH = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 20\d{2}$")


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


def _key_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


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
    required = APPEND_KEYS.get(name, SNAPSHOT_KEYS.get(name, ("Material",)))
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
        months = [column for column in frame if _MONTH.fullmatch(str(column))]
        if not months:
            raise SourceDataError("On_Orders.xlsx needs dated arrival columns, e.g. Sep 2026")
        periods = sorted(pd.Period(pd.to_datetime(column, format="%b %Y"), freq="M") for column in months)
        if len(periods) != len(pd.period_range(periods[0], periods[-1], freq="M")):
            raise SourceDataError("On_Orders.xlsx has a gap in its arrival months")
        frame = validate(
            frame,
            pa.DataFrameSchema(
                {column: pa.Column(float, pa.Check.ge(0), nullable=True, coerce=True) for column in months}
            ),
            stage="source_upload",
            table=name,
        )
    if name == "PN_Yamaha.xlsx" and not supersede_columns(frame.columns) and "Latest SS" not in frame:
        raise SourceDataError("PN_Yamaha.xlsx needs Latest SS or a numbered Supersede column")
    key = _keys(frame, required, dealers=name == "dealers.xlsx")
    required_key_parts = 2 if name == "orders.xlsx" else len(required)
    if key.str.split("\x1f").map(
        lambda parts: any(not part for part in parts[:required_key_parts])
    ).any():
        raise SourceDataError(f"{name}: upload contains a blank business key")
    if name == "dealers.xlsx":
        no_code = frame["Dealer Code"].map(_key_text).str.casefold() == "no code"
        if (no_code & frame["Dealer Name"].map(_key_text).eq("")).any():
            raise SourceDataError("dealers.xlsx: No Code rows need a Dealer Name")
    return frame


def _append(name: str, current: pd.DataFrame, incoming: pd.DataFrame, *, replace_dealers: bool) -> MergeResult:
    columns = list(dict.fromkeys([*current.columns, *incoming.columns]))
    base = current.reindex(columns=columns)
    candidates = incoming.reindex(columns=columns)
    combined = pd.concat([base, candidates], ignore_index=True)
    exact_duplicate = combined.duplicated(keep="first").iloc[len(base):].to_numpy()
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
            raise SourceDataError("dealers.xlsx: uploaded rows repeat a dealer key with different values")
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
        warnings=[f"{len(conflicted)} changed-key row(s) held for review"] if len(conflicted) else [],
    )


def _snapshot(name: str, incoming: pd.DataFrame) -> MergeResult:
    keys = _keys(incoming, SNAPSHOT_KEYS[name])
    if keys.duplicated().any():
        raise SourceDataError(f"{name}: duplicate Material/plant/location or Material keys in snapshot")
    return MergeResult(frame=incoming.reset_index(drop=True), incoming=len(incoming), replaced=len(incoming))


def _pn_yamaha(current: pd.DataFrame, incoming: pd.DataFrame) -> MergeResult:
    if incoming["Material"].map(normalise).duplicated().any():
        raise SourceDataError("PN_Yamaha.xlsx: duplicate Material in upload")
    columns = list(dict.fromkeys([*current.columns, *incoming.columns]))
    base = current.reindex(columns=columns).set_index("Material", drop=False)
    updates = incoming.reindex(columns=columns).set_index("Material", drop=False)
    for column in ("Latest SS", *supersede_columns(columns)):
        if column in base:
            base[column] = base[column].astype(object)
            updates[column] = updates[column].astype(object)
    if base.index.duplicated().any():
        raise SourceDataError("PN_Yamaha.xlsx: duplicate Material in current source")
    existing = updates.index.intersection(base.index)
    before = base.loc[existing].copy()
    input_ss = supersede_columns(incoming.columns)
    changed_chain = pd.Series(False, index=existing)
    for column in input_ss:
        old = before[column].map(normalise)
        new = updates.loc[existing, column].map(normalise)
        changed_chain |= new.ne("") & new.ne(old)
    base.update(updates.loc[existing])
    added = updates.loc[~updates.index.isin(base.index)]
    merged = pd.concat([base, added])
    columns_ss = supersede_columns(merged.columns)
    if columns_ss:
        last = merged.loc[updates.index, columns_ss].ffill(axis=1).iloc[:, -1]
        present = last.notna() & last.astype(str).str.strip().ne("")
        recompute = pd.Index(added.index).union(changed_chain.index[changed_chain])
        recompute = recompute.intersection(last.index[present])
        merged.loc[recompute, "Latest SS"] = last.loc[recompute]
    missing_latest = merged.loc[updates.index, "Latest SS"].isna()
    merged.loc[updates.index[missing_latest], "Latest SS"] = updates.index[missing_latest]
    after = merged.loc[existing]
    unchanged = int((before.eq(after) | (before.isna() & after.isna())).all(axis=1).sum())

    current_resolved, current_cycles = resolve_chains(current)
    proposed_resolved, proposed_cycles = resolve_chains(merged.reset_index(drop=True))
    new_cycles = set(proposed_cycles) - set(current_cycles)
    if new_cycles:
        raise SourceDataError(f"PN_Yamaha.xlsx introduces {len(new_cycles)} new supersession cycle(s)")
    old_disagreements = {
        normalise(row.material)
        for row in current_resolved if row.depth and not row.agrees_with_latest_ss
    }
    new_disagreements = {
        normalise(row.material)
        for row in proposed_resolved if row.depth and not row.agrees_with_latest_ss
    } - old_disagreements
    if new_disagreements:
        raise SourceDataError(
            f"PN_Yamaha.xlsx introduces {len(new_disagreements)} new Latest SS disagreement(s)"
        )
    return MergeResult(
        frame=merged.reset_index(drop=True),
        incoming=len(incoming),
        added=len(added),
        replaced=len(existing) - unchanged,
        unchanged=unchanged,
        warnings=[
            f"Existing source retains {len(current_cycles)} cycle(s) and "
            f"{len(old_disagreements)} chain disagreement(s) for review"
        ] if current_cycles or old_disagreements else [],
    )


def merge_upload(
    name: str,
    current: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    replace_dealers: bool = False,
) -> MergeResult:
    """Preview an upload without mutating either input.

    Business meaning: histories only gain new document lines, stock and open orders are
    complete snapshots, dealer changes require explicit review, and PN changes keep
    Latest SS aligned with the last populated supersede.
    """
    candidate = _validate(name, incoming.dropna(how="all").copy())
    if name in APPEND_KEYS:
        return _append(name, current.copy(), candidate, replace_dealers=replace_dealers)
    if name in SNAPSHOT_KEYS:
        return _snapshot(name, candidate)
    return _pn_yamaha(current.copy(), candidate)
