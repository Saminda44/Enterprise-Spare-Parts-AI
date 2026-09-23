# Step 12 - Stock and Inventory Position

| | |
|---|---|
| **Builds** | `src/inventory/stock.py` |
| **Reads** | `current_stock.xlsx`, `On_Orders.xlsx`, `PN_Yamaha.xlsx`, `part_master` |
| **Writes** | `stock_position` -> appended to `part_master_enriched` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Establish what is on the shelf at the PDC and what is already coming, and compute the inventory position correctly. This is the most common place a replenishment system goes wrong.

## What the files actually are

`current_stock.xlsx`: **26,288 rows x 8 columns**, 19,830 distinct materials.

```
Name 1, Plant, Material Group, Material, Material Description,
Storage Location, Descr. of Storage Loc., Unrestricted
```

**There is only one quantity column: `Unrestricted`.** No Quality Inspection, Restricted, Blocked,
Returns or Transit buckets exist in this export. So `on_hand = Unrestricted`, directly - and the run
report should note that non-sellable stock is invisible here, in case it matters later.

`On_Orders.xlsx`, sheet `Sheet3`: **2,820 rows x 10 columns** - `PN`, `Desc`, then `Jan`...`Aug`.
A month-column pivot, **2026**, totalling **252,568 units**.

## Scope - PDC only

**16 plants** are present. Seeduwa PDC (`W1B4`) holds **471,137 of 544,372 units - 86.6%**.

Filter to **`Plant == "W1B4"`** (15,493 rows). Branch stock is out of scope for replenishment; publish
it as visibility only if wanted, but it never enters inventory position.

| Plant | Location | Units |
|---|---|---|
| W1B4 | Seeduwa - PDC-Parts | 471,137 |
| W734 | Anuradhapura-Agri-Auto | 10,331 |
| W124 | Borella-After Sales | 8,550 |
| W1O4 | Union Place-YMC | 7,322 |
| ...12 more | | |

## Cleaning order

1. Drop fully null columns, then fully null rows.
2. Filter to plant `W1B4`.
3. **Remove every material not present in `PN_Yamaha.xlsx`** - match on `Material` and on all ten
   supersede columns before rejecting. Report the count and value removed; do not drop silently.
4. Aggregate to `active_sku_id` (multiple storage locations within the PDC roll up).

No negative quantities appear in the sample - assert this and fail if that changes.

## On order

Reshape `On_Orders.xlsx` from wide to long: `PN`, `month` (2026), `qty`. Join to `active_sku_id`
through the supersession chain, same as stock.

> **Interpretation flag.** Treat the month columns as **expected arrival month** by default -
> `on_order_interpretation: "arrival"` in config. If procurement confirms they are the month the PO
> was raised, switch to `"raised"` and the loader adds the 3-month lead to derive arrival. Print the
> active interpretation in every run report; this single assumption shifts the entire pipeline
> position by a quarter.

Only months **>= `ctx.as_of`** count as on-order. Earlier months have already arrived and are inside
`on_hand`; counting them again double-counts the pipeline.

## Inventory position

```
IP = on_hand + on_order - backorders
```

With a 3-month lead and monthly review there can be **three orders in flight**. Comparing against
on-hand instead of IP over-orders by roughly a lead time's worth of demand, every month, until the
pipeline lands. Assert `on_order` is populated and report its share of IP.

Backorders: if no source exists, set to zero and **say so** - do not leave it implicit.

## Output

`stock_position`: `active_sku_id` (pk), `on_hand`, `on_order`, `backorders`, `ip`, `value_unrestricted`,
`storage_locations`, `as_of`. Appended to `part_master_enriched`.

## Validation

1. Cleaned stock + open orders reconciles to full position for the cycle.
2. Materials removed for absence from `PN_Yamaha` reported with count and value.
3. On-order share of IP stated; if it is zero everywhere, that is a data problem, not a fact.
4. PDC share of network stock reported so the scope decision stays visible.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. **Are the `On_Orders` months expected arrival, or when the PO was raised?** Everything in Step 14
   shifts by a quarter on this answer.
2. Is there a backorder / open-commitment source, or is `backorders = 0`?
3. Is `current_stock.xlsx` a point-in-time snapshot? If so, as of what date - we need `as_of`.
4. Do any parts ship direct to branches, bypassing the PDC?
