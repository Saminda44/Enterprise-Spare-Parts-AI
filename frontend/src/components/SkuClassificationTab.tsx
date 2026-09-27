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
const ABC_COLOR:  Record<string, string> = { A: "#EF4444", B: "#FFC107", C: "#2CC56F" };
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

  useEffect(() => {
    fetchClassification({
      abc:       abc       || undefined,
      xyz:       xyz       || undefined,
      tier:      tier      || undefined,
      part_type: partType  || undefined,
      limit: 500,
    }).then(setClsData);
  }, [abc, xyz, tier, partType]);

  const clsFiltered = clsData?.rows.filter(r =>
    !search ||
    r.material_9.toLowerCase().includes(search.toLowerCase()) ||
    r.description.toLowerCase().includes(search.toLowerCase())
  ) ?? [];

  if (!clsData) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total SKUs" value={fmt(clsData.total)}                  color="blue"/>
        <KpiCard label="A-Class"    value={fmt(clsData.abc_counts.A ?? 0)}      sub="High value · tight control" color="red"/>
        <KpiCard label="B-Class"    value={fmt(clsData.abc_counts.B ?? 0)}      sub="Medium value"               color="amber"/>
        <KpiCard label="C-Class"    value={fmt(clsData.abc_counts.C ?? 0)}      sub="Low value · bulk order"     color="green"/>
      </div>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">ABC (Value)</h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={Object.entries(clsData.abc_counts).map(([k,v]) => ({ name: k, value: v }))} margin={{ top:5, right:5, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {Object.keys(clsData.abc_counts).map(k => <Cell key={k} fill={ABC_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">XYZ (Demand Variability)</h3>
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
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Demand Category</h3>
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
        clsData.rows.forEach(r => { if (matrix[r.abc] && r.fsn) matrix[r.abc][r.fsn] = (matrix[r.abc][r.fsn] ?? 0) + 1; });
        const maxCell = Math.max(1, ...Object.values(matrix).flatMap(row => Object.values(row)));
        const cellBg = (count: number) => {
          const intensity = Math.round((count / maxCell) * 200);
          return `rgb(${255 - Math.round(intensity * 0.5)}, ${255 - intensity}, ${255 - Math.round(intensity * 0.8)})`;
        };
        return (
          <div className="bg-white rounded-xl shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-1">ABC × FSN Matrix</h3>
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
        <div className="flex gap-3 mb-4 flex-wrap">
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
            {Object.keys(clsData.part_type_counts).map(pt => (
              <option key={pt} value={pt}>{pt} {clsData.part_type_counts?.[pt] ? `(${clsData.part_type_counts[pt].toLocaleString()})` : ""}</option>
            ))}
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                <th className="py-2 pr-3">SKU</th>
                <th className="py-2 pr-3">Description</th>
                <th className="py-2 pr-3">Part Type</th>
                <th className="py-2 pr-3">ABC</th>
                <th className="py-2 pr-3">XYZ</th>
                <th className="py-2 pr-3">FSN</th>
                <th className="py-2 pr-3">Policy</th>
                <th className="py-2 pr-3">Category</th>
                <th className="py-2 pr-3">Segment</th>
                <th className="py-2 pr-3 text-right">Avg Demand</th>
                <th className="py-2 pr-3 text-right">CV</th>
                <th className="py-2 pr-3 text-right">p_zero</th>
                <th className="py-2 text-right">Issue Value (LKR)</th>
              </tr>
            </thead>
            <tbody>
              {clsFiltered.slice(0, 100).map(r => (
                <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                  <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                  <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                  <td className="py-2 pr-3">
                    {r.part_type ? (
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white whitespace-nowrap"
                        style={{ background: PART_TYPE_COLOR[r.part_type] ?? "#94A3B8" }}>
                        {r.part_type}
                      </span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: ABC_COLOR[r.abc] ?? "#94A3B8" }}>{r.abc}</span>
                  </td>
                  <td className="py-2 pr-3">
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: (XYZ_COLOR[r.xyz] ?? "#94A3B8") + "22", color: XYZ_COLOR[r.xyz] ?? "#64748B" }}>{r.xyz}</span>
                  </td>
                  <td className="py-2 pr-3 text-slate-500 text-xs">{r.fsn}</td>
                  <td className="py-2 pr-3">
                    <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                  </td>
                  <td className="py-2 pr-3 text-slate-500 text-xs">{r.demand_category ?? "—"}</td>
                  <td className="py-2 pr-3 text-slate-500 text-xs max-w-[120px] truncate" title={r.demand_segment ?? ""}>{r.demand_segment ?? "—"}</td>
                  <td className="py-2 pr-3 text-right">{r.avg_monthly_demand.toFixed(1)}</td>
                  <td className="py-2 pr-3 text-right">{r.cv.toFixed(2)}</td>
                  <td className="py-2 pr-3 text-right">{(r.p_zero * 100).toFixed(0)}%</td>
                  <td className="py-2 text-right">{fmt(r.total_issue_value_lkr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {clsFiltered.length > 100 && <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {clsFiltered.length.toLocaleString()}</p>}
        </div>
      </div>
    </div>
  );
}
