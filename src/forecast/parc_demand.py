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

import re
from datetime import date

import numpy as np
import pandas as pd
import pandera.pandas as pa
from loguru import logger
from scipy.optimize import nnls

from src.core.context import PlanningContext
from src.core.contracts import validate
from src.core.errors import ContractViolation, SourceDataError
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.dashboard.segments import SEGMENT_MC, SEGMENT_OBM, sku_segments
from src.forecast.models import (
    CANDIDATES,
    FALLBACK_MODEL,
    INSUFFICIENT_HISTORY_CANDIDATES,
    fallback_forecaster,
)
from src.io.parquet import append_columns, read_table, table_exists, write_table

ANNUALIZED_MONTHS = 12
SMOOTHNESS_ALPHA = 1.0
BOOTSTRAP_SAMPLES = 400
QUANTILES = (0.5, 0.9, 0.95)

#: Age bands for the lambda fit. Wear consumption rises through the middle of a fleet's
#: life, so the bands are wide enough to be identified from a short demand history.
AGE_BANDS = ("0-2", "3-5", "6-8", "9-11", "12+")

#: Blend bounds when both forecasts exist: a long history never fully silences the fleet,
#: and a part on a young model never ignores the history it does have.
BLEND_FLOOR = 0.2
BLEND_CEILING = 0.8
#: Months with demand at which the baseline reaches its ceiling weight.
BLEND_FULL_HISTORY_MONTHS = 24
#: The part-level scale k(p) that ties the class curve to the part's own level.
K_CLIP = (0.1, 10.0)
#: "R 15 - 2FB6" -> "2FB6": catalogue compatibility labels end in the model type code.
MODEL_CODE = re.compile(r"-\s*([0-9A-Z]{4})\s*$")

MONTHLY_FORECAST_SCHEMA = pa.DataFrameSchema(
    {
        "active_sku_id": pa.Column(str),
        "segment": pa.Column(str, checks=pa.Check.isin([SEGMENT_MC, SEGMENT_OBM])),
        "month": pa.Column(str, checks=pa.Check.str_matches(r"^\d{4}-(0[1-9]|1[0-2])$")),
        "horizon_index": pa.Column(int, checks=pa.Check.ge(1)),
        "model": pa.Column(str),
        "mu_month_baseline": pa.Column(float, checks=pa.Check.ge(0)),
        "mu_month_parc": pa.Column(float, nullable=True, checks=pa.Check.ge(0)),
        "baseline_weight": pa.Column(float, checks=pa.Check.in_range(0, 1)),
        "forecast_quantity": pa.Column(float, checks=pa.Check.ge(0)),
        "fit_through": pa.Column(str),
        "basis": pa.Column(str),
    },
    coerce=True,
    strict=True,
)


def forecast_months(as_of: date) -> list[str]:
    """Return forecast months from the current cycle through next calendar year-end.

    Business meaning: an October 2026 cycle forecasts October 2026 through December
    2027. The dashboard places completed 2026 actuals before that path. Once the cycle
    enters 2027, the visible calendar rolls through December 2028.
    The purchasing policy still uses its separate lead-time-plus-review interval.
    """
    first = pd.Period(as_of, freq="M")
    final = pd.Period(year=as_of.year + 1, month=12, freq="M")
    return [str(month) for month in pd.period_range(first, final, freq="M")]


def _validate_monthly_forecast(
    frame: pd.DataFrame, months: list[str], expected_skus: int
) -> pd.DataFrame:
    """Enforce one complete future path per forecast SKU before publishing it."""
    checked = validate(
        frame,
        MONTHLY_FORECAST_SCHEMA,
        stage="08_forecast",
        table="forecast_monthly_live",
    )
    expected_rows = expected_skus * len(months)
    if len(checked) != expected_rows:
        raise ContractViolation(
            "[08_forecast] forecast_monthly_live: "
            f"expected {expected_rows:,} rows ({expected_skus:,} SKUs x {len(months)} months), "
            f"got {len(checked):,}"
        )
    if checked.duplicated(["active_sku_id", "month"]).any():
        raise ContractViolation(
            "[08_forecast] forecast_monthly_live: duplicate active_sku_id/month rows"
        )
    actual_months = sorted(checked["month"].unique())
    if actual_months != months:
        raise ContractViolation(
            "[08_forecast] forecast_monthly_live: "
            f"expected months {months[0]}..{months[-1]}, got {actual_months}"
        )
    return checked


