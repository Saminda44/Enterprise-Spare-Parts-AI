# Existing dashboard on the planning backend

The original React UI in `frontend/src` is served by `src.api.main` from
`frontend/dist`. Its `/api/v1` calls read the new pipeline facts and published
`mart_ui_*` tables. The separate `frontend/planning` implementation is preserved.

Run `uv run uvicorn src.api.main:app --port 8090`, then open
http://127.0.0.1:8090. For frontend development, `npm run dev` in `frontend`
proxies `/api` to that same backend. Build with `npm run build`.

Connected outputs: Overview; motorcycle analysis and forecast; UIO; spare-parts
orders/sales analysis; classification; demand forecast; inventory; policy and
order plan; part master; catalogue browsing; pipeline status and run history.
The order-plan Excel download reads final quantities from `mart_monthly_order`,
round-trips quantities and values, and includes provenance in a Metadata sheet
referenced by every sheet's footer.

## Contract mappings

- The old `material_9` field carries the full supersession-resolved `active_sku_id`.
- Stock status and urgency use the lowercase values expected by the original UI.
- `forecast_lt` is three-month mean demand, not four-month protection demand.
- `net_requirement` and `roq` expose the final published purchase quantity so the
  existing Order Plan's value calculation includes MOQ/pack adjustments.
- The existing UIO comparison uses the parc component where available. It does
  not generate a second purchase policy: recommended quantity remains `q_final`.
- EDA year=0 resolves to the latest observed year, matching the existing pickers.
- GET responses refresh when marts change. Unknown `/api/*` paths return JSON 404.

## Catalogue reader: the previous implementation, carried over

The Catalogues page runs the **previous build's reader**, not Step 01's published
facts. `src/catalogue/browser/` holds the four modules moved out of the retired
tree: `pdf_extractor.py` (`YamahaCatalogueExtractor`), `agent.py`
(`CatalogueAgent`), `part_master.py` and `remark_parser.py`. `/catalog/tables`
re-reads the PDF live and `/catalog/agent` resolves per-colour builds, exactly as
before. Only the wiring changed — module paths, settings-derived directories, and
the Postgres mirrors dropped, since this design has no database.

It is kept separate from Step 01 on purpose, and it reads more. On
`AEROX/1UB65460EV-AEROX.pdf`, Step 01 records `colours: 0` with the warning "no
applicable-colour table found on the FOREWORD page"; the carried-over reader
returns 8 colour codes with names and paint codes, 46 named sections, four
variants, the type code `B65J` and manufacture year 2019, and the agent resolves
19 per-colour builds and 26 colour-changing parts. Step 01 remains the pipeline
extraction that feeds part compatibility downstream; this is the interactive
reader the page was built against.

### Model colours

A row whose abbreviation column carries `(*)` in the applicable-colour table is a
model colour for that PDF — `CM6(*) | CYAN METALLIC 6 | 1344`. Where any row is
marked, those rows are the model colours and `model_colour_source` reads
`marked`.

Only 41 of the 107 catalogues in this vintage mark anything; the rest have a
colour table with no `(*)` anywhere (checked against the raw page text, so this is
the PDFs, not the parser). Those are resolved from the document itself. Across all
107: **41 `marked`, 62 `parts`, 1 `listed`, 3 `none`** — model colours now resolve
on 104 catalogues, against 41 before.

- `parts` — the catalogue's own parts reference the listed colours. Phantom
  pruning has already dropped every listed colour that no body part carries a
  colour hint for, so what survives is the table narrowed to colours this model is
  actually built in, and every surviving row is a model colour.
- `listed` — no marker and no part references any listed colour, so nothing
  corroborates the table. Those rows are **not** promoted: a listed colour only
  becomes a variant once the catalogue verifies it. Exactly one catalogue lands
  here, `R 15/2FB6 PC-20160120.pdf`, whose single "colour" is a bare `BIKE` — a
  mis-parsed row, and it now yields no variants rather than a false one.
- `none` — three catalogues yield no colour at all, from the table or from
  description lifting.

