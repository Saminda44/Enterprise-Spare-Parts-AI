"""Schema enforcement at stage boundaries.

These are SAP exports whose column meanings are not self-evident, so a violation raises
rather than warning and continuing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandera.pandas as pa

from src.core.errors import ContractViolation

if TYPE_CHECKING:
    import pandas as pd

_MAX_CASES = 10


def validate(
    df: pd.DataFrame,
    schema: pa.DataFrameSchema,
    *,
    stage: str,
    table: str,
) -> pd.DataFrame:
    """Validate ``df`` against ``schema`` or raise :class:`ContractViolation`.

    Collects every failure (``lazy=True``) so one run surfaces all the problems rather
    than the first one.
    """
    try:
        return schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise ContractViolation(_describe(exc, stage=stage, table=table)) from exc
    except pa.errors.SchemaError as exc:  # non-lazy paths (e.g. wrong type entirely)
        raise ContractViolation(f"[{stage}] {table}: {exc}") from exc


def _describe(exc: pa.errors.SchemaErrors, *, stage: str, table: str) -> str:
    cases = exc.failure_cases
    total = len(cases)
    head = cases.head(_MAX_CASES)
    lines = [f"[{stage}] {table} failed its contract — {total} failure case(s):"]
    for _, row in head.iterrows():
        lines.append(
            f"  column={row.get('column')!r} check={row.get('check')!r} "
            f"failure={row.get('failure_case')!r} index={row.get('index')!r}"
        )
    if total > _MAX_CASES:
        lines.append(f"  ... and {total - _MAX_CASES} more")
    return "\n".join(lines)
