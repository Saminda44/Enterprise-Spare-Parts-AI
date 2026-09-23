"""Forecast candidates.

Each model is a pure function ``fit_predict(history, horizon) -> np.ndarray`` of length
``horizon``. Intermittent methods (Croston, SBA, TSB) are the point of this module: half
these series contain zeros, where the classical smoothers fail.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

Forecaster = Callable[[np.ndarray, int], np.ndarray]


def naive(history: np.ndarray, horizon: int) -> np.ndarray:
    return np.repeat(history[-1] if history.size else 0.0, horizon)


def mean_forecast(history: np.ndarray, horizon: int) -> np.ndarray:
    return np.repeat(history.mean() if history.size else 0.0, horizon)


def moving_average(window: int) -> Forecaster:
    def _forecast(history: np.ndarray, horizon: int) -> np.ndarray:
        tail = history[-window:] if history.size else np.array([0.0])
        return np.repeat(tail.mean(), horizon)

    _forecast.__name__ = f"moving_average_{window}"
    return _forecast


def simple_exponential_smoothing(alpha: float = 0.3) -> Forecaster:
    def _forecast(history: np.ndarray, horizon: int) -> np.ndarray:
        if not history.size:
            return np.zeros(horizon)
        level = history[0]
        for value in history[1:]:
            level = alpha * value + (1 - alpha) * level
        return np.repeat(level, horizon)

    _forecast.__name__ = f"ses_{alpha}"
    return _forecast


def linear_trend(history: np.ndarray, horizon: int) -> np.ndarray:
    if history.size < 2:
        return naive(history, horizon)
    x = np.arange(history.size, dtype=float)
    slope, intercept = np.polyfit(x, history, 1)
    future = np.arange(history.size, history.size + horizon, dtype=float)
    return np.clip(intercept + slope * future, 0.0, None)


def _croston_core(history: np.ndarray, alpha: float, bias: float) -> float:
    """Shared Croston machinery: smooth demand size and inter-arrival interval."""
    nonzero_idx = np.flatnonzero(history)
    if nonzero_idx.size == 0:
        return 0.0
    sizes = history[nonzero_idx]
    intervals = np.diff(np.concatenate(([-1], nonzero_idx))).astype(float)

    size = sizes[0]
    interval = intervals[0] if intervals.size else 1.0
    for s, q in zip(sizes[1:], intervals[1:], strict=False):
        size += alpha * (s - size)
        interval += alpha * (q - interval)
    if interval <= 0:
        return 0.0
    return bias * size / interval


def croston(alpha: float = 0.1) -> Forecaster:
    def _forecast(history: np.ndarray, horizon: int) -> np.ndarray:
        return np.repeat(_croston_core(history, alpha, 1.0), horizon)

    _forecast.__name__ = "croston"
    return _forecast


def sba(alpha: float = 0.1) -> Forecaster:
    """Syntetos-Boylan Approximation — Croston with the (1 - alpha/2) bias correction."""

    def _forecast(history: np.ndarray, horizon: int) -> np.ndarray:
        return np.repeat(_croston_core(history, alpha, 1.0 - alpha / 2.0), horizon)

    _forecast.__name__ = "sba"
    return _forecast


def tsb(alpha: float = 0.1, beta: float = 0.1) -> Forecaster:
    """Teunter-Syntetos-Babai — updates demand probability every period, so it decays
    toward zero for a part that has stopped moving rather than holding its last rate."""

    def _forecast(history: np.ndarray, horizon: int) -> np.ndarray:
        if not history.size:
            return np.zeros(horizon)
        nonzero = history[history > 0]
        size = nonzero[0] if nonzero.size else 0.0
        probability = float((history > 0).mean())
        for value in history:
            occurred = 1.0 if value > 0 else 0.0
            probability += beta * (occurred - probability)
            if value > 0:
                size += alpha * (value - size)
        return np.repeat(max(probability, 0.0) * max(size, 0.0), horizon)

    _forecast.__name__ = "tsb"
    return _forecast


#: Candidates routed by Syntetos-Boylan quadrant. Seasonal models (SARIMA, Prophet) need
#: two full seasonal cycles; with a 24-month file there is only one, so they are dropped
#: at runtime rather than allowed to fit noise. TFT needs a long, wide panel and is out.
CANDIDATES: dict[str, dict[str, Forecaster]] = {
    "smooth": {
        "naive": naive,
        "moving_average_3": moving_average(3),
        "moving_average_6": moving_average(6),
        "ses_0.3": simple_exponential_smoothing(0.3),
        "linear_trend": linear_trend,
    },
    "erratic": {
        "naive": naive,
        "mean": mean_forecast,
        "moving_average_6": moving_average(6),
        "ses_0.3": simple_exponential_smoothing(0.3),
    },
    "intermittent": {
        "croston": croston(),
        "sba": sba(),
        "tsb": tsb(),
        "mean": mean_forecast,
    },
    "lumpy": {
        "sba": sba(),
        "tsb": tsb(),
        "croston": croston(),
        "mean": mean_forecast,
    },
    "no demand": {"naive": naive},
}

#: Parts with too little history get the conservative path only.
INSUFFICIENT_HISTORY_CANDIDATES = {"naive": naive, "mean": mean_forecast}