Validated against the 41 marked catalogues, where the answer is known: in 37 of
them every listed colour is starred, and the parts-derived set never loses a
starred colour. So treating the surviving table as the model's colours agrees with
what the marked catalogues say about themselves.

This matters beyond the colour chips. `CatalogueAgent` builds its variant-to-colour
distribution from the colours flagged `is_model_colour`; on the 63 unmarked
catalogues that list was previously empty, so the agent had nothing to distribute.

`GET /catalog/tables` returns `model_colour_source` alongside `colour_codes`, and
the Catalogues page distinguishes the two cases: a filled star for a colour the
PDF marked, a hollow one for a colour resolved from the document.

### Quantity columns: rows that reached the table priced for nobody

FIG. 16 of ALFA `B931_2XB1` lists five front fenders, one per colour, each with
`1 1` under both models. Only three reached the page. All five were extracted —
the last two came out with no quantity at all, so the per-variant filter dropped
them.

The cause was the footnote guard in the positional column reader. Yamaha suffixes
some descriptions with a small figure reference that physically sits inside the
quantity zone, so a short digit within 15pt of the description's right edge was
routed back into the description. On those two rows the description runs long —
`FENDER, FRONT -VRC1(vivid red)` ends 10pt short of the first quantity column and
`-DPRMG(purplish red)` 8pt short — so both `1`s were eaten, and once the first was
absorbed the second fell within 15pt of it and went the same way.

A footnote marker trails the description text and lands wherever that text ends; a
quantity is aligned to its column. The guard now yields when the digit's centre
sits within `_QTY_COLUMN_TOLERANCE` (4pt) of a quantity column centre — the columns
in these catalogues are about 10pt apart, so half that spacing separates the two
cases cleanly.

Across the 107 catalogues this leaves **659 of 87,162 rows (0.76%)** priced for no
variant, down from the level that hid whole colour variants. The reported
catalogue is now **0 of 748**, and both its models correctly carry all five
colours.

