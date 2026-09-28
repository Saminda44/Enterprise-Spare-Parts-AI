import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { fetchClassification, type ClassificationRow } from "../api/client";
import { POLICY_COLORS as TIER_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "./KpiCard";

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
  } | null;
  classification_coverage: Record<string, { assigned: number; not_classified: number }>;
  abc_fsn_counts: Record<string, Record<string, number>>;
  abc_counts: Record<string, number>; xyz_counts: Record<string, number>;
  fsn_counts: Record<string, number>; segment_counts: Record<string, number>;
  demand_category_counts: Record<string, number>; tier_counts: Record<string, number>;
  part_type_counts: Record<string, number>;
};

export function SkuClassificationTab() {
  const [clsData,  setClsData]  = useState<ClassificationData | null>(null);
  const [abc,      setAbc]      = useState("");
  const [xyz,      setXyz]      = useState("");
  const [tier,     setTier]     = useState("");
  const [partType, setPartType] = useState("");
  const [search,   setSearch]   = useState("");
  const [scope,    setScope]    = useState("");
  const [page,     setPage]     = useState(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchClassification({
        abc: abc || undefined, xyz: xyz || undefined, tier: tier || undefined,
        part_type: partType || undefined, scope: scope || undefined, search: search || undefined,
        limit: 100, offset: page * 100,
      }).then(setClsData);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [abc, xyz, tier, partType, scope, search, page]);

  useEffect(() => { setPage(0); }, [abc, xyz, tier, partType, scope, search]);

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

      {clsData.sales_abc_audit && (
        <p className="text-xs text-slate-500">
          Sales ABC: {clsData.sales_abc_audit.window_start} to {clsData.sales_abc_audit.window_end}.
          {" "}{(clsData.sales_abc_audit.code_linked_lines + clsData.sales_abc_audit.description_linked_lines).toLocaleString()} of {clsData.sales_abc_audit.sales_lines.toLocaleString()} billed lines linked to one Part Master SKU;
          {" "}{clsData.sales_abc_audit.unmapped_lines.toLocaleString()} remain unattributed
          ({clsData.sales_abc_audit.ambiguous_lines.toLocaleString()} ambiguous,
          {" "}{clsData.sales_abc_audit.no_match_lines.toLocaleString()} without a master match).
          {" "}Inactive means no uniquely linked, non-return sale with positive quantity in this window.
        </p>
      )}

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
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Behaviour Classes (Rules)</h3>
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={Object.entries(clsData.segment_counts).map(([k,v],i) => ({ name: k, value: v, fill: SEG_COLORS[i % SEG_COLORS.length] }))} layout="vertical" margin={{ top:0, right:40, left:5, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={130}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[0,3,3,0]}>
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
            <option value="A">A — High value</option>
            <option value="B">B — Medium value</option>
            <option value="C">C — Low value</option>
          </select>
          <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={xyz} onChange={e => setXyz(e.target.value)}>
            <option value="">All XYZ</option>
            <option value="X">X — Stable</option>
            <option value="Y">Y — Variable</option>
            <option value="Z">Z — Irregular</option>
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
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-white">
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                <th className="py-2 pr-3">SKU</th>
                <th className="py-2 pr-3">Description</th>
                <th className="py-2 pr-3">Brand</th>
                <th className="py-2 pr-3">Group</th>
                <th className="py-2 pr-3">Models</th>
                <th className="py-2 pr-3">Part Type</th>
                <th className="py-2 pr-3">Sales ABC / Activity</th>
                <th className="py-2 pr-3">XYZ</th>
                <th className="py-2 pr-3">FSN</th>
                <th className="py-2 pr-3">Policy</th>
                <th className="py-2 pr-3">Category</th>
                <th className="py-2 pr-3">Segment</th>
                <th className="py-2 pr-3 text-right">Avg Demand</th>
                <th className="py-2 pr-3 text-right">CV</th>
                <th className="py-2 pr-3 text-right">p_zero</th>
                <th className="py-2 pr-3 text-right">Billed Sales (LKR)</th>
                <th className="py-2 text-right">Order Issue Value (LKR)</th>
              </tr>
            </thead>
            <tbody>
              {clsData.rows.map(r => (
                <tr key={r.active_sku_id} className="border-b border-slate-50 hover:bg-slate-50/50">
                  <td className="py-2 pr-3 font-mono text-xs text-slate-700" title={r.superseded_numbers || undefined}>{r.active_sku_id}{r.alias_count > 1 && <span className="block text-[10px] text-slate-400">+{r.alias_count - 1} prior</span>}</td>
                  <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                  <td className="py-2 pr-3 text-xs text-slate-500">{r.brand || "-"}</td>
                  <td className="py-2 pr-3 text-xs text-slate-500">{r.material_group || "-"}</td>
                  <td className="py-2 pr-3 text-xs text-slate-500 max-w-[180px] truncate" title={r.compatible_models}>{r.compatible_models || "-"}</td>
                  <td className="py-2 pr-3">
                    {r.part_type ? (
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white whitespace-nowrap"
                        style={{ background: PART_TYPE_COLOR[r.part_type] ?? "#94A3B8" }}>
                        {r.part_type}
                      </span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="py-2 pr-3">
                    {r.abc ? <span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: ABC_COLOR[r.abc] ?? "#94A3B8" }}>{r.abc}</span> : <span className="text-xs font-medium text-slate-500">Inactive</span>}
                  </td>
                  <td className="py-2 pr-3">
                    {r.has_planning ? <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: (XYZ_COLOR[r.xyz] ?? "#94A3B8") + "22", color: XYZ_COLOR[r.xyz] ?? "#64748B" }}>{r.xyz}</span> : "-"}
                  </td>
                  <td className="py-2 pr-3 text-slate-500 text-xs">{r.has_planning ? r.fsn : "-"}</td>
                  <td className="py-2 pr-3">
                    {r.has_planning ? <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span> : "-"}
                  </td>
                  <td className="py-2 pr-3 text-slate-500 text-xs">{r.demand_category ?? "—"}</td>
                  <td className="py-2 pr-3 text-slate-500 text-xs max-w-[120px] truncate" title={r.demand_segment ?? ""}>{r.demand_segment ?? "—"}</td>
                  <td className="py-2 pr-3 text-right">{r.has_planning ? r.avg_monthly_demand?.toFixed(1) ?? "-" : "-"}</td>
                  <td className="py-2 pr-3 text-right">{r.has_planning ? r.cv?.toFixed(2) ?? "-" : "-"}</td>
                  <td className="py-2 pr-3 text-right">{r.has_planning && r.p_zero != null ? `${(r.p_zero * 100).toFixed(0)}%` : "-"}</td>
                  <td className="py-2 pr-3 text-right">{r.sales_net_lkr != null ? fmt(r.sales_net_lkr) : "-"}</td>
                  <td className="py-2 text-right">{r.has_planning && r.total_issue_value_lkr != null ? fmt(r.total_issue_value_lkr) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex justify-between items-center pt-3 text-xs text-slate-500">
          <span>{clsData.total ? `${page * 100 + 1}-${Math.min((page + 1) * 100, clsData.total)} of ${clsData.total.toLocaleString()}` : "No matching parts"}</span>
          <div className="flex gap-2"><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * 100 >= clsData.total} onClick={() => setPage(page + 1)}>Next</button></div>
        </div>
      </div>
    </div>
  );
}