def blend_weight(nonzero_months: int, has_parc: bool) -> float:
    """Weight on the own-history baseline; the rest goes to the parc-driven estimate.

    Business meaning: data sufficiency drives the blend (Step 08). A part with two years
    of demand leans on its history but still moves with its fleet; a part on a model
    launched months ago leans on the fleet; a part with no history at all can only be
    forecast from the fleet.
    """
    if not has_parc:
        return 1.0
    if nonzero_months <= 0:
        return 0.0
    share = nonzero_months / BLEND_FULL_HISTORY_MONTHS
    return float(min(BLEND_CEILING, max(BLEND_FLOOR, share)))


def model_codes(compatible: object) -> list[str]:
    """Model type codes out of a catalogue compatibility list or string."""
    if compatible is None:
        return []
    if isinstance(compatible, str):
        items = compatible.strip("{}[]").split(",")
    else:
        try:
            items = list(compatible)  # type: ignore[call-overload]
        except TypeError:
            return []
    codes = {m.group(1) for x in items if (m := MODEL_CODE.search(str(x).strip().strip('"')))}
    return sorted(codes)


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
    master = read_table("facts", "part_master")
    classification = classification.copy()
    classification["segment"] = (
        classification["active_sku_id"].astype(str).map(sku_segments(master)).fillna(SEGMENT_MC)
    )
    registry = read_table("facts", "model_registry")
    split = read_table("facts", "holdout_split")
    result.rows_in = len(classification)

    holdout_start = str(split.at[0, "holdout_start"])
    months = sorted(history["month"].dropna().astype(str).unique())
    train_months = [m for m in months if m < holdout_start]
    cycle_month = str(pd.Period(ctx.as_of, freq="M"))
    live_months = [m for m in months if m < cycle_month]
    if not live_months:
        raise SourceDataError(
            f"no completed demand month is available before forecast cycle {cycle_month}"
        )
    result.warn(
        f"holdout assertion: the validation forecast fits on {len(train_months)} month(s) up to "
        f"{train_months[-1] if train_months else 'n/a'}; no row at or after {holdout_start} "
        f"enters it (Step 13 opens the holdout once, with this forecast)"
    )
    result.warn(
        f"live forecast refits on {len(live_months)} completed month(s) to {live_months[-1]} "
        f"for cycle {cycle_month}; current/future partial months are excluded"
    )

    panel = (
        history.pivot_table(
            index="active_sku_id", columns="month", values="ordered_quantity", aggfunc="sum"
        )
        .reindex(columns=months)
        .fillna(0.0)
    )

    champion = {
        (r.segment, r.quadrant, r.abc, r.behaviour_class): r.model
        for r in registry.itertuples(index=False)
    }
    quadrant_default = (
        registry.groupby(["segment", "quadrant"])["model"].agg(lambda s: s.mode().iat[0]).to_dict()
    )
    compat, fleet = _fleet_inputs(classification, result)

    validation, lambda_table, _ = _forecast(
        ctx,
        classification,
        panel[train_months],
        champion,
        quadrant_default,
        compat,
        fleet,
        result,
        label="validation",
    )
    reporting_months = forecast_months(ctx.as_of)
    live, lambda_live, monthly_live = _forecast(
        ctx,
        classification,
        panel[live_months],
        champion,
        quadrant_default,
        compat,
        fleet,
        result,
        label="live",
        future_months=reporting_months,
    )
    monthly_live = _validate_monthly_forecast(monthly_live, reporting_months, len(live))

    result.rows_out = len(live)
    result.artifact("forecast_protection", write_table(validation, "facts", "forecast_protection"))
    result.artifact("forecast_live", write_table(live, "facts", "forecast_live"))
    result.artifact(
        "forecast_monthly_live",
        write_table(monthly_live, "facts", "forecast_monthly_live"),
    )
    if not lambda_live.empty:
        result.artifact("lambda_curves", write_table(lambda_live, "facts", "lambda_curves"))

    parc_only = int(live["parc_only"].sum()) if len(live) else 0
    with_parc = int(live["mu_month_parc"].notna().sum()) if len(live) else 0
    parc_share = (
        float(((1 - live["baseline_weight"]) * live["mu_month_parc"].fillna(0.0)).sum())
        / float(live["mu_month"].sum())
        if len(live) and float(live["mu_month"].sum()) > 0
        else 0.0
    )
    result.warn(
        f"live forecast for {len(live):,} SKUs; {with_parc:,} have a parc-driven estimate, "
        f"{parc_only:,} are parc-only (no demand history at all); the parc term carries "
        f"{parc_share:.1%} of forecast demand"
    )
    obm_with_parc = int(live.loc[live["segment"].eq(SEGMENT_OBM), "mu_month_parc"].notna().sum())
    if obm_with_parc:
        raise SourceDataError(
            f"OBM forecast leaked motorcycle fleet demand into {obm_with_parc} SKU(s)"
        )
    result.warn(
        "OBM forecast uses order history only; no outboard installed-base source is supplied"
    )
    result.warn(
        f"protection interval P = {ctx.protection_interval_months} months; uncertainty method "
        f"mix: {live['method'].value_counts().to_dict() if len(live) else {}}"
    )
    result.warn(
        f"reporting forecast runs {reporting_months[0]}..{reporting_months[-1]} "
        f"({len(reporting_months)} months); own-history models generate the monthly path, "
        "while the current MC fleet contribution is held level because no future monthly "
        "fleet scenario is supplied"
    )
    forecast = live

    enriched = append_columns(
        read_table("facts", "part_master_enriched"), forecast, "active_sku_id"
    )
    result.artifact("part_master_enriched", write_table(enriched, "facts", "part_master_enriched"))

    logger.info(f"forecast: {len(forecast):,} SKUs")
    return result


