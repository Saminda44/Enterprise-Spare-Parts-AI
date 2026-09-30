import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  fetchInventory, fetchCoverageHistogram,
  type InventoryRow,
} from "../api/client";
import { POLICY_COLORS as TIER_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "./KpiCard";

const STATUS_COLOR:  Record<string, string> = {
  stockout: "#EF4444", awaiting_stock: "#EC4899", critical: "#F97316", low: "#FFC107", ok: "#2CC56F",
  excess: "#4361EE", no_demand: "#7C3AED", dormant: "#CBD5E1", not_assessed: "#E2E8F0",
};
const STATUS_TEXT: Record<string, string> = {
  stockout: "Stockout", awaiting_stock: "Awaiting stock", critical: "Critical", ok: "OK", excess: "Excess",
  no_demand: "No demand", dormant: "Dormant", not_assessed: "Not stocked",
};

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type InventoryData = {
  total: number; rows: InventoryRow[]; status_counts: Record<string, number>;
  classified_count: number; stock_snapshot_count: number; unassessed_count: number;
  total_value_lkr: number; excess_value_lkr: number;
  on_order_units?: number; on_hand_units?: number;
  planning: { lead_time_months: number };
  stockout_regular?: number;   // zero stock and ≥1 unit/month of demand
};

export function InventoryStatusTab() {
  const [invData,   setInvData]   = useState<InventoryData | null>(null);
  const [hist,      setHist]      = useState<{ bin_start: number; bin_end: number; count: number }[]>([]);
  const [invStatus, setInvStatus] = useState("");
  const [invSearch, setInvSearch] = useState("");
  const [page,      setPage]      = useState(0);

  useEffect(() => {
    fetchCoverageHistogram().then(setHist);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchInventory({ status: invStatus || undefined, search: invSearch || undefined, limit: 100, offset: page * 100 }).then(setInvData);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [invStatus, invSearch, page]);

  useEffect(() => { setPage(0); }, [invStatus, invSearch]);


  if (!invData) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Part Master SKUs" value={fmt(invData.total)}                       color="blue"/>
        <KpiCard label="Valued Stock" value={`LKR ${fmt(invData.total_value_lkr)}`} sub="Demand-classified SKUs" color="green"/>
        <KpiCard label="Stockout" value={fmt(invData.status_counts.stockout ?? 0)}
          sub={`shelf empty, nothing on order · ${fmt(invData.status_counts.awaiting_stock ?? 0)} more empty but an order is coming`} color="red"/>
        <KpiCard label="Excess Value" value={`LKR ${fmt(invData.excess_value_lkr)}`}      sub=">12 months coverage"   color="amber"/>
      </div>

      <p className="text-xs text-slate-500 -mt-2">
        Status uses <b>stock on hand + stock on order</b>: current_stock.xlsx (PDC W1B4) plus On_Orders.xlsx, Yamaha motorcycle (YM)
        and outboard (OB) parts only — {fmt(invData.on_hand_units ?? 0)} on hand + {fmt(invData.on_order_units ?? 0)} on order.
        Cover = (on hand + on order) ÷ the monthly forecast — the same demand the Demand Forecast and Order Plan pages show. <b>Stockout</b>: empty and nothing coming · <b>Awaiting stock</b>: empty,
        order on the way · <b>Critical</b>: under 1 month · <b>OK</b>: 1–12 months · <b>Excess</b>: over 12 months ·
        <b> No demand</b>: stock for a part dealers never ordered.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Status Breakdown (stock + on order)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={Object.entries(invData.status_counts).filter(([k]) => k !== "not_assessed").map(([k,v]) => ({ name: STATUS_TEXT[k] ?? k, key: k, value: v }))} margin={{ top:5, right:10, left:0, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4,4,0,0]}>
                {Object.keys(invData.status_counts).filter(k => k !== "not_assessed").map(k => <Cell key={k} fill={STATUS_COLOR[k] ?? "#94A3B8"}/>)}
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
            <span>— {invData.planning.lead_time_months} mo = lead time</span>
            <span>— 12 mo = excess threshold</span>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <p className="text-xs text-slate-500 mb-3">
          {invData.classified_count.toLocaleString()} parts with dealer demand · {invData.stock_snapshot_count.toLocaleString()} with stock or on order ·
          {" "}{(invData.status_counts.not_assessed ?? 0).toLocaleString()} not stocked (no stock, no order, no demand)
        </p>
        <div className="flex flex-wrap gap-1.5 mb-3">
          {["", "stockout", "awaiting_stock", "critical", "ok", "excess", "no_demand", "dormant", "not_assessed"].map(s => {
            const n = s ? (invData.status_counts[s] ?? 0) : Object.values(invData.status_counts).reduce((a, b) => a + b, 0);
            if (s && !n) return null;
            const active = invStatus === s;
            return (
              <button key={s || "all"} onClick={() => setInvStatus(s)}
                className={`text-xs px-3 py-1 rounded-full border font-medium transition-colors ${active ? "text-white border-transparent" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}
                style={active ? { background: s ? (STATUS_COLOR[s] ?? "#64748B") : "#334155", color: ["not_assessed", "dormant"].includes(s) ? "#334155" : undefined } : undefined}>
                {s ? STATUS_TEXT[s] ?? s : "All"} {n.toLocaleString()}
              </button>
            );
          })}
        </div>
        <div className="flex gap-3 mb-4 flex-wrap">
          <input
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
            placeholder="Search SKU or description…" value={invSearch} onChange={e => setInvSearch(e.target.value)}
          />
        </div>
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-white">
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">SKU</th><th className="py-2 pr-3">Description</th>
                    <th className="py-2 pr-3">Brand</th><th className="py-2 pr-3">Policy</th>
                    <th className="py-2 pr-3 text-right">On hand</th><th className="py-2 pr-3 text-right">On order</th>
                    <th className="py-2 pr-3 text-right">Stock + order</th>
                    <th className="py-2 pr-3 text-right" title="Monthly demand the cover is measured against">Demand / mo</th>
                    <th className="py-2 pr-3 text-right" title="(on hand + on order) ÷ monthly demand">Cover (mo)</th>
                    <th className="py-2 pr-3 text-right">Stock value (LKR)</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {invData.rows.map((r: InventoryRow) => (
                    <tr key={r.active_sku_id} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 font-mono text-xs text-slate-700" title={r.superseded_numbers || undefined}>{r.active_sku_id}{r.alias_count > 1 && <span className="block text-[10px] text-slate-400">+{r.alias_count - 1} prior</span>}</td>
                      <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                      <td className="py-2 pr-3 text-xs text-slate-500">{r.brand || "-"}</td>
                      <td className="py-2 pr-3">{r.has_planning ? <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span> : "-"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{r.stock_on_hand != null ? Math.round(r.stock_on_hand).toLocaleString() : "-"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-pink-600">{r.on_order ? Math.round(r.on_order).toLocaleString() : <span className="text-slate-300">0</span>}</td>
                      <td className="py-2 pr-3 text-right tabular-nums font-semibold">{r.position_qty != null ? Math.round(r.position_qty).toLocaleString() : "-"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-slate-500">{r.cover_demand_monthly != null ? (r.cover_demand_monthly >= 10 ? Math.round(r.cover_demand_monthly).toLocaleString() : r.cover_demand_monthly.toFixed(1)) : "-"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{r.has_planning ? (r.coverage_months == null ? "-" : r.coverage_months >= 999 ? "∞" : r.coverage_months.toFixed(1)) : "-"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{r.has_planning && r.stock_value_lkr != null ? fmt(r.stock_value_lkr) : "-"}</td>
                      <td className="py-2"><span className="text-xs px-2 py-0.5 rounded-full font-medium text-white whitespace-nowrap" style={{ background: STATUS_COLOR[r.stock_status] ?? "#94A3B8", color: ["not_assessed", "dormant"].includes(r.stock_status) ? "#475569" : undefined }}>{STATUS_TEXT[r.stock_status] ?? r.stock_status.replaceAll("_", " ")}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-between items-center pt-3 text-xs text-slate-500">
              <span>{invData.total ? `${page * 100 + 1}-${Math.min((page + 1) * 100, invData.total)} of ${invData.total.toLocaleString()}` : "No matching parts"}</span>
              <div className="flex gap-2"><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * 100 >= invData.total} onClick={() => setPage(page + 1)}>Next</button></div>
            </div>
      </div>
    </div>
  );
}
