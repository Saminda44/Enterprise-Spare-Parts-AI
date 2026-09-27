import { useCallback, useEffect, useRef, useState } from "react";
import {
  FileText, ArrowLeft, Search, X, Loader2,
  CheckCircle2, AlertTriangle, Upload,
} from "lucide-react";
import {
  fetchCatalog, fetchPdfTables, catalogFileUrl,
  fetchCatalogFolders, uploadCatalogPdf,
  fetchAgentBuilds, clearAllAgentCache,
  fetchCatalogueDbStatus, fetchCatalogueDbLoadStatus, loadAllCataloguesToDb,
  type CatalogueDbStatus, type CatalogueDbLoadStatus,
  type CatalogData, type CatalogModel, type PdfTableResult, type ColourCode,
  type AgentResult, type VariantColourEntry,
} from "../api/client";

const MODEL_COLORS: Record<string, string> = {
  "FZ & FZS": "#4361EE", "R 15": "#EF4444", "New Model 2025": "#2CC56F",
  "RAY": "#F97316", "FAZER": "#7C3AED", "ALFA": "#06B6D4", "CRUX": "#FFC107",
  "SALUTO": "#10B981", "SZ": "#EC4899", "YBR": "#94A3B8", "FASINO": "#0EA5E9",
  "LIBERO": "#84CC16", "GLADIATOR": "#F59E0B",
  "NEW MOTORCYCLE & SCOOTER": "#6366F1",
};
function modelColor(name: string) { return MODEL_COLORS[name] ?? "#4361EE"; }

// ── Shared catalogue table ─────────────────────────────────────────────────────

interface CatalogueData {
  headers: string[];
  rows: string[][];
  total: number;
  sections: string[];
}

/** Pick the correct qty from a "/" -separated multi-variant string. */
function variantQty(qty: string, varIdx: number, numVariants: number): string {
  const parts = qty.split("/");
  if (parts.length === 1) return qty;
  const offset = Math.max(0, parts.length - numVariants);
  const raw = parts[offset + varIdx];
  // If right-alignment lands on an empty trailing slot, fall back to the last
  // non-empty part.  This handles residual "1/" cases where a single-variant
  // PDF had a phantom second qty column in the source extractor.
  if ((raw === "" || raw === undefined) && offset > 0) {
    for (let i = offset - 1; i >= 0; i--) {
      if (parts[i]) return parts[i];
    }
  }
  return raw ?? qty;
}

