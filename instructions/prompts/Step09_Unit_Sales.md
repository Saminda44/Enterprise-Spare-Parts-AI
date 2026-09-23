# Step 09 - Vehicle Unit Sales

| | |
|---|---|
| **Builds** | `src/parc/unit_sales.py` |
| **Reads** | `MCSI.xlsx`, `dealers.xlsx` |
| **Writes** | `unit_sales`, `unit_performance` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Build the VIN-level record of motorcycles sold, with model, colour, geography and time - the registration cohorts that feed the parc model.

## What the file actually is

`MCSI.xlsx`, sheet `Unit Sales`: **56,211 rows x 58 columns**, **2025-2026 only** (2025: 23,443;
2026: 32,768). **54,433 distinct VINs**, 12 model codes, 13 model names.

This is VIN-level retail registration - the best possible parc source, but it covers only the last two
years. Everything before 2025 comes from `Sales Summery.xlsx` (Step 10).

Useful columns beyond the standard SAP block:

```
VIN, Year, Month, Model, Model Name, Color, Type,
Dealer code, Dealer Name, Province, District, RM, ASE,
Customer Id, Age At Purchase, Age Today
```

`Type` is Motorcycle (29,205) / Scooter (27,006).

## Rules

- `SlsVolQty` negative = **return** (891 rows). Net them; do not drop them.
- `Sales Organization` and `Sales Office` are glued code+label - use the Step 00 parser.
- `Payer` here is a **retail customer name**, not a dealer. Do **not** join it to `dealers.xlsx`.
- Watch the dealer columns: in some rows `Dealer code`, `Dealer Name`, `Province`, `RM`, `ASE` and
  `District` all carry the same value (e.g. `Borella`), which is the sales office leaking into them.
  Detect and report this rather than treating it as geography.
- `Customer Id`, `Age At Purchase`, `Age Today` contain the literal string `"No order record"` in some
  rows - treat as null, not as a value.

## Analysis to produce

- Units by **model**, by **model x colour**, by **dealer**
- By **RM, ASE, Province, District**
- **Time series** of unit sales by model - monthly, using `Year` and `Month`
- **Price against unit sales** by model, from `Net Sales` / `SlsVolQty`

## Output

`unit_sales`: `vin`, `model_code`, `model_name`, `colour`, `type`, `year`, `month`, `dealer_code`,
`province`, `district`, `rm`, `ase`, `qty`, `net_sales`, `cost`.

This is the **registration cohort feed** for Step 10: each VIN is one vehicle entering the parc in a
known month.

## Validation

1. VIN uniqueness: 54,433 distinct across 56,211 rows - explain the difference (returns, amendments).
2. Unit totals by year reconcile against `Sales Summery.xlsx` 2025 (22,084) and 2026 (32,344). **They
   will not match exactly** - MCSI is retail, Sales Summery is the ZVOR order export. Quantify and
   explain the gap; do not force them to agree.
3. Model codes reconcile to the `Model Classification` sheet.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. MCSI covers 2025-2026 and shows 12 model codes; `Model Classification` lists 113. Confirm MCSI is
   current-range only.
2. MCSI 2025 = 23,443 rows vs Sales Summery 2025 = 22,084 units. Which is authoritative for the parc?
3. Do the corrupted dealer columns (all fields = `Borella`) affect many rows, and is there a clean
   dealer field to use instead?
4. Is there a VIN-level source before 2025, or is annual Sales Summery the only pre-2025 history?
