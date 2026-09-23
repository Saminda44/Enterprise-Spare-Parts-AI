"""Step 07 — rolling-origin backtest and champion selection.

This step does not forecast. It decides, per classification combination, which model to
use, and records why it won.

Never a random split: shuffling a time series leaks the future into the past. The origin
steps forward one month at a time and a fit only ever sees data up to it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.forecast.models import CANDIDATES, INSUFFICIENT_HISTORY_CANDIDATES, Forecaster
from src.io.parquet import read_table, write_table

#: The final months are split off and sealed here, opened once in Step 13, never
#: re-opened. 12 months is the specification's default; with a 24-month file that leaves
#: too little to select on, so it is reduced to 6 and stated.
DEFAULT_HOLDOUT_MONTHS = 12
SHORT_FILE_HOLDOUT_MONTHS = 6
SHORT_FILE_THRESHOLD = 30

#: Fill-rate service quantile used by the pinball loss on intermittent series.
SERVICE_QUANTILE = 0.95

#: A combination with fewer parts than this inherits its parent quadrant's champion.
MIN_PARTS_PER_COMBINATION = 5

#: A challenger must beat the incumbent by this margin to replace it.
HYSTERESIS_MARGIN = 0.05


def mase(actual: np.ndarray, predicted: np.ndarray, train: np.ndarray) -> float:
    """Scale-free, comparable across parts. Denominator is the naive-1 MAE on train."""
    if train.size < 2:
        return float("nan")
    scale = np.abs(np.diff(train)).mean()
    if scale <= 0:
        return float("nan")
    return float(np.abs(actual - predicted).mean() / scale)


def pinball(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    """Pinball loss at the service quantile.

    MAPE is undefined on zeros and MASE rewards forecasting zero, so intermittent and
    lumpy series are scored here instead.
    """
    delta = actual - predicted
    return float(np.mean(np.maximum(quantile * delta, (quantile - 1) * delta)))


def metric_for(quadrant: str) -> str:
    return "mase" if quadrant in {"smooth", "erratic"} else "pinball"


def rolling_origin_score(
    series: np.ndarray, forecaster: Forecaster, horizon: int, quadrant: str, min_train: int
) -> tuple[float, int]:
    """Expanding window, origin stepping forward one month. Returns (score, folds)."""
    scores: list[float] = []
    for origin in range(min_train, series.size - horizon + 1):
        train = series[:origin]
        actual = series[origin : origin + horizon]
        predicted = np.asarray(forecaster(train, horizon), dtype=float)
        if predicted.size != actual.size:
            continue
        if metric_for(quadrant) == "mase":
            score = mase(actual, predicted, train)
        else:
            score = pinball(actual, predicted, SERVICE_QUANTILE)
        if not np.isnan(score):
            scores.append(score)
    if not scores:
        return float("nan"), 0
    return float(np.mean(scores)), len(scores)


@REGISTRY.register(
    "07_model_selection",
    depends_on=["06_classification"],
    description="rolling-origin backtest and champion per segment",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="07_model_selection")
    history = read_table("facts", "demand_history")
    classification = read_table("facts", "sku_classification")
    result.rows_in = len(classification)

    months = sorted(history["month"].dropna().unique())
    horizon = ctx.protection_interval_months
    holdout_months = (
        SHORT_FILE_HOLDOUT_MONTHS if len(months) < SHORT_FILE_THRESHOLD else DEFAULT_HOLDOUT_MONTHS
    )
    if holdout_months != DEFAULT_HOLDOUT_MONTHS:
        result.warn(
            f"HOLDOUT REDUCED to {holdout_months} months: the file carries {len(months)} months, "
            f"so a {DEFAULT_HOLDOUT_MONTHS}-month holdout would leave too little to select on"
        )
    selection_months = months[: len(months) - holdout_months]
    holdout_start = months[len(months) - holdout_months]
    result.warn(
        f"history {months[0]}..{months[-1]}; selection window {selection_months[0]}.."
        f"{selection_months[-1]}; holdout {holdout_start}..{months[-1]} SEALED — opened once "
        f"in Step 13, never re-opened"
    )
    result.warn(
        f"seasonal candidates (SARIMA, Prophet) dropped: {len(months)} months is fewer than the "
        f"two full seasonal cycles they require. TFT dropped: panel too short."
    )

    panel = (
        history.pivot_table(
            index="active_sku_id", columns="month", values="ordered_quantity", aggfunc="sum"
        )
        .reindex(columns=months)
        .fillna(0.0)
    )
    selection_panel = panel[selection_months]
    min_train = max(3, horizon)

    if selection_panel.shape[1] < min_train + horizon:
        result.warn(
            f"selection window has {selection_panel.shape[1]} months, fewer than the "
            f"{min_train + horizon} a rolling-origin fold needs — every segment falls back to naive"
        )

    meta = classification.set_index("active_sku_id")
    rows: list[dict[str, object]] = []
    for sku, series in selection_panel.iterrows():
        if sku not in meta.index:
            continue
        info = meta.loc[sku]
        quadrant = str(info.get("quadrant", "no demand"))
        candidates = (
            INSUFFICIENT_HISTORY_CANDIDATES
            if bool(info.get("insufficient_history", False))
            else CANDIDATES.get(quadrant, CANDIDATES["no demand"])
        )
        values = series.to_numpy(dtype=float)
        for name, forecaster in candidates.items():
            score, folds = rolling_origin_score(values, forecaster, horizon, quadrant, min_train)
            if folds == 0:
                continue
            rows.append(
                {
                    "active_sku_id": sku,
                    "quadrant": quadrant,
                    "abc": str(info.get("abc", "C")),
                    "behaviour_class": str(info.get("behaviour_class", "unclassified")),
                    "model": name,
                    "metric": metric_for(quadrant),
                    "score": score,
                    "folds": folds,
                }
            )

    backtest = pd.DataFrame(rows)
    if backtest.empty:
        result.warn("no backtest folds could be scored — every segment defaults to naive")
        registry = pd.DataFrame(
            [
                {
                    "combination": "ALL",
                    "quadrant": "ALL",
                    "abc": "ALL",
                    "behaviour_class": "ALL",
                    "model": "naive",
                    "score": np.nan,
                    "runner_up": None,
                    "runner_up_score": np.nan,
                    "parts": 0,
                    "metric": "none",
                    "inherited": True,
                    "selected_on": str(ctx.as_of),
                }
            ]
        )
    else:
        result.artifact("backtest_results", write_table(backtest, "facts", "backtest_results"))
        registry = _select(backtest, ctx, result)

    result.rows_out = len(registry)
    result.artifact("model_registry", write_table(registry, "facts", "model_registry"))

    split = pd.DataFrame(
        [
            {
                "holdout_start": holdout_start,
                "holdout_months": holdout_months,
                "selection_start": selection_months[0],
                "selection_end": selection_months[-1],
                "horizon_months": horizon,
            }
        ]
    )
    result.artifact("holdout_split", write_table(split, "facts", "holdout_split"))

    logger.info(f"model registry: {len(registry)} combination(s)")
    return result


def _select(backtest: pd.DataFrame, ctx: PlanningContext, result: StageResult) -> pd.DataFrame:
    """Champion per (quadrant × ABC × behaviour), falling back to the parent quadrant."""
    quadrant_champion: dict[str, str] = {}
    for quadrant, group in backtest.groupby("quadrant"):
        ranked = group.groupby("model")["score"].mean().sort_values()
        if len(ranked):
            quadrant_champion[str(quadrant)] = str(ranked.index[0])

    rows: list[dict[str, object]] = []
    grouped = backtest.groupby(["quadrant", "abc", "behaviour_class"])
    for (quadrant, abc, behaviour), group in grouped:
        parts = group["active_sku_id"].nunique()
        ranked = group.groupby("model")["score"].mean().sort_values()
        inherited = parts < MIN_PARTS_PER_COMBINATION or ranked.empty
        if inherited:
            model = quadrant_champion.get(str(quadrant), "naive")
            best_score = float(ranked.iloc[0]) if len(ranked) else np.nan
            runner_up, runner_score = None, np.nan
        else:
            model = str(ranked.index[0])
            best_score = float(ranked.iloc[0])
            runner_up = str(ranked.index[1]) if len(ranked) > 1 else None
            runner_score = float(ranked.iloc[1]) if len(ranked) > 1 else np.nan
            # If the champion cannot beat naive, use naive and record it.
            if "naive" in ranked.index and model != "naive":
                naive_score = float(ranked.loc["naive"])
                if best_score > naive_score * (1 - HYSTERESIS_MARGIN):
                    model, best_score = "naive", naive_score

        rows.append(
            {
                "combination": f"{quadrant}|{abc}|{behaviour}",
                "quadrant": quadrant,
                "abc": abc,
                "behaviour_class": behaviour,
                "model": model,
                "score": best_score,
                "runner_up": runner_up,
                "runner_up_score": runner_score,
                "parts": int(parts),
                "metric": str(group["metric"].iloc[0]),
                "inherited": bool(inherited),
                "selected_on": str(ctx.as_of),
            }
        )

    registry = pd.DataFrame(rows)
    inherited_count = int(registry["inherited"].sum())
    result.warn(
        f"{len(registry)} combination(s) scored; {inherited_count} inherited their quadrant's "
        f"champion for having fewer than {MIN_PARTS_PER_COMBINATION} parts"
    )
    result.warn(f"champions by quadrant: {quadrant_champion}")
    return registry
