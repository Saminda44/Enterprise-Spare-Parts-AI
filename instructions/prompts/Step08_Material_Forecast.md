# Step 08 - Order Material Forecast

| | |
|---|---|
| **Builds** | `src/forecast/parc_demand.py - src/forecast/run.py` |
| **Reads** | `model_registry`, `demand_history`, `part_master_enriched`, `uio_age_matrix` |
| **Writes** | `forecast_protection` -> appended to `part_master_enriched` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Forecast monthly order quantity 12 months ahead for every part - from its own history and from the vehicle parc by age - and quantify the uncertainty around it.

## Two forecasts, reconciled

**Baseline** - the champion model from Step 07 applied to each part's own history, 12 months ahead,
monthly, weighted toward the **last 24 months**.

**Parc-driven** - demand implied by the vehicle fleet:

```
D(p,t) = SUM over models m in compat(p), SUM over ages a:
             UIO(m, a, t) * lambda(p, a) * s(t) * k(p)
```

- `UIO(m,a,t)` - units in operation, model m, age bucket a, month t (from Step 10)
- `lambda(p,a)` - consumption of part p per vehicle-year at age a
- `s(t)` - seasonal factor
- `k(p)` - a calibration scalar per part

## Estimating lambda

Penalised **non-negative least squares** over observed monthly demand:

```
minimise  SUM_t ( D_obs(p,t) - SUM_a UIO(a,t) * lambda_a )^2
          + alpha * SUM_a ( lambda_a - lambda_{a-1} )^2
subject to lambda_a >= 0
```

The smoothness penalty encodes the physical fact that consumption does not jump between adjacent age
years. Choose `alpha` by cross-validation.

**Pool by behaviour class** (Step 06). A single part rarely has enough signal to fit 16 age
coefficients; a whole class does.

> **Collinearity warning.** Cohort sizes move together over time, so individual `lambda_a` values are
> weakly identified even when the fitted total is accurate. Always report **confidence intervals** on
> lambda, and never present a single age coefficient as a finding without them. The fitted *curve* is
> trustworthy; any one point on it is much less so.

## The Sri Lankan parc is bimodal - this is the whole point

Registrations by year, from `Sales Summery.xlsx`:

```
2014  8,895     2018  55,516     2021       85
2015 16,407     2019  53,681     2022-24  none
2016 23,493     2020  26,701     2025   22,084
2017 39,526                      2026   32,344
```

The 2021-2024 gap is the **vehicle import ban**, not missing data. So the fleet is two blocks: a large
2014-2020 block now aged **6-12 years**, and a young 2025-2026 block.

Consequences you must not average away:

1. The old block sits squarely in the **high-consumption age band** - wear parts for those models are
   where demand is now.
2. The young block will demand **almost nothing for several years**, then step up sharply.
3. A part fitting only 2025-2026 models has essentially **no demand history** and cannot be forecast
   from its own past at all. Parc-driven is the only route for those parts.
4. A part fitting only pre-2021 models faces a parc that is **shrinking through retirement** and will
   not be replenished by new registrations.

Any model that extrapolates recent parts demand forward without the parc will miss all four.

## Reconciliation

Where both forecasts exist, blend with weights driven by data sufficiency: parts with long history
lean baseline; parts on young models lean parc. Publish **both** plus the blend - a buyer who cannot
see the disagreement cannot judge it.

## Uncertainty

Produce, per part, the **distribution** of demand over the protection interval P = L + R = 4 months,
not just a point:

- smooth / erratic: normal approximation, `sigma_P` from residuals
- intermittent / lumpy: **empirical bootstrap** of the 4-month sum from residuals

Step 13 needs the distribution. A point forecast cannot size a buffer.

## Supersession weighting

Weight toward the **latest** part number in each chain when history is split across superseded
numbers - the old number's demand is real but will not recur under that number.

## Output

`forecast_protection`: `active_sku_id`, `month`, `mu`, `sigma`, quantiles (P50/P90/P95), `method`,
`mu_P`, `sigma_P`, plus the bootstrap sample reference. Appended to `part_master_enriched`, refreshed
monthly.

## Validation

1. Holdout untouched - assert programmatically that no row with `month > holdout_start` entered any
   fit.
2. Parc reconstruction: predicted vs actual total demand by model family, plotted.
3. `lambda` curves plotted per behaviour class **with confidence bands**.
4. Parts on 2025-2026-only models are flagged `parc_only` and reported separately.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Does `s(t)` need real seasonality, or is monthly variation mostly noise at part level?
2. For parts fitting both old and new models, should lambda be fitted jointly or per model family?
3. How should the 2021-2024 gap be treated in survival - no registrations, or registrations recorded
   elsewhere (grey imports, re-registrations)?
4. Confirm the 12-month horizon and the 3-month lead time are still right.
