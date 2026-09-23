# Step 14 - Monthly Order Generation

| | |
|---|---|
| **Builds** | `src/inventory/ordering.py - src/marts/` |
| **Reads** | `part_master_enriched`, `policy_selection`, `stock_position` |
| **Writes** | `monthly_order_proposal`, `mart_*` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Turn the selected policies into the actual monthly purchase order - quantities a buyer can send - and publish the marts that explain every line.

## The order function

```
q_raw    = policy_quantity(policy, IP, S, s)       # 0 if not triggered
q_econ   = max(q_raw, EOQ)   if q_raw > 0 and use_eoq  else q_raw
q_moq    = max(q_econ, MOQ)  if q_econ > 0             else 0
q_pack   = ceil(q_moq / pack_size) * pack_size
q_final  = apply_supply_reliability(q_pack)
```

## Objective

Subject to stock, MOQ, ROL and lead time: **maximise service and margin, minimise total cost.**
Stated precisely, because "maximise profit and service and minimise cost" is three objectives and
they conflict:

```
minimise   holding_cost + ordering_cost + lost_margin
subject to achieved_fill_rate >= target(ABC class)
           q respects MOQ, pack size, and any budget cap
```

Lost margin, not lost revenue - a stockout costs the margin forgone. Treating service as a
**constraint** and cost as the **objective** is what makes the problem well-posed; maximising a
weighted blend of all three produces a number nobody can defend.

## EOQ

`EOQ = sqrt(2DS/H)` - D annual demand, S order cost, H annual holding cost per unit. Use it as a
**floor** on a triggered order, never as the order itself: EOQ assumes constant deterministic demand,
which no spare part has. Guard `H > 0` and `D > 0`. Publish the S and H assumptions in the report -
the answer moves with them and nobody will otherwise know.

## Supply reliability - the inflation trap

Suppliers under-ship: measured fill in the sample is **0.745**. To receive `q` you would order
`q / beta_hat`.

**This is dangerous and defaults to off.** If `beta_hat` is low *because* we habitually over-order,
inflating the order lowers `beta_hat` further, which inflates more - a feedback loop ending in a
warehouse full of parts nobody asked for. Therefore:

- `use_supply_inflation` is **config, default `False`**
- when on, cap the factor at `1 / beta_hat <= 1.5`
- estimate `beta_hat` per supplier and part group, never globally
- the **simulator must use the same setting**. A policy selected under inflation-off and executed with
  inflation-on is not the policy that was validated.

## MOQ, pack size, lead time

From the part master where present. Where absent, default to 1 and **say so in the report** - a silent
pack default of 1 on a part that ships in cartons of 24 produces orders that cannot be placed.

## Output contract

`monthly_order_proposal`: `active_sku_id`, `cycle_month`, `policy`, `ip`, `on_hand`, `on_order`,
`s`, `S`, `ss`, `rol`, `q_raw`, `q_final`, `unit_cost`, `value`, `lead_time_months`,
`expected_arrival`, `trigger_reason`, `criticality`, `abc_class`, `flags`.

**Every line carries why.** A buyer who cannot see why a quantity was proposed will not send the
order, and they will be right not to.

## Published marts

| Mart | Contents |
|---|---|
| `mart_monthly_order` | the proposal, buyer-ready |
| `mart_policy_summary` | policy mix by segment, SS and ROL distributions |
| `mart_forecast_accuracy` | backtest and live accuracy by segment and model |
| `mart_service_and_stock` | achieved fill, stockouts, lost sales (units and value), turns, cover |
| `mart_exceptions` | rejected rows, missing masters, data-quality flags |

## Explainability - required per part, on demand

The forecast and its model; sigma; lead time and its sigma; z and the fill target it came from; SS by
all three strategies; the chosen policy and why it beat the alternatives; IP components; and the
arithmetic from IP to `q_final`.

## Monthly run

One command runs Steps 12 -> 13 -> 14 and emits the proposal plus a run report. Parameters refresh
every cycle; policy **selection** re-runs on the configured cadence (default quarterly, with the 5%
hysteresis rule), not every month.

## Validation

1. Worked example: `IP = 120`, `S = 300`, `MOQ = 50`, `pack = 25` -> `q_final = 200`. Committed test.
2. Pack rounding never rounds down; MOQ never applies to a zero order.
3. Marts reconcile to their step outputs row for row.
4. A buyer walks three sample lines end to end and confirms they are placeable.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. **Order cost `S` and annual holding rate `H`** - do finance have figures, or do we assume and
   sensitivity-test?
2. Are MOQ and pack size available anywhere? They are not in `PN_Yamaha.xlsx`.
3. Is there a budget cap per monthly order cycle?
4. What format does the buyer need - CSV, an SAP upload template, or an API call?
