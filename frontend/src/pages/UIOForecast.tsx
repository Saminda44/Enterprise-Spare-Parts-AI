import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fetchBikes, fetchUIODemand, type BikesData, type UIODemandData } from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { TimePicker, filterByRange, type TimeRange, YearPicker, filterByYear, getYears, monthLabel } from "../components/TimePicker";

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type Tab = "forecast" | "demand";

export function UIOForecast() {
  const [searchParams] = useSearchParams();
  const [data,       setData]       = useState<BikesData | null>(null);
  const [demandData, setDemandData] = useState<UIODemandData | null>(null);
  const [tab,        setTab]        = useState<Tab>(searchParams.get("tab") === "demand" ? "demand" : "forecast");
  const [year,       setYear]       = useState<number | "All">("All");
  const [range,      setRange]      = useState<TimeRange>("YTD");
  const [minDemand,  setMinDemand]  = useState(0);

  useEffect(() => {
    fetchBikes().then(d => {
      setData(d);
      const yrs = getYears(d.uio_forecast);
      if (yrs.length) setYear(yrs[0]);
    });
    fetchUIODemand(0).then(setDemandData);
  }, []);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const { uio_forecast } = data;
  const uioActual    = uio_forecast.filter(r => !r.is_forecast);
  const latestUIO    = uioActual[uioActual.length - 1];
  const projectedUIO = uio_forecast[uio_forecast.length - 1];
  const filtered     = filterByRange(filterByYear(uio_forecast, year), range);

  const demandRows = (demandData?.rows ?? []).filter(r => r.uio_demand_monthly >= minDemand);

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <h2 className="text-xl font-bold text-slate-800">UIO Forecast &amp; Demand</h2>
      <p className="text-xs text-slate-500 -mt-4">Step 10 &amp; 6.4 · Fleet growth model + UIO-driven spare-parts demand estimation</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Current UIO"        value={fmt(latestUIO?.uio_total ?? 0)}         sub={latestUIO?.period ?? ""}    color="purple"/>
        <KpiCard label="Projected UIO"      value={fmt(projectedUIO?.uio_total ?? 0)}      sub={projectedUIO?.period ?? ""} color="blue"/>
        <KpiCard label="UIO-Driven SKUs"    value={fmt(demandData?.parts_with_demand ?? 0)} sub="parts with est. demand"    color="green"/>
        <KpiCard label="Est. Monthly Demand" value={fmt(demandData?.sum_uio_demand_monthly ?? 0)} sub={`supply ${((demandData?.supply_pct ?? 0) * 100).toFixed(0)}%`} color="amber"/>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5 space-y-5">
        <div className="flex gap-2 border-b border-slate-100 pb-3">
          {(["forecast", "demand"] as Tab[]).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${tab === t ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              {t === "forecast" ? "UIO Forecast (Step 10)" : "Fleet Demand (Step 08)"}
            </button>
          ))}
        </div>

        {/* ── UIO Forecast tab ── */}
        {tab === "forecast" && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-700">UIO Growth — Forecast</h3>
                <p className="text-xs text-slate-400 mt-0.5">Shaded band = 80% confidence interval. Dashed = forecast horizon.</p>
              </div>
              <div className="flex items-center gap-2">
                <YearPicker years={getYears(uio_forecast)} value={year} onChange={setYear}/>
                <TimePicker value={range} onChange={setRange}/>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={filtered} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                  tickFormatter={p => monthLabel(p, year !== "All")}/>
                <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                <Tooltip formatter={(v: unknown) => v != null ? Number(v).toLocaleString() : "—"}/>
                <Legend/>
                <Area type="monotone" dataKey="upper_80"  stroke="none" fill="#7C3AED" fillOpacity={0.12} name="Upper 80%" legendType="none"/>
                <Area type="monotone" dataKey="lower_80"  stroke="none" fill="#fff"    fillOpacity={1}    name="Lower 80%" legendType="none"/>
                <Area type="monotone" dataKey="uio_total" stroke="#7C3AED" strokeWidth={2.5} fill="#7C3AED" fillOpacity={0.08} name="UIO Total"/>
                <Area type="monotone" dataKey="new_sales" stroke="#4361EE" strokeWidth={2}   fill="none"   name="New Sales" strokeDasharray="4 2"/>
              </AreaChart>
            </ResponsiveContainer>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">Period</th>
                    <th className="py-2 pr-3 text-right">UIO Total</th>
                    <th className="py-2 pr-3 text-right">New Sales</th>
                    <th className="py-2 pr-3 text-right">Attrition</th>
                    <th className="py-2 pr-3 text-right">Lower 80%</th>
                    <th className="py-2 text-right">Upper 80%</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.period} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.is_forecast ? "bg-blue-50/30" : ""}`}>
                      <td className="py-2 pr-3 font-mono text-xs">{r.period}</td>
                      <td className="py-2 pr-3 text-right font-semibold text-purple-700">{r.uio_total.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-green-600">{r.new_sales.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-red-500">{r.attrition.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-xs text-slate-400">{r.lower_80 != null ? r.lower_80.toLocaleString() : "—"}</td>
                      <td className="py-2 text-right text-xs text-slate-400">{r.upper_80 != null ? r.upper_80.toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ── UIO-Based Demand tab ── */}
        {tab === "demand" && (
          demandData ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="Total Parts"      value={fmt(demandData.total_parts)}       color="blue"/>
                <KpiCard label="With UIO Demand"  value={fmt(demandData.parts_with_demand)} sub="replacement freq > 0" color="green"/>
                <KpiCard label="Projected Fleet"  value={fmt(demandData.projected_uio)}     sub="bikes in operation" color="purple"/>
                <KpiCard label="Lead-time Demand" value={fmt(demandData.sum_uio_demand_leadtime)} sub={`${demandData.lead_time_months}-month window`} color="amber"/>
              </div>

              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
                <strong>Method:</strong> replacement_frequency = avg_monthly_issues / model_UIO &nbsp;·&nbsp;
                uio_demand = projected_UIO × frequency × {((demandData.supply_pct) * 100).toFixed(0)}% supply_pct &nbsp;·&nbsp;
                lead-time demand = monthly × {demandData.lead_time_months} months
              </div>

              {/* Filter control */}
              <div className="flex items-center gap-3">
                <label className="text-xs text-slate-500">Min monthly demand:</label>
                {[0, 1, 5, 10].map(v => (
                  <button key={v} onClick={() => setMinDemand(v)}
                    className={`px-3 py-1 text-xs rounded-lg ${minDemand === v ? "bg-brand-blue text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                    {v === 0 ? "All" : `≥ ${v}`}
                  </button>
                ))}
                <span className="text-xs text-slate-400 ml-2">{demandRows.length.toLocaleString()} parts shown</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                      <th className="py-2 pr-3">Part No.</th>
                      <th className="py-2 pr-3">Description</th>
                      <th className="py-2 pr-3">Models</th>
                      <th className="py-2 pr-3 text-right">Hist Avg/Mo</th>
                      <th className="py-2 pr-3 text-right">Model UIO</th>
                      <th className="py-2 pr-3 text-right">Repl. Freq</th>
                      <th className="py-2 pr-3 text-right">UIO Demand/Mo</th>
                      <th className="py-2 text-right">Lead-time Demand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {demandRows.slice(0, 300).map((r, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-purple-50/20">
                        <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material_9}</td>
                        <td className="py-2 pr-3 text-xs text-slate-600 max-w-[180px] truncate" title={r.description}>{r.description}</td>
                        <td className="py-2 pr-3 text-xs text-slate-400 max-w-[120px] truncate" title={r.compatible_models ?? ""}>{r.compatible_models ?? "—"}</td>
                        <td className="py-2 pr-3 text-right text-xs text-slate-500">{r.avg_monthly.toFixed(2)}</td>
                        <td className="py-2 pr-3 text-right text-xs text-slate-500">{r.model_uio_total.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                        <td className="py-2 pr-3 text-right text-xs font-mono text-slate-400">{r.replacement_freq_per_uio.toFixed(5)}</td>
                        <td className="py-2 pr-3 text-right font-semibold text-purple-700">{r.uio_demand_monthly.toFixed(2)}</td>
                        <td className="py-2 text-right font-bold text-slate-800">{r.uio_demand_leadtime.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {demandRows.length > 300 && (
                  <p className="text-xs text-slate-400 mt-2 text-center">Showing 300 of {demandRows.length.toLocaleString()}</p>
                )}
              </div>
            </div>
          ) : <p className="text-slate-400 text-sm py-10 text-center">Published fleet-demand estimates are unavailable.</p>
        )}
      </div>
    </div>
  );
}
