# Step 00 - Foundation

| | |
|---|---|
| **Builds** | `src/core/ - src/io/ - tests/ - pyproject.toml` |
| **Reads** | nothing |
| **Writes** | `PlanningContext`, settings, stage registry, `src/io/sap.py` |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Set up the repository, the data contracts and the orchestration so every later step plugs into the same frame. No business logic here.

## Environment

Python >= 3.11 managed with `uv`. Dependencies: pandas, pyarrow, pandera, pydantic-settings, loguru,
scipy, statsmodels, scikit-learn, chromadb, fastapi, uvicorn, pytest.

## Layout

```
src/
  core/        context.py  registry.py  contracts.py  errors.py
  io/          excel.py  sap.py  parquet.py  chroma.py
  catalogue/   parts/  demand/  forecast/  parc/  inventory/
  api/         main.py  routers/
data/
  raw/  staging/  facts/  marts/
tests/
```

## The context object

```python
@dataclass(frozen=True)
class PlanningContext:
    as_of: date
    lead_time_months: int = 3
    review_period_months: int = 1
    plant: str = "W1B4"          # PDC only - see Step 12
    currency: str = "LKR"
    config: Mapping[str, Any] = field(default_factory=dict)
```

Frozen. Every stage receives it and returns `StageResult(rows_in, rows_out, rejected, warnings,
artifacts)`. No stage reads global state; no stage mutates anything it did not create.

## Contracts

Every table crossing a stage boundary carries a **pandera** schema. A violation raises - it does not
warn and continue. This matters more than usual here, because the source files are SAP exports whose
column meanings are not self-evident.

## The SAP glued-column rule - applies everywhere

Several columns in these exports pack a **code and a label into one string**, separated by runs of
spaces. Verified in the real files:

```
Payer               "26198      Yamaha Sales Center"
Material            "676-42115-00       SHAFT STEERING YAMAHA 40 HP"
Sales Organization  "2501 Associated Motorways"
Sales Office        "W1B1 Seeduwa - PDC"
Sales Employee      "00171976 Arosha Edirisinghe"
```

Build **one** shared parser in `src/io/sap.py`:

```python
def split_code_label(s: str) -> tuple[str | None, str | None]:
    """Split "26198      Yamaha Sales Center" -> ("26198", "Yamaha Sales Center")."""
```

Split on the first run of two or more spaces; fall back to the first single space when the leading
token is purely numeric or matches a part-number pattern. Emit both `*_code` and `*_name` columns and
**never join on the raw glued string**.

`orders.xlsx` does **not** use this encoding - it carries separate `Sold-to Party` (numeric) and
`Sold-To Party Name`. `MCSI.xlsx` uses it for `Sales Organization` and `Sales Office` but its `Payer`
is a retail customer name. So the parser is applied per column, per file, from a declared map - never
blanket across a dataframe.

## Excel loading

Source files are large: `orders.xlsx` 20 MB, `MCSI.xlsx` 18 MB. Read each workbook **once**, convert
to parquet under `data/raw/`, and have every later step read the parquet. Re-reading the workbook per
stage wastes minutes per run.

## Orchestration

Explicit DAG, topologically sorted, fail-closed. A stage whose upstream failed does not run. Each run
writes a report: rows in and out per stage, rejects with reasons, warnings, elapsed time.

## Definition of Done

`uv run pytest` green; the DAG executes end to end on a two-stage stub; the glued-column parser has
tests covering all five patterns above plus a no-op on `orders.xlsx`-style columns.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Confirm Python version and whether `uv` is acceptable, or the team requires pip/conda.
2. Where do the source files land in production - shared drive, scheduled SAP export, manual upload?
3. Is the monthly run scheduled, or triggered by hand?
4. Is there an existing repo and CI to fit into, or is this greenfield?
