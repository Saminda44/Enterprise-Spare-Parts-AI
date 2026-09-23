# Step 11 - Target and Scenario Simulator

| | |
|---|---|
| **Builds** | `src/parc/targets.py - src/parc/scenarios.py` |
| **Reads** | `Sales Summery.xlsx`, `uio_age_matrix`, `unit_sales` |
| **Writes** | `scenarios`, `scenario_uio`, `scenario_demand` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Forecast unit sales for active models and let a planner simulate yearly targets, seeing how each flows through the parc into parts demand.

## Purpose

A planning surface on top of the parc: what unit sales look like next year under different
assumptions, and what that implies for the parts business.

## Inputs

Active models only - the ones still sold. From `Status x Year`, the active families are RAY, FZ, MT,
R15, NMAX, XSR and FASCINO; everything else is inactive and contributes no new units.

## Part A - sales forecast

Forecast unit sales for currently active models from the `Sales Summery` annual series plus the
MCSI monthly detail. Try several models; select on accuracy.

**Caveat to carry into the report:** the usable series for active models is effectively **2025-2026**,
because the import ban zeroed 2021-2024 and pre-ban volumes came from a different market regime. Two
years is a thin basis for a model selection contest. Prefer simple, explainable methods here and say
plainly that the interval is wide, rather than reporting a winner as if it were well-tested.

## Part B - target simulator

Let a planner set a yearly unit target per model or family and see the consequences flow through:

```
target units -> registration cohorts -> uio_age_matrix (scenario) -> parts demand -> stock and orders
```

Scenarios to support:

- **Base** - the forecast as fitted
- **Target** - planner-supplied unit targets
- **Upside / downside** - percentage shifts on the base
- **Survival variants** - the alternate curves from Step 10

Each writes a `uio_age_matrix` with its own `scenario` label; nothing downstream is overwritten.

> Scenario output is **planning information, not the order**. The monthly purchase order in Step 14
> runs on the base scenario unless a human explicitly switches it. Scenario runs must never silently
> become the operational number.

## Output

`scenarios` (definitions and parameters), `scenario_uio`, `scenario_demand`, and a comparison table
showing parts-demand delta per scenario versus base.

## Validation

1. Base scenario reproduces Step 10's `uio_age_matrix` exactly.
2. A +10% unit target produces a demand increase that lags by the age profile - **not** an immediate
   +10% in parts demand. If parts demand moves 1:1 with unit sales, the age mechanism is not wired up.
3. Scenario runs are reproducible from their stored parameters.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Who sets the targets, and at what level - model, family or total?
2. Should the simulator also handle price or margin scenarios, or units only?
3. How far forward - 12 months, or 3-5 years for the parc build-out?
