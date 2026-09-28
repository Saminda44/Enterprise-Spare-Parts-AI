import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  ComposedChart, Line, Legend,
} from "recharts";
import {
  fetchMcsiEda, fetchOverview, fetchOrdersEda, fetchSalesEda,
  type McsiEdaData, type OverviewData, type OrdersEdaData, type SalesEdaData,
} from "../api/client";
import { ChevronRight } from "lucide-react";

const MODEL_COLORS = ["#4361EE","#EF4444","#2CC56F","#FFC107","#7C3AED","#06B6D4","#F97316","#10B981"];
const STATUS_COLOR: Record<string, string> = {
  stockout: "#EF4444", critical: "#F97316", low: "#FFC107", ok: "#2CC56F", excess: "#4361EE",
};
const SEG_PALETTE = ["#F97316","#3B82F6","#22C55E","#8B5CF6","#06B6D4","#94A3B8"];

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function KpiRow({ items }: { items: { label: string; value: string; sub?: string; badge?: "ok" | "warn" | "danger" }[] }) {
  const badgeClass = { ok: "text-green-600", warn: "text-amber-600", danger: "text-red-600" };
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map(({ label, value, sub, badge }) => (
        <div key={label} className="bg-slate-50 rounded-lg px-3 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">{label}</p>
          <p className={`text-lg font-bold leading-tight ${badge ? badgeClass[badge] : "text-slate-800"}`}>{value}</p>
          {sub && <p className="text-[10px] text-slate-400 mt-0.5">{sub}</p>}
        </div>
      ))}
    </div>
  );
}