The India-market catalogues `ENTICER/ENTICER 5US1.pdf` and `YBX/YBX125.pdf`, which
accounted for two thirds of what remained, are now handled by declared per-catalogue
overrides (see *Owner's per-catalogue instructions* below). After every fix listed on
this page, **62 of 87,034 rows (0.07%)** across 106 catalogues are priced for no
model; they are named in that section.

### Remark grammar and per-model colour attribution

Three patterns in the Remarks column restrict a part to colours:

- `FOR [ABBR]`, at clause start or after a prefix — `UR FOR RSH`.
- `EXCEPT [ABBR]` / `EXCEPT FOR [ABBR]` — the part is for every colour but those.
- `UR [ABBR]` — a colour list introduced by a catalogue abbreviation token with
  no `FOR`. `UR MPBM1,MDPBM1` on a GRAPHIC is one of three versions of that decal,
  one per colour group. This used to be read as unrestricted.

A colour code standing alone with **no** keyword stays unrestricted: it is the
part's own paint finish, not a variant. `20P-F5366-00-33 CLUTCH, HUB` remarked
`YB` already carries `-33` (Yamaha Black) in its part number — an internal part's
finish, not a colour the motorcycle is sold in.

On a multimodal catalogue the quantity column is priced per model, so which
colours belong to **which** model is read out of the quantities in two passes:

1. A row whose quantity lands on exactly one variant proves that variant's
   colours. `UR FOR RSH` with quantity `1///` says B65J is built in RSH.
2. A row spanning several variants is distributed, not copied: each colour goes
   to the variant pass 1 already showed holds it, and only a colour nothing has
   claimed falls back to position — Yamaha lists colours in the same order as the
   quantity columns, so `FOR YB,MS1` over two live models pairs first with first.

Copying every named colour onto every live model, which is what this did before,
inflated the rosters badly. On AEROX it gave B65J six colours and B65N five where
the catalogue has three and one. Across the 16 multimodal catalogues the change
cuts model/colour pairs from **164 to 100**; 15 tightened, 1 unchanged. AEROX now
returns B65J `DBNM8, RSH, YB` — the owner's stated answer — and 8 builds, not 19.

**Colours read as models.** Three catalogues head their quantity columns with
colour abbreviations rather than model codes: FAZER `2WS3` (`VRC1, BWC1`),
`FZ & FZS/PC 2GS6` (`CM6, MNM3, MDRM4, BWC1`) and `SALUTO/Saluto RX B441`. The
owner confirmed all three are single-model books, and they are declared as such in
`src/catalogue/browser/overrides.py`: the cover type code becomes the only model.

Cost and side effects worth knowing:

- A first read of an 83-page catalogue takes about 20 seconds. Agent results are
  cached under `data/catalogue_browser/agent_builds/`; `DELETE /catalog/agent/...`
  clears one and `DELETE /catalog/agent-cache/all` clears them all.
- The agent **calls out to `html.duckduckgo.com`** to confirm colour names, as it
  did before. Only Yamaha model and colour strings leave the machine — never VINs,
  dealer codes or prices. Results are cached in
  `data/catalogue_browser/colour_code_cache.json`.
- `/parts/from-catalog` prefers the agent-derived part master, then the browser's
  own batch extraction, then Step 01's `catalogue_parts` fact. The previous build
  had only the first two and returned an empty page until a rebuild had been run;
  the fact fallback keeps the Part Master page populated before that. The response
  carries `source` so the UI can tell which it got.
- `POST /catalog/run-extraction`, `POST /catalog/part-master/rebuild`,
  `/catalog/excel*` and `/catalog/download` are restored and working; the earlier
  mart-derived version did not have them.

### Owner's per-catalogue instructions and PDF misprints

Exceptions the reader cannot infer from the page are declared, one entry per file,
in `src/catalogue/browser/overrides.py` — never special-cased inline:

- **Never extracted, any catalogue:** `9 Digit Part No.`, `Escort 12 Digit Part No.`,
  `Superseded Part No.`, and a remarks column headed `Remarks (9 Digit)`. They are
  alternative numbering for the same part. Across the corpus 3,027 rows carried a
  9-digit value; none do now.
- **ENTICER 5US1, YBX125:** `Existing Part No.` is the part number, `Part Name` the
  description, and the remarks column is dropped.
- **2WS3, PC 2GS6, Saluto RX B441:** single-model (above).
- **RAY 1GC1 WHITE:** excluded. Part name, colour, quantity and remark arrive as one
  field on 29 of its 108 rows.
- **Colour in the description** (`FENDER, FRONT -VRC1`, `COVER (BLACK)`): matched
  against the applicable-colour table and, when the original remark does not
  already restrict the row, appended as `FOR <abbr>` — the original remark is
  kept. A remark's own colour restriction always outranks the description.
- **Colours the table does not list** are used, by the owner's instruction, when
  they name a vehicle colour — the same part printed in at least two colours. Six
  books gain such colours: LIBERO 5TS1 (YAMAHA BLACK, SILVER, DEEP PURPLE BLUE
  METALLIC, DARK CYAN GREEN), CRUX-S (YAMAHA GOLD, BLACK GOLD), FZS21C2 (CALM
  YELLOW, YELLOW), FAZER 45S7 (GRAY, SILVER), RAY 1GC1 (SILVER), Ray Z (CM6). The
  name joins the colour list with `source: description`; `FOR YAMAHA BLACK` parses
  as one colour. Not used, and recorded on the row as `colour_ignored`: paint
  marks (bearing fit grades), standard hardware plating (`NUT HEX(YELLOW)`), and a
  colour only one part carries (`PLATE, CAP -SILVER` in seven FZ books) — tying
  those to a colour no build is sold in would drop the part from every real build.
  A name glossing a code (`-CM6(cyan metallic)`) is the code; a shortened name
  inside exactly one table colour is that colour (`(MAROON)` → CNM); truncated
  printings take the longest form.
- **Image colour tables, transcribed** into `overrides.py`: YBX125 page 3 (00 BG
  Black Gold, 10 DPRC3 Dark Purplish Red Cocktail 3, 20 DPBMC Deep Purplish Blue
  Metallic C) and ENTICER 5US1 page 2. The ENTICER foreword gives names only —
  Candy Maroon, Light Yellow Metallic Grey, Black; they are paired with the body's
  CNM, LYNM9 and BG by initials, confirmed by the owner.
- **CRUX 5KA1 page 58**, parts exclusive to CRUX 5KA2 — a model this book does
  not cover — is read correctly and then withheld (33 rows), with a warning.

Some PDFs misprint the 12-digit number itself. The reader used to skip the
malformed number and store the row under the 9-digit number printed beside it,
or drop it. `_split_run_together_part_numbers` now repairs, only when the result
has the segment lengths of a real part number:

| Printed | Read as | Where |
|---|---|---|
| `10.5TS-E4710-00-00` | ref `10.`, `5TS-E4710-00-00` | LIBERO 5TS1 |
| `5YY.F6331-00-00`, `5TS-F2211.00-00` | hyphen for the dot | FAZER 5YY1, LIBERO 5TS1, CRUX 5KA1 |
| `4LS--F5355-00-00LEVERCAMSHAFT` | `4LS-F5355-00-00` + `LEVERCAMSHAFT` | FAZER 5YY1 |
| `4LS-E3451-00X-00` | `4LS-E3451-00-00` | GLADIATOR 5 SPEED |
| `4LS-F3118-0-00` | `4LS-F3118-00-00` | FAZER 5YY6, GLADIATOR |
| `KIT-5YYWF514-00-00` | `KIT` + `5YY-WF514-00-00` | FAZER 5YY1 |

Two layout cases are also handled:

- **Kit footnotes** under FAZER/GLADIATOR wheel tables (`* BRAKE SHOE 1
  (LOWER)-5YY-F5130-00-00`) were stored with the part name as the ref. The name is
  now the description, with no ref, no quantity and `kit_note` set.
- **Two tables side by side.** CRUX 5KA1 page 58, "PARTS EXCLUSIVE TO MODEL - CRUX
  (5KA2)", was read as one table with the left table's column bounds: right-hand
  parts lost description and quantity, and those sharing a line with a left-hand
  part were dropped. `_side_by_side_tables` parses each half on its own; all 33
  rows now read, filed under the page title — and are then withheld by the
  owner's instruction (above). A second 12-digit column (Escort, Superseded) is
  not mistaken for a table because it lacks a ref beside it.

### Owner's second review, 2026-09-26

| Catalogue | Instruction | Now |
|---|---|---|
| FZS21C2 | `CAST WHEEL, FRONT` + `CALM YELLOW` to Remarks | done; the header has no Q'TY label, so the quantity column is inferred from where digits line up |
| R15 2FB6 | `GASKET, HEAD COVER 1 1`: last 1 is the quantity; a single unmarked table colour is the model colour | done (quantity within 30pt of the column); DPBMY is the model colour (`model_colour_source: single`) |
| YBX125 | `CAP,CLEANER CASE1` not extracted | the PDF prints no quantity for it; taken as 1 (below). `COVER SIDE1 WITH` / `GRAPHICS(4LS2)-BG 1` merged across its wrapped line |
| CRUX 5KA1 | quantity 1 for `LEVER, COCK`, `TIRE (2.75 X 8) TVS`; foreword on the last page; colours incompatible with the table | done; table BG/CNM/DCC2 read from page 67; part-number suffix colours dropped (they tagged suppliers — PRICOL vs JNS meters — as colours) |
| LIBERO G5 | do not extract kit parts | 11 rows dropped: `KIT …`, `BRAKE SHOE KIT`, `TOOL KIT`, and the `*` kit/assembly lines incl. `CHAIN PULLER ASSY. 2 (CONSISTING OF …)` |
| FZS 21C8 | `…-VRC1 FOR BWCQ11` → `…-VRC1 FOR BWC1`, quantity 1; all table colours | done (a colour code glued to its quantity is split); CMY now read |
| R15 2YS1 | quantity on the next line; extract remarks | continuation lines merged; remark `UR LGB/DRSC`, the redundant gloss dropped |
| GLADIATOR | drop the `(` rows; colours from the description suffix | 2 note lines dropped; DRMK now read; suffix codes printed `HO` read as `H0`, but its body panels contradict them, so descriptions decide |
| FZ S 21C6 | `COVER, SIDE 3 -S3` quantity 1 | done |
| R15 1CK5 | drop one of the two copies | `R 15/R15 1CK5.pdf` excluded as a byte-identical copy |

Rules behind those, applied corpus-wide:

- **Colour tables are read under their own header** (`Colour Code | Colour Name |
  Abbreviation`, either order), clipped to the table's x-range, including the last
  three pages. Codes may carry slashes (`FO/90`, `PI/P0`); `CODE-colour` cells
  (`YB-BLACK`) reduce to the code. Against the original reader: 99 of 107 tables
  identical, the other 8 only gain missing colours (or lose the mis-read `BIKE`).
- **A description colour moves to Remarks** and is cut from the description, unless
  the remark already restricts the part (then the description stays as printed). A
  colour nothing verifies is written without `FOR`, so it restricts no build.
- **Part-number suffix colours** are dropped book-wide where descriptions contradict
  them more often than not, and on any row whose description carries its own
  qualifier (`(PRICOL)`, `-CRUX-R`, `(12V 2.0W)`).
- **A part row that prints no quantity takes 1** and is marked `qty_assumed` (20
  rows). Kit footnotes and kit headers keep none.
- **Part numbers must contain a digit**, and a two-segment one in its first segment,
  so `FRONT-CALM` or `FRONT-VRC1` in a description is not read as a part.
- **Note lines** — a part name printed before its part number, landing in the ref
  column with nothing left for the description — are dropped.

**Loss check** against the original reader, all 105 in-scope catalogues: 46 part
numbers removed were 9-digit numbers, 91 were replaced by their repaired 12-digit
form, and every other removal is a row the owner asked to drop (CRUX 5KA2 page 11,
LIBERO G5 kits 9, GLADIATOR note lines 2) or `KIT-5YYWF514-00-00` split into
`5YY-WF514-00-00`. Totals: 86,150 rows, 837 colour remarks from descriptions, 0
9-digit values, **15 rows priced for no model** — 12 brake-shoe kit footnotes
(FAZER 5YY1/5YY6, GLADIATOR) and 3 kit headers (`3L-WF513-00 (CONSISTING OF REF.
NOS. 8 & 10)` in CRUX-S and CRUX 5KA1, `BRAKE PAD KIT` in ENTICER 5US2).

### Catalogue database

Extracted catalogues are stored in PostgreSQL (`src/catalogue/store.py`) and the
Catalogues page reads them back — 30-80 ms instead of 5-20 s per PDF.

Laid out per the owner's diagram (2026-09-27):

| Table | Diagram columns | Notes |
|---|---|---|
| `catalogues` | `catalogue_id` bigint PK, `catalogue_no` text UK, `catalogue_year` smallint, `source_file` | `catalogue_no` is the cover's publication number (`1UB9E-470EA`; AEROX from its file name). 38 of 103 stored books print one; the rest are NULL. |
| `models` | `model_code` PK, `model_name` | 115 variant codes; `model_name` is the model folder (AEROX, FZ & FZS, R 15). A code keeps the name it was first stored under. |
| `catalogue_parts` | `id` bigint PK, `catalogue_id` FK, `section`, `part_no`, `description`, `model_code` FK → `models`, `quantity`, `remarks` | one row per part row per model it is fitted to, with that model's quantity; the 15 kit rows have `model_code` NULL. |
| `part_compatible_models` (view) | `part_no`, `description`, `compatible_models` text[] | e.g. `B65-E3907-10` → `FUEL PUMP COMP.` → `{AEROX - B65L, AEROX - B65N}`. Also `material_key` (separators removed) and `catalogue_count`. |

Beyond the diagram, `catalogues` and `catalogue_parts` keep the reader's detail (file
hash, status and exclusion reason, variants, row number, page, ref, raw quantity string,
colour hint, `qty_assumed`, and the rest in `extra`) so a stored catalogue reads back as
the same `ExtractionResult` a live read returns. `catalogue_colours` holds the colour
table. The schema is created on first use and upgraded in place (bigint keys, the
`model` → `model_code` rename, `models` backfilled), tested on an empty database and on
the loaded one.

