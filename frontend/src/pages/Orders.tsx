import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { Download } from "lucide-react";
import { fetchPolicy, fetchSanity, fetchUIOServicePlan, fetchOrderReview, type PolicyData, type SanityRow, type UIOServicePlanRow, type UIOServicePlanResponse, type ReviewData } from "../api/client";
import { POLICY_COLORS as TIER_COLOR, SS_COLORS as SS_COLOR, policyLabel } from "../api/planning";
import { KpiCard } from "../components/KpiCard";

const URGENCY_COLOR: Record<string, string> = { immediate: "#EF4444", soon: "#FFC107", planned: "#4361EE", none: "#94A3B8" };

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type Tab = "orders" | "review" | "sanity" | "uio";

export function Orders() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<PolicyData | null>(null);
  const [sanity, setSanity]     = useState<SanityRow[]>([]);
  const [uioPlan, setUioPlan]   = useState<UIOServicePlanResponse | null>(null);
  const [urgency, setUrgency]   = useState(searchParams.get("urgency") ?? "");
  const [tier, setTier]         = useState("");
  const [ssMethod, setSsMethod] = useState("");
  const [search, setSearch]     = useState("");
  const [uioSearch, setUioSearch] = useState("");
  const [uioAbcFilter, setUioAbcFilter] = useState("");
  const [uioUrgencyFilter, setUioUrgencyFilter] = useState("");
  const [uioCatalogOnly, setUioCatalogOnly] = useState(false);
  const [tab, setTab]           = useState<Tab>(searchParams.get("flagged") === "true" ? "sanity" : "orders");

  const [review, setReview] = useState<ReviewData | null>(null);
  useEffect(() => {
    fetchOrderReview(500).then(setReview);
    fetchSanity(200).then(setSanity);
    fetchUIOServicePlan(undefined, 500).then(setUioPlan);
  }, []);
  useEffect(() => {
    fetchPolicy({ urgency: urgency || undefined, tier: tier || undefined, ss_method: ssMethod || undefined, search: search || undefined, limit: 500 }).then(setData);
  }, [urgency, tier, ssMethod, search]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const urgBar  = Object.entries(data.urgency_counts).filter(([k]) => k !== "none").map(([k, v]) => ({ name: k, value: v }));
  const tierBar = Object.entries(data.tier_counts).map(([k, v]) => ({ name: policyLabel(k), value: v }));
  const ssBar   = Object.entries(data.ss_method_counts).map(([k, v]) => ({ name: k, value: v }));

  const filtered = data.rows.filter(r =>
    !search || r.material_9.toLowerCase().includes(search.toLowerCase()) || r.description.toLowerCase().includes(search.toLowerCase())
  );
  const totalOrderVal = data.total_order_value_lkr;

  // UIO service plan filtered rows
  const uioRows: UIOServicePlanRow[] = (uioPlan?.rows ?? []).filter(r => {
    if (uioSearch && !r.material_9.toLowerCase().includes(uioSearch.toLowerCase()) && !r.description.toLowerCase().includes(uioSearch.toLowerCase())) return false;
    if (uioAbcFilter && r.abc !== uioAbcFilter) return false;
    if (uioUrgencyFilter && r.order_urgency !== uioUrgencyFilter) return false;
    if (uioCatalogOnly && !r.in_catalog) return false;
    return true;
  });
  const uioValueDelta = uioRows.reduce((s, r) => s + r.delta_vs_roq * r.unit_value_lkr, 0);

  const TABS = [
    { key: "orders" as Tab, label: `Order Plan (${data.total.toLocaleString()})` },
    { key: "review" as Tab, label: `Held for Review (${(review?.total ?? 0).toLocaleString()})` },
    { key: "uio"    as Tab, label: `Fleet Demand & Policy` },
    { key: "sanity" as Tab, label: `Sanity Review (${sanity.length})` },
  ];

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <h2 className="text-xl font-bold text-slate-800">Order Recommendation Plan</h2>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard label="Filtered SKUs"  value={fmt(data.total)}                       color="blue"/>
        <KpiCard label="Immediate"      value={fmt(data.urgency_counts.immediate ?? 0)}    color="red"/>
        <KpiCard label="Soon"           value={fmt(data.urgency_counts.soon ?? 0)}         color="amber"/>
        <KpiCard label="Order Value"    value={`LKR ${fmt(totalOrderVal)}`}                color="purple"/>
        <KpiCard label="Held for Review" value={review ? `LKR ${fmt(review.total_value_lkr)}` : "…"}
          sub={review ? `${review.total.toLocaleString()} lines · order > 3x recent demand · not auto-ordered` : ""} color="amber"/>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Order Urgency</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={urgBar} layout="vertical" margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {urgBar.map(d => <Cell key={d.name} fill={URGENCY_COLOR[d.name] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Selected Policy</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={tierBar} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 11 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {tierBar.map(d => <Cell key={d.name} fill={TIER_COLOR[d.name] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Safety Stock Method</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={ssBar} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="name" tick={{ fontSize: 11 }}/>
              <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {ssBar.map(d => <Cell key={d.name} fill={SS_COLOR[d.name] ?? "#94A3B8"}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        {/* Tab switcher */}
        <div className="flex gap-1 mb-4 border-b border-slate-100 pb-2 items-center">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${tab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}
            >
              {t.label}
            </button>
          ))}
          <div className="flex-1"/>
          <a
            href={`/api/v1/policy/export.xlsx?${new URLSearchParams({ urgency, tier, ss_method: ssMethod, search })}`}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors font-medium"
            download
          >
            <Download size={13}/> Export Excel
          </a>
        </div>

        {tab === "orders" && (
          <>
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search SKU or description…" value={search} onChange={e => setSearch(e.target.value)}
              />
              <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={urgency} onChange={e => setUrgency(e.target.value)}>
                <option value="">All urgencies</option>
                {Object.keys(data.urgency_counts).map(u => <option key={u} value={u}>{u}</option>)}
              </select>
              <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={tier} onChange={e => setTier(e.target.value)}>
                <option value="">All policies</option>
                {Object.keys(data.tier_counts).map(t => <option key={t} value={t}>{policyLabel(t)}</option>)}
              </select>
              <select className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none" value={ssMethod} onChange={e => setSsMethod(e.target.value)}>
                <option value="">All SS methods</option>
                {Object.keys(data.ss_method_counts).map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-2">SKU</th>
                    <th className="py-2 pr-2">Description</th>
                    <th className="py-2 pr-2">Policy</th>
                    <th className="py-2 pr-2">SS Method</th>
                    <th className="py-2 pr-2 text-right">Fill Target %</th>
                    <th className="py-2 pr-2 text-right">z</th>
                    <th className="py-2 pr-2 text-right">SS</th>
                    <th className="py-2 pr-2 text-right">ROL</th>
                    <th className="py-2 pr-2 text-right">ROQ</th>
                    <th className="py-2 pr-2 text-right">Final Qty</th>
                    <th className="py-2 pr-2 text-right">CV</th>
                    <th className="py-2">Urgency</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 100).map(r => (
                    <tr key={r.material_9} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.sanity_flag ? "bg-amber-50/50" : ""}`}>
                      <td className="py-2 pr-2 font-mono text-xs text-slate-700">
                        {r.material_9}
                        {r.sanity_flag && <span className="ml-1 text-amber-500 text-xs" title={r.sanity_note}>⚠</span>}
                      </td>
                      <td className="py-2 pr-2 text-slate-600 max-w-[140px] truncate" title={r.description}>{r.description}</td>
                      <td className="py-2 pr-2">
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                      </td>
                      <td className="py-2 pr-2">
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ background: (SS_COLOR[r.ss_method] ?? "#94A3B8") + "22", color: SS_COLOR[r.ss_method] ?? "#64748B" }}>{r.ss_method}</span>
                      </td>
                      <td className="py-2 pr-2 text-right text-xs">{(r.service_level * 100).toFixed(1)}%</td>
                      <td className="py-2 pr-2 text-right text-xs text-slate-400">{r.z_score.toFixed(2)}</td>
                      <td className="py-2 pr-2 text-right">{r.safety_stock.toFixed(0)}</td>
                      <td className="py-2 pr-2 text-right">{r.rol.toFixed(0)}</td>
                      <td className="py-2 pr-2 text-right">{r.roq.toFixed(0)}</td>
                      <td className="py-2 pr-2 text-right font-semibold text-slate-800">{r.net_requirement.toFixed(0)}</td>
                      <td className="py-2 pr-2 text-right text-xs text-slate-400">{r.cv.toFixed(2)}</td>
                      <td className="py-2">
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: URGENCY_COLOR[r.order_urgency] ?? "#94A3B8" }}>{r.order_urgency}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filtered.length > 100 && <p className="text-xs text-slate-400 mt-2 text-center">Showing 100 of {filtered.length.toLocaleString()}</p>}
            </div>
          </>
        )}

        {/* ── UIO-Based Service Plan ── */}
        {tab === "review" && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              These lines were proposed but <b>not ordered automatically</b>: each asks for more than 3× what the part
              actually sold over the last six months (scaled to the 4-month protection interval)
              {review ? <> — {review.no_demand.toLocaleString()} of them sold nothing at all in that time</> : null}.
              Confirm, trim or drop each before it goes to the supplier.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500 uppercase">
                    <th className="py-2 pr-3">Part</th>
                    <th className="py-2 pr-3">Description</th>
                    <th className="py-2 pr-3">ABC / FSN</th>
                    <th className="py-2 pr-3">Policy</th>
                    <th className="py-2 pr-3 text-right">Held qty</th>
                    <th className="py-2 pr-3 text-right">Held value</th>
                    <th className="py-2 pr-3 text-right">Sold, last 6 mo</th>
                    <th className="py-2 pr-3 text-right">Forecast / mo</th>
                    <th className="py-2 pr-3 text-right">On hand</th>
                    <th className="py-2 pr-3 text-right">On order</th>
                    <th className="py-2">Why held</th>
                  </tr>
                </thead>
                <tbody>
                  {(review?.rows ?? []).map(r => (
                    <tr key={r.material_9} className="border-b border-slate-50 hover:bg-amber-50/40">
                      <td className="py-1.5 pr-3 font-mono text-slate-700 whitespace-nowrap">{r.material_9}</td>
                      <td className="py-1.5 pr-3 text-slate-700">{r.description}</td>
                      <td className="py-1.5 pr-3 text-slate-500">{r.abc} / {r.fsn}</td>
                      <td className="py-1.5 pr-3 text-slate-500">{policyLabel(r.policy_tier)}</td>
                      <td className="py-1.5 pr-3 text-right font-semibold text-amber-700 tabular-nums">{Math.round(r.q_review).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">LKR {fmt(r.value_review_lkr)}</td>
                      <td className={`py-1.5 pr-3 text-right tabular-nums ${r.recent_demand_6m <= 0 ? "text-red-500 font-semibold" : "text-slate-600"}`}>{Math.round(r.recent_demand_6m).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-600">{r.forecast_month.toFixed(1)}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-600">{Math.round(r.stock_on_hand).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-600">{Math.round(r.on_order).toLocaleString()}</td>
                      <td className="py-1.5 text-slate-500">{r.review_flags}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {tab === "uio" && (
          <div className="space-y-5">
            {/* Explanation banner */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-xs text-blue-800">
              <strong>How this works:</strong> Fleet demand comes from the published parc estimate.
              Protection demand covers {uioPlan?.planning.lead_time_months ?? data.planning.lead_time_months} months of lead time
              plus {data.planning.review_period_months} month of review ({data.planning.protection_interval_months} months total).
              Recommended quantity is the selected policy's final order, including MOQ and pack rounding.
              Policy validation: {data.planning.policy_verdict}. {data.planning.inventory_position_note}.

            </div>

            {/* KPIs */}
            {uioPlan && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-white rounded-xl shadow-sm p-4 border-l-4 border-blue-500">
                  <p className="text-xs text-slate-500 uppercase font-semibold tracking-wide">SKUs with History</p>
                  <p className="text-2xl font-bold text-slate-800 mt-1">{uioPlan.skus_with_history.toLocaleString()}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">of {uioPlan.total_skus.toLocaleString()} SKUs with a parc estimate</p>
                </div>
                <div className="bg-white rounded-xl shadow-sm p-4 border-l-4 border-purple-500">
                  <p className="text-xs text-slate-500 uppercase font-semibold tracking-wide">Planning Horizon</p>
                  <p className="text-2xl font-bold text-slate-800 mt-1">{uioPlan.horizon_months} months</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{data.planning.lead_time_months}-mo lead + {data.planning.review_period_months}-mo review</p>
                </div>
                <div className="bg-white rounded-xl shadow-sm p-4 border-l-4 border-teal-500">
                  <p className="text-xs text-slate-500 uppercase font-semibold tracking-wide">Published Order Value</p>
                  <p className="text-2xl font-bold text-teal-700 mt-1">LKR {fmt(uioPlan.total_service_plan_value)}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">final order quantity times published unit cost</p>
                </div>
                <div className={`bg-white rounded-xl shadow-sm p-4 border-l-4 ${uioPlan.value_delta >= 0 ? "border-amber-500" : "border-green-500"}`}>
                  <p className="text-xs text-slate-500 uppercase font-semibold tracking-wide">vs Selected Policy Qty</p>
                  <p className={`text-2xl font-bold mt-1 ${uioPlan.value_delta >= 0 ? "text-amber-600" : "text-green-600"}`}>
                    {uioPlan.value_delta >= 0 ? "+" : ""}LKR {fmt(uioPlan.value_delta)}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">service plan vs policy ROQ total</p>
                </div>
              </div>
            )}

            {/* Demand distribution chart — service plan qty vs base ROQ */}
            {uioPlan && uioPlan.skus_with_history > 0 && (() => {
              const chartData = [
                { label: "Service Plan > ROQ", count: uioPlan.rows.filter(r => r.service_plan_qty > r.base_roq && r.hist_months > 0).length, color: "#EF4444" },
                { label: "Service Plan < ROQ", count: uioPlan.rows.filter(r => r.service_plan_qty < r.base_roq && r.hist_months > 0).length, color: "#2CC56F" },
                { label: "Service Plan ≈ ROQ", count: uioPlan.rows.filter(r => r.service_plan_qty === r.base_roq && r.hist_months > 0).length, color: "#94A3B8" },
                { label: "No History",         count: uioPlan.rows.filter(r => r.hist_months === 0).length, color: "#E2E8F0" },
              ];
              return (
                <div className="bg-white rounded-xl shadow-sm p-4">
                  <p className="text-sm font-semibold text-slate-700 mb-1">Service Plan vs Selected Policy Qty</p>
                  <p className="text-xs text-slate-400 mb-3">Fleet demand versus the selected purchase quantity for the displayed rows</p>
                  <div className="flex items-end gap-6 h-24">
                    {chartData.map(d => (
                      <div key={d.label} className="flex flex-col items-center gap-1 flex-1">
                        <span className="text-sm font-bold text-slate-700">{d.count.toLocaleString()}</span>
                        <div className="w-full rounded-t" style={{ height: Math.max(4, d.count / Math.max(...chartData.map(x => x.count)) * 56), background: d.color }}/>
                        <span className="text-[9px] text-slate-500 text-center leading-tight">{d.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* Filters */}
            <div className="flex gap-3 flex-wrap items-center">
              <input
                className="flex-1 min-w-[220px] border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                placeholder="Search SKU or description…"
                value={uioSearch} onChange={e => setUioSearch(e.target.value)}
              />
              <select className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none" value={uioAbcFilter} onChange={e => setUioAbcFilter(e.target.value)}>
                <option value="">All ABC</option>
                {["A","B","C"].map(a => <option key={a} value={a}>{a}</option>)}
              </select>
              <select className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none" value={uioUrgencyFilter} onChange={e => setUioUrgencyFilter(e.target.value)}>
                <option value="">All urgencies</option>
                {["immediate","soon","planned","none"].map(u => <option key={u} value={u}>{u}</option>)}
              </select>
              <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
                <input type="checkbox" checked={uioCatalogOnly} onChange={e => setUioCatalogOnly(e.target.checked)} className="rounded"/>
                Catalog-mapped only
              </label>
              <span className="text-xs text-slate-400">{uioRows.length.toLocaleString()} SKUs</span>
            </div>

            {/* Side-by-side comparison table */}
            <div className="overflow-x-auto rounded-xl shadow-sm border border-slate-100">
              <table className="text-xs w-full border-collapse bg-white">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-left">
                    <th className="py-2 px-3 text-slate-500 uppercase sticky left-0 bg-slate-50 z-10 min-w-[110px]">SKU</th>
                    <th className="py-2 px-3 text-slate-500 uppercase min-w-[160px]">Description</th>
                    <th className="py-2 px-3 text-slate-500 uppercase">ABC</th>
                    <th className="py-2 px-3 text-slate-500 uppercase">Urgency</th>
                    <th className="py-2 px-3 text-slate-500 uppercase text-right">Hist Months</th>
                    <th className="py-2 px-3 text-slate-500 uppercase text-right">Avg / Month</th>
                    <th className="py-2 px-3 text-center" style={{ background: "#EFF6FF" }}>
                      <span className="text-blue-700 font-bold uppercase">Service Plan ({uioPlan?.horizon_months ?? data.planning.protection_interval_months}mo)</span>
                    </th>
                    <th className="py-2 px-3 text-center" style={{ background: "#F8FAFC" }}>
                      <span className="text-slate-500 font-bold uppercase">Selected Policy Qty</span>
                    </th>
                    <th className="py-2 px-3 text-slate-500 uppercase text-right">Final Qty</th>
                    <th className="py-2 px-3 text-center" style={{ background: "#F0FDF4" }}>
                      <span className="text-green-700 font-bold uppercase">Recommended</span>
                    </th>
                    <th className="py-2 px-3 text-slate-500 uppercase text-right">Delta</th>
                    <th className="py-2 px-3 text-slate-500 uppercase">Catalog Models</th>
                  </tr>
                </thead>
                <tbody>
                  {uioRows.slice(0, 150).map((r, i) => {
                    const hasHistory = r.hist_months > 0;
                    const svcHigher = r.service_plan_qty > r.base_roq;
                    const svcLower  = r.service_plan_qty < r.base_roq;
                    return (
                      <tr key={i} className={`border-b border-slate-50 hover:bg-slate-50/60 ${!hasHistory ? "opacity-60" : ""}`}>
                        <td className="py-1.5 px-3 font-mono text-slate-700 sticky left-0 bg-white z-10">{r.material_9}</td>
                        <td className="py-1.5 px-3 text-slate-600 max-w-[180px] truncate" title={r.description}>{r.description}</td>
                        <td className="py-1.5 px-3">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${r.abc === "A" ? "bg-red-100 text-red-700" : r.abc === "B" ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700"}`}>{r.abc}</span>
                        </td>
                        <td className="py-1.5 px-3">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${r.order_urgency === "immediate" ? "bg-red-100 text-red-700" : r.order_urgency === "soon" ? "bg-amber-100 text-amber-700" : r.order_urgency === "planned" ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500"}`}>{r.order_urgency}</span>
                        </td>
                        <td className="py-1.5 px-3 text-right text-slate-500">
                          {hasHistory ? r.hist_months : <span className="text-slate-300 text-[10px]">no data</span>}
                        </td>
                        <td className="py-1.5 px-3 text-right text-slate-600">
                          {hasHistory ? r.avg_monthly.toFixed(1) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-right font-bold text-blue-700" style={{ background: "#EFF6FF" }}>
                          {hasHistory ? r.service_plan_qty.toLocaleString() : <span className="text-slate-300 text-[10px] font-normal">—</span>}
                        </td>
                        <td className="py-1.5 px-3 text-right text-slate-500">
                          {r.base_roq.toLocaleString()}
                        </td>
                        <td className="py-1.5 px-3 text-right text-slate-500">
                          {r.net_requirement.toLocaleString()}
                        </td>
                        <td className="py-1.5 px-3 text-right font-bold text-green-700" style={{ background: "#F0FDF4" }}>
                          {r.recommended_order.toLocaleString()}
                        </td>
                        <td className="py-1.5 px-3 text-right">
                          {hasHistory ? (
                            <span className={`font-semibold text-[11px] ${svcHigher ? "text-red-600" : svcLower ? "text-green-600" : "text-slate-400"}`}>
                              {svcHigher ? "+" : ""}{r.delta_vs_roq.toLocaleString()}
                              {r.base_roq > 0 && <span className="font-normal text-slate-400 ml-0.5">({r.delta_pct > 0 ? "+" : ""}{r.delta_pct.toFixed(0)}%)</span>}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-slate-400 max-w-[120px] truncate text-[10px]" title={r.catalog_models || undefined}>
                          {r.catalog_models || <span className="text-slate-200">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {uioRows.length === 0 && (
                <p className="text-center py-10 text-slate-400 text-sm">No results for current filters.</p>
              )}
              {uioRows.length > 150 && (
                <p className="text-xs text-slate-400 text-center py-2 border-t border-slate-100">Showing 150 of {uioRows.length.toLocaleString()} — use filters to narrow</p>
              )}
            </div>

            {/* Value summary footer */}
            {uioPlan && (
              <div className="flex gap-6 text-xs text-slate-500 px-1">
                <span>Filtered delta (LKR): <strong className={uioValueDelta >= 0 ? "text-red-600" : "text-green-600"}>{uioValueDelta >= 0 ? "+" : ""}LKR {fmt(uioValueDelta)}</strong></span>
                <span>Catalog-mapped SKUs: <strong className="text-teal-700">{uioPlan.rows.filter(r => r.in_catalog).length}</strong></span>
                <span>Zero-history SKUs: <strong className="text-slate-400">{uioPlan.rows.filter(r => r.hist_months === 0).length}</strong></span>
              </div>
            )}
          </div>
        )}

        {tab === "sanity" && (
          <div className="overflow-x-auto">
            <p className="text-xs text-slate-500 mb-3">
              {sanity.length} SKUs where ROL or ROQ is &gt;3× recent demand. These require manual review before ordering.
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                  <th className="py-2 pr-3">SKU</th>
                  <th className="py-2 pr-3">Description</th>
                  <th className="py-2 pr-3">ABC</th>
                  <th className="py-2 pr-3">Policy</th>
                  <th className="py-2 pr-3 text-right">Avg Demand</th>
                  <th className="py-2 pr-3 text-right">ROL</th>
                  <th className="py-2 pr-3 text-right">ROQ</th>
                  <th className="py-2 pr-3 text-right">Final Qty</th>
                  <th className="py-2 pr-3">Urgency</th>
                  <th className="py-2">Sanity Note</th>
                </tr>
              </thead>
              <tbody>
                {sanity.map(r => (
                  <tr key={r.material_9} className="border-b border-slate-50 hover:bg-amber-50/30">
                    <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                    <td className="py-2 pr-3 text-slate-600 max-w-[150px] truncate" title={r.description}>{r.description}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-2 py-0.5 rounded-full font-bold text-white" style={{ background: r.abc === "A" ? "#EF4444" : r.abc === "B" ? "#FFC107" : "#2CC56F" }}>{r.abc}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium text-white" style={{ background: TIER_COLOR[r.policy_tier] ?? "#94A3B8" }}>{policyLabel(r.policy_tier)}</span>
                    </td>
                    <td className="py-2 pr-3 text-right">{r.avg_monthly_demand.toFixed(1)}</td>
                    <td className="py-2 pr-3 text-right">{r.rol.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right">{r.roq.toFixed(0)}</td>
                    <td className="py-2 pr-3 text-right font-semibold">{r.net_requirement.toFixed(0)}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white" style={{ background: URGENCY_COLOR[r.order_urgency] ?? "#94A3B8" }}>{r.order_urgency}</span>
                    </td>
                    <td className="py-2 text-xs text-amber-700 max-w-[200px]">{r.sanity_note}</td>
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