function SectionCard({ color, title, subtitle, to, children, onNav }: {
  color: string; title: string; subtitle: string; to: string;
  children: React.ReactNode; onNav: (path: string) => void;
}) {
  const border: Record<string, string> = { blue: "border-blue-500", amber: "border-amber-500", violet: "border-violet-500" };
  return (
    <div className={`bg-white rounded-xl shadow-sm border-t-4 ${border[color]} p-5 space-y-4`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-bold text-slate-800">{title}</h3>
          <p className="text-[11px] text-slate-500 mt-0.5">{subtitle}</p>
        </div>
        <button
          onClick={() => onNav(to)}
          className="flex items-center gap-1 text-xs font-semibold text-brand-blue hover:underline whitespace-nowrap shrink-0 mt-0.5"
        >
          View details <ChevronRight size={13}/>
        </button>
      </div>
      {children}
    </div>
  );
}

export function Overview() {
  const navigate = useNavigate();
  const [mcsi,    setMcsi]    = useState<McsiEdaData | null>(null);
  const [inv,     setInv]     = useState<OverviewData | null>(null);
  const [orders,  setOrders]  = useState<OrdersEdaData | null>(null);
  const [sales,   setSales]   = useState<SalesEdaData | null>(null);

  useEffect(() => {
    fetchMcsiEda().then(setMcsi);
    fetchOverview().then(setInv);
    fetchOrdersEda("MC", "ALL").then(setOrders);
    fetchSalesEda("MC", "ALL", 0).then(setSales);
  }, []);

  // ── MC Analysis derived ────────────────────────────────────────────────────
  const mcsiTrend = (mcsi?.monthly_trend ?? []).slice(-12);
  const topModels = (mcsi?.by_model ?? []).slice(0, 5);

  // ── Inventory derived ──────────────────────────────────────────────────────
  const statusBar = Object.entries(inv?.stock_status ?? {}).map(([k, v]) => ({ name: k, value: v }));
  const abcBar    = Object.entries(inv?.abc_counts   ?? {}).map(([k, v]) => ({ name: k, value: v }));

  // ── Spare Parts EDA derived ────────────────────────────────────────────────
  const catMix = (orders?.category_mix ?? []).filter(r => r.segment !== "OBM");
  const ordersTrend = (orders?.monthly_trend ?? []).slice(-12);

  return (
    <div className="flex-1 p-6 space-y-5 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Dashboard Overview</h2>
        <p className="text-xs text-slate-500 mt-0.5">Summary of MC Analysis · Inventory Analysis · Spare Parts Analysis</p>
      </div>

      {/* ══ 1. MC Analysis ══════════════════════════════════════════════════ */}
      <SectionCard color="blue" title="MC Analysis" subtitle="Step 09 - Motorcycle net sales, monthly trend, model and dealer breakdown" to="/mcsi-eda" onNav={navigate}>
        {!mcsi ? (
          <p className="text-xs text-slate-400 italic py-4 text-center">Loading…</p>
        ) : (
          <>
            <KpiRow items={[
              { label: "Total VINs",    value: fmt(mcsi.kpis.total_vins),            sub: `${mcsi.kpis.date_from} → ${mcsi.kpis.date_to}` },
              { label: "Bikes Sold",    value: fmt(mcsi.kpis.sold),                  sub: `avg ${mcsi.kpis.avg_monthly_units}/mo` },
              { label: "Return Rate",   value: `${mcsi.kpis.return_rate_pct.toFixed(2)}%`, sub: `${fmt(mcsi.kpis.returned)} returned`, badge: mcsi.kpis.return_rate_pct > 5 ? "danger" : "warn" },
              { label: "Total Revenue", value: `LKR ${fmt(mcsi.kpis.total_revenue_lkr)}`, sub: `LKR ${fmt(mcsi.kpis.avg_revenue_per_unit)}/unit` },
              { label: "Active Dealers", value: mcsi.kpis.active_dealers.toLocaleString(), sub: `${mcsi.kpis.active_provinces} provinces` },
              { label: "Models Sold",   value: mcsi.kpis.models_sold.toString() },
            ]}/>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Monthly trend */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Monthly Units Sold &amp; Revenue — last 12 months</p>
                <ResponsiveContainer width="100%" height={160}>
                  <ComposedChart data={mcsiTrend} margin={{ top: 4, right: 48, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="period" tick={{ fontSize: 9 }} interval={2}/>
                    <YAxis yAxisId="l" tick={{ fontSize: 9 }} tickFormatter={fmt} width={32}/>
                    <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 9 }} tickFormatter={fmt} width={44}/>
                    <Tooltip formatter={(v: unknown, n: unknown) => [`${n === "Revenue LKR" ? "LKR " : ""}${fmt(Number(v))}`, String(n)]}/>
                    <Legend wrapperStyle={{ fontSize: 10 }}/>
                    <Bar  yAxisId="l" dataKey="sold"        name="Units Sold"  fill="#4361EE" radius={[2,2,0,0]} opacity={0.85}/>
                    <Line yAxisId="r" dataKey="revenue_lkr" name="Revenue LKR" stroke="#F97316" strokeWidth={2} dot={false}/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Top models table */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Top Models by Units Sold</p>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-[10px] text-slate-400 uppercase">
                      <th className="py-1.5 pr-3">Model</th>
                      <th className="py-1.5 pr-3 text-right">Units</th>
                      <th className="py-1.5 pr-3 text-right">Share</th>
                      <th className="py-1.5 text-right">Revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topModels.map((r, i) => (
                      <tr key={r.model} className="border-b border-slate-50">
                        <td className="py-1.5 pr-3 flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: MODEL_COLORS[i % MODEL_COLORS.length] }}/>
                          <span className="font-medium text-slate-800 truncate max-w-[120px]">{r.model}</span>
                        </td>
                        <td className="py-1.5 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                        <td className="py-1.5 pr-3 text-right text-slate-500">{r.share_pct.toFixed(1)}%</td>
                        <td className="py-1.5 text-right text-slate-600">{fmt(r.revenue_lkr)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </SectionCard>

      {/* ══ 2. Inventory Analysis ═══════════════════════════════════════════ */}
      <SectionCard color="amber" title="Inventory Analysis" subtitle="Steps 06, 12-14 - PDC stock, classification, selected policy and monthly order" to="/inventory" onNav={navigate}>
        {!inv ? (
          <p className="text-xs text-slate-400 italic py-4 text-center">Loading…</p>
        ) : (
          <>
            <KpiRow items={[
              { label: "Part Master SKUs", value: fmt(inv.kpis.total_skus),     sub: `${inv.kpis.active_skus.toLocaleString()} forecast (ordered by dealers)` },
              { label: "Stockout SKUs", value: fmt(inv.kpis.stockout_skus),    sub: `${fmt(inv.kpis.critical_skus)} critical`, badge: "danger" },
              { label: "Excess SKUs",   value: fmt(inv.kpis.excess_skus),      sub: `LKR ${fmt(inv.kpis.excess_stock_value_lkr)} tied up`, badge: "warn" },
              { label: "Avg Coverage",  value: `${inv.kpis.avg_coverage_months.toFixed(1)} mo`, sub: "active SKUs" },
              { label: "Immediate Orders", value: fmt(inv.kpis.immediate_orders), sub: `${fmt(inv.kpis.soon_orders)} soon · ${fmt(inv.kpis.planned_orders)} planned`, badge: "danger" },
              { label: "Total Order Value", value: `LKR ${fmt(inv.kpis.total_order_value_lkr)}`, sub: `${inv.planning.cycle_month ?? "Published cycle"} ? recommendation` },
            ]}/>

            {/* Module 6 + Module 3 row — only shown when those modules have run */}
            {((inv.kpis.m6_total_skus_to_order ?? 0) > 0 || (inv.kpis.m3_total_stock_qty ?? 0) > 0) && (
              <>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 pt-1">
                  Planning Results
                  <span className="ml-2 font-normal text-slate-300 normal-case">PDC inventory position and selected monthly policies</span>
                </p>
                <KpiRow items={[
                  { label: "SKUs to Order",      value: fmt(inv.kpis.m6_total_skus_to_order ?? 0),      sub: `${inv.kpis.m6_critical_count ?? 0} critical · ${inv.kpis.m6_high_count ?? 0} high`, badge: (inv.kpis.m6_critical_count ?? 0) > 0 ? "danger" : "ok" },
                  { label: "IP at / below ROL",       value: fmt(inv.kpis.m6_stockout_risk_count ?? 0),      sub: "net position below ROL" },
                  { label: "Excess SKUs",           value: fmt(inv.kpis.m6_overstock_count ?? 0),          sub: "excess inventory" },
                  { label: "Simulated Fill Rate",     value: `${(inv.kpis.m6_weighted_fill_rate_pct ?? 0).toFixed(1)}%`, sub: `${inv.planning.policy_verdict} ? holdout result`, badge: inv.planning.policy_verdict === "PASS" ? "ok" : "warn" },
                  { label: "PDC Stock on Hand",       value: fmt(inv.kpis.m3_total_stock_qty ?? 0),          sub: "units in planning scope" },
                  { label: "PDC Position (Assumed)",        value: fmt(inv.kpis.m3_total_net_position ?? 0),       sub: inv.planning.inventory_position_note, badge: (inv.kpis.m3_total_net_position ?? 0) < 0 ? "danger" : "ok" },
                ]}/>
              </>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Status breakdown */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Status Breakdown</p>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={statusBar} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="name" tick={{ fontSize: 10 }}/>
                    <YAxis tick={{ fontSize: 9 }} tickFormatter={fmt} width={32}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="value" radius={[3,3,0,0]}>
                      {statusBar.map(d => <Cell key={d.name} fill={STATUS_COLOR[d.name] ?? "#94A3B8"}/>)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* ABC classification */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">ABC Classification</p>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={abcBar} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="name" tick={{ fontSize: 12 }}/>
                    <YAxis tick={{ fontSize: 9 }} tickFormatter={fmt} width={32}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="value" radius={[3,3,0,0]}>
                      {abcBar.map(d => (
                        <Cell key={d.name} fill={d.name === "A" ? "#EF4444" : d.name === "B" ? "#FFC107" : "#2CC56F"}/>
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Quick links */}
            <div className="flex flex-wrap gap-2 pt-1 border-t border-slate-100">
              {[
                { label: "Inventory Table",  to: "/inventory"      },
                { label: "Order Plan",        to: "/orders"         },
                { label: "Classification",    to: "/eda?tab=classification" },
                { label: "Demand Forecast",   to: "/forecast"       },
              ].map(link => (
                <button key={link.to} onClick={() => navigate(link.to)}
                  className="text-[11px] font-medium text-slate-500 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md px-2.5 py-1 transition-colors">
                  {link.label}
                </button>
              ))}
            </div>
          </>
        )}
      </SectionCard>

      {/* ══ 3. Spare Parts Analysis ═════════════════════════════════════════ */}
      <SectionCard color="violet" title="Spare Parts Analysis" subtitle="Steps 03-05 - MC dealer demand orders and billed sales" to="/eda" onNav={navigate}>
        {!orders || !sales ? (
          <p className="text-xs text-slate-400 italic py-4 text-center">Loading…</p>
        ) : (
          <>
            <KpiRow items={[
              { label: "Purchase Orders",    value: fmt(orders.total_po),                         sub: `${fmt(orders.total_po_documents)} documents` },
              { label: "Avg Fill Rate",      value: `${(orders.avg_fill_rate * 100).toFixed(1)}%`, sub: `${fmt(orders.fill_rate_lt1_count)} lines short-shipped`, badge: orders.avg_fill_rate < 0.9 ? "warn" : "ok" },
              { label: "Net Revenue",        value: `LKR ${fmt(sales.net_sale_value_lkr)}`,      sub: `${sales.data_year} · billed minus returns` },
              { label: "Return Rate",        value: `${sales.return_rate_pct.toFixed(2)}%`,        sub: `LKR ${fmt(sales.total_return_value_lkr)}`, badge: sales.return_rate_pct > 10 ? "danger" : sales.return_rate_pct > 5 ? "warn" : "ok" },
              { label: "Unique Parts",       value: fmt(sales.unique_parts),                       sub: `${fmt(sales.unique_dealers)} dealers` },
              { label: "Fulfillment Rate",   value: `${sales.fulfillment_pct.toFixed(1)}%`,        sub: "order received → confirmed", badge: sales.fulfillment_pct < 80 ? "warn" : "ok" },
            ]}/>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Monthly trend */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Monthly PO Count &amp; Value — last 12 months</p>
                <ResponsiveContainer width="100%" height={155}>
                  <ComposedChart data={ordersTrend} margin={{ top: 4, right: 48, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="period" tick={{ fontSize: 9 }} interval={2}/>
                    <YAxis yAxisId="l" tick={{ fontSize: 9 }} tickFormatter={fmt} width={32}/>
                    <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 9 }} tickFormatter={fmt} width={44}/>
                    <Tooltip formatter={(v: unknown, n: unknown) => [`${String(n).includes("LKR") ? "LKR " : ""}${fmt(Number(v))}`, String(n)]}/>
                    <Legend wrapperStyle={{ fontSize: 10 }}/>
                    <Bar  yAxisId="l" dataKey="po_count"        name="PO Count"    fill="#7C3AED" radius={[2,2,0,0]} opacity={0.85}/>
                    <Line yAxisId="r" dataKey="confirmed_value_lkr" name="Confirmed LKR" stroke="#2CC56F" strokeWidth={2} dot={false}/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              {/* Category mix */}
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">MC Category Mix</p>
                {catMix.length > 0 ? (
                  <>
                    <ResponsiveContainer width="100%" height={120}>
                      <BarChart data={catMix} layout="vertical" margin={{ top: 2, right: 50, left: 0, bottom: 2 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                        <XAxis type="number" tick={{ fontSize: 9 }} tickFormatter={fmt}/>
                        <YAxis type="category" dataKey="segment" tick={{ fontSize: 10 }} width={72}/>
                        <Tooltip formatter={(v: unknown) => [`LKR ${fmt(Number(v))}`, "Value"]}/>
                        <Bar dataKey="value_lkr" radius={[0,3,3,0]}>
                          {catMix.map((_, i) => <Cell key={i} fill={SEG_PALETTE[i % SEG_PALETTE.length]}/>)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    <table className="w-full text-xs mt-2">
                      <thead>
                        <tr className="border-b border-slate-100 text-[10px] text-slate-400 uppercase text-left">
                          <th className="py-1 pr-3">Category</th>
                          <th className="py-1 pr-3 text-right">Value (LKR)</th>
                          <th className="py-1 pr-3 text-right">Share</th>
                          <th className="py-1 text-right">Fill Rate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {catMix.map((r, i) => (
                          <tr key={r.segment} className="border-b border-slate-50">
                            <td className="py-1 pr-3 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full shrink-0" style={{ background: SEG_PALETTE[i % SEG_PALETTE.length] }}/>
                              <span className="font-medium text-slate-700">{r.segment}</span>
                            </td>
                            <td className="py-1 pr-3 text-right text-slate-600">{fmt(r.value_lkr)}</td>
                            <td className="py-1 pr-3 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                            <td className="py-1 text-right">
                              <span className={`font-semibold ${r.fill_rate_pct >= 95 ? "text-green-600" : r.fill_rate_pct >= 85 ? "text-amber-600" : "text-red-600"}`}>
                                {r.fill_rate_pct.toFixed(1)}%
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="text-xs text-slate-400 italic mt-2">No category data available</p>
                )}
              </div>
            </div>
          </>
        )}
      </SectionCard>
    </div>
  );
}
