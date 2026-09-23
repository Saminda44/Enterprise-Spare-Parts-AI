# Step 07 - Forecast Model Selection

| | |
|---|---|
| **Builds** | `src/forecast/backtest.py - src/forecast/selection.py` |
| **Reads** | `demand_history`, `part_master_enriched` |
| **Writes** | `model_registry`, `backtest_results`, protected holdout split |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

For each classification combination, find the forecasting model that actually performs best on a rolling-origin backtest - and record why it won.

## What this step does

It does **not** forecast. It decides, for each classification combination, which model to use - then
hands that decision to Step 08.

## Candidate models, routed by quadrant

| Quadrant | Candidates |
|---|---|
| **smooth** | ETS, SARIMA, Prophet, moving average, XGBoost, LightGBM |
| **erratic** | ETS, quantile regression, LightGBM, moving average |
| **intermittent** | **Croston**, **SBA**, **TSB**, quantile regression |
| **lumpy** | **SBA**, **TSB**, quantile regression, LightGBM |
| **insufficient_history** | moving average / naive only |

Temporal Fusion Transformer is a candidate **only** if the full history is >= 3 years across a wide
part panel; on a short panel it will overfit and win the backtest for the wrong reason. Gate it on a
minimum-panel-size check rather than optimism.

> Classical seasonal models need **two full seasonal cycles**. With 3 years you have that; with the
> 8-month sample you do not. Assert the available history at runtime and drop SARIMA/Prophet from the
> candidate set when it is short, rather than letting them fit noise.

## Evaluation

**Rolling-origin backtest.** Expanding window, step one month, forecast horizon = lead time + review
= **4 months**. Never a random split - shuffling time series leaks the future into the past.

Metric by quadrant:

| Quadrant | Metric | Why |
|---|---|---|
| smooth, erratic | **MASE** | scale-free, comparable across parts |
| intermittent, lumpy | **pinball loss** at the service quantile | MAPE is undefined on zeros; MASE rewards forecasting zero |

Never MAPE. Half these series contain zeros.

## Selection

Per classification combination (quadrant x ABC x behaviour), aggregate backtest scores across its
parts and pick the winner. **Champion-challenger**: the incumbent is replaced only if the challenger
is better by a stated margin. Record the decision, the margin and the sample size in a registry.

A combination with too few parts to judge inherits its parent quadrant's champion. Say so in the
registry rather than pretending a 3-part combination selected a model.

## The holdout

Split off the **final 12 months** of history as a protected holdout before any of this runs. It is
not touched here and not touched in Step 08. It is opened once, in Step 13, and never re-opened.

With ~3 years of data that leaves ~24 months for training and selection - workable. If the full file
turns out shorter, reduce the holdout to 6 months and **state it**; do not silently shrink it.

## Output

`model_registry`: classification combination, chosen model, hyperparameters, backtest score, runner-up
and its score, sample size, selection date.

## Validation

1. Leakage audit: pick 3 random (part, origin) pairs and prove the fit used only data <= origin.
2. Every quadrant has a champion; no combination is left unassigned.
3. Champions beat the naive baseline. **If a champion cannot beat naive, use naive** and record it -
   that is a real result, not a failure to hide.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Confirm the true span of the full order file so the holdout can be sized.
2. Is a seasonal pattern expected in Sri Lankan motorcycle parts demand - monsoon, festival season,
   year-end? If so, which months?
3. Forecast at `active_sku_id` level for all ~30k parts, or only the moving subset (6,422 appear in
   the 8-month sample)?
4. Is there budget/time for TFT, or should the stack stay classical plus gradient boosting?
