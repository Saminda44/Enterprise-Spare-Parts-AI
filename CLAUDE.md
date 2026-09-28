# CLAUDE.md

Always-loaded context for the Yamaha spare-parts planning system. Read fully before any task.
The deep reference is `instructions/` — 16 step prompts plus an architecture guide, a knowledge
graph and step diagrams. Open the relevant step file before working on that step.

---

## 1. What this project is

A demand-forecasting and inventory-policy system for a **Yamaha motorcycle spare parts
distributor in Sri Lanka (AMW)**, importing from India on a **3-month lead time** with a
**monthly** order cycle. It sets safety stock, reorder level and reorder quantity per part,
driven by both the vehicle parc (units in operation, by age) and the parts' own demand history.

Delivered as a **FastAPI service over published marts**. No Streamlit. No notebooks.

---

## 2. Current state — mid-rework

The project is being rebuilt against `instructions/`. Track progress here.

All 16 steps are built and the pipeline runs end to end. `uv run python -m src.cli run`
executes the DAG; `--skip` reuses an expensive upstream stage's artifacts unchanged.

| Step | State |
|---|---|
| 00 Foundation | ✅ `src/core`, `src/io`, CLI |
| 01 Catalogue | ⚠️ 219,898 rows from 105/107 PDFs, but **94% of rows resolve to "shared"** — only 47 PDFs had a parseable colour table, so colour-variant assignment is weak. The **Catalogues page does not use this**: it runs the previous build's live reader in `src/catalogue/browser/`, which finds colours and sections this stage misses. Model colours there come from the `(*)` marker in the applicable-colour table, and where a PDF carries none they are resolved from the document — 41 marked / 62 parts / 1 listed / 3 none across the 107 catalogues (see `docs/old-ui-backend.md`). Extractions are stored in PostgreSQL (`src/catalogue/store.py`, `POSTGRES_*` in `.env`) and the page reads the stored copy |
| 02 Part Master | ✅ 30,218 parts, 0 cycles; **12.4%** carry model compatibility |
| 03 Orders | ✅ 94,920 order lines, fill **0.739**, 13,247 rejected to exceptions |
| 04 Sales | ⚠️ 73,039 lines after removing **39,704 exact duplicate rows** (every 2025 billing line is in the export twice — 3.12B LKR double-counted; ask for a re-export); this vintage has **no part numbers**, so sales is description-keyed. Revenue **5.98B LKR** (was reported 9.10B) — the export ships **two columns headed "Net Sales"** and the column is now chosen by testing `Net Sales = Sales Pric + Discount` (resolves to `Net Sales_1` at 100%; the other is net of `Surcharge` and made revenue negative). `Material` is a bare description: a parsed code is kept only when it is a real Part Master number (the generic splitter cut double-spaced descriptions in two) |
| 05 Order Analysis | ✅ β̂ per part with shrinkage; lead time flagged as the wrong clock (see below) |
| 06 Classification | ⚠️ **ABC = billed-sales value** (owner, 2026-09-28): sales.xlsx linked to the Part Master in `src/demand/sales_link.py` — Yamaha material groups only (non-Yamaha lubricants, ~5.3B LKR, excluded), unique description, else the only candidate dealers ordered, else split by order share; 99.6% of in-scope value linked, 3,394 SKUs classed. Parts with no linked sale keep order-value ABC (`abc_source`). XYZ/FSN stay order-based. **Behaviour class covers all 24,054 Part Master SKUs** (`part_behaviour`, `src/parts/behaviour.py`): part nature in the description, then the PDF catalogue section (by part number across the chain, else by matching description), then keywords; 969 unclassified (177 of the ordered parts, down from 3,019). Still rule-based — no labelled sample; criticality unset |
| 07 Model Selection | ✅ rolling-origin backtest, 66 combinations, 6-month sealed holdout |
| 08 Forecast | ✅ 7,242 SKUs on dealer **orders** + UIO (owner, 2026-09-28: billed sales are the fulfilled part of the same orders, censored and ending 2025-12, so they are a check — `mart_ui_forecast_sales_check` — not the demand series). Two fits: `forecast_protection` (to the holdout start, Step 13 validation only) and `forecast_live` (all history — what the order uses). Parc term uses each part's own compatible models' fleet via the catalogue store (4,351 SKUs linked); it carries ~14% of forecast demand |
| 09 Unit Sales | ✅ 22,087 VINs; geography unusable on 3.5% (office leak) |
| 10 UIO Cohorts | ✅ import-ban hole survives into the age histogram |
| 11 Targets | ✅ lag test passes: +10% units → **+1.24%** parts demand in year one |
| 12 Stock | ✅ PDC position, **Yamaha MC (YM) and OBM (OB) parts only** — non-PN_Yamaha rows and other brands (KT) rejected, for stock and on-order alike. Inventory status runs on **on hand + on order** against the monthly forecast (Stockout / Awaiting stock / Critical / OK / Excess / No demand); On_Orders months read as the month the PO was **raised** (owner, 2026-09-28): 95,603 units in transit, 31.5% of IP. Year still assumed |
| 13 Policy | ⚠️ gate **FRONTIER** (fill 0.607 vs 0.376 baseline; inventory 379M vs 184M LKR). FSN=N parts now ON_DEMAND/NO_STOCK unless the fleet supports ≥1/month; published s/S use the live forecast |
| 14 Monthly Order | ✅ 915 placeable lines, ~287M LKR; lines above 3x recent demand are **held for buyer review** (1,169 lines, ~104M LKR, `mart_order_review`) |
| 15 FastAPI | ✅ all endpoints serve marts; `uvicorn src.api.main:app --port 8090`. Serves the original dashboard at `/` from `frontend/dist`, using `/api/v1` compatibility routes over the new pipeline |

