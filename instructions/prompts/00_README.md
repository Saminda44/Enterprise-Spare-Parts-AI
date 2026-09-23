# Build Prompts - Yamaha Spare Parts Intelligence

Sixteen prompts, one per step. Each is self-contained: give a coding agent **one** file and it has
the objective, the real data shape, the rules, the output contract, the validation gates and the
questions to ask first.

Written against the **actual data files**, inspected 2026-09-22 - not against assumptions.

| # | File | Builds |
|---|---|---|
| 00 | `Step00_Foundation.md` | repo, contracts, orchestration, the SAP column parser |
| 01 | `Step01_Catalogue_Reader.md` | PDF extraction with the full colour-variant ruleset |
| 02 | `Step02_Part_Master.md` | supersession chain, `active_sku_id`, vector search |
| 03 | `Step03_Cleaned_Orders.md` | demand history and measured lost sales |
| 04 | `Step04_Parts_Sales.md` | billed sales, revenue, margin, geography |
| 05 | `Step05_Order_Analysis.md` | fulfilment, supply reliability, lead time |
| 06 | `Step06_Classification.md` | behaviour, ADI/CV2, ABC/XYZ/FSN |
| 07 | `Step07_Model_Selection.md` | rolling-origin backtest, champion per segment |
| 08 | `Step08_Material_Forecast.md` | parc-driven forecast, lambda(p,a), uncertainty |
| 09 | `Step09_Unit_Sales.md` | VIN-level registrations from MCSI |
| 10 | `Step10_UIO_Cohorts.md` | UIO by age bucket, survival, roll-forward |
| 11 | `Step11_Targets.md` | unit forecast and target simulator |
| 12 | `Step12_Stock.md` | PDC stock, on-order, inventory position |
| 13 | `Step13_Policy_Engine.md` | SS, ROL, ROQ - simulated and selected |
| 14 | `Step14_Monthly_Order.md` | the buyer-ready order, marts, explainability |
| 15 | `Step15_FastAPI_Service.md` | the service layer |

## Scope decisions locked in these prompts

| Decision | Value |
|---|---|
| Output format | Python modules under `src/`. **Never notebooks.** |
| Stock scope | **PDC only** (`Plant == "W1B4"`), cleaned against `PN_Yamaha.xlsx` |
| History | Full `orders.xlsx` is **~3 years**; the 8-month file supplied is a sample |
| On-order months | **2026**, read as expected arrival (config flag, printed every run) |
| Delivery | **FastAPI only** - no Streamlit |
| Lead time | 3 months. Review 1 month. Protection interval **P = 4 months** |
| Policies | (R,S), (R,s,S), on-demand, no-stock. **No VMI, JIT or continuous review** |

## What the data actually contains

Verified by reading all eight files.

| File | Rows | Coverage | Note |
|---|---|---|---|
| `orders.xlsx` | 46,514 x 102 | Jan-Aug 2026 (sample) | fill rate **0.745**; 32% of lines fully rejected |
| `sales.xlsx` | 21,301 x 41 | Jan-Aug 2026 | **May missing**; `Payer` and `Material` are glued code+label |
| `MCSI.xlsx` | 56,211 x 58 | 2025-2026 | VIN-level, 12 model codes |
| `Sales Summery.xlsx` | 20 sheets | 2014-2021, 2025-2026 | **278,732 units**; 113 models classified |
| `current_stock.xlsx` | 26,288 x 8 | snapshot | 16 plants; **only an `Unrestricted` column** |
| `On_Orders.xlsx` | 2,820 x 10 | 2026 Jan-Aug | wide month pivot; 252,568 units |
| `PN_Yamaha.xlsx` | 30,216 x 16 | - | `Latest SS` already resolved |
| `dealers.xlsx` | 414 x 12 | - | Type MC/OBM, RM, ASE, Province, District |

## Three things the data settled

**1. `Payer` was never a contradiction.** It holds both: `"26198      Yamaha Sales Center"`. So does
`Material`: `"676-42115-00       SHAFT STEERING YAMAHA 40 HP"`. One shared parser, applied per column
per file - `orders.xlsx` does not use this encoding.

**2. The revenue formula needed no fixing.** `Revenue Re` and `Cost Reduc` are zero in all 21,301
rows, and `Net Sales = Sales Pric + Discount` holds exactly. Revenue is `Net Sales`; margin is
`Net Sales - Cost`.

**3. The parc has a four-year hole, and it is real.** 2020: 26,701 units. 2021: **85**. 2022-2024:
none. 2025: 22,084. That is Sri Lanka's vehicle import ban. The fleet is bimodal - a large 2014-2020
block now aged 6-12, sitting in the high-consumption band, and a young 2025-2026 block that will
demand little for years. Step 08 and Step 10 both depend on modelling this rather than smoothing it.

## How to use these

Hand a coding agent one step's file. It will ask its questions, propose an architecture, wait, then
build. Do not hand it several at once - each step has a validation gate that should pass before the
next begins.

Steps 01 and 02 can start immediately. Step 03 onward wants the full 3-year `orders.xlsx`.
