import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import {
  fetchBikeDealers, fetchCrosstab,
  type DealersData, type CrosstabData,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";

const PROV_COLORS = ["#4361EE","#7C3AED","#2CC56F","#F97316","#EF4444","#06B6D4","#FFC107","#10B981","#EC4899","#94A3B8"];

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

export function BikeEDA() {
  const [dealers,  setDealers]  = useState<DealersData | null>(null);
  const [crosstab, setCrosstab] = useState<CrosstabData | null>(null);
  const [search,   setSearch]   = useState("");
  const [year,     setYear]     = useState<number | undefined>(undefined);

  useEffect(() => {
    fetchBikeDealers(500, year).then(setDealers);
    fetchCrosstab(year).then(setCrosstab);
  }, [year]);

  const filteredDealers = dealers?.rows.filter(r =>
    !search || [r.province, r.rm, r.ase, r.dealer].some(v => v.toLowerCase().includes(search.toLowerCase()))
  ) ?? [];

  // Province-level aggregation for bar chart
  const provinceData = (() => {
    if (!dealers) return [];
    const map: Record<string, { units: number; revenue: number }> = {};
    for (const r of dealers.rows) {
      if (!map[r.province]) map[r.province] = { units: 0, revenue: 0 };
      map[r.province].units   += r.units_sold;
      map[r.province].revenue += r.revenue_lkr;
    }
    return Object.entries(map)
      .map(([province, v]) => ({ province, ...v }))
      .sort((a, b) => b.units - a.units);
  })();

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-bold text-slate-800">Motorcycle EDA — Dealer Performance</h2>
          <p className="text-xs text-slate-500 mt-0.5">Step 09 · Province → RM → ASE → Dealer hierarchy · Units sold &amp; revenue</p>
        </div>
        {dealers && dealers.available_years.length > 0 && (
          <select
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
            value={year ?? ""}
            onChange={e => setYear(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">All years</option>
            {dealers.available_years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
      </div>

      {dealers ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <KpiCard label="Total Dealers"  value={dealers.total_dealers.toLocaleString()} color="blue" sub={year ? `Year ${year}` : "All years"}/>
            <KpiCard label="Total Units"    value={fmt(dealers.total_units)}               color="green"/>
            <KpiCard label="Total Revenue"  value={`LKR ${fmt(dealers.total_revenue_lkr)}`} color="purple"/>
          </div>

          {/* Province bar chart */}
          <div className="bg-white rounded-xl shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">Units Sold by Province</h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={provinceData} margin={{ top:5, right:10, left:0, bottom:0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                <XAxis dataKey="province" tick={{ fontSize: 11 }}/>
                <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                <Bar dataKey="units" name="Units Sold" radius={[4,4,0,0]}>
                  {provinceData.map((d, i) => <Cell key={d.province} fill={PROV_COLORS[i % PROV_COLORS.length]}/>)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Dealer table */}
          <div className="bg-white rounded-xl shadow-sm p-5 space-y-4">
            <div className="flex items-center gap-3">
              <input
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 max-w-xs focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search dealer, RM, ASE, province…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              <span className="text-xs text-slate-400">{filteredDealers.length} dealers</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">Province</th>
                    <th className="py-2 pr-3">RM</th>
                    <th className="py-2 pr-3">ASE</th>
                    <th className="py-2 pr-3">Dealer</th>
                    <th className="py-2 pr-3">Code</th>
                    <th className="py-2 pr-3 text-right">Units</th>
                    <th className="py-2 text-right">Revenue (LKR)</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDealers.slice(0, 200).map((r, i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 text-xs font-medium text-slate-700">{r.province}</td>
                      <td className="py-2 pr-3 text-xs text-slate-500">{r.rm}</td>
                      <td className="py-2 pr-3 text-xs text-slate-500">{r.ase}</td>
                      <td className="py-2 pr-3 text-xs text-slate-800 font-medium max-w-[180px] truncate" title={r.dealer}>{r.dealer}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-slate-400">{r.dealer_code}</td>
                      <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                      <td className="py-2 text-right text-slate-700">{fmt(r.revenue_lkr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filteredDealers.length > 200 && (
                <p className="text-xs text-slate-400 mt-2 text-center">Showing 200 of {filteredDealers.length}</p>
              )}
            </div>
          </div>

          {/* Province × Model crosstab */}
          {crosstab && crosstab.models.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Province × Model Sales Matrix</h3>
              <div className="overflow-x-auto">
                <table className="text-xs w-full">
                  <thead>
                    <tr className="border-b border-slate-100 text-slate-500 uppercase">
                      <th className="py-2 pr-3 text-left">Province</th>
                      {crosstab.models.map(m => <th key={m} className="py-2 px-2 text-right">{m}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {crosstab.rows.map(r => (
                      <tr key={r.province} className="border-b border-slate-50 hover:bg-slate-50/50">
                        <td className="py-2 pr-3 font-medium text-slate-700">{r.province}</td>
                        {crosstab.models.map(m => (
                          <td key={m} className="py-2 px-2 text-right"
                            style={{ color: (r.totals[m] ?? 0) === 0 ? "#CBD5E1" : "#1E293B" }}>
                            {(r.totals[m] ?? 0).toLocaleString()}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>
      )}
    </div>
  );
}
