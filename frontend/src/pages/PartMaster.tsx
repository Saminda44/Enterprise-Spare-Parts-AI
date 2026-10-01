import { useCallback, useEffect, useRef, useState } from "react";
import {
  Search, X, Loader2, Database, RefreshCw,
  Play, CheckCircle2, AlertTriangle, Package, Layers,
} from "lucide-react";
import {
  fetchPartsFromCatalog, fetchPartMasterStatus, rebuildPartMaster,
  type CatalogDerivedPartsData, type CatalogDerivedPartRow,
  type PartMasterRebuildStatus,
} from "../api/client";
import { useSegment, useCategory, SEGMENT_TEXT, CATEGORY_TEXT } from "../api/segment";

const SUPERSEDE_HEADERS = [
  "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th",
].map(n => `${n} Supersede`);
const SHOW_SUPERSEDE_KEY = "partMaster.showSupersede";

function readShowSupersede(): boolean {
  try { return localStorage.getItem(SHOW_SUPERSEDE_KEY) === "1"; } catch { return false; }
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl shadow-sm px-5 py-4 space-y-0.5">
      <p className="text-xs text-slate-500 font-medium">{label}</p>
      <p className="text-2xl font-bold text-slate-800 leading-tight">{value}</p>
      {sub && <p className="text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

// ── Model badge ───────────────────────────────────────────────────────────────

const MODEL_COLORS: Record<string, string> = {
  "FZ & FZS": "#4361EE", "R 15": "#EF4444", "RAY": "#F97316",
  "FAZER": "#7C3AED", "ALFA": "#06B6D4", "CRUX": "#FFC107",
  "SALUTO": "#10B981", "SZ": "#EC4899", "YBR": "#94A3B8",
  "FASINO": "#0EA5E9", "LIBERO": "#84CC16", "GLADIATOR": "#F59E0B",
  "MT": "#2CC56F", "AEROX": "#FF6B6B", "NMAX": "#9B59B6",
  "ENTICER": "#E67E22", "YBX": "#1ABC9C",
};
function modelBg(name: string) { return MODEL_COLORS[name.trim()] ?? "#64748B"; }

function ModelBadges({ models }: { models: string }) {
  if (!models) return <span className="text-slate-300 text-xs">—</span>;
  const list = models.split(", ").filter(Boolean);
  return (
    <div className="flex flex-wrap gap-1">
      {list.map(m => {
        // Database form "AEROX - B65L", "FZ & FZS - 21C2"; older "AEROX B65J/DBNM8".
        const [modelPart, colourPart] = m.split("/");
        const dashed = modelPart.split(" - ");
        const tokens = modelPart.trim().split(" ");
        const modelName = dashed.length > 1 ? dashed[0].trim() : tokens[0];
        const variant   = dashed.length > 1 ? dashed.slice(1).join(" - ").trim() : tokens.slice(1).join(" ");
        return (
          <span
            key={m}
            className="inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded text-white leading-tight whitespace-nowrap"
            style={{ background: modelBg(modelName) }}
          >
            {modelName}
            {variant && <span className="opacity-80"> {variant}</span>}
            {colourPart && <span className="opacity-60 text-[9px]">/{colourPart}</span>}
          </span>
        );
      })}
    </div>
  );
}

// ── Build-index panel (empty state) ───────────────────────────────────────────

function BuildIndexPanel({ onDone }: { onDone: () => void }) {
  const [status,   setStatus]   = useState<PartMasterRebuildStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStatus = useCallback(() => {
    fetchPartMasterStatus().then(s => {
      setStatus(s);
      if (!s.running && s.last_result?.ok) onDone();
    });
  }, [onDone]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    if (status?.running) {
      pollRef.current = setInterval(loadStatus, 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [status?.running, loadStatus]);

  const handleBuild = async () => {
    setStarting(true);
    await rebuildPartMaster(true);
    setTimeout(loadStatus, 800);
    setStarting(false);
  };

  const running = status?.running || starting;

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-5 text-center">
      <Database size={48} className="text-slate-200" />
      <div>
        <p className="text-base font-semibold text-slate-700">Part master not built yet</p>
        <p className="text-sm text-slate-400 mt-1 max-w-md">
          Reads every PDF catalogue through the AI agent (runs once, then cached),
          aggregates unique part numbers and their compatible models, and builds
          the cross-catalogue part master.
        </p>
      </div>
      <button
        onClick={handleBuild}
        disabled={running}
        className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-brand-blue text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {running
          ? <><Loader2 size={15} className="animate-spin" /> Building…</>
          : <><Play size={15} /> Build Part Master from All PDFs</>}
      </button>
      {status?.running && (
        <p className="text-xs text-slate-400">
          Running agent on unprocessed PDFs — this may take several minutes…
        </p>
      )}
      {status?.last_result && !status.last_result.ok && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-4 py-2">
          <AlertTriangle size={14} /> {status.last_result.error}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export function PartMaster() {
  const segment = useSegment();
  const category = useCategory();
  const [data,        setData]        = useState<CatalogDerivedPartsData | null>(null);
  const [search,      setSearch]      = useState("");
  const [debSearch,   setDebSearch]   = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [kindFilter,  setKindFilter]  = useState<"" | "in_catalogue" | "not_in_catalogue">("");
  const [showSupersede, setShowSupersede] = useState<boolean>(readShowSupersede);
  const toggleSupersede = (on: boolean) => {
    setShowSupersede(on);
    try { localStorage.setItem(SHOW_SUPERSEDE_KEY, on ? "1" : "0"); } catch { /* storage blocked */ }
  };
  const [loading,     setLoading]     = useState(true);
  const [rebuilding,  setRebuilding]  = useState(false);
  const [rebuildStatus] = useState<PartMasterRebuildStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchPartsFromCatalog({ limit: 50000 })
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  // Client-side filtering
  const filtered: CatalogDerivedPartRow[] = (data?.rows ?? []).filter(r => {
    const q = debSearch.toLowerCase();
    // A material id typed without separators ("B65E390710") finds "B65-E3907-10-00".
    const qKey = q.replace(/[^a-z0-9]/g, "");
    const okSearch = !q
      || r.part_no.toLowerCase().includes(q)
      || (qKey.length > 0 && r.part_no.toLowerCase().replace(/[^a-z0-9]/g, "").includes(qKey))
      || (qKey.length > 0 && (r.latest_ss ?? "").toLowerCase().replace(/[^a-z0-9]/g, "").includes(qKey))
      || (qKey.length > 0 && (r.supersedes ?? []).some(
        n => n && n.toLowerCase().replace(/[^a-z0-9]/g, "").includes(qKey)))
      || r.description.toLowerCase().includes(q)
      || (r.catalogue_description ?? "").toLowerCase().includes(q);
    const okModel = !modelFilter
      || r.compatible_models.toLowerCase().includes(modelFilter.toLowerCase());
    const inCatalogue = r.in_catalogue ?? Boolean(r.compatible_models);
    const okKind = !kindFilter
      || (kindFilter === "in_catalogue" ? inCatalogue : !inCatalogue);
    return okSearch && okModel && okKind;
  });

  // Materials with at least one superseded number, shown on the supersede switch.
  const supersededCount = (data?.rows ?? []).filter(r => (r.supersedes ?? []).some(Boolean)).length;

  // Rebuild flow — reads agent builds and aggregates
  const handleRebuild = async () => {
    setRebuilding(true);
    try { await load(); } finally { setRebuilding(false); }
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // ── Not indexed yet ──────────────────────────────────────────────────────────
  if (!loading && data && !data.indexed) {
    return (
      <div className="flex-1 p-6 overflow-y-auto">
        <div className="space-y-2 mb-6">
          <h2 className="text-xl font-bold text-slate-800">{segment ? `${SEGMENT_TEXT[segment]} Part Master` : "Part Master"}</h2>
          <p className="text-xs text-slate-500">
            PN_Yamaha master with catalogue model compatibility
          </p>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-8">
          <BuildIndexPanel onDone={load} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 p-6 overflow-y-auto">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-slate-800">{segment ? `${SEGMENT_TEXT[segment]} Part Master` : "Part Master"}{category && <span className="text-brand-blue"> — {CATEGORY_TEXT[category]}</span>}</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {data
                ? segment
                  ? `${data.total.toLocaleString()} current ${SEGMENT_TEXT[segment]} parts · ${data.total_models} matching catalogue model variants`
                  : data.source === "pn_yamaha_db"
                    ? `${data.total.toLocaleString()} PN_Yamaha materials (Brand YM) · ${data.total_models} model variants`
                    : `${data.total.toLocaleString()} unique part numbers · ${data.total_models} models · PN_Yamaha master`
                : "Loading…"}
            </p>
          </div>
          <button
            onClick={handleRebuild}
            disabled={rebuilding || loading}
            title="Reload the published PN_Yamaha part master"
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 transition-colors"
          >
            {rebuilding
              ? <><Loader2 size={12} className="animate-spin" /> Rebuilding…</>
              : <><RefreshCw size={12} /> Refresh Master</>}
          </button>
        </div>

        {/* Rebuild progress banner */}
        {rebuilding && rebuildStatus && (
          <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-100 rounded-xl text-sm text-blue-700">
            <Loader2 size={15} className="animate-spin shrink-0" />
            <span>
              Processing PDFs — {rebuildStatus.cached_pdfs} cached so far.
              {rebuildStatus.last_result?.agents_run != null &&
                ` ${rebuildStatus.last_result.agents_run} new agents run.`}
            </span>
          </div>
        )}

        {/* KPI row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Kpi
            label={data?.source === "pn_yamaha_db" ? "Materials (YM)" : "Unique Parts"}
            value={loading ? "…" : (data?.total ?? 0).toLocaleString()}
            sub={data?.source === "pn_yamaha_db" ? "PN_Yamaha Brand YM" : "distinct part numbers"}
          />
          <Kpi
            label="Model Variants"
            value={loading ? "…" : (data?.total_models ?? 0).toString()}
            sub={data?.compatibility?.source === "catalogue_database"
              ? `${(data.compatibility.parts_with_models ?? 0).toLocaleString()} parts found in catalogues`
              : "catalogue models indexed"}
          />
          <Kpi
            label="Showing"
            value={loading ? "…" : filtered.length.toLocaleString()}
            sub="after current filters"
          />
          <Kpi
            label="Compatibility"
            value={!data ? "…" : data.compatibility?.source === "catalogue_database" ? "Catalogue DB" : "Step 02"}
            sub={data?.compatibility?.source === "catalogue_database"
              ? "merged across each supersession chain"
              : segment === "obm"
                ? "OBM catalogue models unavailable"
              : data?.compatibility?.error
                ? "catalogue database unreachable — Step 02 fallback"
                : "supersession-resolved current identities"}
          />
        </div>

        {/* Table card */}
        <div className="bg-white rounded-xl shadow-sm p-5 space-y-4">
          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[220px]">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="w-full pl-8 pr-7 py-1.5 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search material, Latest SS or description…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              {search && (
                <button onClick={() => setSearch("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500">
                  <X size={12} />
                </button>
              )}
            </div>

            <select
              value={modelFilter}
              onChange={e => setModelFilter(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
            >
              <option value="">All Models</option>
              {(data?.models ?? []).map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>

            <select
              value={kindFilter}
              onChange={e => setKindFilter(e.target.value as "" | "in_catalogue" | "not_in_catalogue")}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
            >
              <option value="">All materials</option>
              <option value="in_catalogue">In catalogues</option>
              <option value="not_in_catalogue">Not in catalogues</option>
            </select>

            <button
              type="button"
              aria-pressed={showSupersede}
              onClick={() => toggleSupersede(!showSupersede)}
              title={`${showSupersede ? "Hide" : "Show"} PN_Yamaha's 1st to 10th Supersede columns`
                + ` (${supersededCount.toLocaleString()} materials have supersede history)`}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-brand-blue/30 ${
                showSupersede
                  ? "bg-brand-blue text-white hover:opacity-90"
                  : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
            >
              {showSupersede ? "Hide supersede" : "Show supersede"}
            </button>

            <span className="text-xs text-slate-400 ml-auto">
              {filtered.length.toLocaleString()} part{filtered.length !== 1 ? "s" : ""}
            </span>
          </div>

          {/* Table */}
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-slate-400">
              <Loader2 size={28} className="animate-spin" />
              <p className="text-sm">Loading part master…</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2 text-slate-400">
              <Package size={36} className="text-slate-200" />
              <p className="text-sm font-medium">No parts match the current filter</p>
            </div>
          ) : (
            <div className="overflow-auto rounded-xl border border-slate-200 shadow-sm" style={{ maxHeight: "65vh" }}>
              <table className="w-full text-sm border-collapse">
                <thead className="sticky top-0 z-10">
                  <tr style={{ background: "#1B3A6B" }}>
                    {["Material", "Latest SS", "Material Description", "Part Name (catalogue)", "Compatible Models",
                      ...(showSupersede ? SUPERSEDE_HEADERS : [])].map(h => (
                      <th key={h}
                        className="py-2.5 px-3 text-left text-xs font-bold text-white whitespace-nowrap border-r border-blue-800 last:border-r-0">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r, i) => (
                    <tr key={r.part_no} className={i % 2 === 0 ? "bg-white" : "bg-slate-50/60"}>
                      <td className="py-2 px-3 border-b border-slate-100 font-mono text-xs text-slate-700 whitespace-nowrap">
                        {r.part_no}
                      </td>
                      <td className="py-2 px-3 border-b border-slate-100 font-mono text-xs text-slate-500 whitespace-nowrap">
                        {/* PN_Yamaha fills Latest SS on every row; a material that is its
                            own latest supersession shows its own number. */}
                        {r.latest_ss || <span className="text-slate-300">—</span>}
                      </td>
                      <td className="py-2 px-3 border-b border-slate-100 text-slate-700 max-w-[260px]">
                        <span title={r.description}>{r.description || <span className="text-slate-300">—</span>}</span>
                      </td>
                      <td className="py-2 px-3 border-b border-slate-100 text-slate-700 max-w-[260px]">
                        {r.catalogue_description ? (
                          <span title={"Catalogue part no. " + (r.catalogue_part_nos ?? "")}>
                            {r.catalogue_description}
                            {r.matched_on && r.matched_on !== "material" && (
                              <span className="ml-1 text-[10px] text-indigo-600">
                                via {r.matched_on === "latest_ss"
                                  ? "Latest SS"
                                  : r.matched_on === "chain"
                                    ? "supersession chain"
                                    : r.matched_on.replace("supersede_", "Supersede ")}
                              </span>
                            )}
                          </span>
                        ) : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="py-2 px-3 border-b border-slate-100">
                        <ModelBadges models={r.compatible_models} />
                      </td>
                      {showSupersede && SUPERSEDE_HEADERS.map((h, k) => {
                        const n = r.supersedes?.[k] ?? "";
                        return (
                          <td key={h} className="py-2 px-3 border-b border-slate-100 font-mono text-xs text-slate-500 whitespace-nowrap">
                            {n || <span className="text-slate-200">—</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Footer */}
          {data?.indexed && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              {data.agent_master
                ? <><CheckCircle2 size={12} className="text-emerald-500" />
                    AI-agent part master · {data.total.toLocaleString()} unique parts from {data.total_models} models</>
                : data.source === "pn_yamaha_db"
                  ? <><Layers size={12} className="text-slate-300" />
                      PN_Yamaha Brand YM from the database · part name and compatible models where the Material, Latest SS or a superseded number is in a catalogue</>
                  : <><Layers size={12} className="text-slate-300" />
                      Published PN_Yamaha master · one row per current part identity</>
              }
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
