# Step 15 - FastAPI Service Layer

| | |
|---|---|
| **Builds** | `src/api/` |
| **Reads** | all published marts |
| **Writes** | HTTP endpoints - no new data |
| **Format** | Python modules under `src/`. Never a notebook. `run(ctx) -> StageResult`. |

## Objective

Serve the pipeline's outputs - parts search, forecasts, parc, policy and the monthly order proposal - over a documented API, and let the monthly run be triggered and monitored.

## Purpose

Expose the pipeline and its outputs as a service. **FastAPI only** - no Streamlit.

## Structure

```
src/api/
  main.py
  routers/
    parts.py        search, lookup, supersession
    demand.py       history, forecast
    parc.py         uio, cohorts, scenarios
    inventory.py    stock, policy, order proposal
    runs.py         trigger and monitor pipeline runs
  schemas/          pydantic response models
  deps.py           mart loading, caching
```

## Endpoints

| Method | Path | Returns |
|---|---|---|
| `GET` | `/parts/search?q=&brand=&group=` | vector search (Step 02) |
| `GET` | `/parts/{part_no}/supersession` | chain with QUERIED / CURRENT / OLDER / RELATED |
| `GET` | `/parts/{sku}/explain` | the full Step 14 derivation for one part |
| `GET` | `/demand/{sku}/history` | monthly ordered, confirmed, lost |
| `GET` | `/demand/{sku}/forecast` | mu, sigma, quantiles, method |
| `GET` | `/parc/uio?model=&month=` | age-bucket matrix |
| `POST` | `/parc/scenarios` | run a target scenario |
| `GET` | `/inventory/{sku}/position` | on-hand, on-order, IP |
| `GET` | `/inventory/policy/{sku}` | SS, ROL, ROQ, policy and why |
| `GET` | `/orders/proposal?cycle=` | the monthly proposal, filterable |
| `GET` | `/orders/proposal.csv?cycle=` | buyer-ready export |
| `POST` | `/runs/monthly` | trigger Steps 12-14 |
| `GET` | `/runs/{run_id}` | status and run report |
| `GET` | `/health` | liveness plus data freshness |

## Rules

- **The API serves published marts. It computes nothing.** Every number it returns was computed in a
  step, tested, and written to a table. A figure derived in a request handler is a figure nobody can
  reproduce.
- Pydantic response models on every endpoint; no raw dataframe dumps.
- Long runs are **async with a job id** - a monthly pipeline run must not block an HTTP request.
- Paginate anything that can return 30,000 rows.
- `/orders/proposal` is a **recommendation**. There is no endpoint that submits a purchase order to
  SAP. A human sends the order.
- Read-only by default; the only writes are run triggers and scenario definitions.

## Operational

Structured logging with a run id through every layer. `/health` reports the age of each mart, so a
stale pipeline is visible rather than silently serving last month's numbers. Config through
pydantic-settings and environment variables - no secrets in code.

## Validation

1. Contract tests per endpoint against a fixture dataset.
2. `/parts/{sku}/explain` output reconciles exactly to `mart_monthly_order` for the same part.
3. Response time on the proposal endpoint measured with a realistic mart loaded.
4. OpenAPI docs generated and reviewed.

## Protocol

**Clarify -> Architect -> Code -> Validate.** Ask the open questions below first. Present an
architecture note and **wait for confirmation** before writing code. Finish with tests and a
validation report reconciled against the source file.

## Open questions

1. Who and what consumes this API - a front end, SAP, a scheduled job, analysts?
2. Is authentication needed, and if so which scheme (API key, OAuth, internal network only)?
3. Where does it deploy - on-prem, cloud, container?
4. Should scenario runs persist per user, or is it a single shared workspace?
