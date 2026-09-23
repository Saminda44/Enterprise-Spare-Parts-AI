# Step 01 - PDF Catalogue Reader

| | |
|---|---|
| **Builds** | `src/catalogue/pdf_reader.py - src/catalogue/colour_rules.py` |
| **Reads** | `pdf_catalogues/` (mixed layouts) |
| **Writes** | `catalogue_parts`, `model_colour_variants` -> Chroma collection `catalogue` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Extract the parts table from every Yamaha catalogue PDF and resolve, for each part, which model and which colour variant it belongs to. The colour logic below is specified in full - it is not inference to be improvised.

## Shape of the input

PDFs come in several layouts. The **model code appears on page 1** in most of them. Some are
single-model; some are multimodal, with a quantity column per model.

## Step A - the FOREWARD colour table

Read the **FOREWARD** page first and extract the *Applicable Color Table*: abbreviation, colour name,
and colour code number where present. This is the universe of possible colours for that PDF.

An abbreviation marked **`(*)`** is the **model colour** for that PDF.

> **Do not promote the FOREWARD table straight into colour variants.** Real variants are equal to or
> fewer than the table. A variant is confirmed only once its abbreviation or colour name is actually
> observed in the parts table's remarks or descriptions.

## Step B - remarks carrying abbreviations

A row whose **Remark** contains an abbreviation from the table is a **coloured part** belonging to
that abbreviation's colour:

| Remark pattern | Meaning |
|---|---|
| `ABBR` | belongs to that colour |
| `UR ABBR` / `FOR ABBR` | belongs to that colour |
| `EXCEPT ABBR` | **does not** belong - belongs to all *other* confirmed variants |
| `ABBR1, ABBR2` | belongs to each listed colour |

`EXCEPT` inverts against the **confirmed variant set**, not against the full FOREWARD table. Getting
this backwards silently assigns parts to colours that do not exist in the PDF.

## Step C - remarks carrying numbers

When remarks contain numbers and the colour table carries colour numbers, the **suffix after the
final `-`** is the colour-variant number. The part is **shared** and belongs to that variant.

## Step D - colour in the description

Where the remark cannot be resolved against the table, the colour abbreviation or name is often in
the **description** - as a suffix after `-`, or inside brackets. Treat it as a coloured part for that
variant. `UR` / `FOR` / `EXCEPT` apply identically.

**Precedence when C and D disagree:** if remarks carry numbers and the descriptions imply more
colours than the table holds, **go with the suffix numbers**.

## Step E - multimodal catalogues

Where quantities appear per model and remarks carry colour abbreviations:

1. An abbreviation whose quantity appears for **exactly one model** is always a colour variant *of
   that model*.
2. A remark listing **comma-separated abbreviations** is split across models using the variants
   identified in (1).
3. A remark carrying **one abbreviation across several models** means that colour is available for
   every model showing a quantity.

Run (1) before (2). Step 2 has no basis without it.

## Output

`catalogue_parts`: `pdf_file`, `model_code`, `part_no`, `description`, `qty`, `remark_raw`,
`part_kind` in {coloured, shared}, `colour_abbr`, `colour_name`, `colour_code`, `rule_applied`,
`confidence`.

`rule_applied` records which of B/C/D/E fired. Without it, a wrong extraction cannot be audited.

## Accuracy check - required, not optional

Sample **at least 30 parts per PDF layout**, verify by eye against the PDF, and report precision per
rule. Report model-code detection accuracy separately. Rows the rules cannot resolve go to an
exceptions table with the raw remark - **never** guessed into a variant.

Load the resolved table into Chroma **model-variant-wise**, one document per part x variant.

## Definition of Done

Accuracy reported per layout and per rule; exceptions listed with raw remarks; Chroma collection
queryable by model code and colour.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. How many PDFs, and how many distinct layouts?
2. Is the heading always spelled FOREWARD, or do some use FOREWORD or another word?
3. A part with **no remark at all** - shared across every colour, or unknown?
4. Are there PDFs where the model code is not on page 1? What is the fallback?
5. Do the catalogue part numbers use the same format as `PN_Yamaha.xlsx` (`0NH9-28471-00`)?