def _forecast(
    ctx: PlanningContext,
    classification: pd.DataFrame,
    panel: pd.DataFrame,
    champion: dict[tuple[str, str, str, str], str],
    quadrant_default: dict[tuple[str, str], str],
    compat: dict[str, list[str]],
    fleet: pd.DataFrame,
    result: StageResult,
    label: str,
    future_months: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Baseline, parc-driven and blended forecast for every SKU, fitted on ``panel``."""
    lambda_table, parc_demand = _parc_component(ctx, classification, panel, compat, fleet, result)
    rng = np.random.default_rng(20260923)
    horizon = ctx.protection_interval_months
    meta = classification.set_index("active_sku_id")
    rows: list[dict[str, object]] = []
    monthly_rows: list[dict[str, object]] = []
    path_months = future_months or []
    path_length = max(len(path_months), 1)
    path_start = 0
    model_horizon = path_length
    if path_months:
        if not len(panel.columns):
            raise SourceDataError(f"{label} forecast has no fitted history")
        fitted_through = pd.Period(str(panel.columns[-1]), freq="M")
        first_forecast = pd.Period(path_months[0], freq="M")
        first_step = first_forecast.ordinal - fitted_through.ordinal
        if first_step < 1:
            raise SourceDataError(
                f"{label} forecast starts {first_forecast} but is fitted through {fitted_through}"
            )
        path_start = first_step - 1
        model_horizon = path_start + path_length
    for sku, series in panel.iterrows():
        if sku not in meta.index:
            continue
        info = meta.loc[sku]
        segment = str(info.get("segment", SEGMENT_MC))
        quadrant = str(info.get("quadrant", "no demand"))
        key = (
            segment,
            quadrant,
            str(info.get("abc", "C")),
            str(info.get("behaviour_class", "unclassified")),
        )
        model_name = champion.get(key) or quadrant_default.get((segment, quadrant), FALLBACK_MODEL)
        pool = (
            INSUFFICIENT_HISTORY_CANDIDATES
            if bool(info.get("insufficient_history", False))
            else CANDIDATES.get(quadrant, CANDIDATES["no demand"])
        )
        if model_name not in pool:
            # The group's champion is not open to this part (short history, say): fall
            # back to its recent order rate, never to last month alone.
            model_name = FALLBACK_MODEL
        forecaster = pool.get(model_name, fallback_forecaster)
        values = series.to_numpy(dtype=float)
        model_path = np.asarray(forecaster(values, model_horizon), dtype=float)
        baseline_path = model_path[path_start:]
        if baseline_path.shape != (path_length,) or not np.isfinite(baseline_path).all():
            raise SourceDataError(
                f"{label} forecast model {model_name} returned an invalid path for {sku}"
            )
        if (baseline_path < 0).any():
            raise SourceDataError(
                f"{label} forecast model {model_name} returned negative demand for {sku}"
            )
        baseline = float(baseline_path[0])
        fitted = np.asarray(forecaster(values[:-1], 1), dtype=float)[0] if values.size > 1 else 0.0
        residuals = values - fitted if values.size else np.array([0.0])

        parc = float(parc_demand.get(sku, np.nan))
        nonzero = int((values > 0).sum())
        weight = blend_weight(nonzero, not np.isnan(parc))
        blended = baseline if weight == 1.0 else weight * baseline + (1 - weight) * parc

        distribution = protection_distribution(residuals, blended, horizon, quadrant, rng)
        rows.append(
            {
                "active_sku_id": sku,
                "segment": segment,
                "model": model_name,
                "quadrant": quadrant,
                "mu_month_baseline": baseline,
                "mu_month_parc": parc,
                "mu_month": blended,
                "baseline_weight": weight,
                "mu_12m": blended * ANNUALIZED_MONTHS,
                "parc_only": bool(nonzero == 0 and not np.isnan(parc)),
                "fit_through": str(panel.columns[-1]) if len(panel.columns) else "",
                "basis": label,
                **distribution,
            }
        )
        for month_index, month in enumerate(path_months):
            monthly_baseline = float(baseline_path[month_index])
            monthly_blended = (
                monthly_baseline
                if weight == 1.0
                else weight * monthly_baseline + (1 - weight) * parc
            )
            monthly_rows.append(
                {
                    "active_sku_id": str(sku),
                    "segment": segment,
                    "month": month,
                    "horizon_index": month_index + 1,
                    "model": model_name,
                    "mu_month_baseline": monthly_baseline,
                    "mu_month_parc": parc,
                    "baseline_weight": weight,
                    "forecast_quantity": float(monthly_blended),
                    "fit_through": str(panel.columns[-1]) if len(panel.columns) else "",
                    "basis": label,
                }
            )
    return pd.DataFrame(rows), lambda_table, pd.DataFrame(monthly_rows)


def fleet_eligible_skus(classification: pd.DataFrame) -> list[str]:
    """Return MC SKU identities eligible for motorcycle-fleet demand.

    Business meaning: the supplied UIO source is a motorcycle fleet. OBM parts must use
    their own order history until an outboard installed-base source is supplied.
    """
    if "segment" not in classification:
        raise SourceDataError("forecast classification has no MC/OBM segment")
    mc = classification["segment"].astype(str).eq(SEGMENT_MC)
    return classification.loc[mc, "active_sku_id"].astype(str).unique().tolist()


def _fleet_inputs(
    classification: pd.DataFrame, result: StageResult
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """Each SKU's compatible model codes, and the base-scenario fleet by model, year and band.

    Compatibility comes from the catalogue store (PN_Yamaha matched to the PDF catalogues,
    on the material, its Latest SS or its supersession chain). Where the store is not
    reachable, the part master's compatibility is used against the whole fleet, as before.
    """
    if not table_exists("facts", "uio_age_matrix"):
        result.warn("no UIO matrix — parc-driven demand unavailable, baseline only")
        return {}, pd.DataFrame()
    uio = read_table("facts", "uio_age_matrix")
    uio = uio[uio["scenario"] == "base"]
    fleet = (
        uio.assign(
            model_code=uio["enterprise_model_id"].astype(str), age_band=uio["age"].map(age_band)
        )
        .pivot_table(
            index=["model_code", "year"], columns="age_band", values="units", aggfunc="sum"
        )
        .reindex(columns=AGE_BANDS)
        .fillna(0.0)
    )
    skus = fleet_eligible_skus(classification)
    fleet_codes = set(fleet.index.get_level_values("model_code"))
    try:
        compat = _catalogue_compatibility(skus, fleet_codes)
    except Exception as exc:  # noqa: BLE001 - the store is optional; fall back and say so
        compat = {}
        result.warn(f"catalogue store unreachable ({type(exc).__name__}) — using part master")
    if compat:
        result.warn(
            f"MC parc coverage: {len(compat):,}/{len(skus):,} SKUs link to fleet models through "
            f"the catalogue store (PN_Yamaha + PDF catalogues); each is forecast from its own "
            f"compatible models' fleet"
        )
        return compat, fleet
    master = read_table("facts", "part_master")
    mc_skus = set(skus)
    has_compat = master.loc[
        master["compatible_models"].astype(str).str.strip().ne("")
        & master["active_sku_id"].astype(str).isin(mc_skus),
        "active_sku_id",
    ].unique()
    result.warn(
        f"MC parc coverage: {len(has_compat):,} SKUs carry part-master compatibility that is a "
        f"label, not a joinable key — they are forecast from the whole fleet"
    )
    return {str(s): ["*"] for s in has_compat}, fleet


def _catalogue_compatibility(skus: list[str], fleet_codes: set[str]) -> dict[str, list[str]]:
    """SKU -> fleet model codes, from ``pn_yamaha_compatibility`` in the catalogue store."""
    import psycopg

    from src.catalogue.store import material_key, material_key_forms
    from src.core.settings import get_settings

    with (
        psycopg.connect(**get_settings().postgres_params(), connect_timeout=5) as con,
        con.cursor() as cur,
    ):
        cur.execute(
            "select material_key, latest_ss_key, compatible_models from pn_yamaha_compatibility "
            "where compatible_models is not null"
        )
        rows = cur.fetchall()
    by_key: dict[str, set[str]] = {}
    for material, latest, models in rows:
        codes = {c for c in model_codes(models) if c in fleet_codes}
        if not codes:
            continue
        for key in {material, latest} - {None}:
            by_key.setdefault(str(key), set()).update(codes)
    out: dict[str, list[str]] = {}
    for sku in skus:
        codes: set[str] = set()
        for form in material_key_forms(material_key(sku)):
            codes |= by_key.get(form, set())
        if codes:
            out[sku] = sorted(codes)
    return out


def exposure(fleet: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Fleet by year and age band summed over ``codes`` ("*" = the whole fleet)."""
    if codes == ["*"]:
        return fleet.groupby(level="year").sum()
    present = [c for c in codes if c in fleet.index.get_level_values("model_code")]
    if not present:
        return pd.DataFrame(columns=AGE_BANDS)
    return fleet.loc[present].groupby(level="year").sum()


def _parc_component(
    ctx: PlanningContext,
    classification: pd.DataFrame,
    train_panel: pd.DataFrame,
    compat: dict[str, list[str]],
    fleet: pd.DataFrame,
    result: StageResult,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Fit λ(a) per behaviour class on each part's own fleet, and project demand.

    ``D(p,t) = k(p) · Σ_a UIO_p(a,t) · λ_class(a)`` — UIO_p is the fleet of the models the
    part fits, so a part on a fast-growing young model rises with it and a part on a
    shrinking pre-ban model falls. k(p) ties the class curve to the part's own level
    (1 for a part with no history, which can only be forecast from the fleet).
    """
    if fleet.empty or not compat:
        return pd.DataFrame(), {}
    years = sorted(set(fleet.index.get_level_values("year")))
    month_year = {m: int(str(m)[:4]) for m in train_panel.columns}
    usable = [m for m in train_panel.columns if month_year[m] in years]
    if len(usable) < 2 * len(AGE_BANDS):
        result.warn(
            f"only {len(usable)} month(s) overlap the UIO years — too few to fit "
            f"{len(AGE_BANDS)} age bands, so parc-driven demand is unavailable"
        )
        return pd.DataFrame(), {}
    forecast_year = ctx.as_of.year if ctx.as_of.year in years else max(years)

    cache: dict[tuple[str, ...], pd.DataFrame] = {}

    def part_fleet(sku: str) -> pd.DataFrame:
        key = tuple(compat[sku])
        if key not in cache:
            cache[key] = (
                exposure(fleet, list(key)).reindex(index=years, columns=AGE_BANDS).fillna(0.0)
            )
        return cache[key]

    lambda_rows: list[dict[str, object]] = []
    parc_demand: dict[str, float] = {}
    for behaviour, group in classification.groupby("behaviour_class"):
        skus = [s for s in group["active_sku_id"].astype(str) if s in compat]
        if len(skus) < 5:
            continue
        in_panel = [s for s in skus if s in train_panel.index]
        design = np.zeros((len(usable), len(AGE_BANDS)))
        observed = np.zeros(len(usable))
        for sku in in_panel:
            f = part_fleet(sku)
            design += np.vstack([f.loc[month_year[m]].to_numpy(dtype=float) for m in usable])
            observed += train_panel.loc[sku, usable].to_numpy(dtype=float)
        coefficients, errors = fit_lambda(design, observed)
        if coefficients.size == 0 or not np.any(coefficients > 0):
            continue
        for band, value, error in zip(AGE_BANDS, coefficients, errors, strict=False):
            lambda_rows.append(
                {
                    "segment": SEGMENT_MC,
                    "behaviour_class": behaviour,
                    "age_band": band,
                    "age": AGE_BANDS.index(band),
                    "lambda": float(value),
                    "std_error": float(error),
                    "ci_low": float(max(value - 1.96 * error, 0.0)),
                    "ci_high": float(value + 1.96 * error),
                    "parts_pooled": len(in_panel),
                    "months_fitted": len(usable),
                }
            )
        for sku in skus:
            f = part_fleet(sku)
            per_month = f @ coefficients  # expected units per month for each fleet year
            ahead = float(per_month.get(forecast_year, 0.0))
            if ahead <= 0:
                continue
            if sku in train_panel.index:
                observed_total = float(train_panel.loc[sku, usable].sum())
                fitted_total = float(sum(per_month.get(month_year[m], 0.0) for m in usable))
            else:
                observed_total = fitted_total = 0.0
            if observed_total > 0 and fitted_total > 0:
                k = min(K_CLIP[1], max(K_CLIP[0], observed_total / fitted_total))
            else:
                k = 1.0
            parc_demand[sku] = k * ahead

    lambda_table = pd.DataFrame(lambda_rows)
    if not lambda_table.empty:
        result.warn(
            f"lambda fitted for {lambda_table['behaviour_class'].nunique()} behaviour class(es) "
            f"on each part's own fleet, with confidence intervals — cohort collinearity makes "
            f"any single age coefficient weakly identified, so read the curve, not the point"
        )
    return lambda_table, parc_demand
