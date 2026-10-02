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
from src.dashboard.segments import SEGMENT_MC, sku_segments
from src.forecast.models import (
    BENCHMARKS,
    CANDIDATES,
    FALLBACK_MODEL,
    INSUFFICIENT_HISTORY_CANDIDATES,
    Forecaster,
)
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


def rmsse(actual: np.ndarray, predicted: np.ndarray, train: np.ndarray) -> float:
    """Root mean squared scaled error.

    Business meaning: squared error is smallest for the true average rate, so it does not
    reward forecasting low (MASE's absolute error favours the median, which is zero for
    sparse parts) or high (pinball at the service quantile). The order sizes buffer stock
    separately; the forecast itself should be the expected monthly demand (owner,
    2026-10-02). The scale makes parts of different sizes comparable.
    """
    if train.size < 2:
        return float("nan")
    scale = float(np.mean(np.diff(train) ** 2))
    if scale <= 0:
        scale = float(np.mean(train) ** 2) or 1.0
    return float(np.sqrt(np.mean((actual - predicted) ** 2) / scale))


def metric_for(quadrant: str) -> str:  # noqa: ARG001 - one metric for every quadrant now
    return "rmsse"


def rolling_origin_score(
    series: np.ndarray, forecaster: Forecaster, horizon: int, quadrant: str, min_train: int
) -> tuple[float, int, float, float]:
    """Return expanding-window accuracy, signed bias and forecast volatility.

    Business meaning: a model must be accurate without making purchase quantities jump
    between monthly reviews. Bias and volatility are normalized by realised demand so MC
    and OBM parts of different scales remain comparable.
    """
    scores: list[float] = []
    forecast_levels: list[float] = []
    actual_levels: list[float] = []
    for origin in range(min_train, series.size - horizon + 1):
        train = series[:origin]
        actual = series[origin : origin + horizon]
        predicted = np.asarray(forecaster(train, horizon), dtype=float)
        if predicted.size != actual.size:
            continue
        score = rmsse(actual, predicted, train)
        if not np.isnan(score):
            scores.append(score)
            forecast_levels.append(float(predicted.mean()))
            actual_levels.append(float(actual.mean()))
    if not scores:
        return float("nan"), 0, float("nan"), float("nan")
    scale = max(float(np.mean(np.abs(actual_levels))), 1.0)
    bias = float(np.mean(np.asarray(forecast_levels) - np.asarray(actual_levels)) / scale)
    stability = (
        float(np.mean(np.abs(np.diff(forecast_levels))) / scale)
        if len(forecast_levels) > 1
        else 0.0
    )
    return float(np.mean(scores)), len(scores), bias, stability


