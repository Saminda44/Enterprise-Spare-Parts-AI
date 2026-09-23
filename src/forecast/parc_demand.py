"""Step 08 — own-history forecast, parc-driven demand, and the protection-interval
distribution.

``D(p,t) = Σ_m Σ_a UIO(m,a,t) · λ(p,a) · s(t) · k(p)``

λ is fitted by penalised non-negative least squares pooled on behaviour class. The
smoothness penalty encodes the physical fact that consumption does not jump between
adjacent age years.

**Collinearity warning.** Cohort sizes move together over time, so individual λ_a values
are weakly identified even when the fitted total is accurate. The fitted *curve* is
trustworthy; any single age coefficient is much less so, which is why confidence
intervals are reported and never omitted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import nnls

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.forecast.models import CANDIDATES, INSUFFICIENT_HISTORY_CANDIDATES, naive
from src.io.parquet import append_columns, read_table, table_exists, write_table

FORECAST_HORIZON_MONTHS = 12
SMOOTHNESS_ALPHA = 1.0
BOOTSTRAP_SAMPLES = 400
QUANTILES = (0.5, 0.9, 0.95)

#: Age bands for the lambda fit. Wear consumption rises through the middle of a fleet's
#: life, so the bands are wide enough to be identified from a short demand history.
AGE_BANDS = ("0-2", "3-5", "6-8", "9-11", "12+")


def age_band(age: int) -> str:
    if age <= 2:
        return "0-2"
    if age <= 5:
        return "3-5"
    if age <= 8:
        return "6-8"
    if age <= 11:
        return "9-11"
    return "12+"


def fit_lambda(
    design: np.ndarray, observed: np.ndarray, alpha: float = SMOOTHNESS_ALPHA
) -> tuple[np.ndarray, np.ndarray]:
    """Penalised NNLS: minimise ‖y − Xλ‖² + α‖Dλ‖² subject to λ ≥ 0.

    ``D`` is the first-difference operator, so the penalty costs jumps between adjacent
    age coefficients. Returns (lambda, standard errors).
    """
    ages = design.shape[1]
    if ages == 0 or design.size == 0:
        return np.zeros(0), np.zeros(0)

    difference = np.zeros((max(ages - 1, 0), ages))
    for i in range(ages - 1):
        difference[i, i] = -1.0
        difference[i, i + 1] = 1.0

    augmented_x = np.vstack([design, np.sqrt(alpha) * difference])
    augmented_y = np.concatenate([observed, np.zeros(difference.shape[0])])
    solution, _ = nnls(augmented_x, augmented_y)

    residual = observed - design @ solution
    dof = max(len(observed) - np.count_nonzero(solution), 1)
    sigma2 = float(residual @ residual) / dof
    try:
        covariance = np.linalg.pinv(augmented_x.T @ augmented_x) * sigma2
        errors = np.sqrt(np.clip(np.diag(covariance), 0, None))
    except np.linalg.LinAlgError:  # pragma: no cover - singular design
        errors = np.full(ages, np.nan)
    return solution, errors


def protection_distribution(
    residuals: np.ndarray, mu_month: float, horizon: int, quadrant: str, rng: np.random.Generator
) -> dict[str, float]:
    """The distribution of demand over the protection interval, not just a point.

    Normal approximation for smooth and erratic; empirical bootstrap of the P-month sum
    for intermittent and lumpy, where the normal assumption is simply false — fitting a
    normal to 0,0,0,7,0,0,3 produces a negative lower tail and an understated upper one.
    """
    mu_p = mu_month * horizon
    if quadrant in {"smooth", "erratic"} or residuals.size < horizon:
        sigma_month = float(residuals.std(ddof=1)) if residuals.size > 1 else 0.0
        sigma_p = sigma_month * np.sqrt(horizon)
        out = {"mu_p": mu_p, "sigma_p": float(sigma_p), "method": "normal"}
        for q in QUANTILES:
            from scipy.stats import norm

            out[f"p{int(q * 100)}"] = float(mu_p + norm.ppf(q) * sigma_p)
        return out

    draws = rng.choice(residuals, size=(BOOTSTRAP_SAMPLES, horizon), replace=True)
    sums = np.clip(mu_p + draws.sum(axis=1), 0.0, None)
    out = {"mu_p": mu_p, "sigma_p": float(sums.std(ddof=1)), "method": "bootstrap"}
    for q in QUANTILES:
        out[f"p{int(q * 100)}"] = float(np.quantile(sums, q))
    return out


@REGISTRY.register(
    "08_forecast",
    depends_on=["07_model_selection", "10_uio_cohorts"],
    description="baseline and parc-driven forecast with protection-interval uncertainty",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="08_forecast")
    history = read_table("facts", "demand_history")
    classification = read_table("facts", "sku_classification")
    registry = read_table("facts", "model_registry")
    split = read_table("facts", "holdout_split")
    result.rows_in = len(classification)

    holdout_start = str(split.at[0, "holdout_start"])
    months = sorted(history["month"].dropna().unique())
    train_months = [m for m in months if m < holdout_start]
    result.warn(
        f"holdout assertion: fitting on {len(train_months)} month(s) up to "
        f"{train_months[-1] if train_months else 'n/a'}; no row at or after {holdout_start} "
        f"enters any fit"
    )

    panel = (
        history.pivot_table(
            index="active_sku_id", columns="month", values="ordered_quantity", aggfunc="sum"
        )
        .reindex(columns=months)
        .fillna(0.0)
    )
    train_panel = panel[train_months]

    champion = {
        (r.quadrant, r.abc, r.behaviour_class): r.model for r in registry.itertuples(index=False)
    }
    quadrant_default = (
        registry.groupby("quadrant")["model"].agg(lambda s: s.mode().iat[0]).to_dict()
    )

    lambda_table, parc_demand = _parc_component(ctx, classification, train_panel, result)

    rng = np.random.default_rng(20260923)
    horizon = ctx.protection_interval_months
    meta = classification.set_index("active_sku_id")
    rows: list[dict[str, object]] = []

    for sku, series in train_panel.iterrows():
        if sku not in meta.index:
            continue
        info = meta.loc[sku]
        quadrant = str(info.get("quadrant", "no demand"))
        key = (
            quadrant,
            str(info.get("abc", "C")),
            str(info.get("behaviour_class", "unclassified")),
        )
        model_name = champion.get(key) or quadrant_default.get(quadrant, "naive")

        pool = (
            INSUFFICIENT_HISTORY_CANDIDATES
            if bool(info.get("insufficient_history", False))
            else CANDIDATES.get(quadrant, CANDIDATES["no demand"])
        )
        forecaster = pool.get(model_name, naive)

        values = series.to_numpy(dtype=float)
        # Weighted toward the last 24 months, which is the whole file here.
        baseline = float(np.asarray(forecaster(values, 1), dtype=float)[0])

        fitted = np.asarray(forecaster(values[:-1], 1), dtype=float)[0] if values.size > 1 else 0.0
        residuals = values - fitted if values.size else np.array([0.0])

        parc = float(parc_demand.get(sku, np.nan))
        nonzero = int(info.get("nonzero_months", 0))
        # Data sufficiency drives the blend: long history leans baseline, a part on young
        # models with no history can only be forecast from the parc.
        if np.isnan(parc):
            blended, weight = baseline, 1.0
        elif nonzero == 0:
            blended, weight = parc, 0.0
        else:
            weight = min(1.0, nonzero / 12.0)
            blended = weight * baseline + (1 - weight) * parc

        distribution = protection_distribution(residuals, blended, horizon, quadrant, rng)
        rows.append(
            {
                "active_sku_id": sku,
                "model": model_name,
                "quadrant": quadrant,
                "mu_month_baseline": baseline,
                "mu_month_parc": parc,
                "mu_month": blended,
                "baseline_weight": weight,
                "mu_12m": blended * FORECAST_HORIZON_MONTHS,
                "parc_only": bool(nonzero == 0 and not np.isnan(parc)),
                **distribution,
            }
        )

    forecast = pd.DataFrame(rows)
    result.rows_out = len(forecast)
    result.artifact("forecast_protection", write_table(forecast, "facts", "forecast_protection"))
    if not lambda_table.empty:
        result.artifact("lambda_curves", write_table(lambda_table, "facts", "lambda_curves"))

    parc_only = int(forecast["parc_only"].sum()) if len(forecast) else 0
    with_parc = int(forecast["mu_month_parc"].notna().sum()) if len(forecast) else 0
    result.warn(
        f"forecast for {len(forecast):,} SKUs; {with_parc:,} have a parc-driven estimate, "
        f"{parc_only:,} are parc-only (no demand history at all)"
    )
    result.warn(
        f"protection interval P = {horizon} months; uncertainty method mix: "
        f"{forecast['method'].value_counts().to_dict() if len(forecast) else {}}"
    )

    enriched = append_columns(
        read_table("facts", "part_master_enriched"), forecast, "active_sku_id"
    )
    result.artifact("part_master_enriched", write_table(enriched, "facts", "part_master_enriched"))

    logger.info(f"forecast: {len(forecast):,} SKUs")
    return result


def _parc_component(
    ctx: PlanningContext,
    classification: pd.DataFrame,
    train_panel: pd.DataFrame,
    result: StageResult,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Fit λ(p,a) pooled on behaviour class and project parc-driven monthly demand."""
    if not table_exists("facts", "uio_age_matrix"):
        result.warn("no UIO matrix — parc-driven demand unavailable, baseline only")
        return pd.DataFrame(), {}

    uio = read_table("facts", "uio_age_matrix")
    uio = uio[uio["scenario"] == "base"]
    if uio.empty:
        result.warn("UIO matrix has no base scenario — parc-driven demand unavailable")
        return pd.DataFrame(), {}

    master = read_table("facts", "part_master")
    # groupby-any, not set_index: several material rows share an active_sku_id and
    # set_index keeps only the last, silently dropping parts that do have compatibility.
    has_compat = set(
        master.loc[
            master["compatible_models"].astype(str).str.strip().ne(""), "active_sku_id"
        ].unique()
    )
    result.warn(
        f"parc coverage: {len(has_compat):,}/{len(master):,} parts carry model compatibility "
        f"from the catalogue, so only those can be forecast from the fleet"
    )
    if not has_compat:
        return pd.DataFrame(), {}

    # Fleet by age and year, summed over all models (compatibility in this vintage is a
    # model-code label rather than a joinable key for most parts).
    #
    # Age is banded rather than taken year by year: the demand history spans 24 months,
    # so fitting 16 yearly coefficients against ~18 observations would be fitting noise.
    # Bands keep the parameter count to five and the curve interpretable.
    uio = uio.assign(age_band=uio["age"].map(age_band))
    fleet = (
        uio.pivot_table(index="year", columns="age_band", values="units", aggfunc="sum")
        .reindex(columns=AGE_BANDS)
        .fillna(0.0)
    )
    years = sorted(fleet.index)
    month_to_year = {m: int(m[:4]) for m in train_panel.columns}
    usable_months = [m for m in train_panel.columns if month_to_year[m] in fleet.index]

    lambda_rows: list[dict[str, object]] = []
    parc_demand: dict[str, float] = {}

    if len(usable_months) < 2 * len(AGE_BANDS):
        result.warn(
            f"only {len(usable_months)} training month(s) overlap the UIO years — too few to "
            f"fit {len(AGE_BANDS)} age bands, so parc-driven demand is unavailable"
        )
        return pd.DataFrame(), {}

    design_full = np.vstack(
        [fleet.loc[month_to_year[m]].to_numpy(dtype=float) for m in usable_months]
    )

    for behaviour, group in classification.groupby("behaviour_class"):
        skus = [s for s in group["active_sku_id"] if s in train_panel.index and s in has_compat]
        if len(skus) < 5:
            continue
        observed = train_panel.loc[skus, usable_months].sum(axis=0).to_numpy(dtype=float)
        coefficients, errors = fit_lambda(design_full, observed)
        if coefficients.size == 0 or not np.any(coefficients > 0):
            continue

        for band, value, error in zip(AGE_BANDS, coefficients, errors, strict=False):
            lambda_rows.append(
                {
                    "behaviour_class": behaviour,
                    "age_band": band,
                    "age": AGE_BANDS.index(band),
                    "lambda": float(value),
                    "std_error": float(error),
                    "ci_low": float(max(value - 1.96 * error, 0.0)),
                    "ci_high": float(value + 1.96 * error),
                    "parts_pooled": len(skus),
                    "months_fitted": len(usable_months),
                }
            )

        current_year = ctx.as_of.year
        if current_year not in fleet.index:
            current_year = max(years)
        class_demand = float(fleet.loc[current_year].to_numpy(dtype=float) @ coefficients)
        share = train_panel.loc[skus].sum(axis=1)
        total = float(share.sum())
        for sku in skus:
            weight = float(share.get(sku, 0.0)) / total if total else 1.0 / len(skus)
            parc_demand[sku] = class_demand * weight

    lambda_table = pd.DataFrame(lambda_rows)
    if not lambda_table.empty:
        result.warn(
            f"lambda fitted for {lambda_table['behaviour_class'].nunique()} behaviour class(es) "
            f"with confidence intervals — cohort collinearity makes any single age coefficient "
            f"weakly identified, so read the curve, not the point"
        )
    return lambda_table, parc_demand