**Blocking unknowns — none of these can be resolved from the supplied files:**
0. `orders.xlsx` and `sales.xlsx` cover **different populations** — 2025 orders is 44,180
   lines / 644k units / 278 dealers from one sales office (`W1B1`); billed sales is 79,408
   lines / 2.76M units / 427 payers (`Seeduwa - PDC`). Billed value is ~9x ordered value, so
   the two cannot be divided into a fulfilment rate. What `orders.xlsx` is scoped to is unknown.
1. `On_Orders` months carry no year. The owner decided (2026-09-28) they are the month the PO
   was **raised**, so the last `lead_time_months` of POs count as in transit; the **year** (2026) is
   still assumed — confirm with procurement.
2. Fill-rate targets, holding rate, order cost, MOQ and pack size are **assumed** defaults
   in `Settings`. Step 13's numbers move with them.
3. No de-registration records, so survival is assumed; three Weibull scenarios are run.
4. `Delivery − Document` measures **dealer dispatch (2.5 days)**, not the 3-month import
   lead, so σ_L for replenishment is unknown and safety stock understates it.

`legacy/` holds the previous 14-stage build, archived intact.

`legacy/` holds the old `src`, `tests` and `scripts`. It is **reference only** — do not extend it.
Its FastAPI app still serves the existing React dashboard so nothing goes dark mid-rework:

```bash
uvicorn --app-dir legacy src.api.main:app --host 0.0.0.0 --port 8080
```

The owner has selected the original UI (`frontend/src`). The new planning API now
serves its build from `frontend/dist` at `/` and connects its `/api/v1` output
contracts to the new pipeline. Build it with `cd frontend && npm run build`;
`npm run dev` proxies to port 8090. See `docs/old-ui-backend.md` for mappings and
remaining unsupported legacy actions. `frontend/planning/` is preserved as an
alternative implementation; it is not the default served UI.

```bash
cd frontend && npm run build:planning   # tsc + vite -> frontend/dist-planning/
cd frontend && npm run dev:planning     # :5174, proxies /api -> :8090
cd frontend && npm run smoke:planning   # server-renders all 13 pages; catches blank-page errors
```

---

## 3. Your role

Senior hybrid practitioner — analyst, data scientist, data engineer, ML engineer. Switch by task.
Operate with senior rigour: state assumptions, validate before modelling, prefer interpretable
models, never silently swallow a data-quality issue.

---

## 4. Working protocol — non-negotiable

**Clarify → Architect → Code → Validate.** Per step, in that order.

1. **One step at a time.** Each step file has a validation gate. It passes before the next begins.
2. **Ask the step's open questions first.** They are listed at the bottom of every step file.
3. **Present an architecture note and wait** for confirmation before writing code.
4. **Validate every read and every write.** pandera at stage boundaries; a violation raises.
5. **Finish with a validation report** reconciled against the source file, then stop and report.

---

## 5. Critical business rules — apply without being asked

- **One identity per part.** `active_sku_id` resolves the supersession chain. Aggregate on
  anything else and one physical part's demand splits across its old and new numbers,
  understating every forecast.
- **Order document split.** `SD Document Category` `C` = sales order (demand), `H` = return.
  "Demand" always means the `C` set.
- **Lost sales are measured, not inferred.** `Lost Quantity = Order Quantity − Confirmed
  Quantity`. Never treat confirmed quantity as demand.
- **Material category.** Dealer Type `MC`: description contains `YAMALUBE` → Lubricant,
  `KARATE BATTERY` → Battery, `KATANA TYRE` → Tyre, else MC Spare Parts. Dealer Type `OBM` →
  OBM Spare Parts. Match case-insensitively.
- **`Dealer Code` is mixed int/str** in both `dealers.xlsx` and `MCSI.xlsx`. Normalise to trimmed
  text on **both sides** of any join, or it silently misses. Raw parquet mirrors already coerce it.
