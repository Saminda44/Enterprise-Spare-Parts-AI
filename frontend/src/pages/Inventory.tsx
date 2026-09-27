import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  fetchInventory, fetchCoverageHistogram, fetchAtRisk, fetchExcess, fetchStockByLocation,
  type InventoryRow, type AtRiskRow, type ExcessRow, type LocationRow,
} from "../api/client";
import { POLICY_COLORS as TIER_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "../components/KpiCard";

const STATUS_COLOR: Record<string, string> = {
  stockout: "#EF4444", critical: "#F97316", low: "#FFC107", ok: "#2CC56F", excess: "#4361EE",
};
const URGENCY_COLOR: Record<string, string> = { immediate: "#EF4444", soon: "#FFC107", planned: "#4361EE", none: "#94A3B8" };

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type Tab = "all" | "at-risk" | "excess";

export function Inventory() {
  const [searchParams] = useSearchParams();
  const [data, setData]       = useState<{ total: number; rows: InventoryRow[]; status_counts: Record<string, number>; total_value_lkr: number; excess_value_lkr: number } | null>(null);
  const [hist, setHist]       = useState<{ bin_start: number; bin_end: number; count: number }[]>([]);
  const [atRisk, setAtRisk]   = useState<AtRiskRow[]>([]);
  const [excess, setExcess]   = useState<ExcessRow[]>([]);
  const [locations, setLocations] = useState<LocationRow[]>([]);
  const [status, setStatus]   = useState(searchParams.get("status") ?? "");
  const [search, setSearch]   = useState("");
  const [tab, setTab]         = useState<Tab>(searchParams.get("status") === "excess" ? "excess" : searchParams.get("status") === "stockout" ? "at-risk" : "all");

  useEffect(() => {
    fetchInventory({ limit: 500 }).then(setData);
    fetchCoverageHistogram().then(setHist);
    fetchAtRisk(50).then(setAtRisk);
    fetchExcess(100).then(setExcess);
    fetchStockByLocation().then(setLocations).catch(() => setLocations([]));
  }, []);

  useEffect(() => { fetchInventory({ status: status || undefined, limit: 500 }).then(setData); }, [status]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const statusBar = Object.entries(data.status_counts).map(([k, v]) => ({ name: k, value: v }));
  const histData  = hist.map(b => ({ name: b.bin_start.toFixed(1), count: b.count }));

  const filtered = data.rows.filter(r =>
    !search || r.material_9.toLowerCase().includes(search.toLowerCase()) || r.description.toLowerCase().includes(search.toLowerCase())
  );

  const TABS: { key: Tab; label: string }[] = [
    { key: "all",     label: `All (${data.total.toLocaleString()})` },
    { key: "at-risk", label: `At Risk (${atRisk.length})` },
    { key: "excess",  label: `Excess (${excess.length})` },
  ];

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <h2 className="text-xl font-bold text-slate-800">PDC Inventory Status</h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total SKUs"     value={fmt(data.total)}                         color="blue"/>
        <KpiCard label="Stock Value"    value={`LKR ${fmt(data.total_value_lkr)}`}      color="green"/>
        <KpiCard label="Stockout"       value={fmt(data.status_counts.stockout ?? 0)}   sub="Need immediate order" color="red"/>
        <KpiCard label="Excess Value"   value={`LKR ${fmt(data.excess_value_lkr)}`}     sub=">12 months coverage"   color="amber"/>
      </div>

      {locations.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-1">Stock by Plant</h3>
          <p className="text-xs text-slate-400 mb-4">
            Only PDC plant W1B4 contributes to planning stock. Other plants are shown for visibility.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Horizontal bar chart — qty */}
            <div>
              <p className="text-xs text-slate-500 mb-2 font-medium">Unrestricted Qty by Plant</p>
              <ResponsiveContainer width="100%" height={Math.max(160, locations.length * 28)}>
                <BarChart
                  data={locations}
                  layout="vertical"
                  margin={{ top: 0, right: 16, left: 0, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                  <YAxis type="category" dataKey="description" tick={{ fontSize: 10 }} width={120}/>
                  <Tooltip
                    formatter={(v: unknown, _name: unknown, p: { payload?: LocationRow }) =>
                      [`${Number(v).toLocaleString()} units`, p.payload?.is_excluded ? "Excluded" : "Active"]
                    }
                  />
                  <Bar dataKey="qty" radius={[0, 3, 3, 0]}>
                    {locations.map(loc => (
                      <Cell key={loc.description} fill={loc.is_excluded ? "#F59E0B" : "#4361EE"}/>
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-slate-500 uppercase">
                    <th className="py-1.5 pr-3">Plant</th>
                    <th className="py-1.5 pr-3 text-right">Qty</th>
                    <th className="py-1.5 pr-3 text-right">Value (LKR)</th>
                    <th className="py-1.5 pr-3 text-right">SKUs</th>
                    <th className="py-1.5">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {locations.map(loc => (
                    <tr
                      key={loc.description}
                      className={`border-b border-slate-50 ${loc.is_excluded ? "bg-amber-50/60" : ""}`}
                    >
                      <td className="py-1.5 pr-3 font-mono text-slate-700 max-w-[140px] truncate" title={loc.description}>
                        {loc.description}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{loc.qty.toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-right">{loc.value_lkr == null ? "Unavailable" : fmt(loc.value_lkr)}</td>
                      <td className="py-1.5 pr-3 text-right">{loc.sku_count == null ? "Unavailable" : loc.sku_count.toLocaleString()}</td>
                      <td className="py-1.5">
                        {loc.is_excluded
                          ? <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">excluded</span>
                          : <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700">active</span>
                        }
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Status Breakdown</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={statusBar} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {statusBar.map(d => <Cell key={d.name} fill={STATUS_COLOR[d.name] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Stock Coverage Distribution (months, active SKUs &lt;24 mo)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={histData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={7}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()} labelFormatter={l => `${l} months`}/>
              <Bar dataKey="count" fill="#4361EE" radius={[2, 2, 0, 0]}/>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex gap-4 mt-1 text-xs text-slate-400">
            <span>— 3 mo = lead time</span>
            <span>— 6 mo = excess threshold</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex gap-1 mb-4 border-b border-slate-100 pb-2">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${tab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "all" && (
          <>
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search SKU or description…" value={search} onChange={e => setSearch(e.target.value)}
              />
              <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={status} onChange={e => setStatus(e.target.value)}>
                <option value="">All statuses</option>
                {Object.keys(data.status_counts).map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">SKU</th>
                    <th className="py-2 pr-3">Description</th>
                    <th className="py-2 pr-3">Policy</th>
                    <th className="py-2 pr-3">Method</th>
                    <th className="py-2 pr-3 text-right">Stock</th>
                    <th className="py-2 pr-3 text-right">Value (LKR)</th>
                    <th className="py-2 pr-3 text-right">Coverage (mo)</th>
                    <th className="py-2 pr-3 text-right">Post-Order Cov.</th>
                    <th className="py-2 pr-3 text-right">Receipts</th>
                    <th className="py-2 pr-3 text-right">Issues</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 100).map(r => (
                    <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                      <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                      <td className="py-2 pr-3">
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                      </td>
                      <td className="py-2 pr-3 text-xs text-slate-400">{r.method}</td>
                      <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(r.stock_value_lkr)}</td>
                      <td className="py-2 pr-3 text-right">{r.coverage_months === 999 ? "∞" : r.coverage_months.toFixed(1)}</td>
                      <td className="py-2 pr-3 text-right font-semibold" style={{
                        color: (() => {
                          if (r.avg_monthly_demand <= 0) return "#94A3B8";
                          const cov = (r.stock_on_hand + r.forecast_lt) / r.avg_monthly_demand;
                          return cov < 3 ? "#EF4444" : cov < 6 ? "#F97316" : "#2CC56F";
                        })()
                      }}>
                        {r.avg_monthly_demand <= 0 ? "—" :
                          (() => { const c = (r.stock_on_hand + r.forecast_lt) / r.avg_monthly_demand; return c > 900 ? "∞" : c.toFixed(1); })()}
                      </td>
                      <td className="py-2 pr-3 text-right">{r.total_receipts.toFixed(0)}</td>
                      <td className="py-2 pr-3 text-right">{r.total_issues.toFixed(0)}</td>
                      <td className="py-2">
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: STATUS_COLOR[r.stock_status] ?? "#94A3B8" }}>{r.stock_status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filtered.length > 100 && <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {filtered.length.toLocaleString()}</p>}
            </div>
          </>
        )}

        {tab === "at-risk" && (
          <div className="overflow-x-auto">
            <p className="text-xs text-slate-500 mb-3">Top {atRisk.length} SKUs with immediate or soon order urgency, sorted by net requirement descending.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                  <th className="py-2 pr-3">SKU</th>
                  <th className="py-2 pr-3">Description</th>
                  <th className="py-2 pr-3">ABC</th>
                  <th className="py-2 pr-3">Policy</th>
                  <th className="py-2 pr-3 text-right">Stock</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3 text-right">Coverage (mo)</th>
                  <th className="py-2 pr-3 text-right">Final Qty</th>
                  <th className="py-2 pr-3 text-right">Unit Value (LKR)</th>
                  <th className="py-2">Urgency</th>
                </tr>
              </thead>
              <tbody>
                {atRisk.map(r => (
                  <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                    <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: r.abc === "A" ? "#EF4444" : r.abc === "B" ? "#FFC107" : "#2CC56F" }}>{r.abc}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                    </td>
                    <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: STATUS_COLOR[r.stock_status] ?? "#94A3B8" }}>{r.stock_status}</span>
                    </td>
                    <td className="py-2 pr-3 text-right">{r.coverage_months.toFixed(1)}</td>
                    <td className="py-2 pr-3 text-right font-bold text-red-600">{r.net_requirement.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right">{r.unit_value_lkr.toFixed(0)}</td>
                    <td className="py-2">
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: URGENCY_COLOR[r.order_urgency] ?? "#94A3B8" }}>{r.order_urgency}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "excess" && (
          <div className="overflow-x-auto">
            <p className="text-xs text-slate-500 mb-3">Top {excess.length} SKUs with excess stock (&gt;12 months coverage), sorted by stock value descending.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                  <th className="py-2 pr-3">SKU</th>
                  <th className="py-2 pr-3">Description</th>
                  <th className="py-2 pr-3">ABC</th>
                  <th className="py-2 pr-3">Policy</th>
                  <th className="py-2 pr-3 text-right">Stock QTY</th>
                  <th className="py-2 pr-3 text-right">Value (LKR)</th>
                  <th className="py-2 pr-3 text-right">Coverage (mo)</th>
                  <th className="py-2 text-right">Avg Demand</th>
                </tr>
              </thead>
              <tbody>
                {excess.map(r => (
                  <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                    <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: r.abc === "A" ? "#EF4444" : r.abc === "B" ? "#FFC107" : "#2CC56F" }}>{r.abc}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                    </td>
                    <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right font-semibold text-brand-amber">{fmt(r.stock_value_lkr)}</td>
                    <td className="py-2 pr-3 text-right">{r.coverage_months > 900 ? "∞" : r.coverage_months.toFixed(1)}</td>
                    <td className="py-2 text-right">{r.avg_monthly_demand.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
