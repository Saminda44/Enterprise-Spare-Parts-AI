"""MC/OBM model selection and moving-average stability rules."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from src.core.context import PlanningContext
from src.core.errors import SourceDataError
from src.core.result import StageResult
from src.forecast.backtest import _rank_models, _select, rolling_origin_score
from src.forecast.models import CANDIDATES, INSUFFICIENT_HISTORY_CANDIDATES, moving_average
from src.forecast.parc_demand import _forecast, fleet_eligible_skus, forecast_months


def _model_rows(
    segment: str, model: str, score: float, stability: float
) -> list[dict[str, object]]:
    return [
        {
            "active_sku_id": f"{segment}-{model}-{index}",
            "segment": segment,
            "quadrant": "smooth",
            "abc": "A",
            "behaviour_class": "wear",
            "model": model,
            "metric": "rmsse",
            "score": score,
            "bias": 0.0,
            "stability": stability,
            "benchmark": False,
        }
        for index in range(5)
    ]


def test_six_month_average_is_the_only_moving_average_candidate() -> None:
    for candidates in [*CANDIDATES.values(), INSUFFICIENT_HISTORY_CANDIDATES]:
        moving = {name for name in candidates if name.startswith("moving_average_")}
        assert moving <= {"moving_average_6"}
    assert "moving_average_6" in INSUFFICIENT_HISTORY_CANDIDATES


def test_six_month_average_holds_against_small_or_unstable_gain() -> None:
    slight_gain = pd.DataFrame(
        _model_rows("MC", "moving_average_6", 1.0, 0.10) + _model_rows("MC", "ses_0.3", 0.97, 0.05)
    )
    unstable_gain = pd.DataFrame(
        _model_rows("MC", "moving_average_6", 1.0, 0.10) + _model_rows("MC", "ses_0.3", 0.80, 0.20)
    )
    assert _rank_models(slight_gain).index[0] == "moving_average_6"
    assert _rank_models(unstable_gain).index[0] == "moving_average_6"


def test_mc_and_obm_select_independent_champions() -> None:
    frame = pd.DataFrame(
        _model_rows("MC", "moving_average_6", 1.0, 0.10)
        + _model_rows("MC", "ses_0.3", 0.97, 0.05)
        + _model_rows("OBM", "moving_average_6", 1.0, 0.10)
        + _model_rows("OBM", "tsb", 0.80, 0.05)
    )
    selected = _select(
        frame,
        PlanningContext(as_of=date(2026, 10, 1)),
        StageResult(stage="07_model_selection"),
    ).set_index("segment")
    assert selected.loc["MC", "model"] == "moving_average_6"
    assert selected.loc["OBM", "model"] == "tsb"


def test_rolling_origin_reports_bias_and_stability() -> None:
    score, folds, bias, stability = rolling_origin_score(
        np.array([10, 10, 10, 10, 10, 10, 12, 12, 12, 12, 12, 12], dtype=float),
        moving_average(6),
        horizon=2,
        quadrant="smooth",
        min_train=6,
    )
    assert score >= 0
    assert folds == 5
    assert np.isfinite(bias)
    assert stability >= 0


def test_motorcycle_fleet_excludes_obm() -> None:
    classification = pd.DataFrame(
        {
            "active_sku_id": ["MC-1", "OB-1", "MC-2"],
            "segment": ["MC", "OBM", "MC"],
        }
    )
    assert fleet_eligible_skus(classification) == ["MC-1", "MC-2"]


def test_motorcycle_fleet_requires_segment() -> None:
    with pytest.raises(SourceDataError, match="no MC/OBM segment"):
        fleet_eligible_skus(pd.DataFrame({"active_sku_id": ["MC-1"]}))


@pytest.mark.parametrize(
    ("as_of", "first", "last", "count"),
    [
        (date(2026, 10, 1), "2026-10", "2027-12", 15),
        (date(2026, 12, 1), "2026-12", "2027-12", 13),
        (date(2027, 1, 1), "2027-01", "2028-12", 24),
    ],
)
def test_forecast_months_roll_at_calendar_year_end(
    as_of: date, first: str, last: str, count: int
) -> None:
    months = forecast_months(as_of)
    assert (months[0], months[-1], len(months)) == (first, last, count)


def test_monthly_path_covers_every_sku_and_keeps_obm_history_only() -> None:
    classification = pd.DataFrame(
        {
            "active_sku_id": ["MC-1", "OBM-1"],
            "segment": ["MC", "OBM"],
            "quadrant": ["smooth", "smooth"],
            "abc": ["A", "A"],
            "behaviour_class": ["wear", "wear"],
            "insufficient_history": [False, False],
        }
    )
    panel = pd.DataFrame(
        [[1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12]],
        index=["MC-1", "OBM-1"],
        columns=[f"2026-{month:02d}" for month in range(3, 9)],
        dtype=float,
    )
    champions = {(segment, "smooth", "A", "wear"): "moving_average_6" for segment in ("MC", "OBM")}
    months = forecast_months(date(2026, 10, 1))
    live, _, monthly = _forecast(
        PlanningContext(as_of=date(2026, 10, 1)),
        classification,
        panel,
        champions,
        {("MC", "smooth"): "moving_average_6", ("OBM", "smooth"): "moving_average_6"},
        {},
        pd.DataFrame(),
        StageResult(stage="08_forecast"),
        label="live",
        future_months=months,
    )
    assert len(live) == 2
    assert len(monthly) == 2 * len(months)
    assert not monthly.duplicated(["active_sku_id", "month"]).any()
    assert monthly.groupby("active_sku_id")["month"].nunique().eq(len(months)).all()
    assert monthly.loc[monthly["active_sku_id"] == "OBM-1", "mu_month_parc"].isna().all()
    assert monthly.loc[monthly["active_sku_id"] == "MC-1", "forecast_quantity"].eq(3.5).all()


def test_monthly_path_advances_from_fit_month_to_cycle_month() -> None:
    classification = pd.DataFrame(
        {
            "active_sku_id": ["MC-1"],
            "segment": ["MC"],
            "quadrant": ["smooth"],
            "abc": ["A"],
            "behaviour_class": ["wear"],
            "insufficient_history": [False],
        }
    )
    panel = pd.DataFrame(
        [[1, 2, 3, 4, 5, 6, 7, 8]],
        index=["MC-1"],
        columns=[f"2026-{month:02d}" for month in range(1, 9)],
        dtype=float,
    )
    months = forecast_months(date(2026, 10, 1))
    live, _, monthly = _forecast(
        PlanningContext(as_of=date(2026, 10, 1)),
        classification,
        panel,
        {("MC", "smooth", "A", "wear"): "linear_trend"},
        {("MC", "smooth"): "linear_trend"},
        {},
        pd.DataFrame(),
        StageResult(stage="08_forecast"),
        label="live",
        future_months=months,
    )
    assert live.at[0, "fit_through"] == "2026-08"
    assert live.at[0, "mu_month_baseline"] == pytest.approx(10.0)
    assert monthly.iloc[0]["month"] == "2026-10"
    assert monthly.iloc[0]["forecast_quantity"] == pytest.approx(10.0)