- **Rows with `Dealer Code == "No Code"` are real demand.** Do not drop them.
- **Revenue.** `Net Sales = Sales Pric + Discount` (verified exact). Margin is `Net Sales − Cost`.
  `Discount` is stored negative. `Revenue Re` and `Cost Reduc` are zero in every row.
- **Negative `SlsVolQty` is a return.** Net it; do not filter it out.
- **Stock scope is the PDC only** — `Plant == "W1B4"` (86.5% of network units). Branch stock is
  visibility, never inventory position.
- **`IP = on_hand + on_order − backorders`.** Never compare against on-hand alone: with a 3-month
  lead and monthly review there can be three orders in flight.
- **Protection interval `P = L + R = 4` months.**
- **The final 12 months are sealed** in Step 07, opened once in Step 13, never re-opened.
- **Glued SAP columns** pack code and label into one string. Split with `src/io/sap.py`, join on
  the code, never on the raw string. Applied per column from a declared map — never blanket.
- **Sri Lanka timezone** Asia/Colombo. **Currency LKR** — never assume USD.

---

## 6. The data, as verified on disk

Checked 2026-09-22 against `data/raw/`. **Refreshed 2026-09-27:** the owner replaced `orders.xlsx`
(now 155,424 lines, 2024-01 → 2026-08) and `MCSI.xlsx` (56,211 rows, registrations 2025-04 → 2026-08);
the published cycle moved to as_of **2026-09-01**, so On_Orders months are now assumed to be 2026. **These differ from the figures quoted in
`instructions/`**, which describe a Jan–Aug 2026 extract that is not the file present.

| File | Rows | Coverage | Notes |
|---|---|---|---|
| `orders.xlsx` | 108,910 × 102 | 2024-01 → 2025-12 | fill rate **0.744**; C 107,155 / H 1,755 |
| `sales.xlsx` | 113,231 × 41 | 2024-01 → 2025-12 | no missing month; ~93k trailing blank rows |
| `MCSI.xlsx` | 23,415 × 56 | Apr–Dec, one year | sheet `MCSI`; 22,087 VINs; 9 models |
| `current_stock.xlsx` | 26,288 × 8 | snapshot | W1B4 = 86.5%; only an `Unrestricted` column |
| `On_Orders.xlsx` | 2,820 × 10 | `Jan`…`Aug` | **no year in the columns** — see below |
| `PN_Yamaha.xlsx` | 30,218 × 16 | — | `Latest SS` pre-resolved; verify, don't recompute |
| `dealers.xlsx` | 414 × 12 | — | Type MC/OBM, RM, ASE, Province, District |
| `Sales_Summery.xlsx` | 20 sheets | 2014–21, 2025–26 | 113 models classified |
| `pdf_catalogues/` | 107 PDFs | — | across ~30 model folders |

`In_and_Out.xlsx` and `SSOP.xlsx` are present but **out of scope** — the new design takes stock
from `current_stock.xlsx` and supersession from `PN_Yamaha.xlsx`.

**Never hard-code a date window.** A newer export is expected; everything derives its window from
`ctx.as_of` and reports the min/max month it actually observed.

**Open and blocking:** the `On_Orders` month columns carry no year, and it is unconfirmed whether
they mean expected arrival or the month the PO was raised. This shifts the whole pipeline by a
quarter. Config flag `on_order_interpretation` (default `arrival`) is printed in every run report.

---

## 7. Scope, locked

| Decision | Value |
|---|---|
| Output | Python modules under `src/`. **Never notebooks.** |
| Delivery | **FastAPI only** — no Streamlit |
| Timing | Lead 3 months, review 1 month, `P = 4` |
| Policies | (R,S), (R,s,S), on-demand, no-stock. **No VMI, JIT or continuous review** |
| Supply inflation | `q ÷ β̂` is **off by default** — it is a feedback loop |
| Excluded | RL agent and market-basket analysis are not part of this design |

---

## 8. Tech stack

Python 3.12, `uv` (lockfile committed). pandas, pyarrow, pandera, pydantic-settings, loguru,
scipy, statsmodels, scikit-learn, lightgbm/xgboost, statsforecast, pdfplumber, chromadb, fastapi,
uvicorn, typer, pytest. Do not add a dependency without justification.

---

## 9. Project structure

```
src/
  core/        context.py  registry.py  result.py  contracts.py  settings.py  errors.py
  io/          excel.py  sap.py  parquet.py  chroma.py
  cli.py
  (coming)     catalogue/  parts/  demand/  forecast/  parc/  inventory/  api/
data/
  raw/         source workbooks + parquet mirrors + *.meta.json vintages
  staging/  facts/  marts/  reports/
tests/         mirrors src/
frontend/
  planning/    the new dashboard (React + Vite entry #2) -> dist-planning/, served by the API
  src/         the legacy dashboard, served by legacy/src/api
legacy/        the previous build — reference only
instructions/  the 16 step prompts and design docs
```

