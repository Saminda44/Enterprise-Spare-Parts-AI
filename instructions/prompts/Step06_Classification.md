# Step 06 - Parts Classification

| | |
|---|---|
| **Builds** | `src/parts/classify.py - src/parts/behaviour_model.py` |
| **Reads** | `part_master`, `demand_history`, `PN_Yamaha.xlsx`, Chroma `parts_master` |
| **Writes** | `sku_classification` -> appended to `part_master_enriched` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Label every part four ways - behaviour, demand pattern, value and movement - because each later decision routes on these labels rather than treating 30,000 parts alike.

## Classification 1 - behaviour class

Assign every part to exactly one of:

```
service part | wear part | crash part | cosmetic part | engine part
```

Derived from description text, `Material Group`, catalogue section and demand shape. This is a
**text-plus-features classification problem**, so:

1. Hand-label a stratified sample (aim for 300-500 parts across groups).
2. Train several candidates - TF-IDF + linear SVM, gradient boosting on description embeddings plus
   demand features, and a rules baseline from keyword lists.
3. **Select on held-out macro-F1**, not accuracy - the classes are imbalanced, and accuracy will
   reward a model that predicts "service part" for everything.
4. Report the confusion matrix. Report per-class precision and recall, not one number.

The behaviour class is what makes the age-cohort model work: it is the pooling key for `lambda(p,a)`
in Step 08. Wear parts consume on a rising curve with vehicle age; crash parts are roughly flat;
cosmetic parts fall away. Pooling across the wrong class destroys the signal.

## Classification 2 - demand pattern

From `demand_history`, per `active_sku_id`:

```
ADI  = mean interval between non-zero demand periods
CV^2 = (sigma / mean)^2 of non-zero demand sizes
```

Syntetos-Boylan quadrants, cutoffs **ADI = 1.32**, **CV^2 = 0.49**:

| | CV^2 <= 0.49 | CV^2 > 0.49 |
|---|---|---|
| **ADI <= 1.32** | smooth | erratic |
| **ADI > 1.32** | intermittent | lumpy |

This quadrant decides which forecasting family Step 07 is allowed to use, and which safety-stock
strategy Step 13 applies. It is not a report - it is a routing key.

## Classification 3 - value and movement

- **ABC** on annual consumption value (Pareto; default 80/15/5, configurable)
- **XYZ** on demand variability (CV of monthly demand)
- **FSN** on movement frequency (Fast / Slow / Non-moving)

Plus **criticality** (VED) where it can be derived - a part that immobilises a motorcycle is not the
same as a decal, whatever its value. If no source exists for criticality, say so rather than
inventing one; Step 13 treats `criticality = high` specially and must not be fed a guess.

## Minimum history

A part with fewer than **12 non-zero months** gets `insufficient_history = True` and is routed to the
conservative path in Steps 07 and 13. Do not force a quadrant onto a part with four data points.

## Output

Append all classifications to **`part_master_enriched`** (the copy), keyed on `active_sku_id` so the
labels follow the supersession chain. Never write to the base `part_master`.

## Validation

1. Every part gets exactly one label per scheme; no nulls, no doubles.
2. ABC value shares reconcile to total consumption value.
3. The behaviour classifier's held-out macro-F1 and confusion matrix are in the report.
4. Quadrant counts are sane - if 95% of parts land in one quadrant, the cutoffs or the history window
   are wrong.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Is there an existing list or convention at AMW for the five behaviour classes, or do we label from
   scratch?
2. Can you hand-label ~400 parts, or should the first pass be rules-only with labels added later?
3. Is there any criticality / VED source - a "bike does not run without it" flag anywhere?
4. ABC on **value** or on **quantity**? Value is the default; confirm.
