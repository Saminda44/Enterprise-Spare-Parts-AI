"""Model-level motorcycle sales forecasts, and a backtest that scores them on held-out months.

The published forecast and the backtest call the same functions, so a backtest result
describes exactly the method the MC Sales Forecast page shows.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

#: z for a two-sided 80% interval.
Z80 = 1.2816
#: Months the published run rate averages over.
RUN_RATE_MONTHS = 12
#: Months the recent-average alternative averages over.
RECENT_MONTHS = 6

#: A forecast method: (observed period/actual_units rows, horizon periods) -> points.
Method = Callable[[pd.DataFrame, list[str]], list[float]]


def horizon_after(last_period: str, months: int) -> list[str]:
    """The ``months`` periods (YYYY-MM) that follow ``last_period``."""
    last = pd.Period(last_period, freq="M")
    return [str(last + i) for i in range(1, months + 1)]


def seasonal_run_rate(
    observed: pd.DataFrame, horizon: list[str], total: float | None = None
) -> list[float]:
    """The published method: a run-rate total spread on the model's month-of-year profile.

    Business meaning: the model's average month over its last ``RUN_RATE_MONTHS`` months
    with sales, times the horizon length, is the volume to place; each month's share of
    it follows that calendar month's average in the model's history, so a model that sells
    into a festival month keeps that shape. A month the history has never seen gets the
    profile's mean.

    Args:
        observed: one model's rows with ``period`` (YYYY-MM) and ``actual_units``, only
            months that had sales.
        horizon: the periods to forecast.
        total: an externally supplied horizon total; the run rate is used when absent.

    Returns:
        One point forecast per horizon period.
    """
    if observed.empty:
        return [0.0] * len(horizon)
    ordered = observed.sort_values("period")
    if total is None:
        total = float(ordered["actual_units"].tail(RUN_RATE_MONTHS).mean() * len(horizon))
    profile = (
        ordered.assign(mth=ordered["period"].astype(str).str.slice(5, 7))
        .groupby("mth")["actual_units"]
        .mean()
    )
    fallback = float(profile.mean()) if len(profile) else 1.0
    weights = [float(profile.get(period[5:7], fallback)) for period in horizon]
    weight_sum = sum(weights) or 1.0
    return [total * weight / weight_sum for weight in weights]


def monthly_series(observed: pd.DataFrame, last_period: str) -> pd.Series:
    """The model's monthly units from its first sale to ``last_period``, gaps as zero.

    Business meaning: a month in which a model sold nothing is a real zero for it, once it
    is on sale; before its first sale it is not yet in the range and is left out.
    """
    if observed.empty:
        return pd.Series(dtype=float)
    values = (
        observed.assign(period=observed["period"].astype(str))
        .groupby("period")["actual_units"]
        .sum()
    )
    index = pd.period_range(values.index.min(), last_period, freq="M").astype(str)
    return values.reindex(index, fill_value=0.0).astype(float)


def _flat(level: float, horizon: list[str]) -> list[float]:
    return [max(0.0, float(level))] * len(horizon)


def last_month(observed: pd.DataFrame, horizon: list[str]) -> list[float]:
    """Naive: every horizon month at the last observed month."""
    y = monthly_series(observed, _before(horizon))
    return _flat(y.iloc[-1] if len(y) else 0.0, horizon)


def moving_average(months: int) -> Method:
    """Every horizon month at the mean of the last ``months`` months (zeros included)."""

    def method(observed: pd.DataFrame, horizon: list[str]) -> list[float]:
        y = monthly_series(observed, _before(horizon))
        return _flat(y.tail(months).mean() if len(y) else 0.0, horizon)

    method.__doc__ = f"Mean of the last {months} months, held flat."
    return method


def recent_average(observed: pd.DataFrame, horizon: list[str]) -> list[float]:
    """Every horizon month at the model's mean of its last ``RECENT_MONTHS`` months.

    Business meaning: follows a model that is rising or falling, at the cost of ignoring
    seasonality — the history is too short to separate the two with confidence.
    """
    return moving_average(RECENT_MONTHS)(observed, horizon)


def exponential_smoothing(observed: pd.DataFrame, horizon: list[str]) -> list[float]:
    """Simple exponential smoothing; the smoothing weight is the one-step best fit."""
    y = monthly_series(observed, _before(horizon)).to_numpy()
    if len(y) == 0:
        return _flat(0.0, horizon)
    best_sse, best_level = float("inf"), float(y[-1])
    for alpha in ALPHA_GRID:
        level, sse = float(y[0]), 0.0
        for value in y[1:]:
            sse += (value - level) ** 2
            level = alpha * value + (1 - alpha) * level
        if sse < best_sse:
            best_sse, best_level = sse, level
    return _flat(best_level, horizon)


def damped_trend(observed: pd.DataFrame, horizon: list[str]) -> list[float]:
    """Holt's linear trend, damped (phi = ``DAMPING``); weights are the one-step best fit."""
    y = monthly_series(observed, _before(horizon)).to_numpy()
    if len(y) < 2:
        return _flat(y[-1] if len(y) else 0.0, horizon)
    best: tuple[float, float, float] | None = None
    for alpha in ALPHA_GRID:
        for beta in BETA_GRID:
            level, trend, sse = float(y[0]), float(y[1] - y[0]), 0.0
            for value in y[1:]:
                predicted = level + DAMPING * trend
                sse += (value - predicted) ** 2
                new_level = alpha * value + (1 - alpha) * predicted
                trend = beta * (new_level - level) + (1 - beta) * DAMPING * trend
                level = new_level
            if best is None or sse < best[0]:
                best = (sse, level, trend)
    assert best is not None
    _, level, trend = best
    return [
        max(0.0, level + sum(DAMPING**k for k in range(1, step + 1)) * trend)
        for step in range(1, len(horizon) + 1)
    ]


