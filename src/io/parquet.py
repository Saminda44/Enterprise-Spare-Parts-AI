"""Reading and writing the data layers.

``raw`` holds parquet mirrors of the source workbooks; ``staging`` per-step cleaned
output; ``facts`` tables crossing a stage boundary; ``marts`` what the API serves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from src.core.errors import SourceDataError
from src.core.settings import get_settings

Layer = Literal["raw", "staging", "facts", "marts"]


def layer_dir(layer: Layer) -> Path:
    settings = get_settings()
    dirs: dict[str, Path] = {
        "raw": settings.raw_dir,
        "staging": settings.staging_dir,
        "facts": settings.facts_dir,
        "marts": settings.marts_dir,
    }
    try:
        return dirs[layer]
    except KeyError as exc:
        raise ValueError(f"unknown layer {layer!r}; expected one of {list(dirs)}") from exc


def table_path(layer: Layer, name: str) -> Path:
    return layer_dir(layer) / f"{name}.parquet"


def table_exists(layer: Layer, name: str) -> bool:
    return table_path(layer, name).exists()


def write_table(df: pd.DataFrame, layer: Layer, name: str) -> Path:
    path = table_path(layer, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_table(layer: Layer, name: str) -> pd.DataFrame:
    path = table_path(layer, name)
    if not path.exists():
        raise SourceDataError(f"{layer}/{name}.parquet does not exist — run its stage first")
    return pd.read_parquet(path)


def append_columns(base: pd.DataFrame, new: pd.DataFrame, key: str) -> pd.DataFrame:
    """Merge ``new`` onto ``base``, replacing any columns it already contributed.

    Business meaning: steps 06, 08, 12 and 13 each append their columns to
    ``part_master_enriched``. Re-running a step must overwrite its own previous columns
    rather than colliding with them, or the second run of a cycle fails on duplicates.
    """
    overlapping = [c for c in new.columns if c != key and c in base.columns]
    return base.drop(columns=overlapping).merge(new, on=key, how="left")


def table_age_hours(layer: Layer, name: str) -> float | None:
    """Age of a table in hours, or None if it does not exist.

    Step 15 reports this on /health so a stale pipeline is visible rather than silently
    serving last month's numbers.
    """
    path = table_path(layer, name)
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (datetime.now(UTC) - modified).total_seconds() / 3600
