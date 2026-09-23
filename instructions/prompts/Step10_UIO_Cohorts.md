# Step 10 - UIO, Survival and Age Cohorts

| | |
|---|---|
| **Builds** | `src/parc/cohorts.py - src/parc/survival.py` |
| **Reads** | `Sales Summery.xlsx`, `unit_sales` (MCSI) |
| **Writes** | `uio_age_matrix`, `survival_curves`, `registration_forecast` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Build units-in-operation per model, per month, per yearly age bucket - rolled forward with age-specific survival. This matrix is what makes the demand forecast parc-driven.

## What the file actually is

`Sales Summery.xlsx` - **20 sheets**. The ones that matter:

| Sheet | Contents |
|---|---|
| `All Years` | 837 rows: Year x Model x Name x Colour with `Vehicle Units (ZVOR)`, Status, Family, Type, Segment, cc |
| `Model Classification` | **113 models** with Status, First/Last Year Sold, Family, Type, Segment, cc |
| `Model Family x Year` | 22 families x years |
| `Status x Year` | Active/Inactive split by family and year |
| `Color Master` | colour names, abbreviations, codes |
| Year sheets | 2014-2021, 2025, 2026 |

## Registrations by year - and the gap

```
2014   8,895      2018  55,516      2021        85
2015  16,407      2019  53,681      2022-2024  (no sheets)
2016  23,493      2020  26,701      2025   22,084
2017  39,526                        2026   32,344
```

**Total 2014-2026: 278,732 units.**

The 2021-2024 collapse is Sri Lanka's **vehicle import ban**, not a data gap. 2021 has 85 units;
2022-2024 have none. Model this as **genuinely zero registrations**, and make the code say so
explicitly - a future maintainer will otherwise "fix" it by interpolating, and destroy the age
structure.

## Cohort assembly

```
cohort(model, year) = units registered
```

Convert to monthly where MCSI supports it (2025-2026), annual before that. Age buckets are **yearly**:
`0-1`, `1-2`, ... `14-15`, `15+`.

Status comes from `Model Classification`: models last sold 2014-2021 are **Inactive**; 2025-2026
models are **Active**. Both stay in the parc - an inactive model still has bikes on the road consuming
parts. Inactive only means no new units enter.

## Survival analysis

Fit vehicle retirement, **age-specific**:

- **Kaplan-Meier** - non-parametric baseline
- **Weibull** - parametric, extrapolates past observed ages
- **Cox** - if covariates (type, segment, cc) prove informative

Select on held-out concordance / log-likelihood. Report which won and by how much.

> Survival must be **age-specific**, not a flat annual attrition rate. A flat rate says a 1-year-old
> bike and a 14-year-old bike retire at the same pace, which is false and flattens exactly the age
> structure the demand model depends on.

**The identification problem, stated honestly:** with registrations but no de-registration records,
retirement is not directly observed. If that is the case here, the survival curve is an *assumption*
calibrated against whatever signal exists (service visits, parts demand decay, registry data if
obtainable) - not a measurement. Say which it is in the report, and run the downstream policy under
at least two survival scenarios so the sensitivity is visible.

## Roll forward

```
UIO(m, a+1, t+1) = UIO(m, a, t) * survival(m, a)
UIO(m, 0,   t)   = new registrations in month t
```

## Output

```
uio_age_matrix
  enterprise_model_id : str
  month               : date
  age_bucket          : str     # "0-1" ... "14-15", "15+"
  units               : float
  is_forecast         : bool
  is_estimated        : bool
  scenario            : str
```

`is_estimated` marks cohorts inferred rather than observed. `scenario` carries the survival variant.

## Forecasting new registrations

Forecast forward for **active** models only; inactive models contribute no new units. Try several
models against the annual series and select on accuracy - but note the series is short and broken by
the ban, so a simple approach that respects the structural break will likely beat a clever one.

## Validation

1. Total UIO reconciles to cumulative registrations minus cumulative retirements.
2. The age histogram is plotted and inspected - the 2021-2024 hole must be visible in it. If it is
   not, the roll-forward is wrong.
3. Survival curves plotted per model family with confidence bands.
4. Model naming reconciles between MCSI, `All Years` and `Model Classification`; mismatches listed.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. **Are de-registration or scrappage records available anywhere?** This decides whether survival is
   measured or assumed - the single biggest uncertainty in the parc model.
2. Should 2022-2024 be modelled as exactly zero, or were there grey/used imports not in ZVOR?
3. Do model codes mean the same thing across MCSI, `All Years` and `Model Classification`? Any renames?
4. Confirm yearly age buckets with a `15+` tail, or do you want finer resolution for young bikes?
