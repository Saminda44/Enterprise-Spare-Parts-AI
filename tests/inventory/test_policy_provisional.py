"""A future scenario must not evaluate history from projected current stock."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from src.core.context import PlanningContext
from src.inventory import policy


def test_provisional_policy_recomputes_target_without_holdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    forecast = pd.DataFrame(
        {
            "active_sku_id": ["A"],
            "mu_month": [10.0],
            "mu_p": [50.0],
            "sigma_p": [2.0],
            "p95": [54.0],
            "quadrant": ["smooth"],
            "insufficient_history": [False],
        }
    )
    tables = {
        "forecast_protection": forecast,
        "forecast_live": forecast,
        "sku_classification": pd.DataFrame({"active_sku_id": ["A"], "abc": ["B"]}),
        "stock_position": pd.DataFrame(
            {"active_sku_id": ["A"], "on_hand": [3.0], "on_order": [0.0], "ip": [3.0]}
        ),
        "supply_reliability": pd.DataFrame({"active_sku_id": ["A"], "beta_hat": [0.9]}),
        "lead_time_stats": pd.DataFrame(columns=["scope", "std_days"]),
        "demand_history": pd.DataFrame(
            {
                "active_sku_id": ["A", "A"],
                "month": ["2026-07", "2026-08"],
                "ordered_quantity": [10.0, 12.0],
            }
        ),
        "holdout_split": pd.DataFrame({"holdout_start": ["2026-08"]}),
        "orders_clean": pd.DataFrame(
            {"active_sku_id": ["A"], "order_value": [100.0], "confirmed_quantity": [10.0]}
        ),
        "policy_selection": pd.DataFrame({"active_sku_id": ["A"], "policy": ["RS"]}),
    }
    written: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(policy, "read_table", lambda layer, name: tables[name].copy())

    def capture(frame: pd.DataFrame, layer: str, name: str) -> Path:
        written[name] = frame.copy()
        return tmp_path / name

    monkeypatch.setattr(policy, "write_table", capture)
    result = policy.run(PlanningContext(as_of=date(2026, 12, 1), config={"provisional": True}))

    assert result.rows_out == 1
    assert set(written) == {"policy_params"}
    assert written["policy_params"].at[0, "mu_p"] == 50.0
    assert written["policy_params"].at[0, "basis"] == "live_provisional"
    assert any("NOT validated" in warning for warning in result.warnings)
    assert not any("ACCEPTANCE GATE" in warning for warning in result.warnings)
