import { useEffect, useState } from "react";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { fetchForecast, fetchTrend, type ForecastData, type MonthlyPoint } from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { useSegment, useCategory, SEGMENT_TEXT, CATEGORY_TEXT } from "../api/segment";

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return Math.round(n).toLocaleString();
}
const qty = (n: number | null | undefined) =>
  n == null ? "—" : n >= 10 ? Math.round(n).toLocaleString() : n.toFixed(1);

function monthLabel(value: string | null | undefined) {
  if (!value) return "";
  const [year, month] = value.split("-").map(Number);
  return new Intl.DateTimeFormat("en", { month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, 1)));
}

function calendarMonths(start: string, end: string) {
  const [startYear, startMonth] = start.split("-").map(Number);
  const [endYear, endMonth] = end.split("-").map(Number);
  const months: string[] = [];
  let year = startYear;
  let month = startMonth;
  while (year < endYear || (year === endYear && month <= endMonth)) {
    months.push(`${year}-${String(month).padStart(2, "0")}`);
    month += 1;
    if (month === 13) {
      year += 1;
      month = 1;
    }
  }
  return months;
}

function previousMonth(value: string) {
  const [year, month] = value.split("-").map(Number);
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
}

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

function MonthlyForecastTable({ rows, months, visibleMonths, selectedMonth, onSelectMonth }: {
  rows: ForecastData["rows"];
  months: string[];
  visibleMonths: string[];
  selectedMonth: string;
  onSelectMonth: (month: string) => void;
}) {
  const years = [...new Set(visibleMonths.map(month => month.slice(0, 4)))];
  const monthIndex = new Map(months.map((month, index) => [month, index]));
  const mobileMonth = visibleMonths.includes(selectedMonth) ? selectedMonth : visibleMonths[0];
  return (
    <>
    <div className="md:hidden space-y-2">
      <select aria-label="Forecast month" value={mobileMonth} onChange={event => onSelectMonth(event.target.value)}
        className="w-full rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
        {visibleMonths.map(month => <option key={month} value={month}>{monthLabel(month)}</option>)}
      </select>
      <div className="max-h-[620px] overflow-auto border border-slate-100 rounded-lg">
        <table className="w-full table-fixed text-xs" aria-label="Monthly forecast by part">
          <colgroup><col className="w-[100px]"/><col/><col className="w-[80px]"/></colgroup>
          <thead className="sticky top-0 z-10 bg-slate-50 text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left">Part</th>
              <th className="px-2 py-2 text-left">Description</th>
              <th className="px-2 py-2 text-right" title={monthLabel(mobileMonth)}>{monthLabel(mobileMonth).split(" ")[0]}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.material_9} className={`border-b border-slate-100 align-top ${index % 2 ? "bg-slate-50/40" : ""}`}>
                <td className="px-2 py-2 font-mono text-[10px] text-slate-800 break-all">{row.material_9}</td>
                <td className="px-2 py-2 text-slate-700 break-words" title={row.description}>{row.description}</td>
                <td className="px-2 py-2 text-right tabular-nums font-semibold text-slate-900">{qty(row.monthly_forecast?.[monthIndex.get(mobileMonth) ?? -1])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
    <div className="hidden md:block max-h-[620px] overflow-auto border border-slate-100 rounded-lg">
      <table className="w-max min-w-full text-sm" aria-label="Monthly forecast by part">
        <thead className="sticky top-0 z-10 bg-slate-50 shadow-[0_1px_0_#E2E8F0]">
          <tr className="text-[11px] font-semibold text-slate-600 uppercase">
            <th rowSpan={2} scope="col" className="sticky left-0 z-20 bg-slate-50 px-3 py-2.5 text-left min-w-[130px]">Part</th>
            <th rowSpan={2} scope="col" className="px-3 py-2.5 text-left min-w-[220px]">Description</th>
            {years.map(year => (
              <th key={year} colSpan={visibleMonths.filter(month => month.startsWith(year)).length}
                className="border-l border-slate-200 px-3 py-2 text-center">{year}</th>
            ))}
          </tr>
          <tr className="text-[11px] font-semibold text-slate-500 uppercase">
            {visibleMonths.map((month, index) => (
              <th key={month} scope="col" title={monthLabel(month)}
                className={`min-w-[88px] px-3 py-2 text-right ${index === 0 || month.endsWith("-01") ? "border-l border-slate-200" : ""}`}>
                {monthLabel(month).split(" ")[0]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.material_9} className={`border-b border-slate-100 align-top ${index % 2 ? "bg-slate-50/40" : ""}`}>
              <td className={`sticky left-0 z-[1] px-3 py-2.5 font-mono text-xs text-slate-800 whitespace-nowrap ${index % 2 ? "bg-slate-50" : "bg-white"}`}>
                {row.material_9}
              </td>
              <td className="min-w-[220px] max-w-[280px] pr-3 py-2.5">
                <span className="text-slate-800 line-clamp-2" title={row.description}>{row.description}</span>
                <span className="block text-[11px] text-slate-400">Model: {MODEL_TEXT[row.method] ?? row.method}</span>
              </td>
              {visibleMonths.map((month, monthPosition) => (
                <td key={month} className={`px-3 py-2.5 text-right tabular-nums text-slate-800 ${monthPosition === 0 || month.endsWith("-01") ? "border-l border-slate-100" : ""}`}>
                  {qty(row.monthly_forecast?.[monthIndex.get(month) ?? -1])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

export function Forecast() {
  const segment = useSegment();
  const category = useCategory();
  const [data,   setData]   = useState<ForecastData | null>(null);
  const [trend,  setTrend]  = useState<MonthlyPoint[]>([]);
  const [search, setSearch] = useState("");
  const [method, setMethod] = useState("");
  const [basis,  setBasis]  = useState("");
  const [page,   setPage]   = useState(0);
  const [tableView, setTableView] = useState<"monthly" | "summary">("monthly");
  const [yearFilter, setYearFilter] = useState("all");
  const [selectedMonth, setSelectedMonth] = useState("");
  const pageSize = 100;

  useEffect(() => { fetchTrend().then(setTrend); }, [segment, category]);
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
  const forecastPoints = trend.filter(p => p.is_forecast);
  const forecastStart = data.forecast_start ?? forecastPoints[0]?.year_month_str;
  const forecastEnd = data.forecast_end ?? forecastPoints[forecastPoints.length - 1]?.year_month_str;
  const cycleYear = forecastStart?.slice(0, 4);
  const actualPoints = trend.filter(p =>
    !p.is_forecast
    && (!cycleYear || p.year_month_str.startsWith(cycleYear))
    && (!forecastStart || p.year_month_str < forecastStart)
  );
  const actualByMonth = new Map(actualPoints.map(p => [p.year_month_str.slice(0, 7), p.net_demand]));
  const forecastByMonth = new Map(forecastPoints.map(p => [p.year_month_str.slice(0, 7), p.forecast_qty]));
  const calendarStart = cycleYear ? `${cycleYear}-01` : actualPoints[0]?.year_month_str;
  const viewMonths = calendarStart && forecastEnd ? calendarMonths(calendarStart, forecastEnd) : [];
  const trendData = viewMonths.map(month => ({
    month,
    actualQty: !forecastStart || month < forecastStart ? actualByMonth.get(month) ?? null : null,
    forecastQty: forecastStart && month >= forecastStart ? forecastByMonth.get(month) ?? null : null,
  }));
  const monthly = data.monthly_forecast_units ?? 0;
  const lastActual = actualPoints.length ? actualPoints[actualPoints.length - 1].net_demand ?? 0 : 0;
  const latestActualMonth = actualPoints.length
    ? actualPoints[actualPoints.length - 1].year_month_str.slice(0, 7)
    : null;
  const expectedActualMonth = forecastStart ? previousMonth(forecastStart) : null;
  const actualStatus = latestActualMonth
    ? `actual demand through ${monthLabel(latestActualMonth)}`
    : "no current-year actual demand supplied";
  const missingActual = latestActualMonth && expectedActualMonth && latestActualMonth < expectedActualMonth
    ? `; ${monthLabel(expectedActualMonth)} is not supplied`
    : "";
  const horizonText = forecastStart && forecastEnd
    ? `forecast ${monthLabel(forecastStart)} to ${monthLabel(forecastEnd)} (${data.forecast_month_count ?? 0} months)`
    : "forecast unavailable";
  const calendarText = calendarStart && forecastEnd
    ? `${monthLabel(calendarStart)} to ${monthLabel(forecastEnd)}`
    : horizonText;
  const methods = Object.entries(data.method_counts).sort((a, b) => b[1] - a[1]);
  const validation = data.validation ?? [];
  const forecastMonths = data.forecast_months ?? [];
  const forecastYears = [...new Set(forecastMonths.map(month => month.slice(0, 4)))];
  const visibleMonths = forecastMonths.some(month => month.startsWith(yearFilter))
    ? forecastMonths.filter(month => month.startsWith(yearFilter))
    : forecastMonths;

  return (
    <div className="min-w-0 w-full max-w-full flex-1 p-4 md:p-6 space-y-6 overflow-x-hidden overflow-y-auto">
      <div className="min-w-0">
        <h2 className="text-xl font-bold text-slate-800">{segment ? `${SEGMENT_TEXT[segment]} Spare Parts — Demand Forecast` : "Demand Forecast"}{category && <span className="text-brand-blue"> — {CATEGORY_TEXT[category]}</span>}</h2>
        {segment === "obm" && (
          <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-1.5 mt-2 max-w-4xl break-words">
            Outboard parts are not in the motorcycle catalogues and have no motorcycle fleet behind them, so they are forecast
            from their own order history alone.
          </p>
        )}
        <p className="text-xs text-slate-500 mt-1 max-w-4xl break-words">
          <b>One forecast per part</b> — the demand the order plan uses. Each part gets a forecast from its <b>own order history</b>
          (the model that tested best for its demand pattern) and, where the catalogues link it to motorcycle models, a
          forecast from the <b>fleet of those models</b> (units in operation by age). The two are blended by how much history the
          part has: a long history leans on its own orders, a part on young models leans on the fleet.
        </p>
        <p className="text-xs font-medium text-slate-600 mt-1">
          Calendar view: {calendarText} · {actualStatus}{missingActual} · {horizonText}
        </p>
      </div>

      <div className="min-w-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Parts forecast" value={all.toLocaleString()} sub="every part dealers have ordered" color="blue"/>
        <KpiCard label="Current-month forecast" value={fmt(monthly)}
          sub={`${monthLabel(forecastStart)} forecast · last actual ${fmt(lastActual)}`} color="green"/>
        <KpiCard label="Linked to the fleet" value={data.parc_skus.toLocaleString()}
          sub={`${(data.fleet_share_pct ?? 0).toFixed(1)}% of forecast demand comes from the fleet`} color="purple"/>
        <KpiCard label="Forecast zero" value={data.zero_demand_skus.toLocaleString()} sub="rarely ordered, none recently" color="amber"/>
      </div>

      <div className="min-w-0 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="min-w-0 overflow-hidden bg-white rounded-xl shadow-sm p-5 lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-700">Current and next calendar year — all parts</h3>
          <p className="text-xs text-slate-400 mb-2">Actual dealer demand, then forecast through {monthLabel(forecastEnd)}</p>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={trendData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="demandGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#4361EE" stopOpacity={0.15}/>
                  <stop offset="95%" stopColor="#4361EE" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="month" tick={{ fontSize: 10 }}
                ticks={viewMonths.filter((_, index) => index % 4 === 0 || index === viewMonths.length - 1)}
                interval="preserveStartEnd"/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown, name: unknown) => [
                Number(v).toLocaleString(), String(name),
              ]}/>
              <Area type="monotone" dataKey="actualQty" name="Dealer orders" stroke="#4361EE"
                strokeWidth={2} fill="url(#demandGrad)" isAnimationActive={false}/>
              <Line type="monotone" dataKey="forecastQty" stroke="#16A34A" strokeWidth={2.5}
                name="Forecast" strokeDasharray="6 4" dot={false} isAnimationActive={false}/>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="min-w-0 bg-white rounded-xl shadow-sm p-5">
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
          {validation.length > 0 && <div className="mt-4 pt-3 border-t border-slate-100">
            <div className="grid grid-cols-[1fr_3.5rem_4.5rem] gap-2 text-[10px] uppercase text-slate-400 mb-1">
              <span>Model</span><span className="text-right">RMSSE</span><span className="text-right">Stability</span>
            </div>
            {validation.slice(0, 5).map(v => <div key={v.model} className="grid grid-cols-[1fr_3.5rem_4.5rem] gap-2 text-[11px] py-0.5">
              <span className="truncate text-slate-600">{MODEL_TEXT[v.model] ?? v.model}</span>
              <span className="text-right tabular-nums text-slate-700">{v.rmsse.toFixed(2)}</span>
              <span className="text-right tabular-nums text-slate-500">{v.stability.toFixed(2)}</span>
            </div>)}
          </div>}
        </div>
      </div>

      <div className="min-w-0 bg-white rounded-xl shadow-sm p-5 space-y-3">
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex rounded border border-slate-200 p-0.5" role="group" aria-label="Forecast table view">
            {(["monthly", "summary"] as const).map(view => (
              <button key={view} type="button" onClick={() => setTableView(view)} aria-pressed={tableView === view}
                className={`px-3 py-1.5 text-xs font-medium rounded-sm ${tableView === view ? "bg-brand-blue text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                {view === "monthly" ? "Monthly forecast" : "Planning summary"}
              </button>
            ))}
          </div>
          {tableView === "monthly" && forecastYears.length > 0 && (
            <div className="inline-flex rounded border border-slate-200 p-0.5" role="group" aria-label="Forecast years">
              {["all", ...forecastYears].map(year => (
                <button key={year} type="button" onClick={() => setYearFilter(year)} aria-pressed={yearFilter === year}
                  className={`px-3 py-1.5 text-xs font-medium rounded-sm ${yearFilter === year ? "bg-slate-700 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                  {year === "all" ? `All ${forecastMonths.length} months` : year}
                </button>
              ))}
            </div>
          )}
        </div>
        {tableView === "monthly" && forecastMonths.length > 0 && (
          <p className="text-xs font-medium text-slate-600">Per-part forecast: {monthLabel(forecastMonths[0])} to {monthLabel(forecastMonths[forecastMonths.length - 1])}</p>
        )}
        {tableView === "monthly" && forecastMonths.length > 0 ? (
          <MonthlyForecastTable rows={data.rows} months={forecastMonths} visibleMonths={visibleMonths}
            selectedMonth={selectedMonth} onSelectMonth={setSelectedMonth}/>
        ) : (
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
                <th className="py-2.5 pr-3 text-right" title={`Demand over the ${data.planning.protection_interval_months}-month protection interval (lead time + review); up to = 90% likely not to exceed`}>Next {data.planning.protection_interval_months} months<span className="block normal-case font-normal">expected · up to</span></th>
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
        )}
        <div className="flex justify-between items-center text-xs text-slate-500">
          <span>{data.total ? `${page * pageSize + 1}-${Math.min((page + 1) * pageSize, data.total)} of ${data.total.toLocaleString()}` : "No matching parts"}</span>
          <div className="flex gap-2">
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
        {tableView === "summary" && <p className="text-[11px] text-slate-400">
          Blend: the share given to the part's own history rises with the months it has been ordered (from 20% to 80%); the rest
          comes from its fleet. A part with no model link is forecast from its history alone. "Next {data.planning.protection_interval_months} months" is the
          protection interval — the {data.planning.lead_time_months}-month import lead time plus the monthly review — that safety stock and the order cover.
        </p>}
      </div>
    </div>
  );
}