function CatalogueTable({ data, relPath, pdfUrl, meta, variants, colourCodes, modelColourSource, manufactureYear, modelNo, columnLayout, descColourHints }: {
  data: CatalogueData;
  relPath: string;
  pdfUrl?: string;
  meta?: { pages: number; sections: number; ocr: number; warnings: string[]; source?: "database" | "pdf" };
  variants?: string[];
  colourCodes?: ColourCode[];
  modelColourSource?: PdfTableResult["model_colour_source"];
  manufactureYear?: string;
  modelNo?: string;
  columnLayout?: string[];
  descColourHints?: Record<string, string>;
}) {
  // A filled star claims the catalogue itself marked the colour with (*). Where it did
  // not, the colour was resolved from the document and the star is hollow.
  const markedByPdf = modelColourSource === "marked";

  const [section,    setSection]    = useState("");
  const [search,     setSearch]     = useState("");
  const [debSearch,  setDebSearch]  = useState("");
  const [selVariant, setSelVariant] = useState<number>(0);
  // Always stores a colour abbreviation (e.g. "CM6"), never a caption name
  const [selColour,  setSelColour]  = useState<string>("");

  const [agentResult,  setAgentResult]  = useState<AgentResult | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError,   setAgentError]   = useState<string | null>(null);
  const agentFetching = useRef(false);

  useEffect(() => {
    const t = setTimeout(() => setDebSearch(search), 200);
    return () => clearTimeout(t);
  }, [search]);

  // Reset everything when the PDF changes
  useEffect(() => {
    setSection(""); setSearch(""); setSelVariant(0); setSelColour("");
    setAgentResult(null); setAgentLoading(false); setAgentError(null);
    agentFetching.current = false;
  }, [data]);

  // Always pre-fetch agent on PDF open so colour tabs are ready without waiting
  useEffect(() => {
    if (agentResult || agentFetching.current || agentLoading) return;
    agentFetching.current = true;
    setAgentLoading(true);
    setAgentError(null);
    fetchAgentBuilds(relPath)
      .then(d  => { setAgentResult(d); setAgentLoading(false); })
      .catch(e => { setAgentError(e?.message ?? "Agent error"); setAgentLoading(false); agentFetching.current = false; });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [relPath]);

  const numVariants    = variants?.length ?? 0;
  const selVariantCode = variants?.[selVariant] ?? "";

  // Clear colour when switching variants if new variant doesn't have it
  useEffect(() => {
    if (!selColour || !agentResult || !selVariantCode) return;
    const colours = agentResult.variant_colour_map?.[selVariantCode];
    if (colours && !colours.find(c => c.abbreviation === selColour)) {
      setSelColour(""); setSection("");
    }
  }, [selVariantCode, agentResult, selColour]);

  // Colour chips for the selected variant.
  // Shows only colours that appear in FOR/EXCEPT remarks in the PDF — the
  // current variant's roster entry is the authoritative source.
  // Foreword colours absent from all remarks are NOT shown as chips.
  const variantColours: VariantColourEntry[] = (() => {
    // Agent not yet loaded → show foreword colours as placeholders.
    if (!agentResult) {
      if (colourCodes && colourCodes.length > 0) {
        const mc = colourCodes.filter(c => c.is_model_colour);
        return (mc.length ? mc : colourCodes).map(c => ({
          abbreviation: c.abbreviation,
          name: c.name,
          code: c.code,
          is_model_colour: c.is_model_colour ?? false,
        }));
      }
      return [];
    }

    // Agent loaded: derive chips from THIS variant's roster only.
    // roster = colours that actually appear in FOR/EXCEPT remarks.
    const roster = agentResult.rosters?.[selVariantCode] ?? [];
    if (roster.length === 0) {
      // Single-colour PDFs have no colour-specific remarks (no need to
      // differentiate — only one option exists). Still show the one chip
      // so the colour is identifiable; selecting it shows everything as shared.
      if (colourCodes && colourCodes.length === 1) {
        return colourCodes.map(c => ({
          abbreviation: c.abbreviation,
          name: c.name,
          code: c.code,
          is_model_colour: c.is_model_colour ?? false,
        }));
      }
      return [];
    }

    const rosterSet = new Set(roster.map(a => a.toUpperCase()));

    // Prefer variant_colour_map entries (carries foreword-table order + name/code).
    const agentMap = agentResult.variant_colour_map?.[selVariantCode] ?? [];
    const fromMap = agentMap.filter(c => rosterSet.has(c.abbreviation.toUpperCase()));
    if (fromMap.length > 0) return fromMap;

    // Fallback: build entries directly from roster using colour_legend.
    const legend = agentResult.colour_legend ?? {};
    return roster.map(abbr => {
      const entry = (legend[abbr.toUpperCase()] ?? {}) as unknown as Record<string, unknown>;
      return {
        abbreviation: abbr,
        name: (entry.name as string) ?? abbr,
        code: (entry.code as string) ?? "",
        is_model_colour: (entry.is_model_colour as boolean) ?? false,
      };
    });
  })();

  const selColourEntry = variantColours.find(c => c.abbreviation === selColour);

  // ── Colour-abbreviation set for client-side Kind annotation ──────────────
  // Colours that actually appear in FOR/EXCEPT remarks for this variant.
  // Only these colours have colour-specific row restrictions; any colour absent
  // from this set gets "shared" treatment in getRowKind (no rows hidden).
  const colourAbbrSet: ReadonlySet<string> = (() => {
    // Use the current variant's roster — the same set that determines chips.
    const roster = agentResult?.rosters?.[selVariantCode];
    if (roster && roster.length > 0) {
      return new Set(roster.map(a => a.toUpperCase()));
    }
    // Agent not yet loaded: fall back to foreword colour abbreviations.
    if (colourCodes && colourCodes.length > 0) {
      return new Set(colourCodes.map(c => c.abbreviation.toUpperCase()));
    }
    return new Set<string>();
  })();

  // Determine the kind of a row from its remarks.
  // Ports the grammar from remark_parser.py — two clause types produce restrictions:
  //   "EXCEPT [ABBREV]"          → applies to all colours EXCEPT listed
  //   "[...] FOR [ABBREV]"       → applies only to listed colours
  //   "FOR [ABBREV]" (no prefix) → same (clause starts with FOR)
  //   "[ABBREV]" standalone      → part's own paint finish, treated as universal
  //   no restriction found       → universal ("shared")
  // "shared"         — universal part (no colour restriction or excepted from another)
  // "colour_specific"— remarks name the selected colour via FOR pattern
  // "other"          — remarks target a different colour only
  function getRowKind(remarks: string): "shared" | "colour_specific" | "other" {
    if (!selColour || colourAbbrSet.size === 0) return "shared";
    const sel = selColour.toUpperCase();
    // Colour absent from PDF remarks has no remark-based differentiation →
    // treat every part as universal (show all rows for that colour chip).
    if (!colourAbbrSet.has(sel)) return "shared";
    if (!remarks || !remarks.trim()) return "shared";

    const upper = remarks.toUpperCase().trim();

    const applyCodes = new Set<string>();
    const exceptCodes = new Set<string>();
    let hasRestriction = false;

    for (const rawClause of upper.split(";")) {
      const clause = rawClause.trim();
      if (!clause) continue;

      // EXCEPT FOR / EXCEPT pattern
      const exceptM = /^EXCEPT(?:\s+FOR)?\s+(.+)/.exec(clause);
      if (exceptM) {
        const codes = exceptM[1].trim().split(/[\s,]+/).filter(t => colourAbbrSet.has(t));
        if (codes.length > 0) { codes.forEach(t => exceptCodes.add(t)); hasRestriction = true; }
        continue;
      }

      // FOR pattern: "[PREFIX] FOR [ABBR]" (space before FOR) or "FOR [ABBR]" at clause start
      const forPos = clause.indexOf(" FOR ");
      const afterFor = forPos >= 0 ? clause.slice(forPos + 5)
                     : clause.startsWith("FOR ") ? clause.slice(4) : null;
      if (afterFor !== null) {
        const codes = afterFor.trim().split(/[\s,]+/).filter(t => colourAbbrSet.has(t));
        if (codes.length > 0) { codes.forEach(t => applyCodes.add(t)); hasRestriction = true; }
        continue;
      }

      // Standalone token (no FOR, no EXCEPT):
      // A bare colour code marks the PART'S OWN paint finish, not which motorcycle
      // colour variant it belongs to → treat as universal (no restriction recorded).
    }

    if (!hasRestriction) return "shared";

    // EXCEPT mode: part applies to all colours except the listed set
    if (exceptCodes.size > 0 && applyCodes.size === 0) {
      return exceptCodes.has(sel) ? "other" : "shared";
    }

    // Direct inclusion mode
    return applyCodes.has(sel) ? "colour_specific" : "other";
  }

  // Remarks is always the last column; optional columns (nine_digit_part_no,
  // escort_part_no, superseded_part_no) are dropped by the API when all-empty,
  // so the index varies per PDF — derive it from the actual header count.
  const COL_REMARKS = data.headers.length - 1;
  const COL_KIND    = COL_REMARKS + 1;

  // ── All rows for selected variant (PDF order, variant qty decoded) ────────
  const extractedRows: string[][] = data.rows
    .filter(row => {
      const okSection = !section || row[0] === section;
      const q = debSearch.toLowerCase();
      const okSearch = !q || row[2]?.toLowerCase().includes(q) || row[3]?.toLowerCase().includes(q);
      return okSection && okSearch;
    })
    .flatMap(row => {
      if (numVariants === 0) return [row];
      const origQty = row[4] ?? "";
      const vQty = variantQty(origQty, selVariant, numVariants);
      if (origQty.includes("/") && vQty === "") return [];
      return [[...row.slice(0, 4), vQty, ...row.slice(5)]];
    });

  // Annotate every row with a Kind tag when a colour is selected, then filter.
  // "other" rows (parts for a different colour) are hidden from the table.
  // For desc-colour PDFs the colour membership comes from descColourHints (part_no lookup)
  // rather than FOR/EXCEPT patterns in remarks — description and remarks stay unchanged.
  const COL_PART_NO = 2; // part_no is always index 2 (never dropped)
  const COL_DESC    = 3; // description is always index 3 (never dropped)
  const annotatedRows: string[][] = selColour
    ? extractedRows.map(row => {
        // Composite key avoids collision when two colour variants share the same
        // part_no (e.g. YAMAHA BLACK and SL-3 both on 5TS-XF41A-40).
        const hintKey = `${row[COL_PART_NO]}::${row[COL_DESC] ?? ""}`;
        const hint = descColourHints?.[hintKey];
        let kind: string;
        if (hint !== undefined && hint !== "") {
          // colour_hint may be comma-separated (e.g. "YB,DRMK" for multi-colour or
          // EXCEPT logic). Split and check if the selected colour is in the list.
          const hintColours = hint.toUpperCase().split(",").map(h => h.trim());
          kind = hintColours.includes(selColour.toUpperCase()) ? "colour_specific" : "other";
        } else {
          kind = getRowKind(row[COL_REMARKS] ?? "");
        }
        return [...row.slice(0, COL_REMARKS + 1), kind];
      })
    : extractedRows;

  const displayRows: string[][] = selColour
    ? annotatedRows.filter(row => row[COL_KIND] !== "other")
    : annotatedRows;

  const sectionOptions: string[] = data.sections;

  // Colour breakdown counts from annotated rows (before filtering) for the banner
  const colourSpecificCount = selColour
    ? annotatedRows.filter(r => r[COL_KIND] === "colour_specific").length : 0;
  const sharedCount = selColour
    ? annotatedRows.filter(r => r[COL_KIND] === "shared").length : 0;
  const otherCount = selColour
    ? annotatedRows.filter(r => r[COL_KIND] === "other").length : 0;

  const hasColourTabs = variantColours.length > 0 || (agentLoading && !agentResult);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col min-h-0">

      {/* Extraction meta */}
      {meta && (
        <div className="space-y-1.5 mb-3">
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 bg-slate-50 border border-slate-100 rounded-lg px-3 py-2">
            <span className="font-medium text-slate-700">{data.total.toLocaleString()} parts extracted</span>
            {meta.source && (
              <span
                title={meta.source === "database"
                  ? "Served from the catalogue database"
                  : "Read live from the PDF — not yet saved to the database, changed since it was saved, or the database is unreachable"}
                className={`rounded px-1.5 py-0.5 text-[10px] font-medium border ${meta.source === "database"
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-amber-50 text-amber-700 border-amber-200"}`}>
                {meta.source === "database" ? "from database" : "read from PDF"}
              </span>
            )}
            <span>·</span><span>{meta.sections} sections</span>
            <span>·</span><span>{meta.pages} pages scanned</span>
            {modelNo && (
              <><span>·</span>
              <span className="font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 rounded px-1.5 py-0.5 font-mono text-[11px]">{modelNo}</span></>
            )}
            {manufactureYear && (
              <><span>·</span>
              <span className="font-medium text-blue-600">{manufactureYear} model</span></>
            )}
            {meta.ocr > 0 && (
              <><span>·</span>
              <span className="text-amber-600 flex items-center gap-1">
                <AlertTriangle size={11} /> {meta.ocr} image-only pages
              </span></>
            )}
            {meta.warnings.length > 0 && (
              <><span>·</span><span className="text-amber-600">{meta.warnings[0]}</span></>
            )}
          </div>
          {columnLayout && columnLayout.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5 bg-blue-50 border border-blue-100 rounded-lg">
              <span className="text-[10px] font-semibold text-blue-500 uppercase tracking-wide mr-1 shrink-0">
                Columns identified:
              </span>
              {columnLayout.map((col, i) => (
                <span key={i}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-medium whitespace-nowrap">
                  {col}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Model variant pill row ─────────────────────────────────────── */}
      {/* Only show when there are named variants — suppress the synthesised "" variant
          that the agent uses for single-model PDFs (e.g. desc-colour PDFs like CRUX-S). */}
      {numVariants >= 1 && variants!.some(v => v !== "") && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-50 border-b border-slate-200 overflow-x-auto">
          <span className="text-xs font-semibold text-slate-500 shrink-0 mr-1">Model variant:</span>
          {variants!.map((v, i) => (
            <button key={v}
              onClick={() => { setSelVariant(i); setSelColour(""); setSection(""); }}
              className={`px-4 py-1 rounded-full text-xs font-bold shrink-0 transition-colors whitespace-nowrap border ${
                selVariant === i
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-slate-600 border-slate-300 hover:border-blue-400 hover:text-blue-600"
              }`}>
              {v}
            </button>
          ))}
        </div>
      )}

      {/* ── Colour variant pill row ────────────────────────────────────── */}
      {hasColourTabs && (
        <div className="border-b border-amber-200">
          {agentLoading && !agentResult ? (
            <div className="flex items-center gap-2 px-4 py-3 text-xs text-amber-600 bg-amber-50">
              <Loader2 size={11} className="animate-spin" />
              <span>Identifying colour variants…</span>
            </div>
          ) : variantColours.length > 0 ? (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50 overflow-x-auto">
              <span className="text-xs font-semibold text-amber-700 shrink-0 mr-1 whitespace-nowrap">
                Colour variant{manufactureYear ? ` (${manufactureYear})` : ""}:
              </span>
              {/* All pill */}
              <button
                onClick={() => { setSelColour(""); setSection(""); }}
                className={`px-4 py-1 rounded-full text-xs font-bold shrink-0 transition-colors whitespace-nowrap border ${
                  !selColour
                    ? "bg-amber-500 text-white border-amber-500"
                    : "bg-white text-amber-600 border-amber-300 hover:border-amber-500 hover:bg-amber-50"
                }`}>
                All
              </button>
              {variantColours.map(c => (
                <button key={c.abbreviation}
                  onClick={() => { setSelColour(selColour === c.abbreviation ? "" : c.abbreviation); setSection(""); }}
                  title={
                    `${c.abbreviation} · paint code ${c.code}` +
                    (c.is_model_colour
                      ? markedByPdf
                        ? " · model colour, marked (*) in the catalogue"
                        : " · model colour, resolved from the catalogue (no (*) marker)"
                      : "")
                  }
                  className={`px-4 py-1 rounded-full text-xs font-bold shrink-0 transition-colors whitespace-nowrap border flex items-center gap-1 ${
                    selColour === c.abbreviation
                      ? "bg-amber-500 text-white border-amber-500"
                      : "bg-white text-amber-600 border-amber-300 hover:border-amber-500 hover:bg-amber-50"
                  }`}>
                  {c.name}
                  {c.is_model_colour && (
                    <span className="opacity-70">{markedByPdf ? "★" : "☆"}</span>
                  )}
                </button>
              ))}
            </div>
          ) : agentResult ? (
            <div className="px-4 py-2 text-xs text-slate-400 bg-amber-50/30">
              No colour variants found for this model
            </div>
          ) : null}
        </div>
      )}

      {/* ── Colour annotation banner ────────────────────────────────────── */}
      {selColour && (
        <div className="border-b border-amber-100">
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs bg-amber-50">
            <CheckCircle2 size={12} className="text-amber-600 shrink-0" />
            <span className="text-amber-800">
              Complete catalogue for&nbsp;<strong>{selColourEntry?.name ?? selColour}</strong>
              {selVariantCode && <>&nbsp;·&nbsp;variant&nbsp;<strong>{selVariantCode}</strong></>}
              {manufactureYear && <>&nbsp;·&nbsp;<span className="text-amber-600">{manufactureYear} model</span></>}
            </span>
            {/* Source badge */}
            {agentResult?.variant_colour_source && (
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                agentResult.variant_colour_source === "roster"  ? "bg-blue-100 text-blue-700" :
                agentResult.variant_colour_source === "cyclic"  ? "bg-violet-100 text-violet-700" :
                agentResult.variant_colour_source === "web"     ? "bg-teal-100 text-teal-700" :
                                                                   "bg-slate-100 text-slate-500"
              }`}>
                {agentResult.variant_colour_source === "roster"  ? "PDF remarks" :
                 agentResult.variant_colour_source === "cyclic"  ? "PDF foreword" :
                 agentResult.variant_colour_source === "web"     ? "web search" :
                                                                   "all colours"}
              </span>
            )}
            <span className="ml-auto flex items-center gap-2 text-[11px]">
              <span className="px-1.5 py-0.5 rounded bg-amber-200 text-amber-800 font-semibold">{colourSpecificCount} colour&#8209;specific</span>
              <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold">{sharedCount} shared</span>
              {otherCount > 0 && <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{otherCount} hidden</span>}
              <span className="font-bold text-amber-900">{displayRows.length} shown</span>
            </span>
          </div>
          {/* Colour-changing parts summary */}
          {(() => {
            const changingParts = agentResult?.colour_changing_parts ?? [];
            const relevantParts = changingParts.filter(p => selColour && p.per_colour[selColour]);
            if (relevantParts.length === 0) return null;
            return (
              <details className="group bg-amber-50/60 border-t border-amber-100">
                <summary className="flex items-center gap-2 px-4 py-1.5 text-[11px] text-amber-700 cursor-pointer select-none hover:bg-amber-100/50 list-none">
                  <span className="font-semibold">{relevantParts.length} parts change with this colour</span>
                  <span className="text-amber-500 ml-auto group-open:rotate-180 transition-transform">▾</span>
                </summary>
                <div className="px-4 pb-3 pt-1 grid grid-cols-1 gap-1 max-h-52 overflow-y-auto">
                  {relevantParts.map((p, i) => (
                    <div key={i} className="flex items-baseline gap-2 text-[11px]">
                      <span className="font-mono text-amber-800 w-6 shrink-0 text-right">{p.ref_no}</span>
                      <span className="text-slate-700 flex-1 truncate">{p.description || "—"}</span>
                      <span className="font-mono text-[10px] text-amber-600 shrink-0">{p.per_colour[selColour]}</span>
                      <span className="text-slate-400 text-[10px] shrink-0">
                        ({Object.keys(p.per_colour).length} colours)
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            );
          })()}
        </div>
      )}

      {agentError && (
        <div className="flex items-center gap-2 px-4 py-2 text-xs text-red-500 bg-red-50 border-b border-red-100">
          <AlertTriangle size={11} /> {agentError}
          <button
            onClick={() => { agentFetching.current = false; setAgentError(null); setAgentLoading(false); setAgentResult(null); }}
            className="underline ml-1">Retry</button>
        </div>
      )}

      {/* ── Toolbar ────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 py-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Section:</span>
          <select
            value={section} onChange={e => setSection(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
          >
            <option value="">All Sections ({data.total})</option>
            {sectionOptions.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            className="pl-8 pr-7 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-blue/30 w-60"
            placeholder="Search part no. or description…"
            value={search} onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button onClick={() => setSearch("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500">
              <X size={12} />
            </button>
          )}
        </div>
        <span className="text-xs text-slate-400 ml-auto">
          {displayRows.length.toLocaleString()} rows
        </span>
        {pdfUrl && (
          <a href={pdfUrl} target="_blank" rel="noreferrer"
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors">
            <FileText size={12} /> Open PDF
          </a>
        )}
      </div>

      {/* ── Parts table ────────────────────────────────────────────────── */}
      <div className="overflow-auto rounded-xl border border-slate-200 shadow-sm mt-3" style={{ maxHeight: "65vh" }}>
        <table className="w-full text-sm border-collapse">
          <thead className="sticky top-0 z-10">
            <tr style={{ background: "#1B3A6B" }}>
              {[...data.headers, ...(selColour ? ["Kind"] : [])].map((h, i) => (
                <th key={i} className="py-2.5 px-3 text-left text-xs font-bold text-white whitespace-nowrap border-r border-blue-800 last:border-r-0">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <>
              {displayRows.map((row, ri) => {
                const isFirstInSection = ri === 0 || row[0] !== displayRows[ri - 1][0];
                // kind tag is appended at COL_KIND when colour is selected
                const kind = row[COL_KIND];
                const rowBg = kind === "colour_specific"
                  ? (ri % 2 === 0 ? "bg-amber-50/60" : "bg-amber-50/90")
                  : kind === "shared"
                    ? (ri % 2 === 0 ? "bg-white" : "bg-slate-50/40")
                    : kind === "other"
                      ? (ri % 2 === 0 ? "bg-slate-50/20" : "bg-slate-50/30")
                      : (ri % 2 === 0 ? "bg-white" : "bg-slate-50/60");
                const rowOpacity = kind === "other" ? "opacity-40" : "";
                return (
                  <tr key={ri} className={`${rowBg} ${rowOpacity}`}>
                    {row.slice(0, COL_REMARKS + 1).map((cell, ci) => (
                      <td key={ci}
                        className={`py-2 px-3 border-b border-slate-100 whitespace-nowrap
                          ${ci === 0 && isFirstInSection ? "font-semibold text-slate-800" : ""}
                          ${ci === 0 && !isFirstInSection ? "text-slate-300" : ""}
                          ${ci === 2 ? "font-mono text-xs text-slate-700" : ""}
                          ${ci === 4 ? "text-center font-semibold text-brand-blue" : ""}
                          ${ci === 5 || ci === 6 ? "font-mono text-xs text-indigo-600" : ""}
                          ${ci === COL_REMARKS ? "text-slate-400 text-xs" : ""}
                        `}>
                        {ci === 0 && !isFirstInSection ? "" : cell}
                      </td>
                    ))}
                    {!!selColour && (
                      <td className="py-2 px-3 border-b border-slate-100">
                        {kind === "colour_specific" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-amber-100 text-amber-700">Colour</span>
                        )}
                        {kind === "shared" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-emerald-100 text-emerald-700">Shared</span>
                        )}
                        {kind === "other" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-slate-100 text-slate-400">Other</span>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
              {displayRows.length === 0 && (
                <tr>
                  <td colSpan={data.headers.length + (selColour ? 1 : 0)} className="py-12 text-center text-slate-400 text-sm">
                    No rows match the current filter
                  </td>
                </tr>
              )}
            </>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Shared states ──────────────────────────────────────────────────────────────

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3 text-slate-400">
      <Loader2 size={28} className="animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

function EmptyState({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-2 text-slate-400">
      <FileText size={36} className="text-slate-200" />
      <p className="text-sm font-medium">No table data found</p>
      <p className="text-xs text-slate-300">{message ?? "This PDF may be image-only or contain no structured tables"}</p>
    </div>
  );
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────────

function Breadcrumb({ onBack, backLabel = "All Catalogues", label, icon }: {
  onBack: () => void; backLabel?: string; label: string; icon: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3">
      <button onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 transition-colors">
        <ArrowLeft size={15} /> {backLabel}
      </button>
      <span className="text-slate-300">/</span>
      <div className="flex items-center gap-2">
        {icon}
        <span className="font-semibold text-slate-800">{label}</span>
      </div>
    </div>
  );
}

// ── PDF catalogue viewer ───────────────────────────────────────────────────────

function PdfCatalogueViewer({ relPath, filename, pdfUrl, onBack }: {
  relPath: string; filename: string; pdfUrl: string; onBack: () => void;
}) {
  const [result,  setResult]  = useState<PdfTableResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchPdfTables(relPath)
      .then(d => { setResult(d); setLoading(false); })
      .catch(() => { setResult(null); setLoading(false); });
  }, [relPath]);

  const label = filename.replace(/\.pdf$/i, "");
  const meta = result ? {
    pages: result.pages_scanned,
    sections: result.sections_found,
    ocr: result.ocr_flagged,
    warnings: result.warnings,
    source: result.source,
  } : undefined;

  return (
    <div className="space-y-4">
      <Breadcrumb onBack={onBack} label={label} icon={<FileText size={14} className="text-red-400" />} />
      {loading ? <LoadingState label="Extracting parts from PDF…" /> :
       !result || result.headers.length === 0 ? <EmptyState /> :
       <CatalogueTable
         data={result} relPath={relPath} pdfUrl={pdfUrl} meta={meta}
         variants={result.variants} colourCodes={result.colour_codes}
         modelColourSource={result.model_colour_source}
         manufactureYear={result.manufacture_year}
         modelNo={result.model_no}
         columnLayout={result.column_layout}
         descColourHints={result.desc_colour_hints}
       />}
    </div>
  );
}

// ── Extraction modal (used by upload panel) ────────────────────────────────────

function ExtractionModal({ relPath, filename, pdfUrl, onClose }: {
  relPath: string; filename: string; pdfUrl: string; onClose: () => void;
}) {
  const [result,  setResult]  = useState<PdfTableResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchPdfTables(relPath)
      .then(d => { setResult(d); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, [relPath]);

  const meta = result ? {
    pages: result.pages_scanned,
    sections: result.sections_found,
    ocr: result.ocr_flagged,
    warnings: result.warnings,
    source: result.source,
  } : undefined;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] flex flex-col">
        {/* Modal header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100 shrink-0">
          <div className="flex items-center gap-2">
            <FileText size={14} className="text-red-400" />
            <span className="font-semibold text-slate-800 text-sm">
              {filename.replace(/\.pdf$/i, "")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a href={pdfUrl} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors">
              <FileText size={12} /> Open PDF
            </a>
            <button onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>
        {/* Modal body */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading ? <LoadingState label="Extracting parts from PDF…" /> :
           !result || result.headers.length === 0 ? <EmptyState /> :
           <CatalogueTable data={result} relPath={relPath} meta={meta} variants={result.variants} colourCodes={result.colour_codes} modelColourSource={result.model_colour_source} manufactureYear={result.manufacture_year} modelNo={result.model_no} columnLayout={result.column_layout} descColourHints={result.desc_colour_hints} />}
        </div>
      </div>
    </div>
  );
}

// ── Upload PDF panel ───────────────────────────────────────────────────────────

type UploadEntry = {
  file: File;
  status: "idle" | "uploading" | "done" | "error";
  relPath?: string;
  error?: string;
};

function UploadPanel({ onCatalogRefresh }: { onCatalogRefresh: () => void }) {
  const [folders,    setFolders]    = useState<string[]>([]);
  const [entries,    setEntries]    = useState<UploadEntry[]>([]);
  const [folder,     setFolder]     = useState("");
  const [newName,    setNewName]    = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading,  setUploading]  = useState(false);
  const [viewFile,   setViewFile]   = useState<{ relPath: string; filename: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchCatalogFolders().then(fs => {
      setFolders(fs);
      if (fs.length > 0) setFolder(fs[0]);
    });
  }, []);

  const effectiveFolder = folder === "__new__" ? newName.trim() : folder;
  const canUpload = entries.length > 0 && effectiveFolder.length > 0 && !uploading;

  const addFiles = (fileList: FileList | null) => {
    if (!fileList) return;
    const pdfs = Array.from(fileList).filter(f => f.name.toLowerCase().endsWith(".pdf"));
    setEntries(prev => [...prev, ...pdfs.map(f => ({ file: f, status: "idle" as const }))]);
  };

  const removeEntry = (i: number) =>
    setEntries(prev => prev.filter((_, idx) => idx !== i));

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const handleUpload = async () => {
    setUploading(true);
    for (let i = 0; i < entries.length; i++) {
      if (entries[i].status === "done") continue;
      setEntries(prev => prev.map((e, idx) => idx === i ? { ...e, status: "uploading" } : e));
      try {
        const res = await uploadCatalogPdf(entries[i].file, effectiveFolder);
        setEntries(prev => prev.map((e, idx) =>
          idx === i ? { ...e, status: "done", relPath: res.rel_path } : e));
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Upload failed";
        setEntries(prev => prev.map((e, idx) =>
          idx === i ? { ...e, status: "error", error: msg } : e));
      }
    }
    setUploading(false);
    onCatalogRefresh();
    // refresh folder list in case a new folder was created
    fetchCatalogFolders().then(setFolders);
  };

  return (
    <>
      {viewFile && (
        <ExtractionModal
          relPath={viewFile.relPath}
          filename={viewFile.filename}
          pdfUrl={catalogFileUrl(viewFile.relPath)}
          onClose={() => setViewFile(null)}
        />
      )}

      <div className="space-y-5">
        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors select-none
            ${isDragging
              ? "border-brand-blue bg-blue-50"
              : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            multiple
            className="hidden"
            onChange={e => { addFiles(e.target.files); e.target.value = ""; }}
          />
          <Upload size={28} className={`mx-auto mb-2 ${isDragging ? "text-brand-blue" : "text-slate-300"}`} />
          <p className="text-sm font-medium text-slate-600">Drop PDF files here or click to browse</p>
          <p className="text-xs text-slate-400 mt-1">Only .pdf files are accepted · multiple files supported</p>
        </div>

        {/* Selected files list */}
        {entries.length > 0 && (
          <div className="space-y-1.5">
            {entries.map((e, i) => (
              <div key={i}
                className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-50 border border-slate-100">
                <FileText size={14} className="text-red-400 shrink-0" />
                <span className="text-sm text-slate-700 flex-1 truncate">{e.file.name}</span>
                <span className="text-xs text-slate-400 shrink-0">
                  {(e.file.size / 1024).toFixed(0)} KB
                </span>

                {e.status === "idle" && (
                  <button onClick={() => removeEntry(i)}
                    className="text-slate-300 hover:text-slate-500 transition-colors">
                    <X size={13} />
                  </button>
                )}
                {e.status === "uploading" && (
                  <Loader2 size={14} className="animate-spin text-brand-blue shrink-0" />
                )}
                {e.status === "done" && (
                  <>
                    <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                    <button
                      onClick={() => setViewFile({ relPath: e.relPath!, filename: e.file.name })}
                      className="text-xs px-2.5 py-1 rounded-lg bg-brand-blue text-white hover:bg-blue-700 transition-colors shrink-0">
                      Extract
                    </button>
                  </>
                )}
                {e.status === "error" && (
                  <span className="text-xs text-red-500 truncate max-w-[200px]" title={e.error}>
                    {e.error}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Folder selector + upload button */}
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-48">
            <label className="block text-xs font-medium text-slate-500 mb-1.5">Save to folder</label>
            <select
              value={folder}
              onChange={e => setFolder(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
            >
              <option value="" disabled>Select folder…</option>
              {folders.map(f => <option key={f} value={f}>{f}</option>)}
              <option value="__new__">+ Create new folder…</option>
            </select>
          </div>

          {folder === "__new__" && (
            <div className="flex-1 min-w-48">
              <label className="block text-xs font-medium text-slate-500 mb-1.5">New folder name</label>
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="e.g. NMAX"
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
              />
            </div>
          )}

          <button
            onClick={handleUpload}
            disabled={!canUpload}
            className="flex items-center gap-2 px-5 py-2 text-sm rounded-lg bg-brand-blue text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
          >
            {uploading
              ? <><Loader2 size={14} className="animate-spin" /> Uploading…</>
              : <><Upload size={14} /> Upload</>}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Model detail: file list → pick a file → PDF viewer ────────────────────────

function ModelDetail({ model, onBack }: { model: CatalogModel; onBack: () => void }) {
  const [selected, setSelected] = useState<{ relPath: string; filename: string; url: string } | null>(null);

  if (selected) {
    return (
      <PdfCatalogueViewer
        relPath={selected.relPath}
        filename={selected.filename}
        pdfUrl={selected.url}
        onBack={() => setSelected(null)}
      />
    );
  }

  const color = modelColor(model.model);
  return (
    <div className="space-y-4">
      <Breadcrumb
        onBack={onBack} backLabel="PDF Catalogues"
        label={model.model}
        icon={<span className="inline-block w-3 h-3 rounded-full" style={{ background: color }} />}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase tracking-wide">
              <th className="py-2.5 pr-4">Catalogue File</th>
              <th className="py-2.5 pr-4 text-right">Size</th>
              <th className="py-2.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {model.files.map(f => (
              <tr key={f.rel_path}
                className="border-b border-slate-50 hover:bg-slate-50/70 cursor-pointer transition-colors"
                onClick={() => setSelected({ relPath: f.rel_path, filename: f.filename, url: catalogFileUrl(f.rel_path) })}>
                <td className="py-2.5 pr-4">
                  <div className="flex items-center gap-2">
                    <FileText size={13} className="text-red-400 shrink-0" />
                    <span className="text-sm text-slate-700">{f.filename.replace(/\.pdf$/i, "")}</span>
                  </div>
                </td>
                <td className="py-2.5 pr-4 text-right text-xs text-slate-400">
                  {f.size_kb >= 1024 ? `${(f.size_kb / 1024).toFixed(1)} MB` : `${f.size_kb} KB`}
                </td>
                <td className="py-2.5 text-right">
                  <button
                    onClick={e => {
                      e.stopPropagation();
                      setSelected({ relPath: f.rel_path, filename: f.filename, url: catalogFileUrl(f.rel_path) });
                    }}
                    className="text-xs px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 hover:bg-brand-blue hover:text-white transition-colors">
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── PDF model list table ───────────────────────────────────────────────────────

function ModelTable({ models, search, onSearch, onSelect }: {
  models: CatalogModel[]; search: string;
  onSearch: (v: string) => void; onSelect: (m: CatalogModel) => void;
}) {
  const q = search.toLowerCase();
  const filtered = q ? models.filter(m => m.model.toLowerCase().includes(q)) : models;
  return (
    <div className="space-y-3">
      <div className="relative max-w-sm">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input className="w-full pl-8 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
          placeholder="Search model…" value={search} onChange={e => onSearch(e.target.value)} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase tracking-wide">
              <th className="py-2.5 pr-4">Model</th>
              <th className="py-2.5 pr-4 text-right">PDFs</th>
              <th className="py-2.5 pr-4 text-right">Total Size</th>
              <th className="py-2.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(m => {
              const totalKb = m.files.reduce((s, f) => s + f.size_kb, 0);
              const color = modelColor(m.model);
              return (
                <tr key={m.model}
                  className="border-b border-slate-50 hover:bg-slate-50/70 cursor-pointer transition-colors"
                  onClick={() => onSelect(m)}>
                  <td className="py-3 pr-4">
                    <div className="flex items-center gap-3">
                      <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ background: color }} />
                      <span className="font-medium text-slate-800">{m.model}</span>
                    </div>
                  </td>
                  <td className="py-3 pr-4 text-right text-slate-600">{m.pdf_count}</td>
                  <td className="py-3 pr-4 text-right text-slate-400 text-xs">
                    {totalKb >= 1024 ? `${(totalKb / 1024).toFixed(1)} MB` : `${totalKb.toFixed(0)} KB`}
                  </td>
                  <td className="py-3 text-right">
                    <button onClick={e => { e.stopPropagation(); onSelect(m); }}
                      className="text-xs px-3 py-1 rounded-lg bg-brand-blue text-white hover:bg-blue-700 transition-colors">
                      View
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && <p className="text-center text-slate-400 text-sm py-10">No models match "{search}"</p>}
      </div>
    </div>
  );
}

// ── Catalogue database panel ───────────────────────────────────────────────────
// The manual step for a new installation (or after PDFs are copied in): extract the
// PDF catalogues and save them to the database the page then reads from.

function DatabasePanel({ refreshKey }: { refreshKey: number }) {
  const [status, setStatus] = useState<CatalogueDbStatus | null>(null);
  const [job,    setJob]    = useState<CatalogueDbLoadStatus | null>(null);
  const [force,  setForce]  = useState(false);
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    fetchCatalogueDbStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  const stopPolling = () => { if (poll.current) { clearInterval(poll.current); poll.current = null; } };

  const startPolling = useCallback(() => {
    stopPolling();
    poll.current = setInterval(async () => {
      try {
        const s = await fetchCatalogueDbLoadStatus();
        setJob(s);
        if (!s.running) {
          stopPolling();
          refresh();
          setMessage(s.error
            ? `Load failed: ${s.error}`
            : `Done — ${s.loaded ?? 0} saved, ${s.skipped ?? 0} already current, ${s.excluded ?? 0} excluded, ${s.failed?.length ?? 0} failed`
              + (s.pn_yamaha ? ` · PN_Yamaha ${s.pn_yamaha.loaded.toLocaleString()} materials loaded` : ""));
        }
      } catch { /* transient; next tick retries */ }
    }, 3000);
  }, [refresh]);

  // Pick up a load already running (e.g. started from another tab) and the stored counts.
  useEffect(() => {
    refresh();
    fetchCatalogueDbLoadStatus().then(s => {
      setJob(s);
      if (s.running) startPolling();
    }).catch(() => {});
    return stopPolling;
  }, [refresh, startPolling, refreshKey]);

  const handleLoad = async () => {
    setStarting(true);
    setMessage(null);
    try {
      const res = await loadAllCataloguesToDb(force);
      if (!res.queued) setMessage(res.message ?? "A load is already running");
      startPolling();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not start the load");
    } finally {
      setStarting(false);
    }
  };

  const running = !!job?.running;
  const pct = running && job?.total ? Math.round(((job.done ?? 0) / job.total) * 100) : 0;
  const notLoaded = status?.not_loaded?.length ?? 0;
  const excludedCount = status?.excluded ? Object.keys(status.excluded).length : 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold text-slate-700">Catalogue database</span>
        {status === null ? (
          <span className="text-xs text-slate-400">checking…</span>
        ) : !status.reachable ? (
          <span className="flex items-center gap-1 text-xs text-red-600" title={status.error}>
            <AlertTriangle size={12} /> not reachable — pages read PDFs directly
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-slate-600">
            {notLoaded === 0
              ? <CheckCircle2 size={12} className="text-emerald-600" />
              : <AlertTriangle size={12} className="text-amber-600" />}
            {status.loaded ?? 0} of {status.on_disk} PDFs saved
            {excludedCount > 0 && <> · {excludedCount} excluded</>}
            {notLoaded > 0 && <> · <span className="text-amber-700 font-medium">{notLoaded} not saved yet</span></>}
            {" · "}
            {status.pn_yamaha && status.pn_yamaha.rows > 0
              ? <>PN_Yamaha {status.pn_yamaha.rows.toLocaleString()} materials ({status.pn_yamaha.matched.toLocaleString()} in catalogues)</>
              : <span className="text-amber-700 font-medium">PN_Yamaha not loaded</span>}
          </span>
        )}
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-slate-600" title="Also re-extract PDFs that are already saved and unchanged">
            <input type="checkbox" checked={force} disabled={running}
              onChange={e => setForce(e.target.checked)} />
            Re-extract all
          </label>
          <button
            onClick={handleLoad}
            disabled={running || starting || (status !== null && !status.reachable)}
            title="Extract the PDF catalogues and save them to the database, then load PN_Yamaha (Brand YM)"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-brand-blue text-white hover:opacity-90 transition-opacity disabled:opacity-50">
            {running || starting ? <Loader2 size={12} className="animate-spin" /> : null}
            {running ? "Extracting…" : "Extract & save to database"}
          </button>
        </div>
      </div>
      {running && (
        <div className="space-y-1">
          <div className="h-1.5 w-full rounded bg-slate-200 overflow-hidden">
            <div className="h-full bg-brand-blue transition-all" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-[11px] text-slate-500">
            {job?.done ?? 0} / {job?.total ?? 0} · {job?.loaded ?? 0} saved
            {job?.current ? <> · last: <span className="font-mono">{job.current}</span></> : null}
            {" "}— about 10 s per PDF; you can leave this page open or come back later.
          </div>
        </div>
      )}
      {message && <div className="text-[11px] text-slate-600">{message}</div>}
      {!running && job?.failed && job.failed.length > 0 && (
        <ul className="text-[11px] text-red-600 list-disc pl-4">
          {job.failed.map(f => <li key={f.source_file}><span className="font-mono">{f.source_file}</span>: {f.error}</li>)}
        </ul>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

type MainTab = "pdf" | "upload";

export function Catalog() {
  const [pdfData,       setPdfData]       = useState<CatalogData | null>(null);
  const [mainTab,       setMainTab]       = useState<MainTab>("pdf");
  const [selectedModel, setSelectedModel] = useState<CatalogModel | null>(null);
  const [search,        setSearch]        = useState("");
  const [clearingCache, setClearingCache] = useState(false);
  const [clearMsg,      setClearMsg]      = useState<string | null>(null);

  const [dbRefresh,     setDbRefresh]     = useState(0);

  const loadCatalog = useCallback(() => {
    fetchCatalog().then(setPdfData);
    setDbRefresh(k => k + 1);  // a new upload changes what is saved
  }, []);

  const handleClearAllCache = async () => {
    setClearingCache(true);
    setClearMsg(null);
    try {
      const { deleted } = await clearAllAgentCache();
      setClearMsg(`${deleted} cached result${deleted === 1 ? "" : "s"} cleared — colour filters will regenerate on next open`);
    } catch {
      setClearMsg("Failed to clear cache");
    } finally {
      setClearingCache(false);
    }
  };

  useEffect(() => { loadCatalog(); }, [loadCatalog]);

  if (selectedModel) {
    return (
      <div className="flex-1 p-6 overflow-y-auto">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <ModelDetail model={selectedModel} onBack={() => { setSelectedModel(null); setMainTab("pdf"); }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 p-6 overflow-y-auto">
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-slate-800">Parts Catalogues</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {pdfData?.total_pdfs ?? 0} PDFs across {pdfData?.models.length ?? 0} models
          </p>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
            <button onClick={() => setMainTab("pdf")}
              className={`flex items-center gap-2 px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${mainTab === "pdf" ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              <FileText size={14} /> PDF Catalogues
            </button>
            <button onClick={() => setMainTab("upload")}
              className={`flex items-center gap-2 px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${mainTab === "upload" ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              <Upload size={14} /> Upload PDF
            </button>
            <div className="ml-auto flex flex-col items-end gap-1">
              <button
                onClick={handleClearAllCache}
                disabled={clearingCache}
                title="Re-run colour variant analysis for all PDFs"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-50">
                {clearingCache ? <Loader2 size={11} className="animate-spin" /> : null}
                Refresh colour cache
              </button>
              {clearMsg && (
                <span className="text-[10px] text-slate-500">{clearMsg}</span>
              )}
            </div>
          </div>

          <DatabasePanel refreshKey={dbRefresh} />

          {mainTab === "pdf" && pdfData && (
            <ModelTable
              models={pdfData.models}
              search={search}
              onSearch={setSearch}
              onSelect={m => { setSelectedModel(m); setSearch(""); }}
            />
          )}

          {mainTab === "upload" && (
            <UploadPanel onCatalogRefresh={loadCatalog} />
          )}
        </div>
      </div>
    </div>
  );
}
