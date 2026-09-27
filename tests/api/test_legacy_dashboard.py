"""Synthetic integration contracts for the original dashboard and new pipeline."""

from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from src.api.compat.exports import order_workbook
from src.api.compat.filters import clear_cache, mart
from src.api.main import app
from src.core.context import PlanningContext
from src.core.result import StageResult
from src.core.settings import get_settings
from src.dashboard import sku
from src.dashboard.compatibility import service_plan, validate_output
from src.io.parquet import write_table


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPI_ROOT", str(tmp_path))
    get_settings.cache_clear()
    get_settings().ensure_dirs()
    clear_cache()
    yield tmp_path
    clear_cache()
    get_settings.cache_clear()


@pytest.fixture
def published_sku(workspace: Path) -> pd.DataFrame:
    key = {"active_sku_id": "SYNTHETIC-PART"}
    tables = {
        "sku_classification": {
            **key,
            "description": "Synthetic part",
            "abc": "A",
            "xyz": "X",
            "fsn": "F",
            "quadrant": "smooth",
            "mean_monthly_demand": 10.0,
            "cv_monthly": 0.2,
            "nonzero_months": 12,
            "months_observed": 12,
            "annual_consumption_value": 1200.0,
            "last_demand_month": "2025-12",
            "behaviour_class": "wear",
            "criticality": None,
        },
        "forecast_protection": {
            **key,
            "model": "naive",
            "mu_month": 10.0,
            "mu_month_baseline": 9.0,
            "mu_month_parc": 12.0,
            "mu_p": 40.0,
            "sigma_p": 4.0,
            "p50": 40.0,
            "p90": 45.0,
            "p95": 48.0,
        },
        "policy_params": {
            **key,
            "fill_target": 0.98,
            "z": 2.0,
            "safety_stock": 8.0,
            "ss_strategy": "normal",
            "rol": 38.0,
            "months_of_cover": 4.0,
            "unit_value": 12.0,
        },
        "policy_selection": {**key, "policy": "R_S"},
        "stock_position": {
            **key,
            "on_hand": 0.0,
            "on_order": 20.0,
            "backorders": 2.0,
            "ip": 18.0,
            "storage_locations": "SYNTHETIC",
        },
        "monthly_order_proposal": {
            **key,
            "q_final": 25.0,
            "q_raw": 22.0,
            "unit_cost": 10.0,
            "value": 250.0,
            "cycle_month": "2025-12",
            "lead_time_months": 3,
            "trigger_reason": "review",
        },
        "orders_by_material": {
            **key,
            "ordered_quantity": 120.0,
            "confirmed_quantity": 90.0,
            "order_value": 1200.0,
            "fill_rate": 0.75,
        },
        "part_master_enriched": {
            **key,
            "material": "SYNTHETIC-PART",
            "description": "Synthetic part",
            "chain_depth": 0,
            "compatible_models": "SYNTHETIC-MODEL",
            "part_kind": "shared",
            "material_group": "parts",
            "brand": "test",
        },
    }
    for name, row in tables.items():
        write_table(pd.DataFrame([row]), "facts", name)
    result = StageResult("15_dashboard")
    frame = sku.build(PlanningContext(as_of=date(2025, 12, 1)), result)
    validate_output(frame, "mart_ui_sku")
    write_table(frame, "marts", "mart_ui_sku")
    write_table(sku.overview(frame, result), "marts", "mart_ui_overview")
    write_table(service_plan(frame), "marts", "mart_ui_service_plan")
    write_table(pd.DataFrame([tables["monthly_order_proposal"]]), "marts", "mart_monthly_order")
    return frame


def test_forecast_and_order_reconcile_to_new_pipeline(published_sku: pd.DataFrame) -> None:
    row = published_sku.iloc[0]
    assert row["forecast_lt"] == 30.0  # Three months, not the four-month protection demand.
    assert row["forecast_month"] == "2026-01"
    assert row["net_requirement"] == row["roq"] == 25.0  # Pack-rounded, not raw 22.
    assert row["unit_value_lkr"] == 10.0
    client = TestClient(app)
    overview = client.get("/api/v1/overview/kpis").json()
    assert overview["kpis"]["total_order_value_lkr"] == 250.0
    assert overview["stock_status"] == {"stockout": 1}
    policy = client.get("/api/v1/policy?urgency=soon").json()
    assert policy["rows"][0]["order_urgency"] == "soon"
    assert policy["rows"][0]["net_requirement"] == 25.0
    assert client.get("/api/v1/inventory?status=stockout").json()["total"] == 1
    assert client.get("/api/v1/classification?tier=R_S&part_type=shared").json()["total"] == 1
    assert client.get("/api/v1/classification?part_type=absent").json()["total"] == 0