**Byte-identical PDFs are stored once** (catalogue_no is unique and both copies print
the same number): ALFA `B931_2XB1_PC 20150425 updated.pdf` is recorded as a copy of
`Alpha B931_2XB1_PC …`, NMAX `BV3C00-050B.pdf` as a copy of `BV3C00-050A.PDF`, with R15
1CK5 as before. 103 catalogues stored, 4 excluded, 84,600 rows.

**Compatible models for a material:** `GET /api/v1/catalog/db/compatible-models?part_no=B65E390710`
(exact, separators ignored, so the SAP material id and the catalogue's `B65-E3907-10`
both match) or `?q=FUEL PUMP` (part-number prefix or description text). Grouped by
part number, as in the diagram. Of 15,815 part numbers, 9,090 fit more than one model
variant.

**Part Master page.** Its *compatible models* column now comes from this view, merged
per supersession chain: every catalogue number is matched against each PN_Yamaha
material and every number it superseded, and credited to that chain's
`active_sku_id` (one identity per part). Yamaha's 10- and 12-digit forms are one part
(`B65-E3907-10` in the catalogue is `B65-E3907-10-00` in the master), which raised
matches from 6,961 to 12,302 of 15,815 catalogue numbers. 9,915 of 24,054 current
identities now carry compatible models (Step 02's join gave 12.4%). The other 3,513
catalogue numbers have no PN_Yamaha identity and so are not on this page. When the
database is unreachable the page falls back to Step 02 and says so; searching by an
SAP material id without separators works.

**PN_Yamaha in the database.** `pn_yamaha` holds PN_Yamaha's Brand "YM" rows — 25,073
of 30,218 — with `material` (PK), `latest_ss`, `material_description` and
`supersede_1` … `supersede_10`, loaded from the converted workbook in one reconciled
transaction (blank or repeated materials are rejected and counted; none this vintage).
`pn_yamaha_compatibility` (materialized, indexed) gives every material the catalogue's
part name (`catalogue_description`) and `compatible_models` when its Material, Latest SS
or any of its ten superseded numbers is a catalogue part — separators ignored, 10- and
12-digit forms one part — with `matched_on` saying which number matched and
`catalogue_part_nos` the catalogue numbers. When none of a material's own twelve numbers
matches, the rest of its supersession chain is searched — every material sharing its Latest
SS, and the Latest SS material itself — since their rows can list old numbers this one does
not (`matched_on = chain`). 13,803 materials match: 12,845 on Material, 207 on Latest SS,
18 through a superseded number, 733 through the chain. It is refreshed after every PN_Yamaha
or catalogue load; lookups take ~10 ms.

Load with `uv run python -m src.cli pn-yamaha-load` (after `ingest`), `POST
/api/v1/catalog/db/pn-yamaha/load`, or the Catalogues tab's *Extract & save to
database* button, which loads PN_Yamaha after the catalogues. Look up with `GET
/api/v1/catalog/db/pn-yamaha?material=B65E390710` or `?q=FUEL PUMP`.

**Part Master page** now reads `pn_yamaha_compatibility`: one row per YM material —
Material, Latest SS (shown when it differs), Material Description, the catalogue's Part
Name (tagged *via Latest SS* / *via Supersede n* when that is the number that matched),
and Compatible Models. The type filter is *In catalogues / Not in catalogues*; search
covers material, Latest SS (separators ignored) and both descriptions. With the database
unreachable or PN_Yamaha not loaded, the page falls back to Step 02's per-chain master
and its footer says so.

Every write is reconciled inside its transaction (rows and records re-counted); a
mismatch rolls back. `/catalog/tables/...` and the agent serve the stored copy when
the PDF's hash still matches, and read the PDF live otherwise — the response's
`source` says which. Loading is always manual:

```bash
uv run python -m src.cli catalogue-load                 # every PDF (skips current copies)
uv run python -m src.cli catalogue-load --file "CRUX/CRUX-S PC5KA5.pdf"
```

or `POST /api/v1/catalog/db/load/{folder}/{file}`; `GET /api/v1/catalog/db/status`
lists what is stored, excluded and not yet loaded.

On the **Catalogues tab** the *Catalogue database* bar shows how many PDFs are saved
and has an **Extract & save to database** button — the step for a new installation
or after PDFs are copied in. It runs `POST /api/v1/catalog/db/load-all` in the
background (only PDFs without a current copy; tick *Re-extract all* to refresh every
one) with a progress bar fed by `GET /api/v1/catalog/db/load-status`. Each opened
catalogue carries a *from database* / *read from PDF* badge. The button and the CLI
share one loader, `store.load_catalogues`. Connection settings are the
`POSTGRES_*` keys in `.env`.

## Source workbooks refresh the analysis on their own

Before, an edited workbook reached nothing: the dashboard serves published tables, which
changed only when someone ran `ingest` and then the pipeline, and one API cache held
tables until the server restarted. Now (`src/refresh.py`):

- The API watches the source workbooks in `data/raw/` (every 20 s). A file whose
  modification time changes and then holds still for 10 s — Excel has finished saving —
  starts a refresh; so does server start-up if a workbook changed while it was down.
- Only workbooks whose content hash changed are re-converted, and only the stages
  downstream of them re-run: `orders.xlsx` from step 03, `MCSI.xlsx` from step 09,
  `current_stock.xlsx`/`On_Orders.xlsx` from 12, `sales.xlsx` from 04, `PN_Yamaha.xlsx`
  from 02 (and its database copy is reloaded). The PDF catalogue step never re-runs here.
- The cycle date follows the order history: the month after the last complete month of
  orders. When it moves, every stage except the catalogue re-runs. `SPI_REFRESH_AS_OF`
  pins it; `SPI_AUTO_REFRESH_SOURCES=false` turns the watcher off.
- A workbook that fails to convert stops the refresh before any stage runs. Every refresh
  writes `data/reports/run_refresh_<time>.json`, listed on the Pipeline page.
- Every page shows a banner while it runs ("Updating analysis from orders.xlsx — step
  08_forecast (5/11)") and offers a reload when done. The Pipeline page has *Refresh from
  source files* and *Re-run all stages*.
- API table caches are keyed on file modification time, so any pipeline run — CLI or
  refresh — is served without a restart.

First use (2026-09-27): the owner's new `orders.xlsx` (155,424 lines to 2026-08) and
`MCSI.xlsx` (56,211 rows to 2026-08) were picked up at start-up; the cycle moved from
2025-12-01 to 2026-09-01 and all 14 non-catalogue stages re-ran in 51 s.

## MCSI sold and returned are decided per VIN

Step 09 now publishes `unit_sales_vin`, one row per VIN, classified by the owner's rule:
**SlsVolQty summed over the VIN = 1 → sold, = 0 → returned.** Other sums are
`exception`, and a value that is not a 17-character VIN (30 MCSI rows carry `0`) is
`no_vin`; both count as neither. The VIN's model, month and dealer come from its last
sale row; its revenue is netted over every row.

Before, every SlsVolQty −1 row counted as a return and every +1 row as a sale: 891
"returns" (1.59%) and 55,319 sold — more than the 54,433 VINs, because 782 of the 787
VINs with a reversal were re-invoiced and so counted twice. Now: **54,428 sold, 4
returned (0.01%)**; the 891 reversal rows (782 re-billed VINs) are shown on the MCSI page
as billing reversals, not returns. All motorcycle cuts and the monthly sales-forecast
actuals count VINs the same way.

## MCSI colour and model names

The 2026 MCSI export carries `Color` (every row, 19 colours) and `Model Name`; the earlier
vintage had neither, so colour endpoints returned empty lists. Step 09 now keeps both on
each VIN (from the invoice that stands). The dashboard stage publishes
`mart_ui_mc_by_model_colour`, `mart_ui_mc_matrix_color_{rm,ase,province,district}` and
`mart_ui_mc_matrix_model_color_{…}` ("B1N2 – BLACK METALLIC X"), and
`mart_ui_mc_model_names` (each code's commonest name). The MCSI page's By Color tab and
the geography colour views read them; models read "FZ FI V2 (B1N2)", market share shows
two decimals, and each colour gets its own shade within its colour family.

## Two source facts that change what the old KPIs mean

**Order value is confirmed value, not ordered value.** Step 03 publishes
`order_value` as `confirmed quantity x Net Price` — what the dealer will be
billed. The old UI's `total_order_value_lkr` means "order received, all PO lines
including rejected", which is `order_value + lost_sale_value`. That sum
reconciles exactly with the source's own `Net Value (Item)` column
(1,460,069,682 LKR across the two years), so the compatibility layer publishes
both under names that cannot be confused: `ordered_value` and `confirmed_value`,
with `unfulfill_value_lkr` equal to the measured `lost_sale_value`. Reading the
confirmed figure as the ordered figure reports a 100% value fill rate; the real
one is 80.9%.

**`orders.xlsx` and `sales.xlsx` capture different populations.** For 2025 the
orders export carries 44,180 lines, 644,303 units and 278 dealers from a single
sales office (`W1B1`); billed sales carries 79,408 lines, 2,759,138 units and
427 payers from `Seeduwa - PDC`. Billed value is therefore roughly nine times
ordered value, and their ratio is not a fulfilment rate. The sales envelope's
`fulfillment_pct` reports the orders file's own confirmed-against-ordered value
instead, and `order_received_lkr` is left as the real ordered figure so the gap
stays visible. Reconciling the two extracts needs an answer from the owner about
what `orders.xlsx` is scoped to.

## Boundaries requiring a later UI decision

This pass connects outputs and adds no screens or visual components. The pipeline
runner displays current registered stages and persisted run reports. Its old run
buttons are not mapped to full-DAG execution; use the current CLI for execution.
Legacy module execution and report deletion are not connected. Catalogue upload
and re-extraction *are* connected, through the carried-over reader above; an
upload only ever adds a file and is refused if the name already exists, so source
files remain immutable.

RL, market baskets, stock-movement ledgers, SSOP membership, motorcycle colours
on the registration extract (distinct from catalogue paint colours, which the
carried-over reader does resolve) and container utilization have no equivalent in the new requirements or source
vintage. `/api/v1/not-modelled` identifies unsupported legacy fields. Old numeric
contracts still contain some compatibility placeholders; these are not measured
business results. Their presentation needs review before changing the UI.

On-order timing, finance assumptions, survival, and import lead-time uncertainty
remain the existing upstream limitations recorded in CLAUDE.md. This adapter
does not resolve them or change the policy acceptance verdict.

## Validation

`tests/api/test_legacy_dashboard.py` uses synthetic facts to check order and
forecast reconciliation, filters, pagination, returns scoping, cache refresh,
Excel provenance/round-trip, UI deep links, and persisted run status.


## Existing screens updated for the new requirements

The original layout now uses the four-month protection interval (three-month lead
plus one-month review), ordered C-document demand, new RS/RsS/on-demand/no-stock
policy labels and fill-rate targets. Order totals and searches cover all matching
published rows rather than only the browser's first page. Excel exports accept
those same filters. The existing Overview fill-rate card identifies the published
holdout verdict; inventory-position text exposes unresolved source assumptions.
Plant-level values/counts that are not published display Unavailable.

The Part Master table now reads PN_Yamaha supersession-resolved identities,
including parts without catalogue coverage. The UIO comparison uses actual recent
net motorcycle sales on its recent-sales side, rather than repeating the fleet.
Pipeline status uses the current registry. Execution controls are unavailable in
this output connection and no longer imply that legacy modules can be run.

## Outputs requiring additional UI, listed before implementation

No additional pages or panels have been added for these outputs:

| New requirement output | Proposed extension |
| --- | --- |
| Forecast backtest versus seasonal-naive and protection quantiles | Demand Forecast detail |
| Per-SKU order derivation, alternative policies, MOQ/pack steps | Order Plan detail |
| Full holdout service/cost comparison and acceptance frontier | Order Plan validation panel |
| Survival scenarios and lagged sales-target impact | UIO / MC Sales Forecast controls |
| Rejections, mapping gaps, run assumptions and lineage | Pipeline data-quality view |

These remain pending UI review. Existing source-data unknowns remain unresolved.
