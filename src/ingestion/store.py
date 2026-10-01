"""Versioned Excel and PostgreSQL source stores behind one workbook contract."""

from __future__ import annotations

import json
import shutil
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.core.errors import SourceDataError
from src.core.settings import get_settings
from src.io.excel import file_digest

WORKBOOKS = (
    "orders.xlsx", "sales.xlsx", "MCSI.xlsx", "current_stock.xlsx",
    "On_Orders.xlsx", "PN_Yamaha.xlsx", "dealers.xlsx", "Sales_Summery.xlsx",
)
ALIASES = {"Sales_Summery.xlsx": ("Sales Summery.xlsx",)}


def raw_workbook_path(name: str) -> Path:
    """Find an original immutable workbook, including the supplied summary spelling."""
    if name not in WORKBOOKS:
        raise SourceDataError(f"unsupported workbook: {name}")
    raw = get_settings().raw_dir
    for candidate in (name, *ALIASES.get(name, ())):
        path = raw / candidate
        if path.is_file():
            return path
    return raw / name


def active_excel_path(name: str, *, settings: Any | None = None) -> Path:
    """Use a managed upload when present, else the untouched original workbook."""
    if name not in WORKBOOKS:
        raise SourceDataError(f"unsupported workbook: {name}")
    settings = settings or get_settings()
    managed_dir = getattr(settings, "managed_source_dir", None)
    managed = managed_dir / name if managed_dir else None
    if managed is not None and managed.is_file():
        return managed
    for candidate in (name, *ALIASES.get(name, ())):
        raw = settings.raw_dir / candidate
        if raw.is_file():
            return raw
    return settings.raw_dir / name


def _read_excel(path: Path, name: str) -> dict[str, pd.DataFrame]:
    from src.io.excel import workbook_sheets

    if not path.is_file():
        raise SourceDataError(f"source workbook not found: {path}")
    names = workbook_sheets(path)
    if name == "Sales_Summery.xlsx":
        return pd.read_excel(path, sheet_name=None)
    return {names[0]: pd.read_excel(path, sheet_name=0)}


def _cell(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime) and value.tzinfo:
        value = value.replace(tzinfo=None)
    return value


