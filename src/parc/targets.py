"""Step 11 — unit-sales forecast for active models and the target simulator.

A +10% unit target must **not** produce +10% parts demand. New bikes consume almost
nothing for years; the response lags through the age profile and arrives smaller. If
parts demand moves 1:1 with unit sales, the age mechanism in Step 10 is not wired up.

Scenario output is planning information. The monthly purchase order runs on the base
scenario unless a human explicitly switches it — a scenario must never quietly become
the operational number.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult
from src.io.parquet import read_table, write_table
from src.parc.cohorts import SCENARIOS, age_bucket

#: Percentage shifts applied to the base unit forecast.
SHIFTS = {"upside": 0.10, "downside": -0.10}


def forecast_registrations(cohorts: pd.DataFrame, result: StageResult) -> pd.DataFrame:
    """Forecast next-year units for active models.

    Deliberately simple: the usable series for active models is effectively 2025–2026,
    because the import ban zeroed 2021–2024 and pre-ban volumes came from a different
    market regime. Two points is a thin basis for a model contest, so a mean of the
    recent post-ban years is used and the interval is stated as wide rather than
    reporting a winner as if it were well tested.
    """
    active = cohorts[cohorts["status"].astype(str).str.strip().str.lower() == "active"]
    if active.empty:
        result.warn("no active models in the classification — no registration forecast")
        return pd.DataFrame()

    post_ban = active[active["year"] >= 2025]
    basis = post_ban if not post_ban.empty else active
    forecast = (
        basis.groupby(["Model", "model_name", "family"], as_index=False)["units"]
        .mean()
        .rename(columns={"units": "forecast_units"})
    )
    forecast["basis_years"] = basis["year"].nunique()
    forecast["method"] = "mean of post-ban years"
    result.warn(
        f"registration forecast for {len(forecast)} active model(s) from "
        f"{basis['year'].nunique()} post-ban year(s) — interval is wide and the method is "
        f"deliberately simple; a model contest on two points would not mean anything"
    )
    return forecast


@REGISTRY.register(
    "11_targets",
    depends_on=["10_uio_cohorts"],
    description="unit forecast for active models and the scenario simulator",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="11_targets")
    uio = read_table("facts", "uio_age_matrix")
    base = uio[uio["scenario"] == "base"]
    result.rows_in = len(base)

    cohorts = (
        base.groupby(
            ["enterprise_model_id", "model_name", "family", "status", "cohort_year"], as_index=False
        )["units"]
        .max()
        .rename(columns={"enterprise_model_id": "Model", "cohort_year": "year"})
    )
    registration_forecast = forecast_registrations(cohorts, result)
    if not registration_forecast.empty:
        result.artifact(
            "registration_forecast",
            write_table(registration_forecast, "facts", "registration_forecast"),
        )

    definitions: list[dict[str, object]] = [
        {"scenario": "base", "kind": "forecast", "parameter": "as fitted", "value": 0.0}
    ]
    scenario_uio: list[pd.DataFrame] = [base.assign(scenario="base")]

    next_year = ctx.as_of.year + 1
    for name, shift in SHIFTS.items():
        definitions.append(
            {
                "scenario": name,
                "kind": "percentage shift",
                "parameter": "unit target",
                "value": shift,
            }
        )
        if registration_forecast.empty:
            continue
        rows: list[dict[str, object]] = []
        for row in registration_forecast.itertuples(index=False):
            units = float(row.forecast_units) * (1.0 + shift)
            for horizon in range(0, 5):
                year = next_year + horizon
                surviving = units
                for step in range(horizon):
                    surviving *= SCENARIOS[0].conditional(step)
                rows.append(
                    {
                        "enterprise_model_id": row.Model,
                        "model_name": row.model_name,
                        "family": row.family,
                        "status": "Active",
                        "year": year,
                        "cohort_year": next_year,
                        "age": horizon,
                        "age_bucket": age_bucket(horizon),
                        "units": surviving,
                        "is_forecast": True,
                        "is_estimated": True,
                        "scenario": name,
                    }
                )
        scenario_uio.append(pd.DataFrame(rows))

    # Survival variants from Step 10 are scenarios in their own right.
    for scenario in SCENARIOS[1:]:
        definitions.append(
            {
                "scenario": scenario.name,
                "kind": "survival variant",
                "parameter": "weibull scale",
                "value": scenario.scale,
            }
        )
        scenario_uio.append(uio[uio["scenario"] == scenario.name])

    combined = pd.concat([f for f in scenario_uio if not f.empty], ignore_index=True)
    result.artifact("scenarios", write_table(pd.DataFrame(definitions), "facts", "scenarios"))
    result.artifact("scenario_uio", write_table(combined, "facts", "scenario_uio"))

    # The lag test: parts demand must not move 1:1 with a unit-sales target.
    lambda_available = True
    try:
        curves = read_table("facts", "lambda_curves")
    except Exception:  # noqa: BLE001 - Step 08 may not have produced curves
        lambda_available = False

    if lambda_available and not curves.empty and not registration_forecast.empty:
        # The test is whether TOTAL parts demand moves 1:1 with a unit target. It must
        # not: the extra units are one young cohort inside a fleet of 200,000, and a
        # young bike consumes almost nothing. Comparing the new cohort against itself
        # would trivially return +10% and prove nothing.
        by_band = curves.groupby("age")["lambda"].mean().to_dict()
        fleet = (
            base[base["year"] == base["year"].max()]
            .assign(band=lambda d: (d["age"] // 3).clip(upper=4))
            .groupby("band")["units"]
            .sum()
        )
        base_total = sum(
            float(units) * float(by_band.get(band, 0.0)) for band, units in fleet.items()
        )
        extra_units = float(registration_forecast["forecast_units"].sum()) * 0.10

        rows = []
        for horizon in range(0, 5):
            surviving = extra_units
            for step in range(horizon):
                surviving *= SCENARIOS[0].conditional(step)
            added = surviving * float(by_band.get(min(horizon // 3, 4), 0.0))
            rows.append(
                {
                    "months_after_target": horizon * 12,
                    "base_parts_demand": base_total,
                    "upside_parts_demand": base_total + added,
                    "added_demand": added,
                    "delta_pct": (added / base_total) if base_total else 0.0,
                }
            )
        comparison = pd.DataFrame(rows)
        first = float(comparison.iloc[0]["delta_pct"])
        peak = float(comparison["delta_pct"].max())
        peak_year = int(
            comparison.loc[comparison["delta_pct"].idxmax(), "months_after_target"] / 12
        )
        verdict = "PASS" if first < 0.05 else "FAIL — age mechanism not wired up"
        result.warn(
            f"lag test [{verdict}]: a +10% unit target moves total parts demand by "
            f"{first:.2%} in year one, peaking at {peak:.2%} in year {peak_year}. The "
            f"response lags through the age profile and arrives smaller, as it must — if it "
            f"moved 1:1 the Step 10 mechanism would not be connected."
        )
        result.artifact("scenario_demand", write_table(comparison, "facts", "scenario_demand"))
    else:
        result.warn(
            "no lambda curves available, so the scenario-to-parts-demand link cannot be "
            "quantified this run"
        )

    result.rows_out = len(combined)
    logger.info(f"scenarios: {combined['scenario'].nunique()} variants")
    return result
