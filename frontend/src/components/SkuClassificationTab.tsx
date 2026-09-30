import { Fragment, useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { fetchClassification, type ClassificationRow } from "../api/client";
import { POLICY_COLORS as TIER_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "./KpiCard";
import { withSegment } from "../api/segment";

const PART_TYPE_COLOR: Record<string, string> = {
  Engine:       "#EF4444",
  Electrical:   "#F59E0B",
  Wear:         "#F97316",
  Service:      "#2CC56F",
  Crash:        "#4361EE",
  Cosmetic:     "#A855F7",
  Fasteners:    "#64748B",
  Unclassified: "#94A3B8",
};
const ABC_COLOR:  Record<string, string> = { A: "#EF4444", B: "#FFC107", C: "#2CC56F", Inactive: "#94A3B8" };
const XYZ_COLOR:  Record<string, string> = { X: "#4361EE", Y: "#06B6D4", Z: "#94A3B8" };
const SEG_COLORS = ["#EF4444","#F97316","#FFC107","#4361EE","#2CC56F","#7C3AED","#94A3B8"];

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type ClassificationData = {
  total: number; rows: ClassificationRow[];
  classified_count: number; unclassified_count: number;
  active_count: number; inactive_count: number;
  order_classified_count: number;
  sales_abc_audit: {
    window_start: string; window_end: string; sales_lines: number;
    code_linked_lines: number; description_linked_lines: number; unmapped_lines: number;
    ambiguous_lines: number; no_match_lines: number;
    linked_skus: number; active_skus: number; return_only_skus: number;
    out_of_scope_lines?: number; out_of_scope_value?: number;
    in_scope_lines?: number; in_scope_value?: number; linked_value?: number;
    demand_resolved_lines?: number; demand_split_lines?: number;
  } | null;
  classification_coverage: Record<string, { assigned: number; not_classified: number }>;
  abc_fsn_counts: Record<string, Record<string, number>>;
  abc_counts: Record<string, number>; xyz_counts: Record<string, number>;
  fsn_counts: Record<string, number>; segment_counts: Record<string, number>;
  system_counts?: Record<string, number>; behaviour_source_counts?: Record<string, number>;
  demand_category_counts: Record<string, number>; tier_counts: Record<string, number>;
  part_type_counts: Record<string, number>;
};

const LINK_LABEL: Record<string, string> = {
  code: "part no.", description: "unique description",
  demand_resolved: "only part ordered", demand_split: "split by orders",
};

const VALUE_TEXT: Record<string, string> = { A: "High value", B: "Medium value", C: "Low value" };
const MOVEMENT: Record<string, { label: string; tone: string }> = {
  F: { label: "Fast", tone: "bg-green-100 text-green-700" },
  S: { label: "Slow", tone: "bg-amber-100 text-amber-700" },
  N: { label: "Not moving", tone: "bg-slate-100 text-slate-500" },
};
const PATTERN_TEXT: Record<string, string> = {
  smooth: "Steady every month", erratic: "Every month, sizes vary",
  intermittent: "Occasional", lumpy: "Occasional, sizes vary", "no demand": "No orders",
};
const POLICY_TEXT: Record<string, string> = {
  RS: "Top up monthly", RsS: "Reorder at a level", ON_DEMAND: "Order on demand", NO_STOCK: "Don't stock",
};
const XYZ_TEXT: Record<string, string> = { X: "stable", Y: "variable", Z: "irregular" };

function Detail({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <dt className="text-[10px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="text-slate-700 break-words">{value}</dd>
    </div>
  );
}

export function SkuClassificationTab() {
  const [clsData,  setClsData]  = useState<ClassificationData | null>(null);
  const [abc,      setAbc]      = useState("");
  const [xyz,      setXyz]      = useState("");
  const [tier,     setTier]     = useState("");
  const [partType, setPartType] = useState("");
  const [search,   setSearch]   = useState("");
  const [scope,    setScope]    = useState("");
  const [behaviour, setBehaviour] = useState("");
  const [system,    setSystem]    = useState("");
  const [fsn,       setFsn]       = useState("");
  const [planningAbc, setPlanningAbc] = useState("");
  const [pageSize,  setPageSize]  = useState(100);
  const [expanded,  setExpanded]  = useState<string | null>(null);
  const [page,     setPage]     = useState(0);
  // Option lists from the unfiltered book, so a filter never hides its own alternatives.
  const [options, setOptions] = useState<{ segment: Record<string, number>; system: Record<string, number> } | null>(null);
  const filters = {
    abc, xyz, fsn, tier, part_type: partType, scope, search, behaviour, system, planning_abc: planningAbc,
  };
  const anyFilter = Object.values(filters).some(Boolean);
  const clearFilters = () => {
    setAbc(""); setXyz(""); setFsn(""); setTier(""); setPartType(""); setScope(""); setSearch("");
    setBehaviour(""); setSystem(""); setPlanningAbc("");
  };
  const exportHref = withSegment(`/api/v1/classification/export.xlsx?${new URLSearchParams(
    Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) as Record<string, string>
  )}`);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchClassification({
        ...Object.fromEntries(Object.entries(filters).map(([k, v]) => [k, v || undefined])),
        limit: pageSize, offset: page * pageSize,
      }).then(d => {
        setClsData(d);
        if (!anyFilter) {
          const full = d as unknown as ClassificationData;
          setOptions({ segment: full.segment_counts, system: full.system_counts ?? {} });
        }
      });
    }, 250);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abc, xyz, fsn, tier, partType, scope, search, behaviour, system, planningAbc, page, pageSize]);

  useEffect(() => { setPage(0); }, [abc, xyz, fsn, tier, partType, scope, search, behaviour, system, planningAbc, pageSize]);

  if (!clsData) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
        <KpiCard label="Part Master SKUs" value={clsData.total.toLocaleString()} color="blue"/>
        <KpiCard label="A-Class" value={(clsData.abc_counts.A ?? 0).toLocaleString()} color="red"/>
        <KpiCard label="B-Class" value={(clsData.abc_counts.B ?? 0).toLocaleString()} color="amber"/>
        <KpiCard label="C-Class" value={(clsData.abc_counts.C ?? 0).toLocaleString()} color="green"/>
        <KpiCard label="Inactive (12m)" value={clsData.inactive_count.toLocaleString()} sub="No linked sale in window" color="purple"/>
      </div>

      {clsData.sales_abc_audit && (() => {
        const a = clsData.sales_abc_audit;
        const linkedPct = a.in_scope_value ? ((a.linked_value ?? 0) / a.in_scope_value) * 100 : null;
        return (
          <p className="text-xs text-slate-500">
            ABC is ranked on <b>billed sales value</b> (sales.xlsx, {a.window_start} to {a.window_end}) and sets each part's
            fill-rate target; parts with no linked sale in that window keep their order-value class.
            {" "}Of {a.sales_lines.toLocaleString()} billed lines, {(a.out_of_scope_lines ?? 0).toLocaleString()} are
            other brands not in the Part Master (LKR {fmt(a.out_of_scope_value ?? 0)}, mostly non-Yamaha lubricants) and are excluded.
            {" "}Of the Yamaha lines{linkedPct != null ? <>, {linkedPct.toFixed(1)}% of value is linked</> : null}:
            {" "}{a.code_linked_lines.toLocaleString()} by part number,
            {" "}{(a.description_linked_lines - (a.demand_resolved_lines ?? 0) - (a.demand_split_lines ?? 0)).toLocaleString()} by a unique description,
            {" "}{(a.demand_resolved_lines ?? 0).toLocaleString()} resolved to the only part dealers ordered,
            {" "}{(a.demand_split_lines ?? 0).toLocaleString()} split by order share;
            {" "}{a.ambiguous_lines.toLocaleString()} ambiguous with no order evidence and {a.no_match_lines.toLocaleString()} without
            a master description stay unattributed.
          </p>
        );
      })()}

      <section className="border-y border-slate-200 py-4">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Classification and activity coverage</h3>
          <span className="text-xs text-slate-500">{clsData.total.toLocaleString()} Part Master SKUs</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-xs">
            <thead className="text-slate-500 text-left border-b border-slate-200">
              <tr><th className="py-2">Scheme</th><th className="py-2 text-right">Assigned</th><th className="py-2 text-right">Remaining</th><th className="py-2 text-right">Total</th></tr>
            </thead>
            <tbody>
              {Object.entries(clsData.classification_coverage).map(([name, counts]) => (
                <tr key={name} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5 text-slate-700">{name}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-700">{counts.assigned.toLocaleString()}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-500">
                    {counts.not_classified.toLocaleString()}
                    <span className="block text-[10px]">{name === "ABC" ? "Inactive (12m)" : "No class"}</span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums font-medium text-slate-700">{(counts.assigned + counts.not_classified).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Sales ABC and activity (12m)</h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={[...Object.entries(clsData.abc_counts), ["Inactive", clsData.inactive_count] as [string, number]].map(([k,v]) => ({ name: k, value: v }))} margin={{ top:5, right:5, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {[...Object.keys(clsData.abc_counts), "Inactive"].map(k => <Cell key={k} fill={ABC_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">XYZ (Order Variability)</h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={Object.entries(clsData.xyz_counts).map(([k,v]) => ({ name: k, value: v }))} margin={{ top:5, right:5, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {Object.keys(clsData.xyz_counts).map(k => <Cell key={k} fill={XYZ_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Order Demand Pattern</h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={Object.entries(clsData.demand_category_counts).map(([k,v]) => ({ name: k, value: v }))} layout="vertical" margin={{ top:0, right:30, left:10, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={80}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" fill="#4361EE" radius={[0,3,3,0]}/>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ABC × FSN matrix */}
      {(() => {
        const matrix: Record<string, Record<string, number>> = { A: { F:0, S:0, N:0 }, B: { F:0, S:0, N:0 }, C: { F:0, S:0, N:0 } };
        for (const a of ["A", "B", "C"]) for (const f of ["F", "S", "N"]) matrix[a][f] = clsData.abc_fsn_counts[a]?.[f] ?? 0;
        const maxCell = Math.max(1, ...Object.values(matrix).flatMap(row => Object.values(row)));
        const cellBg = (count: number) => {
          const intensity = Math.round((count / maxCell) * 200);
          return `rgb(${255 - Math.round(intensity * 0.5)}, ${255 - intensity}, ${255 - Math.round(intensity * 0.8)})`;
        };
        return (
          <div className="bg-white rounded-xl shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-1">Sales ABC × Order FSN Matrix</h3>
            <p className="text-xs text-slate-400 mb-4">Darker = more SKUs in that segment.</p>
            <div className="overflow-x-auto">
              <table className="mx-auto border-collapse">
                <thead>
                  <tr>
                    <th className="w-16 text-xs text-slate-400 pb-2 pr-3 text-right">ABC ╲ FSN</th>
                    {["F — Fast","S — Slow","N — Non"].map(h => (
                      <th key={h} className="w-36 text-center text-xs font-semibold text-slate-600 pb-2 px-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(["A","B","C"] as const).map(a => (
                    <tr key={a}>
                      <td className="pr-3 py-2 text-right">
                        <span className="text-sm font-bold px-2 py-1 rounded text-white" style={{ background: ABC_COLOR[a] }}>{a}</span>
                      </td>
                      {(["F","S","N"] as const).map(f => {
                        const count = matrix[a][f] ?? 0;
                        return (
                          <td key={f} className="px-2 py-2 text-center">
                            <div className="rounded-lg p-4 min-w-[120px]" style={{ background: cellBg(count) }}>
                              <p className="text-xl font-bold text-slate-800">{count.toLocaleString()}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5">{a}-{f}</p>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* Part Type breakdown */}
      {clsData.part_type_counts && Object.keys(clsData.part_type_counts).length > 0 && (
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Part Type Distribution</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart
              data={Object.entries(clsData.part_type_counts)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => ({ name: k, value: v }))}
              margin={{ top: 5, right: 20, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 11 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {Object.entries(clsData.part_type_counts)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k]) => <Cell key={k} fill={PART_TYPE_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Charts row 2 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700">Behaviour Classes — all Part Master parts</h3>
          <p className="text-xs text-slate-400 mb-3">
            Click a bar to list its parts below. Decided by the part's nature in its description, then its PDF catalogue section, then description keywords
            {clsData.behaviour_source_counts ? <> · {Object.entries(clsData.behaviour_source_counts)
              .map(([k, v]) => `${k}: ${v.toLocaleString()}`).join(" · ")}</> : null}
          </p>
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={Object.entries(clsData.segment_counts).sort((a, b) => b[1] - a[1]).map(([k,v],i) => ({ name: k, value: v, fill: SEG_COLORS[i % SEG_COLORS.length] }))} layout="vertical" margin={{ top:0, right:40, left:5, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={130}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[0,3,3,0]} cursor="pointer"
                onClick={(d: { name?: string }) => { if (d?.name) setBehaviour(behaviour === d.name ? "" : d.name); }}>
                {Object.entries(clsData.segment_counts).map(([k],i) => <Cell key={k} fill={SEG_COLORS[i % SEG_COLORS.length]}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Selected Policy</h3>
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={Object.entries(clsData.tier_counts).map(([k,v]) => ({ name: k, value: v }))} margin={{ top:5, right:10, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 11 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {Object.keys(clsData.tier_counts).map(k => <Cell key={k} fill={TIER_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm p-5">
        <p className="text-xs text-slate-500 mb-3">{clsData.active_count.toLocaleString()} active (12m) | {clsData.inactive_count.toLocaleString()} inactive (12m) | {clsData.order_classified_count.toLocaleString()} with order classifications</p>
        <div className="flex gap-3 mb-4 flex-wrap">
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm" value={scope} onChange={e => setScope(e.target.value)}>
            <option value="">All master parts</option>
            <option value="active">Active (12m)</option>
            <option value="inactive">Inactive (12m)</option>
          </select>
          <input
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
            placeholder="Search SKU or description…" value={search} onChange={e => setSearch(e.target.value)}
          />
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={abc} onChange={e => setAbc(e.target.value)}>
            <option value="">All ABC</option>
            <option value="A">A — High value (98% fill)</option>
            <option value="B">B — Medium value (95% fill)</option>
            <option value="C">C — Low value (90% fill)</option>
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={xyz} onChange={e => setXyz(e.target.value)}>
            <option value="">All XYZ</option>
            <option value="X">X — Stable</option>
            <option value="Y">Y — Variable</option>
            <option value="Z">Z — Irregular</option>
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={behaviour} onChange={e => setBehaviour(e.target.value)}>
            <option value="">All behaviour classes</option>
            {Object.entries(options?.segment ?? clsData.segment_counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <option key={k} value={k}>{k} ({v.toLocaleString()})</option>
            ))}
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={system} onChange={e => setSystem(e.target.value)}>
            <option value="">All systems</option>
            {Object.entries(options?.system ?? clsData.system_counts ?? {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <option key={k} value={k}>{k} ({v.toLocaleString()})</option>
            ))}
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={fsn} onChange={e => setFsn(e.target.value)}>
            <option value="">All FSN</option>
            <option value="F">F — Fast moving</option>
            <option value="S">S — Slow moving</option>
            <option value="N">N — Non-moving</option>
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={tier} onChange={e => setTier(e.target.value)}>
            <option value="">All Policies</option>
            {Object.keys(clsData.tier_counts).map(t => <option key={t} value={t}>{policyLabel(t)}</option>)}
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={partType} onChange={e => setPartType(e.target.value)}>
            <option value="">All Part Types</option>
            {Object.keys(clsData.part_type_counts).filter(pt => pt !== "UNSET").map(pt => (
              <option key={pt} value={pt}>{pt} {clsData.part_type_counts?.[pt] ? `(${clsData.part_type_counts[pt].toLocaleString()})` : ""}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-3 mb-3 text-xs">
          <span className="font-semibold text-slate-700">
            {clsData.total.toLocaleString()} part{clsData.total === 1 ? "" : "s"} {anyFilter ? "match these filters" : "in the Part Master"}
          </span>
          {anyFilter && (
            <button onClick={clearFilters} className="px-2 py-1 border border-slate-200 rounded text-slate-600 hover:bg-slate-50">Clear filters</button>
          )}
          <div className="flex-1"/>
          <label className="text-slate-500">Rows per page{" "}
            <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))} className="border border-slate-200 rounded px-1.5 py-0.5 ml-1">
              {[100, 250, 500, 1000].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <a href={exportHref} download
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700 font-medium">
            Download full list ({clsData.total.toLocaleString()}) · Excel
          </a>
        </div>
        {/* Plain-language key for a first-time reader */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3 text-[11px] text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
          <p><b className="text-slate-700">Value</b> — share of sales value: <b>A</b> the top 80% (a few parts, most money),
            <b> B</b> the next 15%, <b>C</b> the rest. A sets a 98% fill target, B 95%, C 90%.</p>
          <p><b className="text-slate-700">Movement</b> — how recently dealers ordered it: <b>Fast</b> within 3 months,
            <b> Slow</b> within 12, <b>Not moving</b> longer. The pattern says how regular the orders are.</p>
          <p><b className="text-slate-700">Stock policy</b> — how the monthly order treats the part. Click any row for the
            technical detail behind its labels.</p>
        </div>
        <div className="max-h-[640px] overflow-auto border border-slate-100 rounded-lg">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 shadow-[0_1px_0_#E2E8F0]">
              <tr className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                <th className="py-2.5 pl-3 pr-2 w-6"></th>
                <th className="py-2.5 pr-3">Part</th>
                <th className="py-2.5 pr-3">Description</th>
                <th className="py-2.5 pr-3" title="ABC value class that sets the fill-rate target">Value</th>
                <th className="py-2.5 pr-3" title="How recently and how regularly dealers order it">Movement</th>
                <th className="py-2.5 pr-3" title="What drives replacement, and where it is fitted">Part type</th>
                <th className="py-2.5 pr-3" title="How the monthly order treats the part">Stock policy</th>
                <th className="py-2.5 pr-3 text-right" title="Average dealer orders per month over the whole order history — the forecast is on the Demand Forecast page">Past orders<span className="block normal-case font-normal">avg per month</span></th>
                <th className="py-2.5 pr-3 text-right">Billed sales<span className="block normal-case font-normal">LKR, 12 months</span></th>
              </tr>
            </thead>
            <tbody>
              {clsData.rows.map((r, i) => {
                const open = expanded === r.active_sku_id;
                // The planning ABC — the class that sets the fill target, as on the Overview and
                // Order Plan. A part dealers have never ordered is not planned, so not ranked.
                const value = r.has_planning ? r.planning_abc : null;
                const valueSource = r.has_planning
                  ? (r.abc_source === "sales" ? "from billed sales" : "from dealer orders")
                  : (r.abc ? `never ordered · sales class ${r.abc}` : "never ordered");
                const move = r.has_planning ? MOVEMENT[r.fsn] : null;
                const policy = r.has_planning ? POLICY_TEXT[r.policy_tier] : null;
                return (
                  <Fragment key={r.active_sku_id}>
                    <tr onClick={() => setExpanded(open ? null : r.active_sku_id)}
                      className={`cursor-pointer border-b border-slate-100 align-top transition-colors ${open ? "bg-blue-50/60" : i % 2 ? "bg-slate-50/40 hover:bg-blue-50/40" : "hover:bg-blue-50/40"}`}>
                      <td className="py-2.5 pl-3 pr-2 text-slate-400 text-xs select-none">{open ? "▾" : "▸"}</td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        <span className="font-mono text-xs text-slate-800">{r.active_sku_id}</span>
                        {r.alias_count > 1 && (
                          <span className="block text-[11px] text-slate-400" title={r.superseded_numbers}>
                            replaces {r.alias_count - 1} older no.
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 min-w-[220px] max-w-[320px]">
                        <span className="text-slate-800 line-clamp-2" title={r.description}>{r.description}</span>
                        <span className="block text-[11px] text-slate-400">{[r.brand, r.material_group].filter(Boolean).join(" · ")}</span>
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        {value ? (
                          <span className="inline-flex items-center gap-1.5">
                            <span className="w-6 h-6 rounded-full inline-flex items-center justify-center text-xs font-bold text-white" style={{ background: ABC_COLOR[value] ?? "#94A3B8" }}>{value}</span>
                            <span className="text-xs text-slate-700">{VALUE_TEXT[value] ?? ""}</span>
                          </span>
                        ) : <span className="text-xs text-slate-400">Not ranked</span>}
                        <span className="block text-[11px] text-slate-400 mt-0.5">{valueSource}</span>
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        {move ? (
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${move.tone}`}>{move.label}</span>
                        ) : <span className="text-xs text-slate-400">Never ordered</span>}
                        {r.has_planning && r.demand_category && (
                          <span className="block text-[11px] text-slate-400 mt-0.5">{PATTERN_TEXT[r.demand_category] ?? r.demand_category}</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 min-w-[150px]">
                        <span className={`text-xs ${r.demand_segment === "unclassified" ? "text-slate-400" : "text-slate-800"}`}>
                          {r.demand_segment ? r.demand_segment.charAt(0).toUpperCase() + r.demand_segment.slice(1) : "—"}
                        </span>
                        {r.system && r.system !== "Unassigned" && (
                          <span className="block text-[11px] text-slate-400">{r.system}{r.catalogue_section ? ` · ${r.catalogue_section}` : ""}</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        {policy ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-slate-700">
                            <span className="w-2 h-2 rounded-full" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}/>
                            {policy}
                          </span>
                        ) : <span className="text-xs text-slate-400">Not planned</span>}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                        {r.has_planning && r.avg_monthly_demand != null
                          ? (r.avg_monthly_demand >= 10 ? Math.round(r.avg_monthly_demand).toLocaleString() : r.avg_monthly_demand.toFixed(1))
                          : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-800">
                        {r.sales_net_lkr != null ? fmt(r.sales_net_lkr) : <span className="text-slate-300">—</span>}
                      </td>
                    </tr>
                    {open && (
                      <tr className="bg-blue-50/60 border-b border-slate-200">
                        <td/>
                        <td colSpan={8} className="pb-4 pr-3 pt-1">
                          <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-2 text-xs">
                            <Detail label="Order XYZ (variability)" value={r.has_planning ? `${r.xyz} — ${XYZ_TEXT[r.xyz] ?? ""}` : "—"}/>
                            <Detail label="Month-to-month variation (CV)" value={r.has_planning && r.cv != null ? r.cv.toFixed(2) : "—"}/>
                            <Detail label="Months with no orders" value={r.has_planning && r.p_zero != null ? `${(r.p_zero * 100).toFixed(0)}%` : "—"}/>
                            <Detail label="Order value (LKR)" value={r.has_planning && r.total_issue_value_lkr != null ? fmt(r.total_issue_value_lkr) : "—"}/>
                            <Detail label="Sales ABC / XYZ / FSN" value={r.abc ? `${r.abc} / ${r.sales_xyz ?? "—"} / ${r.sales_fsn ?? "—"}` : "No linked sale"}/>
                            <Detail label="Sale linked by" value={r.sales_link ? (LINK_LABEL[r.sales_link] ?? r.sales_link) : "—"}/>
                            <Detail label="Part type decided by" value={r.behaviour_source ?? "—"}/>
                            <Detail label="Stock policy (code)" value={r.has_planning ? policyLabel(r.policy_tier) : "—"}/>
                            <Detail label="Compatible models" value={r.compatible_models || "—"} wide/>
                            <Detail label="Older part numbers" value={r.superseded_numbers || "none"} wide/>
                          </dl>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex justify-between items-center pt-3 text-xs text-slate-500">
          <span>{clsData.total ? `${page * pageSize + 1}-${Math.min((page + 1) * pageSize, clsData.total)} of ${clsData.total.toLocaleString()}` : "No matching parts"}</span>
          <div className="flex gap-2"><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * pageSize >= clsData.total} onClick={() => setPage(page + 1)}>Next</button></div>
        </div>
      </div>
    </div>
  );
}
