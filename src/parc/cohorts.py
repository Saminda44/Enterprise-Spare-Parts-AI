"""Step 10 — units in operation by model, month and yearly age bucket.

The 2021–2024 collapse is Sri Lanka's vehicle import ban, not missing data: 2021 has 85
units and 2022–2024 have none. It is modelled as genuinely zero and must remain visible
in the age histogram. A future maintainer who "fixes" it by interpolating destroys the
age structure the entire demand model rests on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger

from src.core.context import PlanningContext
from src.core.registry import REGISTRY
from src.core.result import StageResult, StageStatus
from src.io.excel import read_source
from src.io.parquet import write_table

MAX_AGE = 15
AGE_BUCKETS = [f"{a}-{a + 1}" for a in range(MAX_AGE)] + [f"{MAX_AGE}+"]


@dataclass(frozen=True)
class SurvivalScenario:
    """A Weibull retirement curve.

    Business meaning: **this is an assumption, not a measurement.** No de-registration
    or scrappage record exists in any supplied file, so vehicle retirement is not
    observed. Downstream policy is therefore run under more than one curve so the
    sensitivity is visible rather than buried in a single number.
    """

    name: str
    shape: float  # Weibull k — >1 means the hazard rises with age
    scale: float  # Weibull lambda, in years — characteristic life

    def survival_to(self, age: float) -> float:
        """S(age) = exp(-(age/scale)^shape)."""
        return float(np.exp(-((max(age, 0.0) / self.scale) ** self.shape)))

    def conditional(self, age: int) -> float:
        """P(surviving age -> age+1 | alive at age) — the age-specific rate."""
        current = self.survival_to(age)
        if current <= 0:
            return 0.0
        return min(1.0, self.survival_to(age + 1) / current)


SCENARIOS = (
    SurvivalScenario("base", shape=2.2, scale=16.0),
    SurvivalScenario("long_life", shape=2.2, scale=20.0),
    SurvivalScenario("short_life", shape=2.2, scale=12.0),
)


def age_bucket(age: int) -> str:
    return f"{MAX_AGE}+" if age >= MAX_AGE else f"{age}-{age + 1}"


def load_registrations(result: StageResult) -> pd.DataFrame:
    """Model × year registration cohorts from the Sales Summery 'All Years' sheet."""
    frame = read_source("sales_summery__all_years")
    frame.columns = [str(c).strip() for c in frame.columns]
    qty_col = "Vehicle Units (ZVOR)"
    frame = frame[pd.to_numeric(frame["Year"], errors="coerce").notna()].copy()
    frame["year"] = pd.to_numeric(frame["Year"], errors="coerce").astype(int)
    frame["units"] = pd.to_numeric(frame[qty_col], errors="coerce").fillna(0)

    cohorts = frame.groupby(["Model", "year"], as_index=False).agg(
        units=("units", "sum"),
        model_name=("Model Name", "first"),
        family=("Model Family", "first"),
        status=("Status", "first"),
        segment=("Segment", "first"),
        vehicle_type=("Motorcycle Type", "first"),
    )
    by_year = cohorts.groupby("year")["units"].sum()
    result.warn(
        "registrations by year: "
        + ", ".join(f"{y}={int(u):,}" for y, u in by_year.items())
        + f"; total {int(by_year.sum()):,}"
    )
    missing = [
        y
        for y in range(int(by_year.index.min()), int(by_year.index.max()) + 1)
        if y not in by_year.index
    ]
    if missing:
        result.warn(
            f"IMPORT BAN — years with no registrations at all: {missing}. Modelled as "
            f"genuinely zero, never interpolated."
        )
    return cohorts


def roll_forward(
    cohorts: pd.DataFrame, scenario: SurvivalScenario, as_of_year: int
) -> pd.DataFrame:
    """Age every cohort forward, losing a share at each step.

    ``UIO(m, a+1, t+1) = UIO(m, a, t) * survival(m, a)``
    """
    rows: list[dict[str, object]] = []
    years = sorted(cohorts["year"].unique())
    start, end = int(min(years)), int(as_of_year)
    for model, group in cohorts.groupby("Model"):
        registrations = dict(zip(group["year"], group["units"], strict=True))
        meta = group.iloc[0]
        for observation_year in range(start, end + 1):
            for cohort_year, units in registrations.items():
                if cohort_year > observation_year:
                    continue
                age = observation_year - cohort_year
                surviving = float(units)
                for step in range(age):
                    surviving *= scenario.conditional(step)
                if surviving < 0.5:
                    continue
                rows.append(
                    {
                        "enterprise_model_id": model,
                        "model_name": meta["model_name"],
                        "family": meta["family"],
                        "status": meta["status"],
                        "year": observation_year,
                        "cohort_year": cohort_year,
                        "age": age,
                        "age_bucket": age_bucket(age),
                        "units": surviving,
                        "is_forecast": False,
                        "is_estimated": True,
                        "scenario": scenario.name,
                    }
                )
    return pd.DataFrame(rows)


@REGISTRY.register(
    "10_uio_cohorts",
    depends_on=["09_unit_sales"],
    description="UIO by model, age bucket and year, under survival scenarios",
)
def run(ctx: PlanningContext) -> StageResult:
    result = StageResult(stage="10_uio_cohorts")
    cohorts = load_registrations(result)
    result.rows_in = len(cohorts)
    if cohorts.empty:
        result.status = StageStatus.FAILED
        result.error = "no registration cohorts found"
        return result

    result.warn(
        "SURVIVAL IS ASSUMED, NOT MEASURED: no de-registration or scrappage record exists "
        "in any supplied file, so retirement is a Weibull assumption calibrated to plausible "
        f"life, not an observation. Scenarios run: {', '.join(s.name for s in SCENARIOS)}."
    )

    frames = [roll_forward(cohorts, scenario, ctx.as_of.year) for scenario in SCENARIOS]
    matrix = pd.concat(frames, ignore_index=True)
    result.rows_out = len(matrix)
    result.artifact("uio_age_matrix", write_table(matrix, "facts", "uio_age_matrix"))

    base = matrix[matrix["scenario"] == "base"]
    current = base[base["year"] == ctx.as_of.year]
    histogram = (
        current.groupby("age_bucket", as_index=False)["units"].sum().sort_values("age_bucket")
    )
    result.artifact("uio_age_histogram", write_table(histogram, "facts", "uio_age_histogram"))

    empty_buckets = [
        bucket
        for bucket in AGE_BUCKETS
        if bucket not in set(histogram["age_bucket"])
        or float(histogram.loc[histogram["age_bucket"] == bucket, "units"].sum()) < 1
    ]
    result.warn(
        f"age histogram at {ctx.as_of.year}: total UIO {current['units'].sum():,.0f} under "
        f"'base'; empty age buckets {empty_buckets} — the import-ban hole must appear here"
    )

    totals = (
        matrix.groupby(["scenario", "year"], as_index=False)["units"]
        .sum()
        .pivot(index="year", columns="scenario", values="units")
        .reset_index()
    )
    result.artifact(
        "uio_totals_by_scenario", write_table(totals, "facts", "uio_totals_by_scenario")
    )

    curves = pd.DataFrame(
        [
            {
                "scenario": s.name,
                "age": age,
                "conditional_survival": s.conditional(age),
                "cumulative_survival": s.survival_to(age),
            }
            for s in SCENARIOS
            for age in range(MAX_AGE + 1)
        ]
    )
    result.artifact("survival_curves", write_table(curves, "facts", "survival_curves"))

    logger.info(f"uio matrix: {len(matrix):,} rows across {len(SCENARIOS)} scenarios")
    return result
