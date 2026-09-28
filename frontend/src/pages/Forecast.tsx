import { useEffect, useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { fetchForecast, fetchTrend, type ForecastData, type MonthlyPoint } from "../api/client";
import { KpiCard } from "../components/KpiCard";

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return Math.round(n).toLocaleString();
}
const qty = (n: number | null | undefined) =>
  n == null ? "—" : n >= 10 ? Math.round(n).toLocaleString() : n.toFixed(1);

/** Plain names for the own-history models Step 07 selects per demand pattern. */
const MODEL_TEXT: Record<string, string> = {
  naive: "Last month", mean: "Long-run average", "ses_0.3": "Smoothed trend",
  moving_average_3: "3-month average", moving_average_6: "6-month average",
  croston: "Intermittent (Croston)", sba: "Intermittent (SBA)", tsb: "Intermittent (TSB)",
  linear_trend: "Linear trend", none: "—",
};
const PATTERN_TEXT: Record<string, string> = {
  smooth: "Steady", erratic: "Steady, sizes vary", intermittent: "Occasional",
  lumpy: "Occasional, sizes vary", "no demand": "No demand",
};

export function Forecast() {
  const [data,   setData]   = useState<ForecastData | null>(null);
  const [trend,  setTrend]  = useState<MonthlyPoint[]>([]);
  const [search, setSearch] = useState("");
  const [method, setMethod] = useState("");
  const [basis,  setBasis]  = useState("");
  const [page,   setPage]   = useState(0);
  const pageSize = 100;

  useEffect(() => { fetchTrend().then(setTrend); }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchForecast({
        search: search || undefined, method: method || undefined, basis: basis || undefined,
        limit: pageSize, offset: page * pageSize,
      }).then(setData);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search, method, basis, page]);
  useEffect(() => { setPage(0); }, [search, method, basis]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const all = data.all_skus ?? data.total;
  const trendData = trend.slice(-24).map(p => ({ month: p.year_month_str.slice(0, 7), qty: p.net_demand }));
  const monthly = data.monthly_forecast_units ?? 0;
  const lastActual = trendData.length ? trendData[trendData.length - 1].qty : 0;
  const methods = Object.entries(data.method_counts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Demand Forecast</h2>
        <p className="text-xs text-slate-500 mt-1 max-w-4xl">
          <b>One forecast per part</b> — the demand the order plan uses. Each part gets a forecast from its <b>own order history</b>
          (the model that tested best for its demand pattern) and, where the catalogues link it to motorcycle models, a
          forecast from the <b>fleet of those models</b> (units in operation by age). The two are blended by how much history the
          part has: a long history leans on its own orders, a part on young models leans on the fleet.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Parts forecast" value={all.toLocaleString()} sub="every part dealers have ordered" color="blue"/>
        <KpiCard label="Forecast demand / month" value={fmt(monthly)} sub={`units, all parts · last actual month ${fmt(lastActual)}`} color="green"/>
        <KpiCard label="Linked to the fleet" value={data.parc_skus.toLocaleString()}
          sub={`${(data.fleet_share_pct ?? 0).toFixed(1)}% of forecast demand comes from the fleet`} color="purple"/>
        <KpiCard label="Forecast zero" value={data.zero_demand_skus.toLocaleString()} sub="rarely ordered, none recently" color="amber"/>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5 lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-700">Monthly demand — dealer orders, all parts</h3>
          <p className="text-xs text-slate-400 mb-2">Dashed line = the forecast for a month, summed over every part</p>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={trendData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="demandGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#4361EE" stopOpacity={0.15}/>
                  <stop offset="95%" stopColor="#4361EE" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="month" tick={{ fontSize: 10 }} interval={3}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown) => [Number(v).toLocaleString(), "Units ordered"]}/>
              <Area type="monotone" dataKey="qty" stroke="#4361EE" strokeWidth={2} fill="url(#demandGrad)"/>
              {monthly > 0 && (
                <ReferenceLine y={monthly} stroke="#2CC56F" strokeDasharray="6 4"
                  label={{ value: `Forecast ${fmt(monthly)}/mo`, position: "insideTopRight", fontSize: 10, fill: "#15803D" }}/>
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700">Own-history model, by part</h3>
          <p className="text-xs text-slate-400 mb-3">Chosen per demand pattern by backtest on past months</p>
          <div className="space-y-2">
            {methods.map(([m, n]) => (
              <button key={m} onClick={() => setMethod(method === m ? "" : m)}
                className={`w-full flex items-center gap-2 text-xs rounded px-1 py-0.5 ${method === m ? "bg-blue-50" : "hover:bg-slate-50"}`}>
                <span className="w-36 text-left text-slate-600 truncate">{MODEL_TEXT[m] ?? m}</span>
                <span className="flex-1 h-2.5 bg-slate-100 rounded-sm overflow-hidden">
                  <span className="block h-full bg-brand-blue rounded-sm" style={{ width: `${(n / (methods[0]?.[1] || 1)) * 100}%` }}/>
                </span>
                <span className="w-12 text-right tabular-nums text-slate-700">{n.toLocaleString()}</span>
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-400 mt-3">Click a model to list its parts.</p>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search part or description…"
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"/>
          {[["", "All parts"], ["fleet", "History + fleet"], ["history", "History only"]].map(([k, label]) => (
            <button key={k} onClick={() => setBasis(k)}
              className={`text-xs px-3 py-1.5 rounded-full border font-medium ${basis === k ? "bg-slate-700 text-white border-slate-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
              {label}
            </button>
          ))}
          {method && (
            <button onClick={() => setMethod("")} className="text-xs px-3 py-1.5 rounded-full bg-blue-50 text-brand-blue border border-blue-100">
              Model: {MODEL_TEXT[method] ?? method} ✕
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500">{data.total.toLocaleString()} parts · sorted by forecast demand</p>
        <div className="max-h-[620px] overflow-auto border border-slate-100 rounded-lg">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 shadow-[0_1px_0_#E2E8F0]">
              <tr className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                <th className="py-2.5 px-3">Part</th>
                <th className="py-2.5 pr-3">Description</th>
                <th className="py-2.5 pr-3">Demand pattern</th>
                <th className="py-2.5 pr-3 text-right">From own history<span className="block normal-case font-normal">per month</span></th>
                <th className="py-2.5 pr-3 text-right">From the fleet<span className="block normal-case font-normal">per month</span></th>
                <th className="py-2.5 pr-3">Blend</th>
                <th className="py-2.5 pr-3 text-right text-slate-700">Forecast<span className="block normal-case font-normal">per month</span></th>
                <th className="py-2.5 pr-3 text-right" title="Demand over the 4-month protection interval (lead time + review); up to = 90% likely not to exceed">Next 4 months<span className="block normal-case font-normal">expected · up to</span></th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => {
                const hw = r.history_weight ?? 1;
                const hasFleet = r.fleet_forecast != null;
                return (
                  <tr key={r.material_9} className={`border-b border-slate-100 align-top ${i % 2 ? "bg-slate-50/40" : ""}`}>
                    <td className="py-2.5 px-3 font-mono text-xs text-slate-800 whitespace-nowrap">{r.material_9}</td>
                    <td className="py-2.5 pr-3 min-w-[220px] max-w-[320px]">
                      <span className="text-slate-800 line-clamp-2" title={r.description}>{r.description}</span>
                      <span className="block text-[11px] text-slate-400">Model: {MODEL_TEXT[r.method] ?? r.method}</span>
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-slate-600 whitespace-nowrap">{PATTERN_TEXT[r.demand_category ?? ""] ?? r.demand_category ?? "—"}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">{qty(r.history_forecast)}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-violet-700">{hasFleet ? qty(r.fleet_forecast) : <span className="text-slate-300">no model link</span>}</td>
                    <td className="py-2.5 pr-3 whitespace-nowrap">
                      {hasFleet ? (
                        <span className="inline-flex items-center gap-2 text-[11px] text-slate-500">
                          <span className="w-20 h-2 rounded-sm overflow-hidden flex bg-violet-200">
                            <span className="h-full bg-brand-blue" style={{ width: `${hw * 100}%` }}/>
                          </span>
                          {Math.round(hw * 100)}% history
                        </span>
                      ) : <span className="text-[11px] text-slate-400">history only</span>}
                    </td>
                    <td className="py-2.5 pr-3 text-right tabular-nums font-bold text-slate-900">{qty(r.forecast_m1)}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums text-slate-600 whitespace-nowrap">
                      {qty(r.protection_demand)} <span className="text-slate-400">· {qty(r.protection_p90)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex justify-between items-center text-xs text-slate-500">
          <span>{data.total ? `${page * pageSize + 1}-${Math.min((page + 1) * pageSize, data.total)} of ${data.total.toLocaleString()}` : "No matching parts"}</span>
          <div className="flex gap-2">
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
        <p className="text-[11px] text-slate-400">
          Blend: the share given to the part's own history rises with the months it has been ordered (from 20% to 80%); the rest
          comes from its fleet. A part with no model link is forecast from its history alone. "Next 4 months" is the
          protection interval — the 3-month import lead time plus the monthly review — that safety stock and the order cover.
        </p>
      </div>
    </div>
  );
}
