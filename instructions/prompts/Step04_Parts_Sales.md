# Step 04 - Parts Sales and Revenue

| | |
|---|---|
| **Builds** | `src/demand/sales.py` |
| **Reads** | `sales.xlsx`, `dealers.xlsx`, `part_master` |
| **Writes** | `parts_sales`, `sales_performance`, `sales_kpis` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Build the billed-sales view - revenue, cost and margin per part and per dealer - and the geographic and time-trend performance cuts.

## What the file actually is

`sales.xlsx`, sheet `Sheet1`: **21,301 rows x 41 columns**, billing dates **2026-01-05 to
2026-08-31**. **May 2026 is absent entirely** - Jan 2,864 / Feb 2,816 / Mar 2,885 / Apr 2,784 /
**May 0** / Jun 3,475 / Jul 2,969 / Aug 3,508. Confirm whether that is an export gap before
publishing any trend that spans it.

## The glued columns - resolved

`Payer` contains **both** dealer code and dealer name:

```
"26198      Yamaha Sales Center"  ->  code 26198, name "Yamaha Sales Center"
```

`Material` does the same: `"676-42115-00       SHAFT STEERING YAMAHA 40 HP"`. Use the Step 00 parser.
Join `Dealer Type` on the **extracted code** against `dealers.xlsx`; fall back to name match only when
the code misses. Unmatched -> `"Not Found"`.

This settles the old data-dictionary contradiction - "Payer = Dealer Code" and "Payer = Dealer Name"
were both correct descriptions of one column.

## Money columns - verified against the data

```
Net Sales = Sales Pric + Discount        (exact, max abs diff 0.0 over all 21,301 rows)
Margin    = Net Sales - Cost
```

`Discount` is stored **negative**. `Tax Amount` sits outside `Net Sales`. `Revenue Re` and
`Cost Reduc` are **zero in every row** - they are not part of any revenue calculation here.

> Use this. Do not implement the old dictionary formula
> `Net Sales - (Tax - Revenue Re - Dealer Commission - Cost of Sales)`; it referenced columns that do
> not exist or are never populated, and as bracketed it added cost to revenue.

`SlsVolQty` is the sold quantity; **negative means a return** or a wrongly entered material being
reversed - 250 such rows in the sample. Keep them and net them; do not filter them out.

`Bill. Type`: F2 19,896 / ZVAT 1,150 / RE 154 / S1 81 / ZRVT 20. Confirm which are returns.

## Cleaning order

Fully null columns first (`Batch` and `Cust. Clas` are entirely null), then fully null rows. Then
`Dealer Type`, then the `part_master` filter, then `Material Category` by the same rules as Step 03
(matching on the **extracted description**, not the glued string).

## Analysis to produce

- Material-wise performance for unique materials
- Dealer-wise, and by **RM, ASE, Province, District** (all four come from `dealers.xlsx`)
- Monthly trend - with the May gap marked, not interpolated

## KPIs

Total invoices, total order lines, total quantity, total cost, total sales, unique SKUs sold.

## Validation

1. `Net Sales == Sales Pric + Discount` asserted row-wise; report any failures.
2. Totals reconcile to the raw file before and after cleaning.
3. Dealer code/name extraction: report how many `Payer` values parsed, and list the unparsed ones.
4. The 328 distinct `Payer` values map to how many of the 414 dealers?

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. **Is May 2026 genuinely missing, or an export error?** Everything monthly depends on the answer.
2. Does the full `sales.xlsx` also cover ~3 years, like orders?
3. Which `Bill. Type` codes are returns - RE and ZRVT only, or also S1?
4. `sales.xlsx` shows 3,794 distinct materials against 6,422 in orders. Is sales a narrower scope
   (one sales org, one channel), or a shorter window?
