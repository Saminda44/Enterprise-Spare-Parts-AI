import { useEffect, useState } from "react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, BarChart, Bar,
} from "recharts";
import {
  fetchForecast, fetchTrend, fetchFusedDemand,
  type ForecastData, type MonthlyPoint, type M2FusedDemandResponse,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";

const METHOD_COLORS = ["#4361EE","#2CC56F","#FFC107","#EF4444","#7C3AED","#06B6D4","#94A3B8"];
const DC_COLORS: Record<string, string> = { AXF:"#EF4444", AYF:"#F97316", AZF:"#FFC107", BXF:"#4361EE", BYF:"#7C3AED", BZF:"#06B6D4", CXF:"#2CC56F", CYF:"#94A3B8", CZF:"#CBD5E1" };

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type ForecastTab = "stage10" | "fused";

export function Forecast() {
  const [tab,   setTab]   = useState<ForecastTab>("stage10");
  const [data,  setData]  = useState<ForecastData | null>(null);
  const [trend, setTrend] = useState<MonthlyPoint[]>([]);
  const [method, setMethod] = useState<string>("");
  const [search, setSearch] = useState("");

  // Module 2 fused demand state
  const [fusedData,   setFusedData]   = useState<M2FusedDemandResponse | null>(null);
  const [fusedSearch, setFusedSearch] = useState("");
  const [fusedMethod, setFusedMethod] = useState("");
  const [fusedDC,     setFusedDC]     = useState("");

  useEffect(() => { fetchTrend().then(setTrend); }, []);
  useEffect(() => { fetchForecast({ method: method || undefined, search: search || undefined, limit: 500 }).then(setData); }, [method, search]);
  useEffect(() => {
    fetchFusedDemand({ limit: 100, method: fusedMethod || undefined, demand_class: fusedDC || undefined })
      .then(setFusedData)
      .catch(() => setFusedData(null));
  }, [fusedMethod, fusedDC]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const methodData = Object.entries(data.method_counts).map(([k, v], i) => ({ name: k, value: v, fill: METHOD_COLORS[i] }));
  const trendData = trend.slice(-24).map(p => ({ month: p.year_month_str.slice(0, 7), qty: p.net_demand }));

  const zeroCount = data.zero_demand_skus;

  const filtered = data.rows.filter(r =>
    !search || r.material_9.toLowerCase().includes(search.toLowerCase()) || r.description.toLowerCase().includes(search.toLowerCase())
  );

  // Module 2 fused demand derived data
  const fusedMethodBarData = fusedData
    ? Object.entries(fusedData.method_counts).map(([name, value], i) => ({ name, value, fill: METHOD_COLORS[i] }))
    : [];
  const fusedFiltered = (fusedData?.rows ?? []).filter(r =>
    !fusedSearch || r.part_no.toLowerCase().includes(fusedSearch.toLowerCase())
  );

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-xl font-bold text-slate-800">Demand Forecast</h2>
        {/* Tab bar */}
        <div className="flex border border-slate-200 rounded-lg overflow-hidden text-sm">
          <button
            onClick={() => setTab("stage10")}
            className={`px-4 py-1.5 font-medium transition-colors ${tab === "stage10" ? "bg-brand-blue text-white" : "text-slate-600 hover:bg-slate-50"}`}
          >
            Material Forecast ? Step 08
          </button>
          <button
            onClick={() => setTab("fused")}
            className={`px-4 py-1.5 font-medium transition-colors border-l border-slate-200 ${tab === "fused" ? "bg-brand-blue text-white" : "text-slate-600 hover:bg-slate-50"}`}
          >
            History + Fleet Blend
          </button>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════
          TAB: Material Forecast ? Step 08
      ════════════════════════════════════════════════════ */}
      {tab === "stage10" && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard label="Total SKUs"    value={fmt(data.total)}   color="blue"/>
            <KpiCard label="Fleet Estimates" value={fmt(data.parc_skus)} sub="SKUs with a parc component" color="purple"/>
            <KpiCard label="Zero Demand"   value={fmt(zeroCount)}    sub="Published monthly forecast is zero" color="amber"/>
            <KpiCard label="Methods Used"  value={`${Object.keys(data.method_counts).length}`} color="teal"/>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Method donut */}
            <div className="bg-white rounded-xl shadow-sm p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Forecast Method Breakdown</h3>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={methodData} cx="50%" cy="50%" innerRadius={60} outerRadius={90} dataKey="value" nameKey="name">
                    {methodData.map(d => <Cell key={d.name} fill={d.fill}/>)}
                  </Pie>
                  <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                </PieChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap gap-2 mt-1">
                {methodData.map(d => (
                  <span key={d.name} className="flex items-center gap-1 text-xs text-slate-600">
                    <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: d.fill }}/>
                    {d.name} ({d.value.toLocaleString()})
                  </span>
                ))}
              </div>
            </div>

            {/* Trend */}
            <div className="bg-white rounded-xl shadow-sm p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Historical Monthly Demand</h3>
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={trendData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="blueGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#4361EE" stopOpacity={0.15}/>
                      <stop offset="95%" stopColor="#4361EE" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                  <XAxis dataKey="month" tick={{ fontSize: 10 }} interval={3}/>
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                  <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                  <Area type="monotone" dataKey="qty" stroke="#4361EE" fill="url(#blueGrad)" strokeWidth={2}/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Table */}
          <div className="bg-white rounded-xl shadow-sm p-5">
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search SKU or description…"
                value={search} onChange={e => setSearch(e.target.value)}
              />
              <select
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
                value={method} onChange={e => setMethod(e.target.value)}
              >
                <option value="">All methods</option>
                {Object.keys(data.method_counts).map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-4">SKU</th>
                    <th className="py-2 pr-4">Description</th>
                    <th className="py-2 pr-4">Method</th>
                    <th className="py-2 pr-4 text-right">Avg Demand</th>
                    <th className="py-2 pr-4 text-right">CV</th>
                    <th className="py-2 pr-4 text-right">LT Forecast</th>
                    <th className="py-2 pr-4 text-right">M+1</th>
                    <th className="py-2 pr-4 text-right">M+2</th>
                    <th className="py-2 text-right">M+3</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 100).map(r => (
                    <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-4 font-mono text-xs text-slate-700">{r.material_9}</td>
                      <td className="py-2 pr-4 text-slate-600 max-w-[200px] truncate">{r.description}</td>
                      <td className="py-2 pr-4">
                        <span className="text-xs bg-brand-blue/10 text-brand-blue px-2 py-0.5 rounded-full">{r.method}</span>
                      </td>
                      <td className="py-2 pr-4 text-right text-slate-700">{r.avg_monthly_demand.toFixed(1)}</td>
                      <td className="py-2 pr-4 text-right text-xs" style={{ color: r.cv_hist > 1 ? "#EF4444" : r.cv_hist > 0.5 ? "#F97316" : "#2CC56F" }}>{r.cv_hist.toFixed(2)}</td>
                      <td className="py-2 pr-4 text-right text-slate-600 font-medium">{r.forecast_lt.toFixed(1)}</td>
                      <td className="py-2 pr-4 text-right text-slate-700">{r.forecast_m1.toFixed(1)}</td>
                      <td className="py-2 pr-4 text-right text-slate-700">{r.forecast_m2.toFixed(1)}</td>
                      <td className="py-2 text-right text-slate-700">{r.forecast_m3.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filtered.length > 100 && <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {filtered.length}</p>}
            </div>
          </div>
        </>
      )}

      {/* ════════════════════════════════════════════════════
          TAB: History + Fleet Blend
      ════════════════════════════════════════════════════ */}
      {tab === "fused" && (
        <>
          {!fusedData ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
              <p className="text-sm font-semibold text-amber-700 mb-1">Published blended forecast unavailable</p>
              <code className="text-xs text-amber-600 bg-amber-100 px-2 py-1 rounded">
                Refresh after the forecast pipeline has completed.
              </code>
            </div>
          ) : (
            <>
              {/* KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="Forecast SKUs" value={fusedData.total.toLocaleString()} color="blue"/>
                <KpiCard label="Methods"            value={`${Object.keys(fusedData.method_counts).length}`} color="teal"/>
                <KpiCard label="Demand Classes"     value={`${fusedData.demand_class_counts ? Object.keys(fusedData.demand_class_counts).length : "—"}`} color="purple"/>
                <KpiCard label="Showing"            value={`${Math.min(fusedFiltered.length, 100)} rows`} sub="use filters to narrow" color="amber"/>
              </div>

              {/* Method bar chart + demand class donut */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-white rounded-xl shadow-sm p-5">
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">SKUs per Fusion Method</h3>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={fusedMethodBarData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false}/>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }}/>
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt} width={40}/>
                      <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                      <Bar dataKey="value" name="SKU-months" radius={[4, 4, 0, 0]}>
                        {fusedMethodBarData.map(d => <Cell key={d.name} fill={d.fill}/>)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {fusedMethodBarData.map(d => (
                      <span key={d.name} className="flex items-center gap-1 text-xs text-slate-500">
                        <span className="w-2 h-2 rounded-full inline-block" style={{ background: d.fill }}/>
                        {d.name}: {d.value.toLocaleString()}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="bg-white rounded-xl shadow-sm p-5">
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">Demand Class Distribution</h3>
                  {fusedData.demand_class_counts && Object.keys(fusedData.demand_class_counts).length > 0 ? (
                    <>
                      <ResponsiveContainer width="100%" height={180}>
                        <PieChart>
                          <Pie
                            data={Object.entries(fusedData.demand_class_counts).map(([k, v]) => ({ name: k, value: v, fill: DC_COLORS[k] ?? "#94A3B8" }))}
                            cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                            dataKey="value" nameKey="name"
                          >
                            {Object.entries(fusedData.demand_class_counts).map(([k]) => (
                              <Cell key={k} fill={DC_COLORS[k] ?? "#94A3B8"}/>
                            ))}
                          </Pie>
                          <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="flex flex-wrap gap-2 mt-1">
                        {Object.entries(fusedData.demand_class_counts).map(([k, v]) => (
                          <span key={k} className="flex items-center gap-1 text-xs text-slate-500">
                            <span className="w-2 h-2 rounded-full inline-block" style={{ background: DC_COLORS[k] ?? "#94A3B8" }}/>
                            {k}: {v.toLocaleString()}
                          </span>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-xs text-slate-400 mt-8 text-center">No demand class data in this slice</p>
                  )}
                </div>
              </div>

              {/* Filter bar + table */}
              <div className="bg-white rounded-xl shadow-sm p-5">
                <div className="flex gap-3 mb-4 flex-wrap">
                  <input
                    className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[160px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                    placeholder="Filter by part no…"
                    value={fusedSearch} onChange={e => setFusedSearch(e.target.value)}
                  />
                  <select
                    className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
                    value={fusedMethod} onChange={e => setFusedMethod(e.target.value)}
                  >
                    <option value="">All methods</option>
                    {Object.keys(fusedData.method_counts).map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                  {fusedData.demand_class_counts && (
                    <select
                      className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
                      value={fusedDC} onChange={e => setFusedDC(e.target.value)}
                    >
                      <option value="">All classes</option>
                      {Object.keys(fusedData.demand_class_counts).map(dc => <option key={dc} value={dc}>{dc}</option>)}
                    </select>
                  )}
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                        <th className="py-2 pr-4">Part No</th>
                        <th className="py-2 pr-4">Month</th>
                        <th className="py-2 pr-4 text-right">Demand Qty</th>
                        <th className="py-2 pr-4">Method</th>
                        <th className="py-2 pr-4 text-right">CV</th>
                        <th className="py-2">Demand Class</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fusedFiltered.slice(0, 100).map((r, i) => (
                        <tr key={`${r.part_no}-${r.month}-${i}`} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="py-1.5 pr-4 font-mono text-xs text-slate-700">{r.part_no}</td>
                          <td className="py-1.5 pr-4 text-xs text-slate-500">{r.month}</td>
                          <td className="py-1.5 pr-4 text-right font-medium text-slate-700">{r.demand_qty.toFixed(1)}</td>
                          <td className="py-1.5 pr-4">
                            <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-100 px-2 py-0.5 rounded-full">{r.method}</span>
                          </td>
                          <td className="py-1.5 pr-4 text-right text-xs"
                            style={{ color: r.cv != null ? (r.cv > 1 ? "#EF4444" : r.cv > 0.5 ? "#F97316" : "#2CC56F") : "#94A3B8" }}>
                            {r.cv != null ? r.cv.toFixed(2) : "—"}
                          </td>
                          <td className="py-1.5">
                            <span className="text-xs px-2 py-0.5 rounded-full font-semibold"
                              style={{ background: `${DC_COLORS[r.demand_class] ?? "#94A3B8"}20`, color: DC_COLORS[r.demand_class] ?? "#64748B" }}>
                              {r.demand_class}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {fusedFiltered.length > 100 && (
                    <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {fusedFiltered.length} — use filters to narrow</p>
                  )}
                  {fusedFiltered.length === 0 && (
                    <p className="text-xs text-slate-400 mt-4 text-center">No rows match the current filters</p>
                  )}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