Every stage is `run(ctx) -> StageResult`. No module-level mutable state; same input, same output.

---

## 10. Daily commands

```bash
uv run python -m src.cli ingest            # workbooks -> parquet (hash-skipped)
uv run python -m src.cli stages            # list the registered DAG
uv run python -m src.cli run --as-of 2025-12-01
uv run python -m src.cli run --only 03_orders
uv run python -m src.cli catalogue-load     # PDF catalogues -> PostgreSQL (manual; --file for one)
uv run python -m src.cli pn-yamaha-load     # PN_Yamaha Brand YM -> PostgreSQL (after ingest)

# The API watches data/raw: an edited workbook is re-ingested and the stages downstream of it
# re-run automatically (src/refresh.py); the cycle as_of follows the order history. Manual:
# POST /api/v1/pipeline/refresh  (Pipeline page: "Refresh from source files"). Pin with SPI_REFRESH_AS_OF.

uv run pytest -q
uv run ruff check src tests --fix && uv run ruff format src tests
uv run mypy src                            # strict on src/core and src/io

uvicorn src.api.main:app --port 8090                    # API + planning dashboard at /
uvicorn --app-dir legacy src.api.main:app --port 8080   # old dashboard (being retired)
```

---

## 11. Coding conventions

- Type hints on every public function; `mypy --strict` for `src/core` and `src/io`.
- Google-style docstrings. Any function encoding a business rule gets a **"Business meaning"** line.
- No magic numbers — constants in config or `PlanningContext`.
- Pure functions for transformations; I/O at the edges. DataFrames in, DataFrames out, never mutate
  an input.
- Reject rows to an exceptions table **with a reason and a count**. Never drop silently.
- `loguru.logger`, never `print()` in `src/`.
- Specific exceptions from `src/core/errors.py`, never bare `Exception`.

---

## 12. Security rules — enforce always

- **Secrets in `.env` only**, loaded via pydantic-settings. Never paste credentials into code or chat.
- **Real data never leaves the project** — no real VINs, dealer codes, customer names or prices into
  external tools or LLMs. Use synthetic samples that preserve schema only.
- **`data/raw/` is immutable.** Read-only; never edit a source file in place.
- **PDFs are untrusted input** — cap size, parse defensively.
- **Generated reports carry a metadata footer**: source file hashes, commit SHA, generation
  timestamp, model version. Non-negotiable — these decisions move LKR-millions.

---

## 13. Files Claude must NEVER touch

- Anything under `data/raw/` — immutable source.
- `.env` — secrets.
- `uv.lock` — only via `uv add` / `uv lock`.
- `instructions/**` — the specification. Raise disagreements; do not edit it.
- `docs/adr/*.md` once merged — append a new ADR instead.
- Any file the user has marked "frozen" in a comment.

---

## 14. The sixteen steps

```
00 Foundation ──┬─ 01 Catalogue ── 02 Part Master ──┬── 06 Classification ──┐
                │                                    │                      │
                ├─ 03 Orders ──┬── 05 Order Analysis─┤                      │
                ├─ 04 Sales ───┘                     │                      │
                │                                    ├── 07 Model Selection ┤
                ├─ 09 Unit Sales ── 10 UIO Cohorts ──┴── 08 Forecast ───────┤
                │                      └── 11 Targets                       │
                └─ 12 Stock ──────────────────────────────────────────── 13 Policy Engine
                                                                             │
                                                              14 Monthly Order
                                                                             │
                                                                    15 FastAPI
```

**Step 13 is the acceptance gate**: achieved fill rate ≥ target per ABC class *and* average
inventory value ≤ baseline, on the sealed holdout. A win on one axis only is a frontier to show
the owner, not a pass to claim.

---

## 15. When to pause and ask

- Schema mismatch on ingestion (column missing, type wrong).
- A forecast model cannot beat a seasonal-naive baseline.
- A supersession cycle (A→B→A).
- ROL or ROQ more than 3× recent realised demand for a SKU.
- A single dealer above 40% of a month's return value.
- PDF extraction confidence below 0.85 on any catalogue page.
- Any computation needing data not provided — especially Step 13's fill-rate targets, holding
  cost rate, order cost and the current baseline rule, none of which exist in any source file.

---

## 16. Where to find more

- **The specification**: `instructions/prompts/Step*.md` — one per step, self-contained.
- **Design guides**: `instructions/architecture.html`, `knowledge_graph.html`, `step_diagrams.html`.
- **Run reports**: `data/reports/run_*.json`.
- **Source vintages**: `data/raw/*.meta.json` — hash, row count, ingestion time.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
