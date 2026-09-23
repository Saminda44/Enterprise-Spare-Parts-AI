# Step 13 - Safety Stock, Reorder Level, Reorder Quantity

| | |
|---|---|
| **Builds** | `src/inventory/policy.py - src/inventory/simulation.py` |
| **Reads** | `forecast_protection`, `sku_classification`, `supply_reliability`, `lead_time_stats`, `stock_position` |
| **Writes** | `policy_params`, `policy_selection`, `simulation_results` -> appended to `part_master_enriched` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Compute dynamic safety stock, reorder level and reorder quantity for every part - chosen by simulation rather than by formula alone, and proven on a protected holdout.

## This is the project's acceptance gate

Everything before it is preparation. If this step cannot beat the current way of ordering on the
holdout, the project has not succeeded - and that must be reportable, not hidden.

# Part A - safety stock

Three strategies. **Bracketing is computed for every part** as a cross-check, whichever is used.

| Strategy | Formula | Applied to |
|---|---|---|
| Bracketing | `SS = max_monthly_demand * L_max - d_bar * L_bar` (floor 0) | baseline, cross-check, `insufficient_history` |
| Normal approx | `SS = z * sqrt(P * sigma_d^2 + d_bar^2 * sigma_L^2)` | smooth, erratic |
| Empirical quantile | `SS = Q_tau(D_P) - mu_P` from the Step 08 bootstrap | **intermittent, lumpy** |

`P = L + R = 4` months. `sigma_d = sigma_P / sqrt(P)`, `d_bar = mu_P / P`, `sigma_L` from Step 05.

Empirical quantile is preferred for intermittent and lumpy because the normal assumption is simply
**false** there. Fitting a normal to a part that sells `0,0,0,7,0,0,3` produces a negative lower tail
and an understated upper one.

## Fill rate is not service level

With target fill rate `beta`, expected units short per cycle is `EUS = sigma_eff * G(z)`, where
`G(z) = phi(z) - z*(1 - Phi(z))` is the unit normal loss. Solve numerically (scipy `brentq`) for z
such that:

```
sigma_eff * G(z) / (d_bar * R)  <=  1 - beta
```

Clamp `z` to [0, 4.5].

> **Do not substitute a cycle-service-level lookup table.** CSL asks "what fraction of cycles avoid a
> stockout"; fill rate asks "what fraction of units are served". Swapping them over-stocks slow movers
> and under-stocks fast ones - and the error is largest exactly where the money is.

# Part B - candidate policies

| Policy | Rule |
|---|---|
| **(R,S)** | `S = mu_P + SS`; order `max(0, S - IP)` every review |
| **(R,s,S)** | order only when `IP <= s`, up to `S = s + delta_econ`, `delta_econ = max(EOQ, MOQ, pack)` |
| **On-demand** | no cycle stock; order against firm requirements only |
| **No-stock** | stop ordering (dead parts, pending owner review) |

All four are **monthly-executable**. Continuous review, Min-Max, VMI and JIT are **excluded** - none
can execute on a monthly order cycle against a ~3-month import lead.

### Assignment (config-driven)

| Segment | Candidates |
|---|---|
| smooth | RS |
| erratic, intermittent | RS, RsS |
| lumpy | RsS, RS |
| lumpy x C-class x FSN=S | RsS, RS, ON_DEMAND |
| FSN=N or C-class zero-movers | ON_DEMAND, NO_STOCK |
| `insufficient_history` | RS with bracketing floor |
| **criticality = high** | always includes RS; never ON_DEMAND or NO_STOCK |

# Part C - simulate, select, validate

One walk-forward monthly simulator. **Monthly loop, in this exact order:**

1. **Receive** - pipeline orders due at t arrive at `qty * beta_hat`; the short-shipped remainder is
   logged and gone (lost-sales world).
2. **Demand** - realise actual demand (raw, not outlier-adjusted; the policy must survive real
   spikes). Serve from on-hand; shortfall is lost sales, recorded in units and value.
3. **Review and order** - use parameters computed from data **<= t only** (wire in the Step 07
   rolling-origin artefacts; never refit inside the simulator). `IP = on_hand + pipeline`. `q_final`
   from the Step 14 order function. Append to pipeline with a sampled lead time.
4. Snapshot state.

**(A) Score** every (part x candidate) over the selection window.

**(B) Select** - feasibility first (achieved fill >= target), then minimum holding + ordering cost.
If nothing is feasible, take maximum fill. **Hysteresis: a challenger replaces the incumbent only if
it improves cost by >= 5% while feasible**, so the policy mix does not churn every quarter.

**(C) Validate on holdout** - selected portfolio vs baseline vs sensitivities (`beta_hat` +/- 10pp,
lead time +1 month, fill target +/- 2pp), on the untouched final 12 months, same seed across runs.

> **Never re-open selection based on holdout results.** That un-blinds the holdout and the number
> stops meaning anything. A failed holdout sends you back to Step 06/08 configuration with a **fresh**
> split, recorded in the report.

## Reporting views

`ROL = mu_L + SS_L` and `months_of_cover = S / d_bar`, published for business familiarity.

## Validation gates

1. **Hand-traced toy world** - 2 parts, 12 months, one RS and one RsS (triggering both sides of `s`),
   worked by hand in the report; the simulator reproduces it exactly. Committed as a golden test.
2. **Conservation** - per part-run: `received - served - delta_on_hand = 0`, and
   `ordered * beta_hat = received` within rounding. Asserted across all runs.
3. **Two leakage audits** - (a) three random (part, t) cells used only data <= t; (b) recompute three
   random selections from stored scores and confirm no holdout month contributed.
4. z-solver reproduces textbook z for `beta = 0.95` within tolerance.
5. Worked example: `d_bar = 50/month`, `L = 3`, `SS = 40` -> **ROL = 190**. Committed as a test.

## Acceptance criteria

Portfolio achieved fill rate **>= target per ABC class** *and* average inventory value **<= baseline**,
on the holdout.

If it wins on only one axis, present the frontier honestly and let the owner choose. **Do not massage
a single-axis win into a pass.**

## Definition of Done

All gates pass; both leakage audits clean; holdout report reviewed with the owner and a **go / no-go
verdict recorded**.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. **What are the target fill rates per ABC class?** Nothing here can be sized without them.
2. What is the current baseline ordering rule, so there is something to beat?
3. Annual holding cost rate (% of unit value) and cost per purchase order?
4. Is there a total inventory value cap, or a budget per cycle?
5. For `criticality = high`, is there a different fill target?
