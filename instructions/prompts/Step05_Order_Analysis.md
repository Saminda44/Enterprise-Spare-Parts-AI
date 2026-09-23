# Step 05 - Order Analysis, Lost Sales and Lead Time

| | |
|---|---|
| **Builds** | `src/demand/order_analysis.py` |
| **Reads** | `demand_history`, `returns_history`, `part_master` |
| **Writes** | `fulfilment_stats`, `supply_reliability` (beta_hat), `lead_time_stats`, `returns_summary` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Quantify how well orders are being served, how reliable supply is, and how long replenishment actually takes. These three feed the safety-stock maths directly.

## Part A - fulfilment, from the sales-order set

Per line, classify:

| Condition | Class |
|---|---|
| `Order Qty == Confirmed Qty` | **fully confirmed** |
| `Order Qty > Confirmed Qty > 0` | **partially confirmed** |
| `Confirmed Qty == 0` | **fully rejected** |

Report **lines and quantities** for each, and roll the same classification up to the **purchase
order** (`Sales Document`) level: a PO is fully confirmed only if all its lines are.

Sample baseline to reproduce: 30,553 fully confirmed / 913 partial / 15,055 fully rejected lines;
592,829 ordered vs 441,737 confirmed units - **fill rate 0.745**.

## Part B - supply reliability

```
beta_hat = confirmed / ordered
```

Estimate **per part** and **per material category**, with a monthly series so drift is visible. Guard
against parts with only one or two order lines - use a shrinkage estimator toward the category mean
rather than letting a single fully-rejected line produce beta_hat = 0.

`beta_hat` feeds Step 14, where **inflating orders by 1/beta_hat is off by default**. Record it here;
decide there.

## Part C - lead time

The order export carries `Document Date`, `Delivery Date` and `Material Availability Date`.

```
lead_time = Delivery Date - Document Date
```

Compute the distribution per part and per category: mean, **standard deviation**, P50, P90. The
standard deviation is what Step 13 needs - a point estimate of lead time is not enough to size safety
stock.

If those date fields prove unreliable, fall back to the planning assumption of **3 months** and say so
loudly in the run report, because a wrong sigma_L silently mis-sizes every buffer.

## Part D - returns

From the `H` set (194 rows in the sample): number of return invoices, total return quantity, total
return value, unique SKUs returned, and **return rate** against sales. Break down by Material
Category.

## Part E - performance cuts

Material-wise, dealer-wise, and by RM / ASE / Province / District - mirroring Step 04 so the ordered
and billed views can be compared side by side.

## KPIs

Total invoices, total ordered quantity, total confirmed quantity, total sales value, unique SKUs
ordered.

## Validation

1. The three fulfilment classes partition the line set exactly - no row in two classes, none in none.
2. Line-level and PO-level rollups reconcile.
3. `beta_hat` between 0 and 1 for every part; list any part where it is exactly 0 and say how many
   lines produced it.
4. Lead-time distribution plotted and eyeballed before it is used.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Are `Delivery Date` and `Material Availability Date` reliably populated in the full file? They are
   the only route to a measured lead-time sigma.
2. Should `Reason for Rejection` filter what counts as lost sales? A credit-block rejection is not a
   stock failure.
3. For `beta_hat`, what minimum number of order lines makes a part's estimate trustworthy?