def _before(horizon: list[str]) -> str:
    """The period just before the horizon — the forecast origin."""
    return str(pd.Period(horizon[0], freq="M") - 1)


def interval_spread(observed: pd.DataFrame) -> float:
    """Standard deviation of the model's monthly units, for the 80% band."""
    return float(observed["actual_units"].std(ddof=1)) if len(observed) > 1 else 0.0


#: Grids for the smoothing weights, fitted on one-step-ahead squared error.
ALPHA_GRID = [round(0.05 * k, 2) for k in range(1, 20)]
BETA_GRID = [round(0.05 * k, 2) for k in range(1, 11)]
#: Trend damping for the damped-trend method.
DAMPING = 0.9
#: Months of model mix used to split a family forecast.
MIX_MONTHS = 3
#: Months averaged by the family-level method.
FAMILY_MA_MONTHS = 3
#: Weighted mix: each month back counts this fraction of the month after it.
MIX_DECAY = 0.5
#: Growth: last GROWTH_WINDOW months against the GROWTH_WINDOW before them.
GROWTH_WINDOW = 3
#: Monthly growth is capped at ±GROWTH_CAP, then damped by GROWTH_DAMPING per month ahead.
GROWTH_CAP = 0.05
GROWTH_DAMPING = 0.8

#: Model-level methods the backtest scores, in display order.
METHODS: dict[str, tuple[str, Method]] = {
    "seasonal_run_rate": (
        f"Published: {RUN_RATE_MONTHS}-month run rate × seasonal profile",
        seasonal_run_rate,
    ),
    "last_month": ("Last month (naive)", last_month),
    "ma3": ("3-month average", moving_average(3)),
    "recent_average": (f"{RECENT_MONTHS}-month average", recent_average),
    "ses": ("Exponential smoothing", exponential_smoothing),
    "damped_trend": ("Damped trend (Holt)", damped_trend),
}
#: The family-level method: forecast the family, split to models on recent mix.
FAMILY_METHOD = (
    "family_ma3",
    f"Family {FAMILY_MA_MONTHS}-month average, split by recent model mix",
)
#: The improved method: family split on a weighted mix, total grown on a damped trend.
GROWTH_METHOD = (
    "family_growth",
    "Improved: family mix × total 3-month level with damped growth",
)
#: The method the page recommends.
RECOMMENDED = GROWTH_METHOD[0]


def all_methods() -> list[tuple[str, str]]:
    """Every scored method as (key, label), model-level first."""
    return [(key, label) for key, (label, _) in METHODS.items()] + [FAMILY_METHOD, GROWTH_METHOD]


def damped_growth_path(series: pd.Series, horizon: int) -> list[float]:
    """Multipliers on today's level for each month ahead, from recent momentum.

    Business meaning: the market has kept growing since the import ban lifted, and a
    flat forecast under-shot every backtest by about 10%. The monthly growth of the last
    ``GROWTH_WINDOW`` months over the ``GROWTH_WINDOW`` before them is capped at
    ±``GROWTH_CAP`` and fades by ``GROWTH_DAMPING`` each month ahead, so the forecast
    bends toward the trend without extrapolating a recovery forever.

    Args:
        series: the monthly total, oldest first.
        horizon: months ahead.

    Returns:
        One cumulative multiplier per month ahead; all 1.0 when history is too short.
    """
    y = series.to_numpy(dtype=float)
    window = GROWTH_WINDOW
    if len(y) < 2 * window or y[-2 * window : -window].mean() <= 0:
        return [1.0] * horizon
    rate = (y[-window:].mean() / y[-2 * window : -window].mean()) ** (1 / window) - 1
    rate = max(-GROWTH_CAP, min(GROWTH_CAP, float(rate)))
    path, cumulative = [], 1.0
    for step in range(1, horizon + 1):
        cumulative *= 1 + rate * GROWTH_DAMPING**step
        path.append(cumulative)
    return path


