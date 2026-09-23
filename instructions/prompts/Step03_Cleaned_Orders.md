# Step 03 - Order Cleaning and Demand History

| | |
|---|---|
| **Builds** | `src/demand/orders.py` |
| **Reads** | `orders.xlsx`, `dealers.xlsx`, `part_master` |
| **Writes** | `demand_history` (sales orders), `returns_history`, `order_exceptions` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Turn the raw order export into a clean monthly demand history per part - including the **measured lost sales** that make this dataset unusually good for inventory work.

## What the file actually is

`orders.xlsx`, sheet `Sheet1`: the sample supplied is **46,514 rows x 102 columns**, Jan-Aug 2026.
**The production file holds about 3 years.** Build for 3 years; never hard-code the 8-month window.

Of the 102 columns, roughly 60 are empty contract/cancellation fields. Keep this shortlist:

```
Document Date, Sales Document, Sales Document Item, Sales Document Type,
SD Document Category, Sold-to Party, Sold-To Party Name, Material,
Material Description, Order Quantity (Item), Confirmed Quantity (Item),
Net Price, Net Value (Item), Plant, Storage Location, Reason for Rejection,
Delivery Date, Item Category, Sales Office
```

`Material` here is the **bare part number** (`17540-53U01`) - no glued description. `Sold-to Party` is
numeric and separate from `Sold-To Party Name`.

## Cleaning order - this order, not the reverse

1. Drop **fully null columns**, then **fully null rows**. (Doing rows first leaves the ~60 empty
   columns in place and they then block the row test.)
2. Join `dealers.xlsx` (**414 rows**) on `Dealer Code` = `Sold-to Party` **and** `Dealer Name` =
   `Sold-To Party Name`. Bring `Type` into a new **`Dealer Type`** column; unmatched becomes
   `"Not Found"`.
3. **Do not remove rows whose `Dealer Code` is `"No Code"`.** They are real demand.
4. Join `part_master`. Drop rows matching neither `Material` nor any of the ten supersede columns -
   to an exceptions table with counts, not silently.

## Split by document category

| `SD Document Category` | Meaning | Sample count |
|---|---|---|
| `C` | **Sales Order** | 46,320 |
| `H` | **Return Sale** | 194 |

Split into two outputs. Everything downstream that says "demand" means the `C` set.

## Material Category

```
Dealer Type == "MC":
    description contains "YAMALUBE"        -> Lubricant
    description contains "KARATE BATTERY"  -> Battery
    description contains "KATANA TYRE"     -> Tyre
    otherwise                              -> MC Spare Parts
Dealer Type == "OBM":                      -> OBM Spare Parts
```

Match case-insensitively on `Material Description`. Report the count falling in each bucket and the
count where `Dealer Type` is `"Not Found"` - those get no category and must not be silently dropped.

## Lost sales - measured, not inferred

```
Lost Quantity   = Order Quantity (Item) - Confirmed Quantity (Item)
Lost Sale Value = Lost Quantity x Net Price
Order Value     = Confirmed Quantity (Item) x Net Price
```

**This is the most valuable column in the project.** Most inventory systems have to infer stockouts
from demand that never appears. Here the shortfall is recorded on every line.

In the sample: **74.5% overall fill rate**, 15,055 lines (32%) fully rejected. Expect the same shape
across 3 years and make sure nothing in the pipeline quietly treats confirmed quantity as demand.

## Output

`demand_history` at `active_sku_id` x month, carrying ordered, confirmed and lost quantity and value,
dealer type, material category. Plus `returns_history` from the `H` set.

## Validation

1. Row counts reconcile: raw = kept + rejected, by reason.
2. `Order Qty >= Confirmed Qty` on every row; any violation is a data error - list them.
3. Monthly totals tie back to the raw file.
4. Dealer join coverage stated; `"Not Found"` share reported.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. The sample is Jan-Aug 2026. What is the true start date of the full file, and are any months
   missing the way May is missing from `sales.xlsx`?
2. `Sales Document Type` is `ZP2A` (27,041) / `ZP1A` (19,279) / `ZRE` (194). What distinguishes ZP1A
   from ZP2A - and should both count as demand?
3. 32% of lines fully rejected is very high. Is that genuine unavailability, or do some rejection
   reasons mean something else (credit block, cancelled by dealer)?
4. `Reason for Rejection` - which codes mean "no stock" versus a commercial reason? Only the former is
   lost sales.
