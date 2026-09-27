import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  fetchInventory, fetchCoverageHistogram, fetchAtRisk, fetchExcess,
  type InventoryRow, type AtRiskRow, type ExcessRow,
} from "../api/client";
import { POLICY_COLORS as TIER_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "./KpiCard";

const STATUS_COLOR:  Record<string, string> = { stockout: "#EF4444", critical: "#F97316", low: "#FFC107", ok: "#2CC56F", excess: "#4361EE" };
const URGENCY_COLOR: Record<string, string> = { immediate: "#EF4444", soon: "#FFC107", planned: "#4361EE", none: "#94A3B8" };

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type InvTab = "all" | "at-risk" | "excess";
type InventoryData = {
  total: number; rows: InventoryRow[]; status_counts: Record<string, number>;
  total_value_lkr: number; excess_value_lkr: number;
  stockout_regular?: number;   // zero stock and ≥1 unit/month of demand
};

export function InventoryStatusTab() {
  const [invData,   setInvData]   = useState<InventoryData | null>(null);
  const [hist,      setHist]      = useState<{ bin_start: number; bin_end: number; count: number }[]>([]);
  const [atRisk,    setAtRisk]    = useState<AtRiskRow[]>([]);
  const [excess,    setExcess]    = useState<ExcessRow[]>([]);
  const [invStatus, setInvStatus] = useState("");
  const [invSearch, setInvSearch] = useState("");
  const [invTab,    setInvTab]    = useState<InvTab>("all");

  useEffect(() => {
    fetchCoverageHistogram().then(setHist);
    fetchAtRisk(50).then(setAtRisk);
    fetchExcess(100).then(setExcess);
  }, []);
  useEffect(() => {
    fetchInventory({ status: invStatus || undefined, limit: 500 }).then(setInvData);
  }, [invStatus]);

  const invFiltered = invData?.rows.filter(r =>
    !invSearch ||
    r.material_9.toLowerCase().includes(invSearch.toLowerCase()) ||
    r.description.toLowerCase().includes(invSearch.toLowerCase())
  ) ?? [];

  const INV_TABS: { key: InvTab; label: string }[] = [
    { key: "all",     label: `All (${invData?.total.toLocaleString() ?? "…"})` },
    { key: "at-risk", label: `At Risk (${atRisk.length})` },
    { key: "excess",  label: `Excess (${excess.length})` },
  ];

  if (!invData) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total SKUs"   value={fmt(invData.total)}                          color="blue"/>
        <KpiCard label="Stock Value"  value={`LKR ${fmt(invData.total_value_lkr)}`}       color="green"/>
        <KpiCard label="Zero stock"   value={fmt(invData.status_counts.stockout ?? 0)}    sub={`${fmt(invData.stockout_regular ?? 0)} with ≥1/month demand need ordering · rest are slow movers`} color="red"/>
        <KpiCard label="Excess Value" value={`LKR ${fmt(invData.excess_value_lkr)}`}      sub=">12 months coverage"   color="amber"/>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Status Breakdown</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={Object.entries(invData.status_counts).map(([k,v]) => ({ name: k, value: v }))} margin={{ top:5, right:10, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {Object.keys(invData.status_counts).map(k => <Cell key={k} fill={STATUS_COLOR[k] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Stock Coverage Distribution (months)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={hist.map(b => ({ name: b.bin_start.toFixed(1), count: b.count }))} margin={{ top:5, right:10, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={7}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()} labelFormatter={l => `${l} months`}/>
              <Bar dataKey="count" fill="#4361EE" radius={[2,2,0,0]}/>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex gap-4 mt-1 text-xs text-slate-400">
            <span>— 3 mo = lead time</span>
            <span>— 6 mo = excess threshold</span>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex gap-1 mb-4 border-b border-slate-100 pb-2">
          {INV_TABS.map(t => (
            <button key={t.key} onClick={() => setInvTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${invTab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              {t.label}
            </button>
          ))}
        </div>

        {invTab === "all" && (
          <>
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search SKU or description…" value={invSearch} onChange={e => setInvSearch(e.target.value)}
              />
              <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={invStatus} onChange={e => setInvStatus(e.target.value)}>
                <option value="">All statuses</option>
                {Object.keys(invData.status_counts).map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">SKU</th><th className="py-2 pr-3">Description</th>
                    <th className="py-2 pr-3">Policy</th><th className="py-2 pr-3">Method</th>
                    <th className="py-2 pr-3 text-right">Stock</th><th className="py-2 pr-3 text-right">Value (LKR)</th>
                    <th className="py-2 pr-3 text-right">Coverage (mo)</th><th className="py-2 pr-3 text-right">Post-Order Cov.</th>
                    <th className="py-2 pr-3 text-right">Receipts</th><th className="py-2 pr-3 text-right">Issues</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {invFiltered.slice(0, 100).map((r: InventoryRow) => (
                    <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                      <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                      <td className="py-2 pr-3"><span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span></td>
                      <td className="py-2 pr-3 text-xs text-slate-400">{r.method}</td>
                      <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                      <td className="py-2 pr-3 text-right">{fmt(r.stock_value_lkr)}</td>
                      <td className="py-2 pr-3 text-right">{r.coverage_months === 999 ? "∞" : r.coverage_months.toFixed(1)}</td>
                      <td className="py-2 pr-3 text-right font-semibold" style={{ color: (() => { if (r.avg_monthly_demand <= 0) return "#94A3B8"; const c = (r.stock_on_hand + r.forecast_lt) / r.avg_monthly_demand; return c < 3 ? "#EF4444" : c < 6 ? "#F97316" : "#2CC56F"; })() }}>
                        {r.avg_monthly_demand <= 0 ? "—" : (() => { const c = (r.stock_on_hand + r.forecast_lt) / r.avg_monthly_demand; return c > 900 ? "∞" : c.toFixed(1); })()}
                      </td>
                      <td className="py-2 pr-3 text-right">{r.total_receipts.toFixed(0)}</td>
                      <td className="py-2 pr-3 text-right">{r.total_issues.toFixed(0)}</td>
                      <td className="py-2"><span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: STATUS_COLOR[r.stock_status] ?? "#94A3B8" }}>{r.stock_status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {invFiltered.length > 100 && <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {invFiltered.length.toLocaleString()}</p>}
            </div>
          </>
        )}

        {invTab === "at-risk" && (
          <div className="overflow-x-auto">
            <p className="text-xs text-slate-500 mb-3">Top {atRisk.length} SKUs with immediate or soon order urgency, sorted by net requirement descending.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                  <th className="py-2 pr-3">SKU</th><th className="py-2 pr-3">Description</th>
                  <th className="py-2 pr-3">ABC</th><th className="py-2 pr-3">Policy</th>
                  <th className="py-2 pr-3 text-right">Stock</th><th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3 text-right">Coverage (mo)</th><th className="py-2 pr-3 text-right">Final Qty</th>
                  <th className="py-2 pr-3 text-right">Unit Value (LKR)</th><th className="py-2">Urgency</th>
                </tr>
              </thead>
              <tbody>
                {atRisk.map((r: AtRiskRow) => (
                  <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                    <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                    <td className="py-2 pr-3"><span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: r.abc === "A" ? "#EF4444" : r.abc === "B" ? "#FFC107" : "#2CC56F" }}>{r.abc}</span></td>
                    <td className="py-2 pr-3"><span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span></td>
                    <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                    <td className="py-2 pr-3"><span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: STATUS_COLOR[r.stock_status] ?? "#94A3B8" }}>{r.stock_status}</span></td>
                    <td className="py-2 pr-3 text-right">{r.coverage_months.toFixed(1)}</td>
                    <td className="py-2 pr-3 text-right font-bold text-red-600">{r.net_requirement.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right">{r.unit_value_lkr.toFixed(0)}</td>
                    <td className="py-2"><span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: URGENCY_COLOR[r.order_urgency] ?? "#94A3B8" }}>{r.order_urgency}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {invTab === "excess" && (
          <div className="overflow-x-auto">
            <p className="text-xs text-slate-500 mb-3">Top {excess.length} SKUs with excess stock (&gt;12 months coverage), sorted by stock value descending.</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                  <th className="py-2 pr-3">SKU</th><th className="py-2 pr-3">Description</th>
                  <th className="py-2 pr-3">ABC</th><th className="py-2 pr-3">Policy</th>
                  <th className="py-2 pr-3 text-right">Stock QTY</th><th className="py-2 pr-3 text-right">Value (LKR)</th>
                  <th className="py-2 pr-3 text-right">Coverage (mo)</th><th className="py-2 text-right">Avg Demand</th>
                </tr>
              </thead>
              <tbody>
                {excess.map((r: ExcessRow) => (
                  <tr key={r.material_9} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                    <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                    <td className="py-2 pr-3"><span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: r.abc === "A" ? "#EF4444" : r.abc === "B" ? "#FFC107" : "#2CC56F" }}>{r.abc}</span></td>
                    <td className="py-2 pr-3"><span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span></td>
                    <td className="py-2 pr-3 text-right">{r.stock_on_hand.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right font-semibold text-amber-500">{fmt(r.stock_value_lkr)}</td>
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