@pytest.mark.parametrize(
    "path",
    [
        "forecast",
        "policy",
        "classification",
        "inventory",
        "forecast/fused-demand",
        "inventory/position",
    ],
)
def test_pagination_validation(published_sku: pd.DataFrame, path: str) -> None:
    client = TestClient(app)
    assert client.get("/api/v1/" + path + "?offset=-1").status_code == 422
    assert client.get("/api/v1/" + path + "?limit=0").status_code == 422
    response = client.get("/api/v1/" + path + "?limit=1&offset=1")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["rows"] == []


def test_service_plan_uses_parc_and_keeps_final_policy(published_sku: pd.DataFrame) -> None:
    original = published_sku.copy(deep=True)
    frame = service_plan(published_sku)
    row = frame.loc[frame["horizon_months"] == 5].iloc[0]
    assert row["service_plan_qty"] == 60.0
    assert row["recommended_order"] == 25.0
    pd.testing.assert_frame_equal(published_sku, original)
    response = TestClient(app).get("/api/v1/policy/uio-service-plan?horizon_months=5").json()
    assert response["rows"][0]["service_plan_qty"] == 60.0
    assert response["rows"][0]["recommended_order"] == 25.0


def test_trend_does_not_mix_other_sku_returns(workspace: Path) -> None:
    write_table(
        pd.DataFrame(
            [
                {
                    "active_sku_id": "A",
                    "month": "2025-12",
                    "ordered_quantity": 10.0,
                    "confirmed_quantity": 8.0,
                    "order_value": 100.0,
                }
            ]
        ),
        "facts",
        "demand_history",
    )
    write_table(
        pd.DataFrame(
            [
                {"active_sku_id": "A", "month": "2025-12", "ordered_quantity": 2.0},
                {"active_sku_id": "B", "month": "2025-12", "ordered_quantity": 99.0},
            ]
        ),
        "facts",
        "returns_history",
    )
    row = TestClient(app).get("/api/v1/forecast/trend?sku=A").json()[0]
    assert row["return_qty"] == 2.0
    assert row["net_demand"] == 10.0  # C-order demand stays gross; returns are separate.


def test_cache_observes_republished_mart(workspace: Path) -> None:
    write_table(pd.DataFrame({"value": [1]}), "marts", "synthetic")
    assert mart("synthetic").iloc[0]["value"] == 1
    write_table(pd.DataFrame({"value": [2, 3]}), "marts", "synthetic")
    assert mart("synthetic")["value"].tolist() == [2, 3]


def test_export_has_final_quantities_metadata_and_literal_cells(
    published_sku: pd.DataFrame,
) -> None:
    response = TestClient(app).get("/api/v1/policy/export.xlsx?urgency=soon")
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content))
    assert "Metadata" in book.sheetnames
    metadata = dict(book["Metadata"].values)
    assert {
        "source_file_hashes",
        "code_commit_sha",
        "generated_at_utc",
        "model_version",
    } <= metadata.keys()
    assert book["Order Plan"].oddFooter.left.text
    frame = pd.DataFrame(
        {"active_sku_id": ["001"], "description": ["=1+1"], "q_final": [25.0], "value": [250.0]}
    )
    book = load_workbook(BytesIO(order_workbook(frame, {"model_version": "synthetic"})))
    assert book["Order Plan"]["B2"].data_type == "s"


def test_missing_api_does_not_serve_html(workspace: Path) -> None:
    client = TestClient(app)
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert client.get("/api/v1/overview/kpis").status_code == 503


def test_original_ui_is_served_and_deep_links_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.api.main as main

    (tmp_path / "index.html").write_text("<html>Original UI</html>", encoding="utf-8")
    monkeypatch.setattr(main, "DASHBOARD_DIR", tmp_path)
    client = TestClient(app)
    assert client.get("/").text == "<html>Original UI</html>"
    assert client.get("/orders").text == "<html>Original UI</html>"