@REGISTRY.register(
    "07_model_selection",
    depends_on=["06_classification"],
    description="rolling-origin backtest and champion per segment",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="07_model_selection")
    history = read_table("facts", "demand_history")
    classification = read_table("facts", "sku_classification")
    master = read_table("facts", "part_master")
    classification = classification.copy()
    classification["segment"] = (
        classification["active_sku_id"].astype(str).map(sku_segments(master)).fillna(SEGMENT_MC)
    )
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
            f"{min_train + horizon} a rolling-origin fold needs — every segment falls back to "
            f"{FALLBACK_MODEL}"
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
        pool = [(name, f, False) for name, f in candidates.items()]
        pool += [(name, f, True) for name, f in BENCHMARKS.items() if name not in candidates]
        for name, forecaster, benchmark in pool:
            score, folds, bias, stability = rolling_origin_score(
                values, forecaster, horizon, quadrant, min_train
            )
            if folds == 0:
                continue
            rows.append(
                {
                    "active_sku_id": sku,
                    "segment": str(info.get("segment", SEGMENT_MC)),
                    "quadrant": quadrant,
                    "abc": str(info.get("abc", "C")),
                    "behaviour_class": str(info.get("behaviour_class", "unclassified")),
                    "model": name,
                    "metric": metric_for(quadrant),
                    "score": score,
                    "bias": bias,
                    "stability": stability,
                    "folds": folds,
                    "benchmark": benchmark,
                }
            )

    backtest = pd.DataFrame(rows)
    if backtest.empty:
        result.warn(
            f"no backtest folds could be scored — every segment defaults to {FALLBACK_MODEL}"
        )
        registry = pd.DataFrame(
            [
                {
                    "combination": "ALL",
                    "segment": "ALL",
                    "quadrant": "ALL",
                    "abc": "ALL",
                    "behaviour_class": "ALL",
                    "model": FALLBACK_MODEL,
                    "score": np.nan,
                    "bias": np.nan,
                    "stability": np.nan,
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


def _rank_models(group: pd.DataFrame) -> pd.DataFrame:
    """Rank candidates with the six-month moving average as stable incumbent."""
    ranked = (
        group.groupby("model")
        .agg(score=("score", "mean"), bias=("bias", "mean"), stability=("stability", "mean"))
        .assign(abs_bias=lambda frame: frame["bias"].abs())
        .sort_values(["score", "stability", "abs_bias"])
    )
    if ranked.empty or FALLBACK_MODEL not in ranked.index:
        return ranked
    best = str(ranked.index[0])
    if best == FALLBACK_MODEL:
        return ranked
    incumbent = ranked.loc[FALLBACK_MODEL]
    challenger = ranked.loc[best]
    gain = (
        (float(incumbent["score"]) - float(challenger["score"])) / float(incumbent["score"])
        if float(incumbent["score"]) > 0
        else 0.0
    )
    if gain < HYSTERESIS_MARGIN or float(challenger["stability"]) > float(incumbent["stability"]):
        order = [FALLBACK_MODEL, *[name for name in ranked.index if name != FALLBACK_MODEL]]
        return ranked.loc[order]
    return ranked


def _select(backtest: pd.DataFrame, ctx: PlanningContext, result: StageResult) -> pd.DataFrame:
    """Champion per (segment x quadrant x ABC x behaviour).

    Business meaning: MC and OBM never share a champion. A challenger replaces the
    six-month moving average only when it is at least 5% more accurate and no more
    volatile. Benchmarks are reported but never selected.
    """
    is_benchmark = backtest.get("benchmark", pd.Series(False, index=backtest.index)).astype(bool)
    benchmarks = backtest[is_benchmark]
    candidates = backtest[~is_benchmark]
    quadrant_champion: dict[tuple[str, str], str] = {}
    for (segment, quadrant), group in candidates.groupby(["segment", "quadrant"]):
        ranked = _rank_models(group)
        if len(ranked):
            quadrant_champion[(str(segment), str(quadrant))] = str(ranked.index[0])

    rows: list[dict[str, object]] = []
    grouped = candidates.groupby(["segment", "quadrant", "abc", "behaviour_class"])
    for (segment, quadrant, abc, behaviour), group in grouped:
        parts = group["active_sku_id"].nunique()
        ranked = _rank_models(group)
        inherited = parts < MIN_PARTS_PER_COMBINATION or ranked.empty
        if inherited:
            model = quadrant_champion.get((str(segment), str(quadrant)), FALLBACK_MODEL)
        else:
            model = str(ranked.index[0])
        selected = ranked.loc[model] if model in ranked.index else None
        best_score = float(selected["score"]) if selected is not None else np.nan
        selected_bias = float(selected["bias"]) if selected is not None else np.nan
        selected_stability = float(selected["stability"]) if selected is not None else np.nan
        runner_up = next((str(name) for name in ranked.index if name != model), None)
        runner_score = float(ranked.loc[runner_up, "score"]) if runner_up is not None else np.nan
        naive_rows = benchmarks[
            (benchmarks["segment"] == segment)
            & (benchmarks["quadrant"] == quadrant)
            & (benchmarks["abc"] == abc)
            & (benchmarks["behaviour_class"] == behaviour)
            & (benchmarks["model"] == "naive")
        ]
        naive_score = float(naive_rows["score"].mean()) if len(naive_rows) else np.nan

        rows.append(
            {
                "combination": f"{segment}|{quadrant}|{abc}|{behaviour}",
                "segment": segment,
                "quadrant": quadrant,
                "abc": abc,
                "behaviour_class": behaviour,
                "model": model,
                "score": best_score,
                "bias": selected_bias,
                "stability": selected_stability,
                "runner_up": runner_up,
                "runner_up_score": runner_score,
                "naive_score": naive_score,
                "parts": int(parts),
                "metric": str(group["metric"].iloc[0]),
                "inherited": bool(inherited),
                "selected_on": str(ctx.as_of),
            }
        )

    registry = pd.DataFrame(rows)
    inherited_count = int(registry["inherited"].sum())
    result.warn(
        f"{len(registry)} segment combination(s) scored; {inherited_count} inherited their "
        f"segment/quadrant champion for having fewer than {MIN_PARTS_PER_COMBINATION} parts"
    )
    result.warn(f"champions by segment and quadrant: {quadrant_champion}")
    comparable = registry.dropna(subset=["score", "naive_score"])
    beats = int((comparable["score"] < comparable["naive_score"]).sum())
    result.warn(
        f"benchmark: the chosen model beats last-month-only (naive) in {beats} of "
        f"{len(comparable)} combination(s); naive and mean are reported, never chosen"
    )
    return registry