def _write_excel(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    from openpyxl import Workbook

    book = Workbook(write_only=True)
    for sheet_name, frame in sheets.items():
        sheet = book.create_sheet(title=sheet_name)
        sheet.append([str(column) for column in frame.columns])
        for row in frame.itertuples(index=False, name=None):
            sheet.append([_cell(value) for value in row])
    book.save(path)


class SourceStore(ABC):
    """The input side of the pipeline; stages consume its parquet materialization."""

    @abstractmethod
    def read(self, name: str) -> dict[str, pd.DataFrame]:
        """Read every sheet in the current workbook version."""

    @abstractmethod
    def publish(
        self, name: str, sheets: dict[str, pd.DataFrame], *,
        upload_sha256: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically select an immutable new source version."""

    @abstractmethod
    def version(self, name: str) -> dict[str, Any]:
        """Current version identity and upload metadata."""


class ExcelSourceStore(SourceStore):
    """Managed Excel copies overlaid on immutable originals."""

    def read(self, name: str) -> dict[str, pd.DataFrame]:
        return _read_excel(active_excel_path(name), name)

    def version(self, name: str) -> dict[str, Any]:
        path = active_excel_path(name)
        if not path.is_file():
            raise SourceDataError(f"source workbook not found: {name}")
        sidecar = path.with_suffix(".upload.json")
        metadata = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        return {
            "version_id": file_digest(path),
            "sha256": file_digest(path),
            "source_modified": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            "metadata": metadata,
            "path": path,
        }

    def publish(
        self, name: str, sheets: dict[str, pd.DataFrame], *,
        upload_sha256: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if name not in WORKBOOKS:
            raise SourceDataError(f"unsupported workbook: {name}")
        target_dir = get_settings().managed_source_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        temporary = target_dir / f".{uuid.uuid4().hex}-{name}"
        _write_excel(temporary, sheets)
        try:
            saved = _read_excel(temporary, name)
            if set(saved) != set(sheets) or any(len(saved[key]) != len(value) for key, value in sheets.items()):
                raise SourceDataError(f"{name}: published workbook failed its row-count round trip")
            if target.exists():
                archive = target_dir / "archive" / name.removesuffix(".xlsx")
                archive.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, archive / f"{file_digest(target)}.xlsx")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        record = {
            **metadata,
            "upload_sha256": upload_sha256,
            "applied_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "rows_by_sheet": {key: len(frame) for key, frame in sheets.items()},
        }
        target.with_suffix(".upload.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return self.version(name)


class PostgresSourceStore(SourceStore):
    """Append-only database versions; a head pointer selects the active tables."""

    def _connect(self):  # noqa: ANN202 - psycopg's connection is runtime-typed
        import psycopg

        return psycopg.connect(**get_settings().postgres_params())

    @staticmethod
    def _ensure(conn: Any) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS planning_source_versions ("
            "version_id text PRIMARY KEY, workbook text NOT NULL, "
            "upload_sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), "
            "metadata jsonb NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS planning_source_rows ("
            "version_id text NOT NULL REFERENCES planning_source_versions(version_id), "
            "sheet text NOT NULL, ordinal integer NOT NULL, payload jsonb NOT NULL, "
            "PRIMARY KEY (version_id, sheet, ordinal))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS planning_source_heads ("
            "workbook text PRIMARY KEY, version_id text NOT NULL "
            "REFERENCES planning_source_versions(version_id))"
        )

    def _head(self, conn: Any, name: str) -> tuple[str, str, datetime, dict[str, Any]] | None:
        row = conn.execute(
            "SELECT v.version_id, v.upload_sha256, v.created_at, v.metadata "
            "FROM planning_source_heads h JOIN planning_source_versions v "
            "ON v.version_id = h.version_id WHERE h.workbook = %s", (name,),
        ).fetchone()
        return row if row else None

    def _bootstrap(self, name: str) -> None:
        path = raw_workbook_path(name)
        if not path.is_file():
            raise SourceDataError(f"{name}: no PostgreSQL version or original workbook to import")
        self.publish(name, _read_excel(path, name), upload_sha256=file_digest(path), metadata={"bootstrap": True})

    def version(self, name: str) -> dict[str, Any]:
        if name not in WORKBOOKS:
            raise SourceDataError(f"unsupported workbook: {name}")
        with self._connect() as conn:
            self._ensure(conn)
            head = self._head(conn, name)
        if head is None:
            self._bootstrap(name)
            return self.version(name)
        version_id, digest, created, metadata = head
        return {
            "version_id": version_id, "sha256": version_id,
            "upload_sha256": digest, "source_modified": created.isoformat(),
            "metadata": metadata,
        }

    def read(self, name: str) -> dict[str, pd.DataFrame]:
        version = self.version(name)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sheet, ordinal, payload FROM planning_source_rows "
                "WHERE version_id = %s ORDER BY sheet, ordinal", (version["version_id"],),
            ).fetchall()
        columns = version["metadata"]["columns_by_sheet"]
        grouped: dict[str, list[dict[str, Any]]] = {sheet: [] for sheet in columns}
        for sheet, _, payload in rows:
            grouped[sheet].append(payload)
        return {
            sheet: pd.DataFrame.from_records(grouped[sheet], columns=columns[sheet])
            for sheet in columns
        }

    def publish(
        self, name: str, sheets: dict[str, pd.DataFrame], *,
        upload_sha256: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if name not in WORKBOOKS:
            raise SourceDataError(f"unsupported workbook: {name}")
        from psycopg.types.json import Jsonb

        version_id = uuid.uuid4().hex
        record = {
            **metadata,
            "columns_by_sheet": {sheet: list(frame.columns) for sheet, frame in sheets.items()},
            "rows_by_sheet": {sheet: len(frame) for sheet, frame in sheets.items()},
        }
        with self._connect() as conn:
            self._ensure(conn)
            conn.execute(
                "INSERT INTO planning_source_versions(version_id, workbook, upload_sha256, metadata) "
                "VALUES (%s, %s, %s, %s)",
                (version_id, name, upload_sha256, Jsonb(record)),
            )
            for sheet, frame in sheets.items():
                payloads = json.loads(frame.to_json(orient="records", date_format="iso"))
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO planning_source_rows(version_id, sheet, ordinal, payload) "
                        "VALUES (%s, %s, %s, %s)",
                        ((version_id, sheet, index, Jsonb(payload)) for index, payload in enumerate(payloads)),
                    )
            conn.execute(
                "INSERT INTO planning_source_heads(workbook, version_id) VALUES (%s, %s) "
                "ON CONFLICT (workbook) DO UPDATE SET version_id = EXCLUDED.version_id",
                (name, version_id),
            )
        return self.version(name)


def source_store() -> SourceStore:
    """Select the source of record without changing any planning stage."""
    return PostgresSourceStore() if get_settings().data_backend == "postgres" else ExcelSourceStore()


def stock_snapshot_date() -> date:
    """The uploaded stock date, or the configured date for the original workbook."""
    metadata = source_store().version("current_stock.xlsx")["metadata"]
    value = metadata.get("stock_snapshot_as_of")
    return date.fromisoformat(value) if value else get_settings().stock_snapshot_as_of