def test_run_history_reads_persisted_status(workspace: Path) -> None:
    report = {
        "started_at": "2025-12-01T00:00:00+00:00",
        "finished_at": "2025-12-01T00:01:00+00:00",
        "ok": False,
        "stages": [{"stage": "15_dashboard", "status": "failed"}],
    }
    (get_settings().reports_dir / "run_synthetic.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    client = TestClient(app)
    jobs = client.get("/api/v1/pipeline/jobs").json()
    assert jobs["total"] == 1
    assert jobs["jobs"][0]["status"] == "FAILED"
    assert client.get("/api/v1/pipeline/jobs/synthetic").json()["status"] == "FAILED"


def test_new_requirement_summary_covers_all_filtered_rows(published_sku: pd.DataFrame) -> None:
    extra = published_sku.copy()
    extra["material_9"] = extra["active_sku_id"] = "SYNTHETIC-SECOND"
    extra["description"] = "Second test part"
    extra["value"] = 400.0
    write_table(pd.concat([published_sku, extra], ignore_index=True), "marts", "mart_ui_sku")
    client = TestClient(app)
    data = client.get("/api/v1/policy?limit=1").json()
    assert len(data["rows"]) == 1
    assert data["total"] == 2
    assert data["total_order_value_lkr"] == 650.0
    filtered = client.get("/api/v1/policy?search=SECOND").json()
    assert filtered["total_order_value_lkr"] == 400.0
    assert filtered["total"] == 1
    forecast = client.get("/api/v1/forecast?search=SECOND").json()
    assert forecast["total"] == forecast["parc_skus"] == 1
    assert forecast["zero_demand_skus"] == 0


def test_default_service_plan_uses_protection_interval(published_sku: pd.DataFrame) -> None:
    write_table(
        pd.DataFrame([{"arm": "selected", "verdict": "FRONTIER", "fill_rate": 0.96}]),
        "marts",
        "mart_service_and_stock",
    )
    client = TestClient(app)
    data = client.get("/api/v1/policy/uio-service-plan").json()
    assert data["horizon_months"] == 4
    assert data["rows"][0]["service_plan_qty"] == 48.0
    assert data["rows"][0]["avg_monthly"] == 12.0
    overview = client.get("/api/v1/overview/kpis").json()
    assert overview["planning"]["policy_verdict"] == "FRONTIER"
    assert overview["planning"]["protection_interval_months"] == 4


def test_uio_comparison_does_not_copy_fleet_into_recent_sales(workspace: Path) -> None:
    write_table(
        pd.DataFrame(
            [
                {
                    "year": 2025,
                    "model_name": "Synthetic model",
                    "uio_forecast": 200.0,
                    "is_forecast": False,
                }
            ]
        ),
        "marts",
        "mart_ui_parc_by_model",
    )
    write_table(
        pd.DataFrame(
            [
                {
                    "year": 2025,
                    "model_name": "Synthetic model",
                    "units_sold": 12.0,
                    "returned": 1.0,
                    "revenue_lkr": 120.0,
                    "vins": 13.0,
                    "dealers": 1.0,
                }
            ]
        ),
        "marts",
        "mart_ui_mc_by_model",
    )
    data = TestClient(app).get("/api/v1/bikes/uio").json()
    assert data["external"][0]["uio"] == 200.0
    assert data["mcsi"][0]["uio"] == 12.0
    assert data["mcsi"][0]["uio_pct"] == 100.0


def test_master_view_uses_resolved_identity_without_catalogue(published_sku: pd.DataFrame) -> None:
    master = pd.DataFrame(
        [
            {
                "material": "OLD",
                "active_sku_id": "NEW",
                "description": "Old part",
                "chain_depth": 1,
                "compatible_models": None,
                "part_kind": None,
            },
            {
                "material": "NEW",
                "active_sku_id": "NEW",
                "description": "Current part",
                "chain_depth": 0,
                "compatible_models": None,
                "part_kind": None,
            },
        ]
    )
    write_table(master, "facts", "part_master_enriched")
    data = TestClient(app).get("/api/v1/parts/master-view").json()
    assert data["total"] == 1
    assert data["source"] == "PN_Yamaha"
    assert data["rows"][0]["part_no"] == "NEW"
    assert data["rows"][0]["description"] == "Current part"
    assert data["rows"][0]["kind"] == "unclassified"


def test_location_unknown_values_are_not_reported_as_zero(workspace: Path) -> None:
    write_table(pd.DataFrame([{"Plant": "W1B4", "Unrestricted": 20.0}]), "facts", "stock_by_plant")
    row = TestClient(app).get("/api/v1/inventory/stock-by-location").json()[0]
    assert row["qty"] == 20.0
    assert row["value_lkr"] is None
    assert row["sku_count"] is None
