# Step 02 - Part Master and Supersession

| | |
|---|---|
| **Builds** | `src/parts/master.py - src/parts/supersession.py - src/parts/search.py` |
| **Reads** | Step 01 Chroma, `PN_Yamaha.xlsx`, `Sales Summery.xlsx` (Model Classification) |
| **Writes** | `part_master`, `part_master_enriched`, Chroma collection `parts_master` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Establish one identity per physical part - resolving the supersession chain to a single `active_sku_id` - and attach model compatibility to it. Everything downstream aggregates on this identifier.

## Inputs - what is actually there

`PN_Yamaha.xlsx`, sheet `Supersession`: **30,216 rows x 16 columns**.

```
Material, Latest SS, Material description, Material Type, Material Group, Brand,
1st Supersede ... 10th Supersede
```

`Latest SS` is **already resolved** in the source - do not recompute it, but **do** verify it against
the chain and report disagreements. Material Type is `ERSA`; Material Group looks like `AWPYM0027`;
Brand like `YM`.

## Part A - model compatibility

From the Step 01 Chroma collection, derive for each unique part number the set of models it fits, as:

```
family name - model code (year)
```

e.g. `RAY - B2UG (2025)`. Model family, code and year come from the `Model Classification` sheet of
`Sales Summery.xlsx`, which carries `Model`, `Model Name`, `Model Family`, `First Year Sold`,
`Last Year Sold`, `Motorcycle Type`, `Segment`, `cc` for **113 models**. Join catalogue model codes to
that sheet; report any code that does not match.

Carry `part_kind` (coloured / shared) through from Step 01.

## Part B - the supersession tool

Two capabilities, both required.

**1. Vector search.** Embed each part from its description, part number, all supersede numbers, group
and brand. Search by description tolerant of typos (`"oil seal yb50"`), or by any part number.
Filterable by Brand and Material Group. Persist to Chroma.

**2. Part-number lookup.** Accept any number from `Material`, `Latest SS`, or any of the ten
supersede columns. Return every related part, each labelled:

| Label | Meaning |
|---|---|
| `QUERIED` | the number asked for |
| `CURRENT` | the latest number in the chain |
| `OLDER` | a superseded predecessor |
| `RELATED` | linked through the chain, neither of the above |

Accept numbers **with or without dashes**, and **partial** numbers (`5VL-F341E` matches all its
versions). Unknown number returns `not found` - never a fuzzy guess, because a wrong supersession
merge corrupts every downstream demand series.

## Part C - the join

Left join **onto `PN_Yamaha`**: for each `Material`, look up the part master by `Material` and by
each of the ten supersede columns, and bring across `description`, `part_kind` and
`compatible_models`.

## active_sku_id

Resolve every chain to one identifier - use `Latest SS` where it is present and consistent, otherwise
the chain head. **Every downstream step aggregates on `active_sku_id`, never on the raw material
number.** Without it, demand for one physical part is split across its old and new numbers and every
forecast is understated.

## Output

`part_master` -> parquet + Chroma. Then write `part_master_enriched` as a **separate copy**; Steps 6,
8, 12 and 13 append their columns to that copy, never to the base.

## Validation

1. Chain integrity: no cycles; every `Latest SS` is its own chain head.
2. `Latest SS` disagreements with the derived chain, counted and listed.
3. Lookup returns identical results for `5VLF341E`, `5VL-F341E` and the partial form.
4. Coverage: what share of the 30,216 parts got a model compatibility, and what share did not.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Where `Latest SS` disagrees with the supersede chain, which wins?
2. Should parts with **no catalogue match** stay in the master with empty compatibility, or be flagged
   out of scope?
3. Is `Material Group` (`AWPYM0027`, `AWPOB0119`) meaningful for classification, and is there a lookup
   for what each group means?
4. Brand `YM` vs others - is the scope Yamaha only, or all brands in the file?