def family_growth(
    train: pd.DataFrame, families: dict[str, str], horizon: list[str]
) -> dict[str, list[float]]:
    """The improved method: family split on a weighted mix, scaled to a growing total.

    Business meaning: model shares come from each family's recent mix, weighting the
    latest month most (a replacement model's rise shows up sooner); the overall volume is
    the total's 3-month level carried forward on a damped growth trend, which removes most
    of the flat forecast's under-shoot. In the rolling backtest this cut total error from
    16.5% to 12.9% and bias from −9.6% to −3.5%, with model-level error unchanged.
    """
    origin = _before(horizon)
    split = family_split(train, families, horizon, weighted=True)
    if not split:
        return split
    series = {
        model: monthly_series(group[["period", "actual_units"]], origin)
        for model, group in train.groupby(train["model"].astype(str))
    }
    total = pd.DataFrame(series).fillna(0.0).sum(axis=1).sort_index()
    level = float(total.tail(FAMILY_MA_MONTHS).mean())
    path = damped_growth_path(total, len(horizon))
    split_total = [sum(values[i] for values in split.values()) for i in range(len(horizon))]
    return {
        model: [
            value * (level * path[i] / split_total[i]) if split_total[i] else 0.0
            for i, value in enumerate(values)
        ]
        for model, values in split.items()
    }


def family_split(
    train: pd.DataFrame, families: dict[str, str], horizon: list[str], weighted: bool = False
) -> dict[str, list[float]]:
    """Forecast each family's total, then split it to its models on their recent mix.

    Business meaning: a family's volume is steadier than any one model's — a new model
    often takes its sales from an older one in the same family (FZ-S-FI NEW and FZ-S DLX
    growing as FZS-FI V4 fades). Forecasting the family and splitting on the last
    ``MIX_MONTHS`` months of mix keeps the volume and follows the replacement.

    Args:
        train: training rows ``period``, ``model``, ``actual_units``.
        families: model code -> family; a model without one is its own family.
        horizon: periods to forecast.
        weighted: split on a mix that weights recent months more (``MIX_DECAY``) instead
            of the plain last ``MIX_MONTHS`` months.

    Returns:
        Model -> one point per horizon period, for every model sold in the window.
    """
    origin = _before(horizon)
    series = {
        model: monthly_series(group[["period", "actual_units"]], origin)
        for model, group in train.groupby(train["model"].astype(str))
    }
    by_family: dict[str, list[str]] = {}
    for model in series:
        by_family.setdefault(families.get(model) or model, []).append(model)
    out: dict[str, list[float]] = {}
    for models in by_family.values():
        panel = pd.DataFrame({m: series[m] for m in models}).fillna(0.0)
        level = float(panel.sum(axis=1).tail(FAMILY_MA_MONTHS).mean())
        if weighted:
            ages = range(len(panel) - 1, -1, -1)
            mix = panel.mul([MIX_DECAY**age for age in ages], axis=0).sum()
        else:
            mix = panel.tail(MIX_MONTHS).sum()
        mix = mix / mix.sum() if mix.sum() else pd.Series(1.0 / len(models), index=models)
        for model in models:
            out[model] = _flat(level * float(mix[model]), horizon)
    return out


