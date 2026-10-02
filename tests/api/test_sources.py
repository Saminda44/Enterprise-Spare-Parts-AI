"""Managed source upload behavior."""

from types import SimpleNamespace

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src import refresh
from src.api.compat import sources


def test_unchanged_stock_upload_records_new_snapshot_date(monkeypatch) -> None:
    published: dict[str, object] = {}
    frame = pd.DataFrame({"Material": ["A"], "Unrestricted": [1.0]})
    merged = SimpleNamespace(
        incoming=1,
        added=0,
        replaced=0,
        unchanged=1,
        conflicts=0,
        warnings=[],
        notes=[],
        frame=frame,
    )
    payload = {
        "name": "current_stock.xlsx",
        "version": "version-1",
        "incoming": 1,
        "added": 0,
        "replaced": 0,
        "unchanged": 1,
        "conflicts": 0,
        "result_rows": 1,
        "warnings": [],
        "notes": [],
        "summary_updated": False,
    }

    class FakeStore:
        def version(self, _name: str) -> dict:
            return {
                "version_id": "version-1",
                "metadata": {"stock_snapshot_as_of": "2026-08-31"},
            }

        def read(self, _name: str) -> dict[str, pd.DataFrame]:
            return {"Sheet1": frame}

        def publish(
            self,
            name: str,
            sheets: dict[str, pd.DataFrame],
            *,
            upload_sha256: str,
            metadata: dict,
        ) -> dict:
            published.update(
                name=name,
                sheets=sheets,
                upload_sha256=upload_sha256,
                metadata=metadata,
            )
            return self.version(name)

    monkeypatch.setattr(sources, "_authorize", lambda _request: None)
    monkeypatch.setattr(sources, "_prepare", lambda *_args: (payload, merged, None))
    monkeypatch.setattr(sources, "source_store", lambda: FakeStore())
    monkeypatch.setattr(refresh, "refresh_in_background", lambda _reason: True)

    app = FastAPI()
    app.include_router(sources.router)
    response = TestClient(app).post(
        "/sources/apply",
        data={
            "name": "current_stock.xlsx",
            "expected_version": "version-1",
            "stock_snapshot_as_of": "2026-09-30",
        },
        files={"file": ("current_stock.xlsx", b"unchanged")},
    )

    assert response.status_code == 200
    assert response.json()["applied"] is True
    assert response.json()["refresh_started"] is True
    assert published["metadata"]["stock_snapshot_as_of"] == "2026-09-30"
