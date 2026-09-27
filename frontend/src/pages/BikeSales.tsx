import { useEffect, useState, Fragment } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  AreaChart, Area, Legend, Line, LineChart, ComposedChart,
} from "recharts";
import { Check } from "lucide-react";
import {
  fetchBikes, fetchModelForecast, fetchTargets, saveTargets, fetchTargetBreakdown,
  fetchUpliftInputs, saveUpliftInputs, fetchDealerUpliftBaseline,
  fetchForecastBacktest, type ForecastBacktest, type BacktestStats,
  fetchMonthlyAllocation, type MonthlyAllocationRow,
  fetchActualModelColour, type ActualModelColourRow,
  type BikesData, type ModelForecastData, type SalesTargets, type TargetBreakdownRow,
  type UpliftFactorsRow,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { TimePicker, filterByRange, type TimeRange, YearPicker, filterByYear, getYears, monthLabel } from "../components/TimePicker";

const MODEL_COLORS = ["#4361EE","#EF4444","#2CC56F","#FFC107","#7C3AED","#06B6D4","#F97316","#94A3B8","#10B981","#EC4899"];

function colorHex(name: string): string {
  const u = name.toUpperCase();
  if (u.includes("REDDISH YELLOW") || u.includes("YELLOW COCKTAIL")) return "#FFC107";
  if (u.includes("YELLOW"))  return "#FFC107";
  if (u.includes("ORANGE"))  return "#F97316";
  if (u.includes("GREEN"))   return "#2CC56F";
  if (u.includes("CYAN"))    return "#06B6D4";
  if (u.includes("BLUE") || u.includes("PURPLISH")) return "#4361EE";
  if (u.includes("GRAY") || u.includes("GREY"))     return "#94A3B8";
  if (u.includes("RED"))     return "#EF4444";
  if (u.includes("BLACK"))   return "#1E293B";
  return "#CBD5E1";
}

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

export function BikeSales() {
  const [data,      setData]      = useState<BikesData | null>(null);
  const [modelFcst, setModelFcst] = useState<ModelForecastData | null>(null);
  // Opens on everything: the history and the whole forecast horizon, which runs into next year.
  const [forecastYear,  setForecastYear]  = useState<number | "All">("All");
  const [forecastRange, setForecastRange] = useState<TimeRange>("All");
  const [selectedModel, setSelectedModel] = useState<string>("All Models");
  const [targets,      setTargets]      = useState<SalesTargets>({ yearly_target: 40000, monthly_overrides: {} });
  const [draftYearly,  setDraftYearly]  = useState("40000");
  const [draftMonthly, setDraftMonthly] = useState<Record<string, string>>({});
  const [pinnedMonths, setPinnedMonths] = useState<Set<string>>(new Set());
  const [saving,       setSaving]       = useState(false);
  const [breakdownMonth,   setBreakdownMonth]   = useState<string | null>(null);
  const [breakdown,        setBreakdown]        = useState<TargetBreakdownRow[] | null>(null);
  const [breakdownTarget,  setBreakdownTarget]  = useState<number | null>(null);
  const [breakdownLoading, setBreakdownLoading] = useState(false);

  const [view, setView] = useState<"forecast" | "target">("forecast");
  const [amfView, setAmfView] = useState<"year" | "next12">("year");

  // Backtest: fit on a past window, forecast the months after it, compare with actuals.
  const [btStart, setBtStart] = useState("2025-04");
  const [btEnd,   setBtEnd]   = useState("2025-12");
  const [backtest, setBacktest] = useState<ForecastBacktest | null>(null);
  const [btMethod, setBtMethod] = useState<string | null>(null);
  useEffect(() => {
    if (!/^\d{4}-\d{2}$/.test(btStart) || !/^\d{4}-\d{2}$/.test(btEnd) || btEnd < btStart) return;
    let live = true;
    fetchForecastBacktest(btStart, btEnd, 12).then(d => { if (live) setBacktest(d); });
    return () => { live = false; };
  }, [btStart, btEnd]);

  // Monthly allocation: each future month's target split to models and colours (whole units).
  const [monthlyAlloc, setMonthlyAlloc] = useState<MonthlyAllocationRow[] | null>(null);
  // Actual sold per model, colour and month — the closed months of the allocation table.
  const [actualMC, setActualMC] = useState<ActualModelColourRow[] | null>(null);
  useEffect(() => {
    const year = typeof forecastYear === "number" ? forecastYear : new Date().getFullYear();
    let live = true;
    fetchActualModelColour(year).then(d => { if (live) setActualMC(d); });
    return () => { live = false; };
  }, [forecastYear]);
  useEffect(() => {
    if (!data) return;
    const year = typeof forecastYear === "number" ? forecastYear : new Date().getFullYear();
    const lastActual = data.sales_forecast.filter(r => !r.is_forecast).map(r => r.period).sort().pop() ?? "";
    const perMonth = Math.round(Number(draftYearly) / 12) || 0;
    const targets: Record<string, number> = {};
    for (let m = 1; m <= 12; m++) {
      const k = `${year}-${String(m).padStart(2, "0")}`;
      if (k > lastActual) targets[k] = Number(draftMonthly[k] ?? perMonth) || 0;
    }
    if (Object.keys(targets).length === 0) { setMonthlyAlloc([]); return; }
    let live = true;
    const timer = setTimeout(() => {
      fetchMonthlyAllocation(targets).then(d => { if (live) setMonthlyAlloc(d); });
    }, 300);  // wait for typing to pause before re-allocating
    return () => { live = false; clearTimeout(timer); };
  }, [data, forecastYear, draftYearly, draftMonthly]);

  // Uplift factors state
  const [upliftOpen,        setUpliftOpen]        = useState(false);
  const [upliftInputs,      setUpliftInputs]      = useState<Record<string, UpliftFactorsRow>>({});
  const [dealerBaseline,    setDealerBaseline]    = useState<Record<string, number>>({});
  const [savingUplift,      setSavingUplift]      = useState(false);

  useEffect(() => {
    fetchBikes().then(d => {
      setData(d);
      const year = new Date().getFullYear();
      if (getYears(d.sales_forecast).includes(year)) setForecastYear(year);
    });
    fetchModelForecast().then(setModelFcst);
    fetchTargets().then(t => {
      const year = new Date().getFullYear();
      setTargets(t);
      setDraftYearly(String(t.yearly_target));
      setDraftMonthly(buildMonthlyDraft(t.yearly_target, t.monthly_overrides, year));
      setPinnedMonths(new Set(Object.keys(t.monthly_overrides).filter(k => k.startsWith(`${year}-`))));
      loadBreakdown("Yearly", t.yearly_target);
    });
    fetchUpliftInputs().then(rows => {
      const map: Record<string, UpliftFactorsRow> = {};
      rows.forEach(r => { map[r.month_key] = r; });
      setUpliftInputs(map);
    });
    fetchDealerUpliftBaseline().then(setDealerBaseline);
  }, []);

  const TARGET_YEAR = typeof forecastYear === "number" ? forecastYear : new Date().getFullYear();
  const MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  function monthKey(year: number, m: number) {
    return `${year}-${String(m).padStart(2, "0")}`;
  }

  function buildMonthlyDraft(yearly: number, overrides: Record<string, number>, year: number) {
    const def = Math.round(yearly / 12) || 0;
    const draft: Record<string, string> = {};
    for (let m = 1; m <= 12; m++) {
      const k = monthKey(year, m);
      draft[k] = String(overrides[k] ?? def);
    }
    return draft;
  }

  // lockUpToMonth: months 1..lockUpToMonth keep their current value; only later unpinned months rebalance.
  function rebalanceFree(
    yearly: number,
    pinned: Set<string>,
    draft: Record<string, string>,
    changedKey?: string,
    changedVal?: string,
    lockUpToMonth: number = 0,
  ): Record<string, string> {
    const next = { ...draft };
    if (changedKey !== undefined) next[changedKey] = changedVal ?? "";
    let lockedSum = 0;
    const freeMths: string[] = [];
    for (let m = 1; m <= 12; m++) {
      const mk = monthKey(TARGET_YEAR, m);
      if (m <= lockUpToMonth || pinned.has(mk)) {
        lockedSum += Number(next[mk]) || 0;
      } else {
        freeMths.push(mk);
      }
    }
    const remaining = yearly - lockedSum;
    const freeCount = freeMths.length;
    if (freeCount > 0 && remaining >= 0) {
      const base = Math.floor(remaining / freeCount);
      const rem = remaining - base * freeCount;
      freeMths.forEach((mk, i) => { next[mk] = String(base + (i < rem ? 1 : 0)); });
    }
    // If freeCount === 0 or remaining < 0: leave values as-is — UI shows imbalance warning.
    return next;
  }

  function handleYearlyChange(val: string) {
    setDraftYearly(val);
    const yearly = Number(val) || 0;
    // Only rebalance from the current calendar month onward; past months are frozen.
    const lockUpto = new Date().getMonth(); // getMonth() is 0-based → equals (currentMonth - 1)
    setDraftMonthly(prev => rebalanceFree(yearly, pinnedMonths, prev, undefined, undefined, lockUpto));
  }

  function handleMonthChange(k: string, val: string) {
    const newPinned = new Set(pinnedMonths).add(k);
    setPinnedMonths(newPinned);
    // Freeze the edited month and everything before it; rebalance only what comes after.
    const m = parseInt(k.split("-")[1]); // 1-12
    setDraftMonthly(prev => rebalanceFree(Number(draftYearly) || 0, newPinned, prev, k, val, m));
  }

  function resetMonthlyToDefault() {
    setPinnedMonths(new Set());
    const def = Math.round(Number(draftYearly) / 12) || 0;
    const reset: Record<string, string> = {};
    for (let m = 1; m <= 12; m++) {
      reset[monthKey(TARGET_YEAR, m)] = String(def);
    }
    setDraftMonthly(prev => ({ ...prev, ...reset }));
  }

  function loadBreakdown(k: string, targetVal: number) {
    setBreakdownMonth(k);
    setBreakdownTarget(targetVal);
    setBreakdownLoading(true);
    setBreakdown(null);
    fetchTargetBreakdown(k, targetVal).then(d => { setBreakdown(d); setBreakdownLoading(false); });
  }

  function getUpliftRow(k: string): UpliftFactorsRow {
    return upliftInputs[k] ?? {
      month_key: k,
      promotion_pct: 0, new_model_pct: 0,
      dealer_pct: dealerBaseline[k] ?? 0,
      pricing_pct: 0, other_pct: 0,
    };
  }

  function setUpliftField(k: string, field: keyof Omit<UpliftFactorsRow, "month_key">, val: string) {
    setUpliftInputs(prev => ({
      ...prev,
      [k]: { ...getUpliftRow(k), [field]: parseFloat(val) || 0 },
    }));
  }

  function totalUpliftPct(k: string): number {
    const r = getUpliftRow(k);
    return r.promotion_pct + r.new_model_pct + r.dealer_pct + r.pricing_pct + r.other_pct;
  }

  function handleSaveUplift() {
    setSavingUplift(true);
    const rows = Object.values(upliftInputs);
    saveUpliftInputs(rows).finally(() => setSavingUplift(false));
  }

  function handleSaveTargets() {
    setSaving(true);
    const yearly = Number(draftYearly) || 0;
    const def = Math.round(yearly / 12);
    // Only persist months that deviate from the default
    const overrides: Record<string, number> = { ...targets.monthly_overrides };
    for (const [k, v] of Object.entries(draftMonthly)) {
      const num = Number(v) || 0;
      if (num !== def) {
        overrides[k] = num;
      } else {
        delete overrides[k];
      }
    }
    const updated: SalesTargets = { yearly_target: yearly, monthly_overrides: overrides };
    saveTargets(updated).then(() => {
      setTargets(updated);
      setSaving(false);
      fetchBikes().then(setData);
    });
  }

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const { sales_forecast } = data;

  const actualSales  = sales_forecast.filter(r => !r.is_forecast);
  const latestActual = actualSales[actualSales.length - 1];
  const forecastOnly = sales_forecast.filter(r => r.is_forecast);

  // ── Time-filtered data ──────────────────────────────────────────────────────
  const fcstFiltered = filterByRange(filterByYear(sales_forecast, forecastYear), forecastRange);


  // ── Model forecast pivot (period → { model: count }) ────────────────────────
  // Forecast Base works on active models (Sales Summery Model Classification status).
  const allModels = modelFcst?.active_models ?? modelFcst?.models ?? [];
  const inactiveModels = (modelFcst?.models ?? []).filter(m => !allModels.includes(m));

  /** Stacked bar data for "All Models" view */
  const modelStackData = (() => {
    if (!modelFcst) return [];
    const periods = [...new Set(modelFcst.rows.map(r => r.period))].sort();
    return filterByRange(filterByYear(
      periods.map(p => {
        const obj: Record<string, number | string | boolean> = { period: p, is_forecast: false };
        let isFcst = false;
        for (const r of modelFcst.rows.filter(x => x.period === p)) {
          obj[r.model] = r.actual ?? r.forecast;
          if (r.is_forecast) isFcst = true;
        }
        obj.is_forecast = isFcst;
        return obj as { period: string; is_forecast: boolean } & Record<string, number>;
      }),
      forecastYear,
    ), forecastRange);
  })();

  /** Single-model line data */
  const singleModelData = (() => {
    if (!modelFcst || selectedModel === "All Models") return [];
    return filterByRange(filterByYear(
      modelFcst.rows
        .filter(r => r.model === selectedModel)
        .sort((a, b) => a.period.localeCompare(b.period))
        .map(r => ({ period: r.period, actual: r.actual, forecast: r.forecast, is_forecast: r.is_forecast })),
      forecastYear,
    ), forecastRange);
  })();

  /** Forecast with the month's uplift factors applied (forecast months only). */
  function adjustedForecast(r: { period: string; forecast: number; is_forecast: boolean }): number {
    return r.is_forecast ? Math.round(r.forecast * (1 + totalUpliftPct(r.period) / 100)) : r.forecast;
  }

  // ── Target Base rows: the 12 months of the target year, targets live from the editor ──
  const targetDefault = Math.round(Number(draftYearly) / 12) || 0;
  const targetRows = MONTH_LABELS.map((label, idx) => {
    const key = monthKey(TARGET_YEAR, idx + 1);
    const row = sales_forecast.find(r => r.period === key);
    const target = Number(draftMonthly[key] ?? targetDefault) || 0;
    const actual = row && !row.is_forecast ? row.actual : null;
    const adjusted = row && row.is_forecast ? adjustedForecast(row) : null;
    // What the month is measured on: the actual once closed, the adjusted forecast before.
    const outlook = actual ?? adjusted;
    return { key, label, target, actual, adjusted, outlook };
  });
  const targetYearTotal = targetRows.reduce((s, r) => s + r.target, 0);
  const closed = targetRows.filter(r => r.actual != null);
  const ytdActual = closed.reduce((s, r) => s + (r.actual ?? 0), 0);
  const ytdTarget = closed.reduce((s, r) => s + r.target, 0);
  const yearOutlook = targetRows.reduce((s, r) => s + (r.actual ?? r.adjusted ?? 0), 0);

  // ── Active model forecast: next 12 months per model against its last 12 months ──
  const mfRows = modelFcst?.rows ?? [];
  const fcPeriods = [...new Set(mfRows.filter(r => r.is_forecast).map(r => r.period))].sort();
  const actualPeriods = [...new Set(mfRows.filter(r => !r.is_forecast).map(r => r.period))].sort();
  const last12 = new Set(actualPeriods.slice(-12));
  const infoByModel = new Map((modelFcst?.model_info ?? []).map(m => [m.model, m]));
  const NEW_LAUNCH_MONTHS = 6;
  const activeForecast = allModels.map(model => {
    const rows = mfRows.filter(r => r.model === model);
    const byPeriod = new Map(rows.filter(r => r.is_forecast).map(r => [r.period, r.forecast]));
    const last12Actual = rows.filter(r => !r.is_forecast && last12.has(r.period))
      .reduce((s, r) => s + (r.actual ?? 0), 0);
    const next12 = fcPeriods.reduce((s, p) => s + (byPeriod.get(p) ?? 0), 0);
    const next12Adj = fcPeriods.reduce((s, p) => s + (byPeriod.get(p) ?? 0) * (1 + totalUpliftPct(p) / 100), 0);
    return {
      model, byPeriod, last12Actual, next12, next12Adj,
      growth: last12Actual ? next12 / last12Actual - 1 : null,
      history: infoByModel.get(model)?.history_months ?? 0,
    };
  }).sort((a, b) => b.next12 - a.next12);
  const activeNext12 = activeForecast.reduce((s, r) => s + r.next12, 0);
  const activeNext12Adj = activeForecast.reduce((s, r) => s + r.next12Adj, 0);
  const activeLast12 = activeForecast.reduce((s, r) => s + r.last12Actual, 0);
  const activeChart = activeForecast.map(r => ({
    model: r.model, "Last 12 months (actual)": r.last12Actual, "Next 12 months (forecast)": Math.round(r.next12),
  }));

  // ── Current year per active model: actual for closed months, base forecast after ──
  const CURRENT_YEAR = new Date().getFullYear();
  const yearMonths = MONTH_LABELS.map((_, i) => monthKey(CURRENT_YEAR, i + 1));
  const lastActualPeriod = actualPeriods[actualPeriods.length - 1] ?? "";
  const yearClosed = yearMonths.filter(p => p <= lastActualPeriod);
  const yearOpen = yearMonths.filter(p => p > lastActualPeriod);
  const yearByModel = allModels.map(model => {
    const rows = mfRows.filter(r => r.model === model);
    const cells = new Map<string, number>();
    for (const p of yearMonths) {
      const row = rows.find(r => r.period === p);
      cells.set(p, row ? (row.is_forecast ? row.forecast : (row.actual ?? 0)) : 0);
    }
    const ytd = yearClosed.reduce((s, p) => s + (cells.get(p) ?? 0), 0);
    const rest = yearOpen.reduce((s, p) => s + (cells.get(p) ?? 0), 0);
    const restAdj = yearOpen.reduce((s, p) => s + (cells.get(p) ?? 0) * (1 + totalUpliftPct(p) / 100), 0);
    return { model, cells, ytd, rest, restAdj, history: infoByModel.get(model)?.history_months ?? 0 };
  }).filter(r => r.ytd + r.rest > 0).sort((a, b) => (b.ytd + b.rest) - (a.ytd + a.rest));
  const yearTotals = yearByModel.reduce(
    (s, r) => ({ ytd: s.ytd + r.ytd, rest: s.rest + r.rest, restAdj: s.restAdj + r.restAdj }),
    { ytd: 0, rest: 0, restAdj: 0 });

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <h2 className="text-xl font-bold text-slate-800">Unit Sales Forecast</h2>
      <p className="text-xs text-slate-500 -mt-4">Published unit forecast for active models — one backtest-selected method feeds every figure on this page; targets and uplift are planning inputs</p>

      <div className="flex gap-1 border-b border-slate-200 -mb-2">
        {(["forecast", "target"] as const).map(v => (
          <button key={v} onClick={() => setView(v)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              view === v ? "border-brand-blue text-brand-blue" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}>
            {v === "forecast" ? "Forecast Base" : "Target Base"}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        {view === "forecast" && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <KpiCard label="Latest Actual"  value={fmt(latestActual?.actual ?? 0)}    sub={latestActual?.period ?? ""} color="blue"/>
              <KpiCard label="Next Month"     value={fmt(forecastOnly[0]?.forecast ?? 0)} sub={forecastOnly[0]?.period ?? ""} color="purple"/>
              <KpiCard label="12-mo Base Forecast" value={fmt(forecastOnly.reduce((s,r)=>s+r.forecast,0))} sub={data.forecast_method ? "published, backtest-selected" : "published"} color="green"/>
              <KpiCard label="12-mo Adjusted" value={fmt(forecastOnly.reduce((s,r)=>s+adjustedForecast(r),0))} sub="with uplift factors" color="purple"/>
            </div>

            <div>
              {/* Controls row — always visible regardless of selected model */}
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-slate-500">Model:</span>
                  <select
                    className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
                    value={selectedModel}
                    onChange={e => setSelectedModel(e.target.value)}
                  >
                    <option value="All Models">All Models (Total)</option>
                    <optgroup label="By Model">
                      {allModels.map(m => <option key={m} value={m}>{m}</option>)}
                    </optgroup>
                  </select>
                </div>
                <div className="flex-1"/>
                <div className="flex items-center gap-2">
                  <YearPicker years={getYears(sales_forecast)} value={forecastYear} onChange={setForecastYear}/>
                  <TimePicker value={forecastRange} onChange={setForecastRange}/>
                </div>
              </div>

              {/* ── Uplift Factors accordion ── */}
              {(() => {
                const FACTORS: { key: keyof Omit<UpliftFactorsRow, "month_key">; label: string }[] = [
                  { key: "promotion_pct",  label: "Promotions" },
                  { key: "new_model_pct", label: "New Model" },
                  { key: "dealer_pct",    label: "Dealer Exp." },
                  { key: "pricing_pct",   label: "Pricing" },
                  { key: "other_pct",     label: "Other" },
                ];
                return (
                  <div className="border border-slate-200 rounded-xl overflow-hidden">
                    {/* Accordion header */}
                    <button
                      onClick={() => setUpliftOpen(o => !o)}
                      className="w-full flex items-center justify-between px-4 py-2.5 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
                    >
                      <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
                        ▲ Uplift Factors
                        <span className="ml-2 font-normal text-slate-400 normal-case tracking-normal">
                          — adjust base forecast for promotions, new models, dealer growth, pricing
                        </span>
                      </span>
                      <span className="text-xs text-slate-400">{upliftOpen ? "▲ collapse" : "▼ expand"}</span>
                    </button>

                    {upliftOpen && (
                      <div className="p-4 space-y-3 bg-white">
                        <div className="overflow-x-auto">
                          <table className="text-xs w-full">
                            <thead>
                              <tr className="border-b border-slate-200">
                                <th className="py-1.5 pr-4 text-left font-medium text-slate-500 uppercase tracking-wide w-28">Factor</th>
                                {MONTH_LABELS.map((lbl, idx) => {
                                  const k = monthKey(TARGET_YEAR, idx + 1);
                                  const tot = totalUpliftPct(k);
                                  return (
                                    <th key={k} className="py-1.5 px-1 text-center font-medium text-slate-500 min-w-[58px]">
                                      <div>{lbl}</div>
                                      {tot !== 0 && (
                                        <div className={`text-[10px] font-bold ${tot > 0 ? "text-green-600" : "text-red-500"}`}>
                                          {tot > 0 ? "+" : ""}{tot.toFixed(1)}%
                                        </div>
                                      )}
                                    </th>
                                  );
                                })}
                              </tr>
                            </thead>
                            <tbody>
                              {FACTORS.map(({ key, label }) => (
                                <tr key={key} className="border-b border-slate-50">
                                  <td className="py-1.5 pr-4 font-medium text-slate-600">
                                    {label}
                                    {key === "dealer_pct" && (
                                      <span className="ml-1 text-[10px] text-slate-400">*auto</span>
                                    )}
                                  </td>
                                  {MONTH_LABELS.map((_, idx) => {
                                    const k = monthKey(TARGET_YEAR, idx + 1);
                                    const val = getUpliftRow(k)[key];
                                    return (
                                      <td key={k} className="py-1 px-1">
                                        <div className="relative">
                                          <input
                                            type="number"
                                            step="0.1"
                                            value={val === 0 ? "" : val}
                                            placeholder="0"
                                            onChange={e => setUpliftField(k, key, e.target.value)}
                                            className={`w-full rounded px-1 py-1 text-[11px] text-center border focus:outline-none focus:ring-1 focus:ring-brand-blue/40 ${
                                              val > 0 ? "border-green-300 bg-green-50 text-green-700" :
                                              val < 0 ? "border-red-300 bg-red-50 text-red-700" :
                                              "border-slate-200 bg-white text-slate-500"
                                            }`}
                                          />
                                          <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[9px] text-slate-400 pointer-events-none">%</span>
                                        </div>
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                              {/* Total row */}
                              <tr className="bg-slate-50 font-semibold">
                                <td className="py-1.5 pr-4 text-slate-700">Total uplift</td>
                                {MONTH_LABELS.map((_, idx) => {
                                  const k = monthKey(TARGET_YEAR, idx + 1);
                                  const tot = totalUpliftPct(k);
                                  return (
                                    <td key={k} className={`py-1.5 px-1 text-center text-[11px] ${
                                      tot > 0 ? "text-green-600" : tot < 0 ? "text-red-500" : "text-slate-400"
                                    }`}>
                                      {tot !== 0 ? `${tot > 0 ? "+" : ""}${tot.toFixed(1)}%` : "—"}
                                    </td>
                                  );
                                })}
                              </tr>
                            </tbody>
                          </table>
                        </div>
                        <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                          <p className="text-[11px] text-slate-400">
                            *Dealer Exp. auto-filled from MCSI active-dealer trend (0.8× elasticity) — editable
                          </p>
                          <button
                            onClick={handleSaveUplift}
                            disabled={savingUplift}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-brand-blue text-white hover:bg-blue-700 transition-colors disabled:opacity-50"
                          >
                            <Check size={13}/> {savingUplift ? "Saving…" : "Save Uplift"}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}

              {selectedModel === "All Models" && (
              <>
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-1">Total — Actual vs Forecast (80% CI)</h3>
                  <p className="text-xs text-slate-400 mb-3">Active models. Shaded band = 80% range from what this method actually missed by in the backtest (months 7+ widened by assumption). Dashed = forecast.</p>
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={fcstFiltered} margin={{ top:5, right:10, left:0, bottom:5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                      <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                        tickFormatter={p => monthLabel(p, forecastYear !== "All")}/>
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                      <Tooltip formatter={(v: unknown) => v != null ? Math.round(Number(v)).toLocaleString() : "—"}/>
                      <Legend/>
                      <Area type="monotone" dataKey="upper_80" stroke="none" fill="#4361EE" fillOpacity={0.15} name="Upper 80%"/>
                      <Area type="monotone" dataKey="lower_80" stroke="none" fill="#fff" fillOpacity={1} name="Lower 80%" legendType="none"/>
                      <Area type="monotone" dataKey="forecast" stroke="#4361EE" strokeWidth={2} fill="none" name="Forecast" strokeDasharray="5 3"/>
                      <Area type="monotone" dataKey="actual"   stroke="#2CC56F" strokeWidth={2} fill="none" name="Actual" dot={{ r: 3 }}/>
                    </AreaChart>
                  </ResponsiveContainer>
                </div>

                {/* Stacked bar by model */}
                {modelFcst && (
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Sales &amp; Forecast by Model</h3>
                    <p className="text-xs text-slate-400 mb-3">Stacked bars show each model's contribution. Lighter colors = forecast periods.</p>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={modelStackData} margin={{ top:5, right:10, left:0, bottom:5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                        <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                          tickFormatter={p => monthLabel(p, forecastYear !== "All")}/>
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                        <Tooltip formatter={(v: unknown, n: unknown) => [Math.round(Number(v)).toLocaleString(), String(n)]}/>
                        <Legend wrapperStyle={{ fontSize: 10 }}/>
                        {allModels.map((m, i) => (
                          <Bar key={m} dataKey={m} stackId="a" fill={MODEL_COLORS[i % MODEL_COLORS.length]}
                            name={m} radius={i === allModels.length - 1 ? [3,3,0,0] : undefined}
                          >
                            {modelStackData.map((entry, idx) => (
                              <Cell key={`${m}-${idx}`} fillOpacity={entry.is_forecast ? 0.45 : 1}/>
                            ))}
                          </Bar>
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </>
            )}

              {/* ── Single model: actuals + forecast line ── */}
              {selectedModel !== "All Models" && (
              <div>
                <h3 className="text-sm font-semibold text-slate-700 mb-1">
                  {selectedModel} — Actual vs Forecast
                </h3>
                <p className="text-xs text-slate-400 mb-3">
                  Forecast = this model's share of its family's recent sales (latest month weighted most) × the total's 3-month level on a damped growth trend — the same method as every other figure on this page.
                </p>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={singleModelData} margin={{ top:5, right:10, left:0, bottom:5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                      tickFormatter={p => monthLabel(p, forecastYear !== "All")}/>
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                    <Tooltip formatter={(v: unknown, n: unknown) => [v != null ? Math.round(Number(v)).toLocaleString() : "—", String(n)]}/>
                    <Legend/>
                    <Line type="monotone" dataKey="actual"   stroke="#2CC56F" strokeWidth={2.5} dot={{ r: 4 }} name="Actual" connectNulls={false}/>
                    <Line type="monotone" dataKey="forecast" stroke="#4361EE" strokeWidth={2} strokeDasharray="6 3" dot={false} name="Forecast"/>
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

              {/* ── Active model forecast ── */}
              {activeForecast.length > 0 && (
                <div className="border border-slate-200 rounded-xl p-4 space-y-4">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="flex-1 min-w-[260px]">
                      <h3 className="text-sm font-semibold text-slate-700">
                        {amfView === "year"
                          ? <>Active Model Forecast — {CURRENT_YEAR} <span className="font-normal text-slate-400">(actual to {lastActualPeriod || "—"}, forecast after)</span></>
                          : <>Active Model Forecast — next {fcPeriods.length} months
                              {fcPeriods.length > 0 && (
                                <span className="ml-1.5 font-normal text-slate-400">({fcPeriods[0]} → {fcPeriods[fcPeriods.length - 1]})</span>
                              )}</>}
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {allModels.length} models Active in Sales Summery's Model Classification
                        {inactiveModels.length > 0 && <> · not shown (not active): {inactiveModels.join(", ")}</>}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {(["year", "next12"] as const).map(v => (
                        <button key={v} onClick={() => setAmfView(v)}
                          className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors border ${
                            amfView === v ? "bg-slate-700 text-white border-slate-700" : "text-slate-500 border-slate-200 hover:bg-slate-50"
                          }`}>
                          {v === "year" ? `Current year ${CURRENT_YEAR}` : "Next 12 months"}
                        </button>
                      ))}
                    </div>
                  </div>

                  {amfView === "year" ? (
                    <>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <KpiCard label={`YTD actual ${CURRENT_YEAR}`} value={fmt(yearTotals.ytd)}
                          sub={yearClosed.length ? `${yearClosed[0].slice(5)}–${yearClosed[yearClosed.length - 1].slice(5)} · sold VINs` : "no closed month yet"} color="green"/>
                        <KpiCard label="Rest of year (base)" value={fmt(Math.round(yearTotals.rest))}
                          sub={yearOpen.length ? `${yearOpen.length} month(s) forecast` : "year complete"} color="blue"/>
                        <KpiCard label={`Full year ${CURRENT_YEAR}`} value={fmt(Math.round(yearTotals.ytd + yearTotals.rest))}
                          sub="actual + base forecast" color="purple"/>
                        <KpiCard label="Full year with uplift" value={fmt(Math.round(yearTotals.ytd + yearTotals.restAdj))}
                          sub="uplift on forecast months only" color="purple"/>
                      </div>

                      <ResponsiveContainer width="100%" height={Math.max(220, yearByModel.length * 34)}>
                        <BarChart data={yearByModel.map(r => ({ model: r.model, "YTD actual": r.ytd, "Rest of year (forecast)": Math.round(r.rest) }))}
                          layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                          <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                          <YAxis type="category" dataKey="model" tick={{ fontSize: 10 }} width={200}/>
                          <Tooltip formatter={(v: unknown, n: unknown) => [Math.round(Number(v)).toLocaleString(), String(n)]}/>
                          <Legend wrapperStyle={{ fontSize: 11 }}/>
                          <Bar dataKey="YTD actual" stackId="y" fill="#2CC56F"/>
                          <Bar dataKey="Rest of year (forecast)" stackId="y" fill="#93A5F5" radius={[0, 3, 3, 0]}/>
                        </BarChart>
                      </ResponsiveContainer>

                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-200 text-left text-slate-500 uppercase">
                              <th className="py-2 pr-3 sticky left-0 bg-white">Model</th>
                              <th className="py-2 px-2 text-right text-green-600">YTD actual</th>
                              <th className="py-2 px-2 text-right text-brand-blue">Rest of year</th>
                              <th className="py-2 px-2 text-right">Full year</th>
                              <th className="py-2 px-2 text-right text-violet-600">With uplift</th>
                              <th className="py-2 px-2 text-right">Share</th>
                              {yearMonths.map(p => (
                                <th key={p} className={`py-2 px-2 text-right normal-case ${yearOpen.includes(p) ? "text-brand-blue" : "text-green-700"}`}>
                                  {monthLabel(p, true)}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {yearByModel.map(r => (
                              <tr key={r.model} className="border-b border-slate-50 hover:bg-slate-50/50">
                                <td className="py-1.5 pr-3 font-medium text-slate-800 whitespace-nowrap sticky left-0 bg-white">
                                  {r.model}
                                  {r.history < NEW_LAUNCH_MONTHS && (
                                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-semibold"
                                      title="Few months of sales — the forecast rests on very little history">new · {r.history} mo</span>
                                  )}
                                </td>
                                <td className="py-1.5 px-2 text-right font-semibold text-green-600">{r.ytd.toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right text-brand-blue">{Math.round(r.rest).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right font-bold text-slate-800">{Math.round(r.ytd + r.rest).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right font-semibold text-violet-600">{Math.round(r.ytd + r.restAdj).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right text-slate-500">
                                  {yearTotals.ytd + yearTotals.rest ? `${((r.ytd + r.rest) / (yearTotals.ytd + yearTotals.rest) * 100).toFixed(1)}%` : "—"}
                                </td>
                                {yearMonths.map(p => {
                                  const open = yearOpen.includes(p);
                                  const v = r.cells.get(p) ?? 0;
                                  return (
                                    <td key={p} className={`py-1.5 px-2 text-right tabular-nums ${open ? "bg-blue-50/60 text-brand-blue italic" : "text-green-700"}`}>
                                      {Math.round(v).toLocaleString()}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                            <tr className="border-t-2 border-slate-200 font-semibold">
                              <td className="py-1.5 pr-3 text-slate-700 sticky left-0 bg-white">All active models</td>
                              <td className="py-1.5 px-2 text-right text-green-700">{yearTotals.ytd.toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-brand-blue">{Math.round(yearTotals.rest).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-slate-800">{Math.round(yearTotals.ytd + yearTotals.rest).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-violet-700">{Math.round(yearTotals.ytd + yearTotals.restAdj).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-slate-600">100.0%</td>
                              {yearMonths.map(p => (
                                <td key={p} className={`py-1.5 px-2 text-right tabular-nums ${yearOpen.includes(p) ? "bg-blue-50/60 text-brand-blue italic" : "text-green-800"}`}>
                                  {Math.round(yearByModel.reduce((s, r) => s + (r.cells.get(p) ?? 0), 0)).toLocaleString()}
                                </td>
                              ))}
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <p className="text-[11px] text-slate-400">
                        <span className="text-green-700 font-semibold">Green</span> months are actual sold VINs;
                        <span className="text-brand-blue font-semibold italic"> blue</span> months are the published base forecast.
                        "With uplift" applies the Uplift Factors to the forecast months only — actuals are never adjusted.
                        A <span className="text-amber-700 font-semibold">new</span> badge marks models with under {NEW_LAUNCH_MONTHS} months of sales.
                      </p>
                    </>
                  ) : (
                    <>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <KpiCard label="Next 12M (base)" value={fmt(Math.round(activeNext12))} sub="active models" color="blue"/>
                        <KpiCard label="Next 12M (with uplift)" value={fmt(Math.round(activeNext12Adj))} sub="uplift factors applied" color="purple"/>
                        <KpiCard label="Last 12M actual" value={fmt(activeLast12)} sub="sold VINs, active models" color="green"/>
                        <KpiCard label="Change" value={activeLast12 ? `${((activeNext12 / activeLast12 - 1) * 100).toFixed(1)}%` : "—"}
                          sub="next 12M base vs last 12M" color={activeNext12 >= activeLast12 ? "green" : "red"}/>
                      </div>

                      <ResponsiveContainer width="100%" height={Math.max(220, activeChart.length * 34)}>
                        <BarChart data={activeChart} layout="vertical" margin={{ top: 5, right: 30, left: 10, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                          <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                          <YAxis type="category" dataKey="model" tick={{ fontSize: 10 }} width={200}/>
                          <Tooltip formatter={(v: unknown, n: unknown) => [Math.round(Number(v)).toLocaleString(), String(n)]}/>
                          <Legend wrapperStyle={{ fontSize: 11 }}/>
                          <Bar dataKey="Last 12 months (actual)" fill="#2CC56F" radius={[0, 3, 3, 0]}/>
                          <Bar dataKey="Next 12 months (forecast)" fill="#4361EE" radius={[0, 3, 3, 0]}/>
                        </BarChart>
                      </ResponsiveContainer>

                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-200 text-left text-slate-500 uppercase">
                              <th className="py-2 pr-3 sticky left-0 bg-white">Model</th>
                              <th className="py-2 px-2 text-right">Last 12M</th>
                              <th className="py-2 px-2 text-right text-brand-blue">Next 12M</th>
                              <th className="py-2 px-2 text-right text-violet-600">With uplift</th>
                              <th className="py-2 px-2 text-right">Change</th>
                              <th className="py-2 px-2 text-right">Share</th>
                              {fcPeriods.map(p => (
                                <th key={p} className="py-2 px-2 text-right font-mono normal-case">{monthLabel(p, false)}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {activeForecast.map(r => (
                              <tr key={r.model} className="border-b border-slate-50 hover:bg-slate-50/50">
                                <td className="py-1.5 pr-3 font-medium text-slate-800 whitespace-nowrap sticky left-0 bg-white">
                                  {r.model}
                                  {r.history < NEW_LAUNCH_MONTHS && (
                                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-semibold"
                                      title="Few months of sales — the forecast rests on very little history">new · {r.history} mo</span>
                                  )}
                                </td>
                                <td className="py-1.5 px-2 text-right text-green-600">{r.last12Actual.toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right font-semibold text-brand-blue">{Math.round(r.next12).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right font-semibold text-violet-600">{Math.round(r.next12Adj).toLocaleString()}</td>
                                <td className={`py-1.5 px-2 text-right ${r.growth == null ? "text-slate-300" : r.growth >= 0 ? "text-green-600" : "text-red-500"}`}>
                                  {r.growth == null ? "—" : `${r.growth >= 0 ? "+" : ""}${(r.growth * 100).toFixed(1)}%`}
                                </td>
                                <td className="py-1.5 px-2 text-right text-slate-500">
                                  {activeNext12 ? `${(r.next12 / activeNext12 * 100).toFixed(1)}%` : "—"}
                                </td>
                                {fcPeriods.map(p => (
                                  <td key={p} className="py-1.5 px-2 text-right text-slate-600 tabular-nums">
                                    {Math.round(r.byPeriod.get(p) ?? 0).toLocaleString()}
                                  </td>
                                ))}
                              </tr>
                            ))}
                            <tr className="border-t-2 border-slate-200 font-semibold">
                              <td className="py-1.5 pr-3 text-slate-700 sticky left-0 bg-white">All active models</td>
                              <td className="py-1.5 px-2 text-right text-green-700">{activeLast12.toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-brand-blue">{Math.round(activeNext12).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-violet-700">{Math.round(activeNext12Adj).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-slate-600">
                                {activeLast12 ? `${activeNext12 >= activeLast12 ? "+" : ""}${((activeNext12 / activeLast12 - 1) * 100).toFixed(1)}%` : "—"}
                              </td>
                              <td className="py-1.5 px-2 text-right text-slate-600">100.0%</td>
                              {fcPeriods.map(p => (
                                <td key={p} className="py-1.5 px-2 text-right text-slate-700 tabular-nums">
                                  {Math.round(activeForecast.reduce((s, r) => s + (r.byPeriod.get(p) ?? 0), 0)).toLocaleString()}
                                </td>
                              ))}
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <p className="text-[11px] text-slate-400">
                        Next 12M = published forecast per model; "With uplift" applies the Uplift Factors above month by
                        month. Last 12M = sold VINs in the last 12 closed months. A <span className="text-amber-700 font-semibold">new</span> badge
                        marks models with under {NEW_LAUNCH_MONTHS} months of sales.
                      </p>
                    </>
                  )}
                </div>
              )}

              {/* Table */}
              {selectedModel === "All Models" ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                      <th className="py-2 pr-3">Period</th>
                      <th className="py-2 pr-3 text-right">Actual</th>
                      <th className="py-2 pr-3 text-right">Base Forecast</th>
                      <th className="py-2 pr-3 text-right">Uplift</th>
                      <th className="py-2 pr-3 text-right text-violet-600">Adjusted Forecast</th>
                      <th className="py-2 pr-3 text-right">Lower 80%</th>
                      <th className="py-2 text-right">Upper 80%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fcstFiltered.map(r => {
                      const upliftPct = r.is_forecast ? totalUpliftPct(r.period) : 0;
                      return (
                      <tr key={r.period} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.is_forecast ? "bg-blue-50/30" : ""}`}>
                        <td className="py-2 pr-3 font-mono text-xs">{r.period}</td>
                        <td className="py-2 pr-3 text-right text-green-600 font-semibold">
                          {r.actual != null ? Math.round(r.actual).toLocaleString() : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{Math.round(r.forecast).toLocaleString()}</td>
                        <td className={`py-2 pr-3 text-right text-xs ${upliftPct > 0 ? "text-green-600" : upliftPct < 0 ? "text-red-500" : "text-slate-300"}`}>
                          {upliftPct !== 0 ? `${upliftPct > 0 ? "+" : ""}${upliftPct.toFixed(1)}%` : "—"}
                        </td>
                        <td className="py-2 pr-3 text-right font-bold text-violet-600">
                          {r.is_forecast ? adjustedForecast(r).toLocaleString() : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2 pr-3 text-right text-xs text-slate-400">{Math.round(r.lower_80).toLocaleString()}</td>
                        <td className="py-2 text-right text-xs text-slate-400">{Math.round(r.upper_80).toLocaleString()}</td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                      <th className="py-2 pr-3">Period</th>
                      <th className="py-2 pr-3 text-right">Actual</th>
                      <th className="py-2 text-right">Forecast</th>
                    </tr>
                  </thead>
                  <tbody>
                    {singleModelData.map(r => (
                      <tr key={r.period} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.is_forecast ? "bg-blue-50/30" : ""}`}>
                        <td className="py-2 pr-3 font-mono text-xs">{r.period}</td>
                        <td className="py-2 pr-3 text-right text-green-600 font-semibold">
                          {r.actual != null ? Math.round(r.actual).toLocaleString() : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-2 text-right font-semibold text-brand-blue">{Math.round(r.forecast).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            </div>
          </div>
        )}

        {view === "forecast" && (() => {
          const SELECTED_COLOR = "#7C3AED";
          const PUBLISHED_COLOR = "#4361EE";
          const pct = (v: number | null | undefined, signed = false) =>
            v == null ? "—" : `${signed && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
          const methodKey = backtest ? (btMethod && backtest.methods.some(m => m.key === btMethod) ? btMethod : (backtest.recommended ?? backtest.methods[0]?.key)) : null;
          const publishedKey = backtest?.published ?? "seasonal_run_rate";
          const methodLabel = (k: string | null) => backtest?.methods.find(m => m.key === k)?.label ?? k ?? "";
          const board = backtest ? [...backtest.summary].sort((a, b) => (a.wape_pct ?? Infinity) - (b.wape_pct ?? Infinity)) : [];
          const bestKey = board[0]?.key;
          const scored = backtest?.scored_periods ?? [];
          const scoredSet = new Set(scored);
          const chartData = backtest && methodKey ? [
            ...backtest.history.map(h => ({ period: h.period, train_actual: h.train_actual })),
            ...backtest.monthly.filter(r => scoredSet.has(r.period)).map(r => ({
              period: r.period, actual: r.actual, actual_new_models: r.actual_new_models,
              selected: r[methodKey] as number, published: r[publishedKey] as number,
            })),
          ] : [];
          const monthRows = backtest && methodKey ? backtest.monthly.filter(r => scoredSet.has(r.period)).map(r => ({
            period: r.period, actual: r.actual, forecast: Number(r[methodKey] ?? 0),
          })) : [];
          const scoredRows = monthRows.filter(r => r.actual != null && scoredSet.has(r.period));
          const sumActual = scoredRows.reduce((s, r) => s + (r.actual ?? 0), 0);
          const sumFcScored = scoredRows.reduce((s, r) => s + r.forecast, 0);
          return (
            <div className="mt-6 border border-slate-200 rounded-xl p-4 space-y-5">
              <div className="flex flex-wrap items-start gap-3">
                <div className="flex-1 min-w-[260px]">
                  <h3 className="text-sm font-semibold text-slate-700">
                    Backtest — a forecast made as of {btEnd}, using {btStart} → {btEnd} data only, checked against what then sold
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Every method sees the training window only; the months it is scored on were never visible to it
                    {scored.length > 0 && <> · scored on {scored[0]} → {scored[scored.length - 1]} ({scored.length} months with actuals)</>}
                    {" "}· active models, sold VINs. <b className="text-slate-500">This is a test of the method, not the plan:</b> its
                    numbers are what the method would have said back then, so they differ from the live forecast above,
                    which uses every month up to the latest actual.
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span>Train</span>
                  <input type="month" value={btStart} onChange={e => setBtStart(e.target.value)}
                    className="border border-slate-200 rounded-lg px-2 py-1 text-xs bg-white"/>
                  <span>to</span>
                  <input type="month" value={btEnd} onChange={e => setBtEnd(e.target.value)}
                    className="border border-slate-200 rounded-lg px-2 py-1 text-xs bg-white"/>
                  <span>→ forecast 12 months</span>
                </div>
              </div>

              {!backtest && <p className="text-xs text-slate-400 animate-pulse">Running backtest…</p>}
              {backtest && backtest.summary.length === 0 && (
                <p className="text-xs text-slate-400">No actuals fall after this training window — nothing to compare yet.</p>
              )}

              {backtest && backtest.summary.length > 0 && methodKey && (
                <>
                  {/* Scoreboard: every method on the same months */}
                  <div>
                    <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Method scoreboard — click a method to inspect it</h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-500 uppercase text-left">
                            <th className="py-2 pr-3">Method</th>
                            <th className="py-2 px-2 text-right">Forecast ({scored.length} mo)</th>
                            <th className="py-2 px-2 text-right text-green-600">Actual</th>
                            <th className="py-2 px-2 text-right">Total error</th>
                            <th className="py-2 pl-2 text-right" title="Σ|forecast − actual| ÷ Σ actual, per model and month">Model WAPE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {board.map(s => (
                            <tr key={s.key} onClick={() => setBtMethod(s.key)}
                              className={`border-b border-slate-50 cursor-pointer transition-colors ${s.key === methodKey ? "bg-violet-50" : "hover:bg-slate-50"}`}>
                              <td className="py-1.5 pr-3">
                                <span className="inline-flex items-center gap-2">
                                  <span className={`w-3 h-3 rounded-full border-2 ${s.key === methodKey ? "border-violet-600 bg-violet-600" : "border-slate-300"}`}/>
                                  <span className={s.key === methodKey ? "font-semibold text-violet-700" : "text-slate-700"}>{methodLabel(s.key)}</span>
                                  {s.key === bestKey && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold">lowest error</span>}
                                  {s.key === backtest.recommended && <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 font-semibold">recommended</span>}
                                  {s.key === publishedKey && <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-semibold">currently on page</span>}
                                </span>
                              </td>
                              <td className="py-1.5 px-2 text-right font-semibold text-slate-800">{Math.round(s.forecast).toLocaleString()}</td>
                              <td className="py-1.5 px-2 text-right text-green-600">{Math.round(s.actual).toLocaleString()}</td>
                              <td className={`py-1.5 px-2 text-right ${(s.error_pct ?? 0) < 0 ? "text-red-500" : "text-amber-600"}`}>{pct(s.error_pct, true)}</td>
                              <td className={`py-1.5 pl-2 text-right font-semibold ${s.key === bestKey ? "text-emerald-700" : "text-slate-600"}`}>{pct(s.wape_pct)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Chart: training actuals, then forecast vs actual */}
                  <div>
                    <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">
                      Monthly units — <span className="text-violet-700 normal-case">{methodLabel(methodKey)}</span>
                    </h4>
                    <ResponsiveContainer width="100%" height={280}>
                      <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                        <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0} tickFormatter={p => monthLabel(p, false)}/>
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                        <Tooltip formatter={(v: unknown, n: unknown) => [v != null ? Math.round(Number(v)).toLocaleString() : "—", String(n)]}/>
                        <Legend wrapperStyle={{ fontSize: 11 }}/>
                        <Bar dataKey="train_actual" name="Actual (training data)" fill="#CBD5E1" radius={[3,3,0,0]}/>
                        <Bar dataKey="actual" name="Actual (scored)" fill="#2CC56F" stackId="act"/>
                        <Bar dataKey="actual_new_models" name="New launches (not forecastable)" fill="#A7F3D0" stackId="act" radius={[3,3,0,0]}/>
                        <Line type="monotone" dataKey="selected" name={methodLabel(methodKey)} stroke={SELECTED_COLOR} strokeWidth={2.5} dot={{ r: 3 }}/>
                        {methodKey !== publishedKey && (
                          <Line type="monotone" dataKey="published" name="Currently on page" stroke={PUBLISHED_COLOR} strokeWidth={1.5} strokeDasharray="5 4" dot={false}/>
                        )}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>

                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                    {/* Month by month */}
                    <div className="overflow-x-auto">
                      <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Forecast vs actual, month by month</h4>
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-500 uppercase text-left">
                            <th className="py-2 pr-3">Month</th>
                            <th className="py-2 px-2 text-right text-green-600">Actual</th>
                            <th className="py-2 px-2 text-right text-violet-600">Forecast</th>
                            <th className="py-2 px-2 text-right">Difference</th>
                            <th className="py-2 pl-2 text-right">Error</th>
                          </tr>
                        </thead>
                        <tbody>
                          {monthRows.map(r => {
                            const diff = r.actual != null ? r.forecast - r.actual : null;
                            return (
                              <tr key={r.period} className={`border-b border-slate-50 ${r.actual == null ? "text-slate-400" : ""}`}>
                                <td className="py-1.5 pr-3 font-mono">{r.period}</td>
                                <td className="py-1.5 px-2 text-right text-green-600 font-semibold">{r.actual != null ? Math.round(r.actual).toLocaleString() : <span className="text-slate-300">not yet</span>}</td>
                                <td className="py-1.5 px-2 text-right text-violet-700 font-semibold">{Math.round(r.forecast).toLocaleString()}</td>
                                <td className={`py-1.5 px-2 text-right ${diff == null ? "text-slate-300" : diff < 0 ? "text-red-500" : "text-amber-600"}`}>
                                  {diff == null ? "—" : `${diff > 0 ? "+" : ""}${Math.round(diff).toLocaleString()}`}
                                </td>
                                <td className={`py-1.5 pl-2 text-right ${diff == null ? "text-slate-300" : diff < 0 ? "text-red-500" : "text-amber-600"}`}>
                                  {diff == null || !r.actual ? "—" : pct(diff / r.actual * 100, true)}
                                </td>
                              </tr>
                            );
                          })}
                          <tr className="border-t-2 border-slate-200 font-semibold">
                            <td className="py-1.5 pr-3 text-slate-700">Scored months</td>
                            <td className="py-1.5 px-2 text-right text-green-700">{sumActual.toLocaleString()}</td>
                            <td className="py-1.5 px-2 text-right text-violet-700">{Math.round(sumFcScored).toLocaleString()}</td>
                            <td className={`py-1.5 px-2 text-right ${sumFcScored - sumActual < 0 ? "text-red-500" : "text-amber-600"}`}>
                              {`${sumFcScored - sumActual > 0 ? "+" : ""}${Math.round(sumFcScored - sumActual).toLocaleString()}`}
                            </td>
                            <td className={`py-1.5 pl-2 text-right ${sumFcScored - sumActual < 0 ? "text-red-500" : "text-amber-600"}`}>
                              {sumActual ? pct((sumFcScored - sumActual) / sumActual * 100, true) : "—"}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>

                    {/* Model by model */}
                    <div className="overflow-x-auto">
                      <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">Forecast vs actual, by model (scored months)</h4>
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-500 uppercase text-left">
                            <th className="py-2 pr-3">Model</th>
                            <th className="py-2 px-2 text-right" title="Months with sales in the training window">Train mo</th>
                            <th className="py-2 px-2 text-right text-green-600">Actual</th>
                            <th className="py-2 px-2 text-right text-violet-600">Forecast</th>
                            <th className="py-2 px-2 text-right">Error</th>
                            <th className="py-2 pl-2 text-right">WAPE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {backtest.models.map(r => {
                            const st = r[methodKey] as BacktestStats;
                            return (
                              <tr key={r.model} className="border-b border-slate-50 hover:bg-slate-50/50">
                                <td className="py-1.5 pr-3 font-medium text-slate-800 whitespace-nowrap">
                                  {r.model}
                                  {r.train_months < 3 && (
                                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-semibold"
                                      title="Very little training history — one launch month drives the forecast">thin fit</span>
                                  )}
                                </td>
                                <td className="py-1.5 px-2 text-right text-slate-500">{r.train_months}</td>
                                <td className="py-1.5 px-2 text-right font-semibold text-green-600">{Math.round(st.actual).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right font-semibold text-violet-700">{Math.round(st.forecast).toLocaleString()}</td>
                                <td className={`py-1.5 px-2 text-right ${(st.error_pct ?? 0) < 0 ? "text-red-500" : "text-amber-600"}`}>{pct(st.error_pct, true)}</td>
                                <td className="py-1.5 pl-2 text-right text-slate-600">{pct(st.wape_pct)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Model-wise monthly forecast, with each month's actual under it */}
                  {(() => {
                    const mm = backtest.model_monthly ?? [];
                    const months = [...new Set(mm.map(r => r.period))].filter(p => scoredSet.has(p)).sort();
                    type Cell = { fc: number; act: number | null };
                    const byModel = new Map<string, { isNew: boolean; cells: Map<string, Cell> }>();
                    for (const r of mm) {
                      const entry = byModel.get(r.model) ?? { isNew: r.is_new, cells: new Map<string, Cell>() };
                      entry.cells.set(r.period, { fc: Number(r[methodKey] ?? 0), act: r.actual });
                      byModel.set(r.model, entry);
                    }
                    const rows = [...byModel.entries()].map(([model, e]) => {
                      const fcTotal = months.reduce((s, p) => s + (e.cells.get(p)?.fc ?? 0), 0);
                      const actScored = months.filter(p => scoredSet.has(p)).reduce((s, p) => s + (e.cells.get(p)?.act ?? 0), 0);
                      const fcScored = months.filter(p => scoredSet.has(p)).reduce((s, p) => s + (e.cells.get(p)?.fc ?? 0), 0);
                      return { model, ...e, fcTotal, actScored, fcScored };
                    }).filter(r => r.fcTotal > 0 || r.actScored > 0)
                      .sort((a, b) => Number(a.isNew) - Number(b.isNew) || b.fcTotal - a.fcTotal);
                    const colTotal = (p: string, which: "fc" | "act", includeNew: boolean) =>
                      rows.filter(r => includeNew || !r.isNew).reduce((s, r) => s + ((r.cells.get(p)?.[which] as number | null) ?? 0), 0);
                    const errClass = (fc: number, act: number | null) =>
                      act == null ? "text-slate-300" : fc < act ? "text-red-500" : "text-amber-600";
                    return (
                      <div className="overflow-x-auto">
                        <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-1">
                          Model-wise monthly forecast — <span className="text-violet-700 normal-case">{methodLabel(methodKey)}</span>
                        </h4>
                        <p className="text-[11px] text-slate-400 mb-2">
                          Each cell: <span className="font-semibold text-violet-700">forecast</span> on top, actual beneath
                          (<span className="text-red-500">red</span> = forecast under, <span className="text-amber-600">amber</span> = over).
                          Only months with an actual are shown — this grid tests the forecast made as of {btEnd}; the live
                          forecast for the months ahead is in the Active Model Forecast above.
                        </p>
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-200 text-slate-500 uppercase">
                              <th className="py-2 pr-3 text-left sticky left-0 bg-white">Model</th>
                              {months.map(p => (
                                <th key={p} className={`py-2 px-2 text-right font-mono normal-case ${scoredSet.has(p) ? "" : "text-slate-300"}`}>
                                  {monthLabel(p, false)}
                                </th>
                              ))}
                              <th className="py-2 px-2 text-right text-violet-600">Forecast total</th>
                              <th className="py-2 px-2 text-right text-green-600">Actual total</th>
                              <th className="py-2 pl-2 text-right">Error</th>
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map(r => (
                              <tr key={r.model} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.isNew ? "bg-emerald-50/30" : ""}`}>
                                <td className="py-1.5 pr-3 font-medium text-slate-800 whitespace-nowrap sticky left-0 bg-white">
                                  {r.model}
                                  {r.isNew && (
                                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold"
                                      title="No sales in the training window, so no method can forecast it">new launch</span>
                                  )}
                                </td>
                                {months.map(p => {
                                  const c = r.cells.get(p) ?? { fc: 0, act: null };
                                  return (
                                    <td key={p} className="py-1 px-2 text-right tabular-nums leading-tight">
                                      <div className="font-semibold text-violet-700">{r.isNew ? "—" : Math.round(c.fc).toLocaleString()}</div>
                                      <div className={`text-[10px] ${r.isNew ? "text-emerald-700" : errClass(c.fc, c.act)}`}>
                                        {c.act != null ? Math.round(c.act).toLocaleString() : ""}
                                      </div>
                                    </td>
                                  );
                                })}
                                <td className="py-1.5 px-2 text-right font-bold text-violet-700 tabular-nums">{r.isNew ? "—" : Math.round(r.fcTotal).toLocaleString()}</td>
                                <td className="py-1.5 px-2 text-right tabular-nums text-slate-600">
                                  {Math.round(r.actScored).toLocaleString()}
                                </td>
                                <td className={`py-1.5 pl-2 text-right ${r.isNew ? "text-slate-300" : errClass(r.fcScored, r.actScored)}`}>
                                  {r.isNew || !r.actScored ? "—" : pct((r.fcScored - r.actScored) / r.actScored * 100, true)}
                                </td>
                              </tr>
                            ))}
                            <tr className="border-t-2 border-slate-300 font-semibold bg-violet-50/40">
                              <td className="py-1.5 pr-3 text-slate-700 sticky left-0 bg-violet-50">Monthly total — forecast</td>
                              {months.map(p => (
                                <td key={p} className="py-1.5 px-2 text-right text-violet-700 tabular-nums">{Math.round(colTotal(p, "fc", false)).toLocaleString()}</td>
                              ))}
                              <td className="py-1.5 px-2 text-right text-violet-800 tabular-nums">
                                {Math.round(months.reduce((s, p) => s + colTotal(p, "fc", false), 0)).toLocaleString()}
                              </td>
                              <td colSpan={2}/>
                            </tr>
                            <tr className="font-semibold">
                              <td className="py-1.5 pr-3 text-slate-700 sticky left-0 bg-white">Monthly total — actual (forecast models)</td>
                              {months.map(p => (
                                <td key={p} className="py-1.5 px-2 text-right text-green-700 tabular-nums">
                                  {scoredSet.has(p) ? Math.round(colTotal(p, "act", false)).toLocaleString() : ""}
                                </td>
                              ))}
                              <td colSpan={3}/>
                            </tr>
                            <tr className="text-slate-500">
                              <td className="py-1.5 pr-3 sticky left-0 bg-white">Monthly total — actual incl. new launches</td>
                              {months.map(p => (
                                <td key={p} className="py-1.5 px-2 text-right tabular-nums">
                                  {scoredSet.has(p) ? Math.round(colTotal(p, "act", true)).toLocaleString() : ""}
                                </td>
                              ))}
                              <td colSpan={3}/>
                            </tr>
                            <tr className="text-slate-500">
                              <td className="py-1.5 pr-3 sticky left-0 bg-white">Monthly error (forecast models)</td>
                              {months.map(p => {
                                const fc = colTotal(p, "fc", false), act = colTotal(p, "act", false);
                                return (
                                  <td key={p} className={`py-1.5 px-2 text-right ${scoredSet.has(p) ? errClass(fc, act) : ""}`}>
                                    {scoredSet.has(p) && act ? pct((fc - act) / act * 100, true) : ""}
                                  </td>
                                );
                              })}
                              <td colSpan={3}/>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    );
                  })()}

                  <p className="text-[11px] text-slate-400">
                    <b>Total error</b> = (forecast − actual) ÷ actual over the scored months; misses in opposite directions
                    cancel. <b>Model WAPE</b> = Σ|forecast − actual| ÷ Σ actual taken per model and month, so one model's miss
                    is not offset by another's — the fairer accuracy measure, and the one methods are ranked on.
                    {backtest.new_models.length > 0 && <> Not forecastable from the training window (no sales in it):{" "}
                      {backtest.new_models.map(m => `${m.model} ${Math.round(m.actual).toLocaleString()} units`).join(", ")} —
                      shown as “new launches” in the chart and left out of the score.</>}
                  </p>
                </>
              )}
            </div>
          );
        })()}

        {view === "target" && (
          <div className="space-y-5">
            {/* Target Base: year picker */}
            <div className="flex items-center gap-3">
              <p className="text-xs text-slate-500 flex-1">
                Targets are planner inputs, split to models on the last 12 months of MCSI mix. Actuals and the
                adjusted forecast (Forecast Base, with uplifts) are measured against them.
              </p>
              <YearPicker years={getYears(sales_forecast)} value={forecastYear} onChange={setForecastYear}/>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <KpiCard label={`Target ${TARGET_YEAR}`} value={fmt(targetYearTotal)} sub="yearly, as edited" color="blue"/>
              <KpiCard label="YTD Achievement"
                value={ytdTarget ? `${(ytdActual / ytdTarget * 100).toFixed(1)}%` : "—"}
                sub={`${ytdActual.toLocaleString()} actual / ${ytdTarget.toLocaleString()} target`}
                color={ytdActual >= ytdTarget ? "green" : "red"}/>
              <KpiCard label="Year Outlook"
                value={fmt(yearOutlook)}
                sub="actual to date + adjusted forecast" color="purple"/>
              <KpiCard label="Outlook vs Target"
                value={`${yearOutlook - targetYearTotal >= 0 ? "+" : ""}${(yearOutlook - targetYearTotal).toLocaleString()}`}
                sub={targetYearTotal ? `${((yearOutlook / targetYearTotal - 1) * 100).toFixed(1)}% vs target` : ""}
                color={yearOutlook >= targetYearTotal ? "green" : "red"}/>
            </div>

            {/* ── Sales Targets — always-visible section ── */}
            {(() => {
              const defVal = Math.round(Number(draftYearly) / 12) || 0;
              const monthlySum = Object.entries(draftMonthly)
                .filter(([k]) => k.startsWith(`${TARGET_YEAR}-`))
                .reduce((s, [, v]) => s + (Number(v) || 0), 0);
              const yearlyNum = Number(draftYearly) || 0;
              const delta = monthlySum - yearlyNum;
              return (
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-4">
                  <h3 className="text-sm font-semibold text-slate-700">Sales Targets</h3>

                  {/* ── Yearly row ── */}
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-2">
                      <label className="text-xs font-medium text-slate-600">Yearly Target (units):</label>
                      <input
                        type="number"
                        value={draftYearly}
                        onChange={e => handleYearlyChange(e.target.value)}
                        className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-brand-blue/30 bg-white"
                      />
                    </div>
                    <p className="text-xs text-slate-500 flex-1">
                      Default per month = {defVal.toLocaleString()} units &nbsp;·&nbsp; Custom months show in <span className="text-blue-700 font-semibold">blue</span>
                    </p>
                  </div>

                  {/* ── Monthly grid ── */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                        Monthly Targets — {TARGET_YEAR}
                      </p>
                      <button
                        onClick={resetMonthlyToDefault}
                        className="text-[11px] text-slate-400 hover:text-red-500 transition-colors"
                      >
                        Reset all to default
                      </button>
                    </div>
                    <div className="grid grid-cols-6 gap-2">
                      {MONTH_LABELS.map((lbl, idx) => {
                        const k = monthKey(TARGET_YEAR, idx + 1);
                        const isCustom = pinnedMonths.has(k);
                        return (
                          <div key={k}>
                            <p
                              onClick={() => loadBreakdown(k, Number(draftMonthly[k] ?? defVal))}
                              className={`text-[10px] text-center mb-1 cursor-pointer select-none transition-colors ${
                                breakdownMonth === k
                                  ? "text-amber-600 font-bold underline underline-offset-2"
                                  : "text-slate-500 hover:text-amber-500"
                              }`}
                            >{lbl}</p>
                            <input
                              type="number"
                              value={draftMonthly[k] ?? defVal}
                              onChange={e => handleMonthChange(k, e.target.value)}
                              className={`w-full rounded-lg px-1 py-1.5 text-xs text-center focus:outline-none focus:ring-2 focus:ring-brand-blue/30 transition-colors ${
                                isCustom
                                  ? "border-2 border-blue-400 bg-blue-50 font-bold text-blue-800"
                                  : "border border-slate-200 bg-white text-slate-700"
                              }`}
                            />
                          </div>
                        );
                      })}
                    </div>
                    {/* Sum vs yearly */}
                    <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                      <span>Σ monthly = <strong className={delta === 0 ? "text-green-600" : "text-amber-600"}>{monthlySum.toLocaleString()}</strong></span>
                      <span>vs yearly {yearlyNum.toLocaleString()}</span>
                      {delta !== 0 && (
                        <span className={`font-semibold ${delta > 0 ? "text-red-500" : "text-amber-600"}`}>
                          {delta > 0 ? "+" : ""}{delta.toLocaleString()} {delta > 0 ? "over" : "under"}
                        </span>
                      )}
                      {delta === 0 && <span className="text-green-600 font-semibold">✓ balanced</span>}
                    </div>
                  </div>

                  {/* ── Save ── */}
                  <div className="flex items-center justify-end pt-1 border-t border-blue-200">
                    <button onClick={handleSaveTargets} disabled={saving}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-brand-blue text-white hover:bg-blue-700 transition-colors disabled:opacity-50">
                      <Check size={13}/> {saving ? "Saving…" : "Save"}
                    </button>
                  </div>
                </div>
              );
            })()}


            {/* Target vs actual vs adjusted forecast, month by month */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-1">Target vs Actual vs Forecast — {TARGET_YEAR}</h3>
              <p className="text-xs text-slate-400 mb-3">Bars = monthly target (live as you edit) · green = actual · violet = adjusted forecast</p>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={targetRows} margin={{ top:5, right:10, left:0, bottom:5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                  <XAxis dataKey="label" tick={{ fontSize: 10 }}/>
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                  <Tooltip formatter={(v: unknown, n: unknown) => [v != null ? Math.round(Number(v)).toLocaleString() : "—", String(n)]}/>
                  <Legend/>
                  <Bar dataKey="target" name="Target" fill="#FDE68A" radius={[3,3,0,0]}/>
                  <Line type="monotone" dataKey="actual" name="Actual" stroke="#2CC56F" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false}/>
                  <Line type="monotone" dataKey="adjusted" name="Adjusted Forecast" stroke="#7C3AED" strokeWidth={2} strokeDasharray="6 3" dot={{ r: 2 }} connectNulls={false}/>
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* ── Breakdown panel (yearly default / month on focus) ── */}
            {breakdownMonth && (
              <div className="bg-white rounded-xl shadow-sm border border-amber-200 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold text-slate-700">
                      {breakdownMonth === "Yearly" ? "Yearly Target" : `${breakdownMonth} — Target`}
                      <span className="ml-1.5 text-amber-600 font-bold">
                        ({(breakdownTarget ?? 0).toLocaleString()} units)
                      </span>
                    </h3>
                    {breakdownMonth !== "Yearly" && (
                      <button
                        onClick={() => loadBreakdown("Yearly", Number(draftYearly) || 0)}
                        className="text-xs text-slate-400 hover:text-amber-600 transition-colors underline underline-offset-2"
                      >
                        ← Yearly
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-slate-400">
                    Split on {breakdown?.[0]?.window_start ? `${breakdown[0].window_start} → ${breakdown[0].window_end}` : "the last 12 months"} MCSI mix · active models · whole units
                  </p>
                </div>
                {breakdownLoading && <p className="text-xs text-slate-400 animate-pulse">Loading…</p>}
                {breakdown && (() => {
                  // Build ordered model groups preserving API sort (desc allocated)
                  const groups: { model: string; rows: TargetBreakdownRow[] }[] = [];
                  const seen = new Map<string, TargetBreakdownRow[]>();
                  for (const r of breakdown) {
                    if (!seen.has(r.model)) {
                      const arr: TargetBreakdownRow[] = [];
                      seen.set(r.model, arr);
                      groups.push({ model: r.model, rows: arr });
                    }
                    seen.get(r.model)!.push(r);
                  }
                  // Extension: the whole target year — actual sold in closed months,
                  // each future month's target allocated on the same mix (whole units).
                  const yearMonthsAll = targetRows.map(r => r.key);
                  const closedMonths = targetRows.filter(r => r.actual != null).map(r => r.key);
                  const openMonths = yearMonthsAll.filter(p => !closedMonths.includes(p));
                  const isClosed = (p: string) => closedMonths.includes(p);
                  const cell = new Map<string, number>();
                  const add = (model: string, color: string, p: string, v: number) => {
                    for (const key of [`${model}|${color}|${p}`, `${model}||${p}`, `||${p}`]) {
                      cell.set(key, (cell.get(key) ?? 0) + v);
                    }
                  };
                  for (const r of actualMC ?? []) if (isClosed(r.period)) add(r.model, r.color, r.period, r.units);
                  for (const r of monthlyAlloc ?? []) if (!isClosed(r.period)) add(r.model, r.color, r.period, r.allocated_units);
                  const at = (model: string, color: string, p: string) => cell.get(`${model}|${color}|${p}`) ?? 0;
                  const sumOver = (model: string, color: string, ps: string[]) => ps.reduce((s, p) => s + at(model, color, p), 0);
                  const targetByMonth = new Map(targetRows.map(r => [r.key, r.target]));
                  const fcByMonth = new Map(targetRows.map(r => [r.key, r.adjusted]));
                  const yearlyAllocated = breakdown.reduce((s, r) => s + r.allocated_units, 0);
                  const monthCls = (p: string, first: boolean) =>
                    `py-1 px-2 text-right tabular-nums ${isClosed(p) ? "bg-green-50/40" : "bg-amber-50/30"} ${first ? "border-l-2 border-slate-200" : ""}`;
                  const firstOpen = openMonths[0];
                  const edge = (p: string) => p === yearMonthsAll[0] || p === firstOpen;
                  const ext = yearMonthsAll.length > 0;
                  return (
                  <div className="overflow-x-auto">
                    <table className="text-xs w-full">
                      <thead>
                        {ext && (
                          <tr className="text-[10px] uppercase tracking-wide">
                            <th colSpan={4}/>
                            {closedMonths.length > 0 && (
                              <th colSpan={closedMonths.length}
                                className="pt-1 pb-0.5 px-2 text-center font-semibold text-green-700 bg-green-50 border-l-2 border-slate-200">
                                Actual sold — {closedMonths[0].slice(5)}–{closedMonths[closedMonths.length - 1].slice(5)}
                              </th>
                            )}
                            {openMonths.length > 0 && (
                              <th colSpan={openMonths.length}
                                className="pt-1 pb-0.5 px-2 text-center font-semibold text-amber-700 bg-amber-50 border-l-2 border-slate-200">
                                Allocation of each month's target
                              </th>
                            )}
                            <th colSpan={3} className="pt-1 pb-0.5 px-2 text-center font-semibold text-slate-600 bg-slate-50 border-l-2 border-slate-200">
                              {TARGET_YEAR} totals
                            </th>
                          </tr>
                        )}
                        <tr className="border-b-2 border-slate-200 text-left text-slate-500 uppercase tracking-wide">
                          <th className="py-1.5 pr-3 font-medium">Model / Color</th>
                          <th className="py-1.5 pr-3 text-right font-medium">Historical (12m)</th>
                          <th className="py-1.5 pr-3 text-right font-medium">Share %</th>
                          <th className="py-1.5 pr-2 text-right font-bold text-slate-700">Allocated</th>
                          {yearMonthsAll.map(p => (
                            <th key={p} className={`py-1.5 px-2 text-right font-medium normal-case ${isClosed(p) ? "text-green-700 bg-green-50/60" : "text-amber-700 bg-amber-50/60"} ${edge(p) ? "border-l-2 border-slate-200" : ""}`}>
                              {monthLabel(p, true)}
                            </th>
                          ))}
                          {ext && (
                            <>
                              <th className="py-1.5 px-2 text-right font-bold text-green-700 border-l-2 border-slate-200" title="Sold in the closed months">Σ actual</th>
                              <th className="py-1.5 px-2 text-right font-bold text-amber-700" title="Allocated in the future months">Σ allocation</th>
                              <th className="py-1.5 px-2 text-right font-bold text-slate-700" title="Actual so far + allocation for the rest of the year">Year</th>
                            </>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {groups.map(({ model, rows }) => {
                          const histTotal  = rows.reduce((s, r) => s + r.historical_units, 0);
                          const shareTotal = rows.reduce((s, r) => s + r.share_pct, 0);
                          const allocTotal = rows.reduce((s, r) => s + r.allocated_units, 0);
                          const mAct = sumOver(model, "", closedMonths);
                          const mAlloc = sumOver(model, "", openMonths);
                          return (
                            <Fragment key={model}>
                              <tr className="bg-slate-50 border-t-2 border-slate-200">
                                <td className="py-2 pr-3 font-semibold text-slate-800">{model}</td>
                                <td className="py-2 pr-3 text-right text-slate-600 font-medium">{histTotal.toLocaleString()}</td>
                                <td className="py-2 pr-3 text-right text-slate-600 font-medium">{shareTotal.toFixed(1)}%</td>
                                <td className="py-2 pr-2 text-right font-bold text-amber-700">{allocTotal.toLocaleString()}</td>
                                {yearMonthsAll.map(p => (
                                  <td key={p} className={`${monthCls(p, edge(p))} py-2 font-semibold ${isClosed(p) ? "text-green-700" : "text-amber-700"}`}>
                                    {at(model, "", p).toLocaleString()}
                                  </td>
                                ))}
                                {ext && (
                                  <>
                                    <td className="py-2 px-2 text-right tabular-nums font-bold text-green-700 border-l-2 border-slate-200">{mAct.toLocaleString()}</td>
                                    <td className="py-2 px-2 text-right tabular-nums font-bold text-amber-700">{mAlloc.toLocaleString()}</td>
                                    <td className="py-2 px-2 text-right tabular-nums font-bold text-slate-800">{(mAct + mAlloc).toLocaleString()}</td>
                                  </>
                                )}
                              </tr>
                              {rows.map((r, i) => {
                                const cAct = sumOver(model, r.color, closedMonths);
                                const cAlloc = sumOver(model, r.color, openMonths);
                                return (
                                  <tr key={i} className="border-b border-slate-100 hover:bg-amber-50/30 transition-colors">
                                    <td className="py-1 pl-5 pr-3">
                                      <span className="inline-flex items-center gap-1.5 text-slate-600">
                                        <span className="w-2 h-2 rounded-full shrink-0 ring-1 ring-slate-300"
                                          style={{ background: colorHex(r.color) }}/>
                                        {r.color}
                                      </span>
                                    </td>
                                    <td className="py-1 pr-3 text-right text-slate-400">{r.historical_units.toLocaleString()}</td>
                                    <td className="py-1 pr-3 text-right text-slate-400">{r.share_pct.toFixed(1)}%</td>
                                    <td className="py-1 pr-2 text-right text-amber-600 font-medium">{r.allocated_units.toLocaleString()}</td>
                                    {yearMonthsAll.map(p => (
                                      <td key={p} className={`${monthCls(p, edge(p))} ${isClosed(p) ? "text-green-700/80" : "text-slate-500"}`}>
                                        {at(model, r.color, p).toLocaleString()}
                                      </td>
                                    ))}
                                    {ext && (
                                      <>
                                        <td className="py-1 px-2 text-right tabular-nums text-green-700 border-l-2 border-slate-200">{cAct.toLocaleString()}</td>
                                        <td className="py-1 px-2 text-right tabular-nums text-amber-700">{cAlloc.toLocaleString()}</td>
                                        <td className="py-1 px-2 text-right tabular-nums text-slate-700">{(cAct + cAlloc).toLocaleString()}</td>
                                      </>
                                    )}
                                  </tr>
                                );
                              })}
                            </Fragment>
                          );
                        })}
                        {(() => {
                          const tAct = closedMonths.reduce((s, p) => s + (cell.get(`||${p}`) ?? 0), 0);
                          const tAlloc = openMonths.reduce((s, p) => s + (cell.get(`||${p}`) ?? 0), 0);
                          return (
                            <tr className="border-t-2 border-slate-300 font-semibold">
                              <td className="py-2 pr-3 text-slate-700">Total</td>
                              <td className="py-2 pr-3 text-right text-slate-600">{breakdown.reduce((s, r) => s + r.historical_units, 0).toLocaleString()}</td>
                              <td className="py-2 pr-3 text-right text-slate-600">100.0%</td>
                              <td className="py-2 pr-2 text-right text-amber-800">{yearlyAllocated.toLocaleString()}</td>
                              {yearMonthsAll.map(p => (
                                <td key={p} className={`${monthCls(p, edge(p))} py-2 ${isClosed(p) ? "text-green-800" : "text-amber-800"}`}>
                                  {(cell.get(`||${p}`) ?? 0).toLocaleString()}
                                </td>
                              ))}
                              {ext && (
                                <>
                                  <td className="py-2 px-2 text-right tabular-nums text-green-800 border-l-2 border-slate-200">{tAct.toLocaleString()}</td>
                                  <td className="py-2 px-2 text-right tabular-nums text-amber-800">{tAlloc.toLocaleString()}</td>
                                  <td className="py-2 px-2 text-right tabular-nums text-slate-900">{(tAct + tAlloc).toLocaleString()}</td>
                                </>
                              )}
                            </tr>
                          );
                        })()}
                        {ext && (
                          <>
                            <tr className="text-slate-500">
                              <td colSpan={4} className="py-1.5 pr-3 text-right">Monthly target</td>
                              {yearMonthsAll.map(p => (
                                <td key={p} className={`${monthCls(p, edge(p))} text-amber-700`}>
                                  {Math.round(targetByMonth.get(p) ?? 0).toLocaleString()}
                                </td>
                              ))}
                              <td className="py-1.5 px-2 text-right tabular-nums text-amber-700 border-l-2 border-slate-200">
                                {Math.round(closedMonths.reduce((s, p) => s + (targetByMonth.get(p) ?? 0), 0)).toLocaleString()}
                              </td>
                              <td className="py-1.5 px-2 text-right tabular-nums text-amber-700">
                                {Math.round(openMonths.reduce((s, p) => s + (targetByMonth.get(p) ?? 0), 0)).toLocaleString()}
                              </td>
                              <td className="py-1.5 px-2 text-right tabular-nums text-amber-800">
                                {Math.round(yearMonthsAll.reduce((s, p) => s + (targetByMonth.get(p) ?? 0), 0)).toLocaleString()}
                              </td>
                            </tr>
                            <tr className="text-slate-500">
                              <td colSpan={4} className="py-1.5 pr-3 text-right">Adjusted forecast</td>
                              {yearMonthsAll.map(p => (
                                <td key={p} className={`${monthCls(p, edge(p))} text-violet-600`}>
                                  {!isClosed(p) && fcByMonth.get(p) != null ? Math.round(fcByMonth.get(p) as number).toLocaleString() : ""}
                                </td>
                              ))}
                              <td className="border-l-2 border-slate-200"/>
                              <td className="py-1.5 px-2 text-right tabular-nums text-violet-600">
                                {Math.round(openMonths.reduce((s, p) => s + (fcByMonth.get(p) ?? 0), 0)).toLocaleString()}
                              </td>
                              <td/>
                            </tr>
                            <tr className="text-slate-500">
                              <td colSpan={4} className="py-1.5 pr-3 text-right">Actual / forecast − target</td>
                              {yearMonthsAll.map(p => {
                                const basis = isClosed(p) ? (cell.get(`||${p}`) ?? 0) : fcByMonth.get(p);
                                const gap = basis != null ? Math.round(basis - (targetByMonth.get(p) ?? 0)) : null;
                                return (
                                  <td key={p} className={`${monthCls(p, edge(p))} ${gap == null ? "" : gap < 0 ? "text-red-500" : "text-green-600"}`}>
                                    {gap == null ? "—" : `${gap > 0 ? "+" : ""}${gap.toLocaleString()}`}
                                  </td>
                                );
                              })}
                              <td colSpan={3} className="border-l-2 border-slate-200"/>
                            </tr>
                          </>
                        )}
                      </tbody>
                    </table>
                    {ext && (
                      <p className="text-[11px] text-slate-400 mt-2">
                        <b>Allocated</b> splits the {breakdownMonth === "Yearly" ? "yearly" : breakdownMonth} target on the sales mix.
                        The month columns cover {TARGET_YEAR}: <span className="text-green-700 font-semibold">green</span> months
                        are what each model and colour actually sold; <span className="text-amber-700 font-semibold">amber</span> months
                        split that month's target from the editor on the same mix, in whole units. <b>Year</b> = actual so far +
                        allocation for the rest. The last rows compare each month with its target — actual for closed months,
                        adjusted forecast for open ones (red = short).
                      </p>
                    )}
                  </div>
                  );
                })()}
              </div>
            )}



            {/* Target table: each month's target against its actual */}
            <div className="space-y-3">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                      <th className="py-2 pr-3">Month</th>
                      <th className="py-2 pr-3 text-right text-amber-600">Target</th>
                      <th className="py-2 pr-3 text-right">Actual</th>
                      <th className="py-2 pr-3 text-right">Gap vs Target</th>
                      <th className="py-2 text-right">Achievement</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targetRows.map(r => {
                      const gap = r.actual != null ? Math.round(r.actual - r.target) : null;
                      return (
                        <tr key={r.key} className={`border-b border-slate-50 hover:bg-slate-50/50 ${r.actual == null ? "bg-blue-50/30" : ""}`}>
                          <td className="py-2 pr-3 font-mono text-xs">{r.key}</td>
                          <td className="py-2 pr-3 text-right text-amber-600 font-semibold">{Math.round(r.target).toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-green-600 font-semibold">
                            {r.actual != null ? Math.round(r.actual).toLocaleString() : <span className="text-slate-300">—</span>}
                          </td>
                          <td className="py-2 pr-3 text-right text-xs" style={{ color: gap == null ? "#CBD5E1" : gap < 0 ? "#EF4444" : "#2CC56F" }}>
                            {gap != null ? `${gap > 0 ? "+" : ""}${gap.toLocaleString()}` : "—"}
                          </td>
                          <td className="py-2 text-right text-xs">
                            {r.actual != null && r.target
                              ? <span className={r.actual >= r.target ? "text-green-600 font-semibold" : "text-red-500 font-semibold"}>
                                  {(r.actual / r.target * 100).toFixed(1)}%
                                </span>
                              : <span className="text-slate-300">—</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-slate-400">
                Gap vs Target = actual − target, for closed months.
                Achievement is actual ÷ target for closed months.
              </p>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