def backtest(
    actual: pd.DataFrame,
    train_start: str,
    train_end: str,
    horizon_months: int,
    families: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fit each model on a training window, forecast the months after it, keep actuals.

    Business meaning: shows how the forecast would have done had it been made at the end
    of the training window — the honest test of a method, because none of the months it
    is scored on were visible to it.

    Args:
        actual: monthly ``period``, ``model``, ``actual_units`` (months with sales only).
        train_start: first training period, YYYY-MM, inclusive.
        train_end: last training period, YYYY-MM, inclusive.
        horizon_months: how many months after ``train_end`` to forecast.
        families: model code -> family, for the family-level method.

    Returns:
        One row per model and test period: ``actual_units`` (0 when no sale was recorded,
        NaN beyond the last observed month), ``train_months`` and one column per method.
    """
    horizon = horizon_after(train_end, horizon_months)
    last_observed = str(actual["period"].max()) if not actual.empty else ""
    frame = actual.assign(period=actual["period"].astype(str))
    train = frame[(frame["period"] >= train_start) & (frame["period"] <= train_end)]
    family_points = family_split(train, families or {}, horizon)
    growth_points = family_growth(train, families or {}, horizon)
    rows: list[dict[str, object]] = []
    for model in sorted(frame["model"].astype(str).unique()):
        observed = train[train["model"].astype(str) == model][["period", "actual_units"]]
        test = frame[(frame["model"].astype(str) == model) & frame["period"].isin(horizon)]
        seen = dict(zip(test["period"], test["actual_units"], strict=False))
        points = {key: method(observed, horizon) for key, (_, method) in METHODS.items()}
        points[FAMILY_METHOD[0]] = family_points.get(model, [0.0] * len(horizon))
        points[GROWTH_METHOD[0]] = growth_points.get(model, [0.0] * len(horizon))
        for i, period in enumerate(horizon):
            rows.append(
                {
                    "model": model,
                    "period": period,
                    "train_months": len(observed),
                    "actual_units": (
                        float(seen.get(period, 0.0)) if period <= last_observed else None
                    ),
                    **{key: values[i] for key, values in points.items()},
                }
            )
    return pd.DataFrame(rows)


#: Band estimation: rolling origins need this many months of training first.
BAND_MIN_TRAIN = 6
#: The furthest horizon the backtest scores; later months widen the last band.
BAND_MAX_H = 6
#: The band is the 10th–90th percentile of actual ÷ forecast — an 80% interval.
BAND_QUANTILES = (0.10, 0.90)


def band_ratios(
    actual: pd.DataFrame, families: dict[str, str]
) -> dict[str, dict[int, tuple[float, float]]]:
    """How far actuals landed from the recommended forecast, by months ahead.

    Business meaning: the 80% band on the page is what this method has actually missed
    by, not a textbook formula. Each past month is used as a forecast origin; the ratio
    actual ÷ forecast is collected per horizon, at total level (for the total line) and
    per model (for model lines, which miss by more).

    Args:
        actual: monthly ``period``, ``model``, ``actual_units``.
        families: model code -> family.

    Returns:
        ``{"total": {h: (low, high)}, "model": {h: (low, high)}}``; empty when the
        history is too short to score any origin.
    """
    periods = sorted(actual["period"].astype(str).unique())
    origins = periods[BAND_MIN_TRAIN - 1 : -1]
    total_ratios: dict[int, list[float]] = {}
    model_ratios: dict[int, list[float]] = {}
    for origin in origins:
        result = backtest(actual, periods[0], origin, BAND_MAX_H, families)
        result = result[result["actual_units"].notna() & (result["train_months"] > 0)]
        if result.empty:
            continue
        step = {p: i + 1 for i, p in enumerate(horizon_after(origin, BAND_MAX_H))}
        result = result.assign(h=result["period"].map(step))
        for h, group in result.groupby("h"):
            forecast = float(group[RECOMMENDED].sum())
            if forecast > 0:
                total_ratios.setdefault(int(h), []).append(
                    float(group["actual_units"].sum()) / forecast
                )
            fitted = group[group[RECOMMENDED] > 0]
            model_ratios.setdefault(int(h), []).extend(
                (fitted["actual_units"] / fitted[RECOMMENDED]).tolist()
            )
    low, high = BAND_QUANTILES

    def quantiles(ratios: dict[int, list[float]]) -> dict[int, tuple[float, float]]:
        return {
            h: (float(pd.Series(v).quantile(low)), float(pd.Series(v).quantile(high)))
            for h, v in sorted(ratios.items())
            if len(v) >= 2
        }

    return {"total": quantiles(total_ratios), "model": quantiles(model_ratios)}


def band_at(bands: dict[int, tuple[float, float]], step: int) -> tuple[float, float]:
    """The (low, high) multipliers for ``step`` months ahead.

    Beyond the furthest scored horizon the last band is widened in log space by
    √(step / last) — an assumption, since no forecast that far ahead has been scored.
    With no bands at all the multipliers are (1, 1): no interval is claimed.
    """
    if not bands:
        return (1.0, 1.0)
    if step in bands:
        return bands[step]
    last = max(bands)
    low, high = bands[last]
    low, high = max(low, 1e-6), max(high, 1e-6)
    centre = (np.log(low) + np.log(high)) / 2
    half = (np.log(high) - np.log(low)) / 2 * float(np.sqrt(step / last))
    return (float(np.exp(centre - half)), float(np.exp(centre + half)))


def whole_unit_split(total: int, weights: list[float]) -> list[int]:
    """Split ``total`` into whole units in proportion to ``weights``, summing exactly.

    Business meaning: a target is allocated in whole motorcycles. Each share is rounded
    down, and the units left over go one each to the largest remainders (the largest
    remainder method), so the parts always add back to the target — no bike is created
    or lost by rounding.
    """
    weight_sum = sum(weights)
    if total <= 0 or weight_sum <= 0:
        return [0] * len(weights)
    exact = [total * w / weight_sum for w in weights]
    floors = [int(x) for x in exact]
    leftover = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        floors[i] += 1
    return floors
