"""Chroma access — a search index, never a contract.

No pipeline decision reads from Chroma, so a re-index can never change a number. Steps 01
and 02 write to it; the API searches it.

``chromadb`` is imported lazily so the rest of the pipeline neither needs it installed
nor pays its import cost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.settings import get_settings

_MISSING = (
    "chromadb is not installed. It is only needed for catalogue and parts search "
    "(steps 01-02 and the /parts/search endpoint). Install it with: uv add chromadb"
)


def chroma_dir() -> Path:
    return get_settings().root / "data" / "chroma"


def get_client(persist_dir: Path | None = None) -> Any:
    """A persistent Chroma client rooted at ``data/chroma``."""
    try:
        import chromadb
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ModuleNotFoundError(_MISSING) from exc

    target = persist_dir or chroma_dir()
    target.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(target))


def get_collection(name: str, *, persist_dir: Path | None = None) -> Any:
    """Fetch or create a collection by name (``catalogue``, ``parts_master``)."""
    return get_client(persist_dir).get_or_create_collection(name)


def is_available() -> bool:
    """Whether chromadb can be imported — for /health and run reports."""
    try:
        import chromadb  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True
