import { useEffect, useState, type CSSProperties } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  ComposedChart, Line, Legend, PieChart, Pie,
} from "recharts";
import {
  fetchMcsiEda, fetchBikeDealers, fetchDealerModelMatrix, fetchGeoModel, fetchGeoModelColor,
  type McsiEdaData, type DealersData, type DealerModelMatrix,
  type GeoModelData, type GeoMatrixLevel,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { ModelPriceTab } from "../components/ModelPriceTab";
import { BuyerAgeTab } from "../components/BuyerAgeTab";
import { TrendingUp, Users, RotateCcw, DollarSign } from "lucide-react";

const MODEL_COLORS  = ["#4361EE","#EF4444","#2CC56F","#FFC107","#7C3AED","#06B6D4","#F97316","#10B981","#EC4899","#94A3B8"];
const PROV_COLORS   = ["#4361EE","#7C3AED","#2CC56F","#F97316","#EF4444","#06B6D4","#FFC107","#10B981","#EC4899","#94A3B8"];

// Map the actual SAP color name to a visual hex for charts.
// Priority order matters: "REDDISH YELLOW" must be checked before "RED".
// A colour family is chosen from the MCSI colour name; within a family each name gets
// its own shade (stable, from the name), so "BLACK METALLIC X", "MAT BLACK 2" and
// "LOW GLOSS BLACK" stay distinguishable when stacked.
const COLOR_FAMILIES: Record<string, string[]> = {
  yellow: ["#FFC107", "#FACC15", "#EAB308"],
  orange: ["#F97316", "#FB923C", "#EA580C"],
  green:  ["#2CC56F", "#16A34A", "#4ADE80", "#15803D"],
  cyan:   ["#06B6D4", "#22D3EE", "#0891B2"],
  blue:   ["#4361EE", "#1D4ED8", "#6366F1", "#3B82F6", "#7C3AED"],
  red:    ["#EF4444", "#DC2626", "#F87171"],
  gray:   ["#94A3B8", "#64748B", "#CBD5E1", "#475569", "#A1A1AA"],
  black:  ["#0F172A", "#1E293B", "#334155", "#3F3F46"],
  white:  ["#E2E8F0", "#F1F5F9"],
  other:  ["#CBD5E1", "#A8A29E"],
};

function colorFamily(u: string): string {
  if (u.includes("YELLOW")) return "yellow";
  if (u.includes("ORANGE")) return "orange";
  if (u.includes("GREEN"))  return "green";
  if (u.includes("CYAN"))   return "cyan";
  if (u.includes("PURPLISH RED") || u.includes("DUL RED") || /\bRED\b/.test(u)) return "red";
  if (u.includes("BLUE") || u.includes("PURPLISH")) return "blue";
  if (u.includes("GRAY") || u.includes("GREY") || u.includes("SILVER")) return "gray";
  if (u.includes("BLACK"))  return "black";
  if (u.includes("WHITE"))  return "white";
  return "other";
}

// Step `rank` of a shade ramp built from a family swatch: rank 0 is the swatch itself, each
// later rank mixes further toward white (toward slate for light swatches such as White).
function familyShade(hex: string, rank: number): string {
  const n = parseInt(hex.slice(1), 16);
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const target = isLightHex(hex) ? [100, 116, 139] : [255, 255, 255];
  const t = Math.min(0.78, rank * 0.16);
  const mixed = rgb.map((c, i) => Math.round(c + (target[i] - c) * t));
  return "#" + mixed.map(c => c.toString(16).padStart(2, "0")).join("");
}

// One label and one representative swatch per family, for the family analysis.
const FAMILY_META: Record<string, { label: string; swatch: string }> = {
  black:  { label: "Black",         swatch: "#0F172A" },
  gray:   { label: "Gray / Silver", swatch: "#94A3B8" },
  blue:   { label: "Blue",          swatch: "#4361EE" },
  cyan:   { label: "Cyan",          swatch: "#06B6D4" },
  green:  { label: "Green",         swatch: "#2CC56F" },
  red:    { label: "Red",           swatch: "#EF4444" },
  orange: { label: "Orange",        swatch: "#F97316" },
  yellow: { label: "Yellow",        swatch: "#FFC107" },
  white:  { label: "White",         swatch: "#E2E8F0" },
  other:  { label: "Other",         swatch: "#A8A29E" },
};

function getColorHex(name: string): string {
  const u = name.toUpperCase();
  const shades = COLOR_FAMILIES[colorFamily(u)];
  let hash = 0;
  for (let i = 0; i < u.length; i++) hash = (hash * 31 + u.charCodeAt(i)) >>> 0;
  return shades[hash % shades.length];
}

// Light fills (whites, pale greys, yellows) need dark text and an outline to stay readable.
function isLightHex(hex: string): boolean {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.299 * r + 0.587 * g + 0.114 * b > 170;
}

function pillStyle(name: string): CSSProperties {
  const bg = getColorHex(name);
  const light = isLightHex(bg);
  return {
    background: bg,
    color: light ? "#1E293B" : "#FFFFFF",
    boxShadow: light ? "inset 0 0 0 1px #94A3B8" : undefined,
  };
}

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type Tab = "trend" | "model" | "price" | "age" | "color" | "year" | "geo" | "dealer";

export function McsiEDA() {
  const [data,     setData]     = useState<McsiEdaData | null>(null);
  const [dealers,  setDealers]  = useState<DealersData | null>(null);
  const [tab,      setTab]      = useState<Tab>("trend");
  const [dlrSearch, setDlrSearch] = useState("");
  const [dlrYear,   setDlrYear]   = useState<number | undefined>(undefined);
  const [dealerView, setDealerView] = useState<"overview" | "matrix">("overview");
  const [geoSub,      setGeoSub]      = useState<"rm" | "ase" | "province" | "district">("rm");
  const [geoView,     setGeoView]     = useState<"overview" | "model" | "model_color">("overview");
  const [dealerMatrix, setDealerMatrix] = useState<DealerModelMatrix | null>(null);
  const [dealerMatrixError, setDealerMatrixError] = useState(false);
  const [geoModel,      setGeoModel]      = useState<GeoModelData | null>(null);
  const [geoModelColor, setGeoModelColor] = useState<GeoModelData | null>(null);
  const [hoveredModel,  setHoveredModel]  = useState<string | null>(null);
  const [hoveredColor,  setHoveredColor]  = useState<string | null>(null);
  const [colorView,     setColorView]     = useState<"colour" | "family">("colour");
  const [hoveredFamily, setHoveredFamily] = useState<string | null>(null);
  const [hoveredFamModel, setHoveredFamModel] = useState<string | null>(null);
  const [collapsedFams, setCollapsedFams] = useState<Set<string>>(new Set());

  useEffect(() => { fetchMcsiEda().then(setData); }, []);
  useEffect(() => {
    fetchDealerModelMatrix().then(setDealerMatrix).catch(() => setDealerMatrixError(true));
  }, []);
  useEffect(() => { fetchGeoModel().then(setGeoModel); }, []);
  useEffect(() => { fetchGeoModelColor().then(setGeoModelColor); }, []);
  useEffect(() => { fetchBikeDealers(500, dlrYear).then(setDealers); }, [dlrYear]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const { kpis, monthly_trend, by_year, by_model, by_province, by_color, by_rm, by_ase, by_district } = data;

  const TABS: { key: Tab; label: string }[] = [
    { key: "trend",  label: "Monthly Trend"        },
    { key: "model",  label: "By Model"              },
    { key: "price",  label: "Price vs Sales"        },
    { key: "age",    label: "Buyer Age × Model × Colour" },
    { key: "color",  label: "By Color"              },
    { key: "year",   label: "By Year"               },
    { key: "geo",    label: "RM / ASE / Geography" },
    { key: "dealer", label: "Dealer Performance" },
  ];

  // ── Dealer Performance tab data prep ───────────────────────────────────────
  const filteredDealers = dealers?.rows.filter(r =>
    !dlrSearch || [r.province, r.rm, r.ase, r.dealer].some(v =>
      v.toLowerCase().includes(dlrSearch.toLowerCase())
    )
  ) ?? [];

  const provinceBarData = (() => {
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

  // ── Color tab data prep ─────────────────────────────────────────────────────
  // Colour totals across all models; colours are ordered biggest first, so the legend
  // reads as a ranking and the stack starts with the dominant colour.
  const colorTotals = by_color.reduce<Record<string, number>>((acc, r) => {
    acc[r.color] = (acc[r.color] ?? 0) + r.units_sold;
    return acc;
  }, {});
  const colorGrandTotal = Object.values(colorTotals).reduce((s, v) => s + v, 0);
  const colorKeys = Object.keys(colorTotals).sort((a, b) => colorTotals[b] - colorTotals[a]);
  // Pivot: one row per model with a key per color (values are number | string)
  type ColorBarRow = Record<string, number | string>;
  const colorBarData: ColorBarRow[] = Object.values(
    by_color.reduce<Record<string, ColorBarRow>>((acc, r) => {
      if (!acc[r.model]) acc[r.model] = { model: r.model };
      acc[r.model][r.color] = ((acc[r.model][r.color] as number) ?? 0) + r.units_sold;
      return acc;
    }, {})
  ).sort((a, b) => {
    const totalA = colorKeys.reduce((s, c) => s + ((a[c] as number) ?? 0), 0);
    const totalB = colorKeys.reduce((s, c) => s + ((b[c] as number) ?? 0), 0);
    return totalB - totalA;
  });

  // ── Colour family prep: each MCSI colour rolls up to its family (same rule as the chart shades)
  type FamilyStat = { family: string; units: number; colours: Set<string>; models: Map<string, number> };
  const familyStats: Record<string, FamilyStat> = {};
  const modelFamily: Record<string, Record<string, number>> = {};
  for (const r of by_color) {
    const fam = colorFamily(r.color.toUpperCase());
    const st = (familyStats[fam] ??= { family: fam, units: 0, colours: new Set(), models: new Map() });
    st.units += r.units_sold;
    st.colours.add(r.color);
    st.models.set(r.model, (st.models.get(r.model) ?? 0) + r.units_sold);
    const mf = (modelFamily[r.model] ??= {});
    mf[fam] = (mf[fam] ?? 0) + r.units_sold;
  }
  const familyKeys = Object.keys(familyStats).sort((a, b) => familyStats[b].units - familyStats[a].units);
  const familyTotal = familyKeys.reduce((s, f) => s + familyStats[f].units, 0);
  const familyModels = Object.keys(modelFamily)
    .map(model => ({ model, total: Object.values(modelFamily[model]).reduce((s, v) => s + v, 0) }))
    .sort((a, b) => b.total - a.total);
  // One row per family with a key per model (units); the chart expands each bar to 100%.
  const familyModelData = familyKeys.map(f => {
    const st = familyStats[f];
    const row: Record<string, number | string> = {
      label: FAMILY_META[f].label, _key: f, _total: st.units, unitsLabel: st.units.toLocaleString(),
    };
    for (const [model, units] of st.models) row[model] = units;
    return row;
  });
  // Each family bar is drawn in shades of that family's own colour: the model with the most
  // units gets the family swatch, the next ones step lighter (darker for White).
  const familyModelRank = new Map(familyKeys.map(f => [
    f,
    new Map([...familyStats[f].models.entries()].sort((a, b) => b[1] - a[1]).map(([m], i) => [m, i])),
  ]));
  const shadeFor = (fam: string, model: string) =>
    familyShade(FAMILY_META[fam].swatch, familyModelRank.get(fam)?.get(model) ?? 0);
  const pctOf = (v: number, t: number) => (t ? (v / t) * 100 : 0).toFixed(1);

  // Pie data for model share
  // "FZ FI V2 (B1N2)": the model name with its code, as the chart, pie and table show it.
  const modelRows = by_model.map(r => ({ ...r, label: r.model_label || r.model }));
  const modelPie = modelRows.slice(0, 8).map((r, i) => ({
    name: r.label, value: r.units_sold, share_pct: r.share_pct, fill: MODEL_COLORS[i % MODEL_COLORS.length],
  }));

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-800">MCSI Motorcycle Sales EDA</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Step 09 · VIN-level sold/returned classification · {kpis.date_from} → {kpis.date_to}
        </p>
      </div>

      {/* KPI grid — single row on large screens */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <KpiCard label="Total VINs Processed" value={fmt(kpis.total_vins)}
          sub={`${kpis.date_from} → ${kpis.date_to}`} color="blue"/>
        <KpiCard label="Bikes Sold" value={fmt(kpis.sold)}
          sub={`avg ${Math.round(kpis.avg_monthly_units).toLocaleString()} / month`} color="green" icon={<TrendingUp size={18}/>}/>
        <KpiCard label="Returns" value={fmt(kpis.returned)}
          sub={`${kpis.return_rate_pct.toFixed(2)}% return rate`}
          color={kpis.return_rate_pct > 5 ? "red" : "amber"} icon={<RotateCcw size={18}/>}/>
        <KpiCard label="Total Revenue" value={`LKR ${fmt(kpis.total_revenue_lkr)}`}
          sub={`LKR ${fmt(kpis.avg_revenue_per_unit)} / unit`} color="purple" icon={<DollarSign size={18}/>}/>
        <KpiCard label="Active Dealers" value={fmt(kpis.active_dealers)}
          color="blue" icon={<Users size={18}/>}/>
        <KpiCard label="Models Sold" value={kpis.models_sold.toString()} color="purple"/>
      </div>

      {/* Tab content */}
      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex gap-1 mb-5 border-b border-slate-100 pb-2 flex-wrap">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${
                tab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Monthly Trend ── */}
        {tab === "trend" && (
          <div className="space-y-5">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-1">Monthly Units Sold &amp; Revenue</h3>
              <p className="text-xs text-slate-400 mb-3">Bars = units sold (left axis) · Line = revenue LKR (right axis)</p>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={monthly_trend} margin={{ top: 5, right: 50, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                  <XAxis dataKey="period" tick={{ fontSize: 9 }} interval={2}/>
                  <YAxis yAxisId="left"  tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                  <Tooltip formatter={(v: unknown, name: unknown) =>
                    [`${name === "Revenue LKR" ? "LKR " : ""}${fmt(Number(v))}`, String(name)]}/>
                  <Legend wrapperStyle={{ fontSize: 11 }}/>
                  <Bar  yAxisId="left"  dataKey="sold"        name="Units Sold"   fill="#4361EE" radius={[3,3,0,0]} opacity={0.85}/>
                  <Line yAxisId="right" dataKey="revenue_lkr" name="Revenue LKR"  stroke="#F97316" strokeWidth={2} dot={false}/>
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Returns callout */}
            <div className={`rounded-lg px-4 py-3 border ${kpis.return_rate_pct > 5 ? "bg-red-50 border-red-100" : "bg-amber-50 border-amber-100"}`}>
              <p className="text-sm font-semibold text-slate-700">
                Return Rate: <span className={kpis.return_rate_pct > 5 ? "text-red-600" : "text-amber-600"}>
                  {kpis.return_rate_pct.toFixed(2)}%
                </span>
                <span className="ml-3 font-normal text-slate-500 text-xs">
                  ({kpis.returned.toLocaleString()} returned out of {(kpis.sold + kpis.returned).toLocaleString()} VINs)
                </span>
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Business rule: a VIN whose SlsVolQty sums to 1 is sold; one whose SlsVolQty sums to 0 is returned.
              </p>
              {(kpis.billing_reversals ?? 0) > 0 && (
                <p className="text-xs text-slate-500 mt-0.5">
                  Not counted as returns: {kpis.billing_reversals!.toLocaleString()} billing reversal row(s) (SlsVolQty −1);
                  {" "}{(kpis.rebilled_vins ?? 0).toLocaleString()} of those VINs were re-invoiced and are counted once, as sold.
                </p>
              )}
            </div>
          </div>
        )}

        {/* ── By Model ── */}
        {tab === "model" && (
          <div className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {/* Horizontal bar */}
              <div>
                <h3 className="text-sm font-semibold text-slate-700 mb-3">Units Sold by Model</h3>
                <ResponsiveContainer width="100%" height={Math.max(200, modelRows.length * 30)}>
                  <BarChart data={modelRows} layout="vertical" margin={{ top: 0, right: 60, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 9 }} width={190}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="units_sold" radius={[0, 3, 3, 0]} label={{ position: "right", fontSize: 10 }}>
                      {by_model.map((_, i) => <Cell key={i} fill={MODEL_COLORS[i % MODEL_COLORS.length]}/>)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Pie chart */}
              <div>
                <h3 className="text-sm font-semibold text-slate-700 mb-3">Market Share</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={modelPie} cx="50%" cy="50%" outerRadius={85} dataKey="value" nameKey="name"
                      label={(props: any) => `${props.name}: ${Number(props.share_pct).toFixed(2)}%`}
                      labelLine={false}>
                      {modelPie.map((d, i) => <Cell key={i} fill={d.fill}/>)}
                    </Pie>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Model table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">Model</th>
                    <th className="py-2 pr-3 text-right">Units Sold</th>
                    <th className="py-2 pr-3 text-right">Share %</th>
                    <th className="py-2 pr-3 text-right">Revenue (LKR)</th>
                    <th className="py-2 text-right">Avg Rev / Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {modelRows.map((r, i) => (
                    <tr key={r.model} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 flex items-center gap-2">
                        <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ background: MODEL_COLORS[i % MODEL_COLORS.length] }}/>
                        <span className="font-medium text-slate-800">{r.model_description || r.model}</span>
                        {r.model_description && (
                          <span className="font-mono text-xs text-slate-400">{r.model}</span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-slate-500">{r.share_pct.toFixed(2)}%</td>
                      <td className="py-2 pr-3 text-right">{fmt(r.revenue_lkr)}</td>
                      <td className="py-2 text-right text-slate-500">{fmt(r.avg_revenue_per_unit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── By Color ── */}
        {tab === "price" && <ModelPriceTab/>}
        {tab === "age"   && <BuyerAgeTab/>}

        {tab === "color" && (
          <div className="flex gap-1 border-b border-slate-100 pb-2 mb-5">
            {(["colour", "family"] as const).map(v => (
              <button key={v} onClick={() => setColorView(v)}
                className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                  colorView === v ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"
                }`}>
                {v === "colour" ? "By Colour" : "By Colour Family"}
              </button>
            ))}
          </div>
        )}

        {tab === "color" && colorView === "family" && (
          <div className="space-y-6">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-1">Colour Family Mix</h3>
              <p className="text-xs text-slate-400 mb-3">
                Each MCSI colour grouped into its family by name (e.g. MAT BLACK 2 and LOW GLOSS BLACK → Black;
                GRAYISH GREEN → Green) · sold VINs only · {familyTotal.toLocaleString()} units
              </p>

              {/* Overall mix as one 100% bar */}
              <div className="flex h-7 w-full rounded-md overflow-hidden ring-1 ring-slate-200">
                {familyKeys.map(f => {
                  const share = familyTotal ? familyStats[f].units / familyTotal : 0;
                  const sw = FAMILY_META[f].swatch;
                  return (
                    <div key={f} title={`${FAMILY_META[f].label}: ${pctOf(familyStats[f].units, familyTotal)}%`}
                      onMouseEnter={() => setHoveredFamily(f)} onMouseLeave={() => setHoveredFamily(null)}
                      className="h-full flex items-center justify-center text-[10px] font-semibold transition-opacity"
                      style={{ width: `${share * 100}%`, background: sw,
                        color: isLightHex(sw) ? "#1E293B" : "#FFFFFF",
                        opacity: hoveredFamily && hoveredFamily !== f ? 0.25 : 1 }}>
                      {share >= 0.06 ? `${FAMILY_META[f].label} ${pctOf(familyStats[f].units, familyTotal)}%` : ""}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Family cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {familyKeys.map(f => {
                const st = familyStats[f];
                const sw = FAMILY_META[f].swatch;
                const [topModel, topUnits] = [...st.models.entries()].sort((a, b) => b[1] - a[1])[0];
                const dim = hoveredFamily !== null && hoveredFamily !== f;
                return (
                  <div key={f}
                    onMouseEnter={() => setHoveredFamily(f)} onMouseLeave={() => setHoveredFamily(null)}
                    className={`rounded-lg border border-slate-200 p-3 transition-opacity ${dim ? "opacity-40" : ""}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-3.5 h-3.5 rounded-sm shrink-0"
                        style={{ background: sw, boxShadow: isLightHex(sw) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                      <span className="text-sm font-semibold text-slate-800 flex-1">{FAMILY_META[f].label}</span>
                      <span className="text-xs font-semibold text-slate-500 tabular-nums">{pctOf(st.units, familyTotal)}%</span>
                    </div>
                    <div className="text-xl font-bold text-slate-800 tabular-nums">{st.units.toLocaleString()}
                      <span className="text-xs font-normal text-slate-400 ml-1">units</span>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1">
                      {st.colours.size} colour{st.colours.size === 1 ? "" : "s"} · offered on {st.models.size} model{st.models.size === 1 ? "" : "s"}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      Top model: <span className="text-slate-700 font-medium">{topModel}</span> ({pctOf(topUnits, st.units)}%)
                    </div>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {[...st.colours].sort().map(c => (
                        <span key={c} className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={pillStyle(c)}>{c}</span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Each colour family, split by the models that sell it */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-1">Colour Family by Model</h3>
              <p className="text-xs text-slate-400 mb-3">
                Each bar is 100% of one colour family's sold units, split by the models that carry it ·
                drawn in that family's colour, darkest = model with the most units · units on the right ·
                hover a model below to pick it out
              </p>

              {/* Model legend: biggest model first, with its total units */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-4 gap-y-1 mb-4">
                {familyModels.map(({ model, total }) => {
                  const dim = hoveredFamModel !== null && hoveredFamModel !== model;
                  return (
                    <div key={model}
                      onMouseEnter={() => setHoveredFamModel(model)}
                      onMouseLeave={() => setHoveredFamModel(null)}
                      className={`flex items-center gap-2 px-2 py-1 rounded-md cursor-default transition-opacity ${
                        hoveredFamModel === model ? "bg-slate-100" : "hover:bg-slate-50"} ${dim ? "opacity-40" : ""}`}>
                      <span className="text-xs text-slate-700 truncate flex-1" title={model}>{model}</span>
                      <span className="text-xs font-semibold text-slate-800 tabular-nums">{total.toLocaleString()}</span>
                    </div>
                  );
                })}
              </div>

              <ResponsiveContainer width="100%" height={Math.max(220, familyModelData.length * 46)}>
                <BarChart data={familyModelData} layout="vertical" stackOffset="expand"
                  margin={{ top: 5, right: 70, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => `${Math.round(Number(v) * 100)}%`}/>
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 11 }} width={110}/>
                  <YAxis yAxisId="units" orientation="right" type="category" dataKey="unitsLabel"
                    tick={{ fontSize: 10, fill: "#64748B" }} axisLine={false} tickLine={false} width={60}/>
                  <Tooltip cursor={{ fill: "#F8FAFC" }} content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const row = payload[0].payload as Record<string, number | string>;
                    const fam = String(row._key);
                    const total = Number(row._total);
                    const items = [...familyStats[fam].models.entries()].sort((a, b) => b[1] - a[1]);
                    return (
                      <div className="bg-white border border-slate-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                        <div className="flex items-center gap-2 font-semibold text-slate-800 mb-1">
                          <span className="w-2.5 h-2.5 rounded-sm"
                            style={{ background: FAMILY_META[fam].swatch,
                              boxShadow: isLightHex(FAMILY_META[fam].swatch) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                          {FAMILY_META[fam].label} — shared by {items.length} model{items.length === 1 ? "" : "s"}
                        </div>
                        {items.map(([model, units]) => (
                          <div key={model} className="flex items-center gap-2 py-0.5">
                            <span className="w-2.5 h-2.5 rounded-sm shrink-0"
                              style={{ background: shadeFor(fam, model),
                                boxShadow: isLightHex(shadeFor(fam, model)) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                            <span className="text-slate-600 flex-1">{model}</span>
                            <span className="font-semibold text-slate-800 tabular-nums ml-4">{units.toLocaleString()}</span>
                            <span className="text-slate-400 tabular-nums w-12 text-right">{pctOf(units, total)}%</span>
                          </div>
                        ))}
                        <div className="flex justify-between border-t border-slate-100 mt-1 pt-1 text-slate-500">
                          <span>Total</span><span className="tabular-nums">{total.toLocaleString()}</span>
                        </div>
                      </div>
                    );
                  }}/>
                  {familyModels.map(({ model }) => (
                    <Bar key={model} dataKey={model} stackId="fm" name={model}
                      stroke="#FFFFFF" strokeWidth={1.5}
                      fillOpacity={hoveredFamModel !== null && hoveredFamModel !== model ? 0.15 : 1}
                      label={(props: { x?: number | string; y?: number | string; width?: number | string;
                                       height?: number | string; index?: number }) => {
                        const x = Number(props.x), y = Number(props.y);
                        const w = Number(props.width), h = Number(props.height);
                        const row = familyModelData[props.index ?? 0];
                        if (!row || !(Number(row[model]) > 0) || w < 60) return <g/>;
                        const fill = shadeFor(String(row._key), model);
                        const maxChars = Math.floor((w - 8) / 5.6);
                        const text = model.length > maxChars ? model.slice(0, Math.max(0, maxChars - 1)) + "…" : model;
                        return (
                          <text x={x + w / 2} y={y + h / 2} dy={3.5} textAnchor="middle" fontSize={10}
                            fontWeight={600} pointerEvents="none"
                            fill={isLightHex(fill) ? "#1E293B" : "#FFFFFF"}
                            opacity={hoveredFamModel !== null && hoveredFamModel !== model ? 0.2 : 1}>
                            {text}
                          </text>
                        );
                      }}>
                      {familyModelData.map(row => (
                        <Cell key={String(row._key)} fill={shadeFor(String(row._key), model)}/>
                      ))}
                    </Bar>
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Family → model table, same shape and shading as the chart above */}
            <div className="overflow-x-auto">
              <div className="flex items-center mb-2">
                <h3 className="text-sm font-semibold text-slate-700">Colour Family by Model — Detail</h3>
                <div className="ml-auto flex gap-1">
                  <button onClick={() => setCollapsedFams(new Set())}
                    className="px-2.5 py-1 text-xs rounded-md font-medium border text-slate-500 border-slate-200 hover:bg-slate-50">
                    Expand all
                  </button>
                  <button onClick={() => setCollapsedFams(new Set(familyKeys))}
                    className="px-2.5 py-1 text-xs rounded-md font-medium border text-slate-500 border-slate-200 hover:bg-slate-50">
                    Collapse all
                  </button>
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3 text-left">Family / Model</th>
                    <th className="py-2 px-2 text-right">Units</th>
                    <th className="py-2 px-2 text-left w-[32%]">Share of family</th>
                    <th className="py-2 px-2 text-right" title="How much of the model's own sales this family is">Share of model</th>
                    <th className="py-2 pl-2 text-right">Share of all units</th>
                  </tr>
                </thead>
                <tbody>
                  {familyKeys.map(f => {
                    const st = familyStats[f];
                    const sw = FAMILY_META[f].swatch;
                    const open = !collapsedFams.has(f);
                    const models = [...st.models.entries()].sort((a, b) => b[1] - a[1]);
                    return [
                      <tr key={f} className="border-t border-slate-200 bg-slate-50 cursor-pointer select-none hover:bg-slate-100"
                        onClick={() => setCollapsedFams(prev => {
                          const next = new Set(prev);
                          if (next.has(f)) next.delete(f); else next.add(f);
                          return next;
                        })}>
                        <td className="py-2 pr-3">
                          <span className="inline-flex items-center gap-2">
                            <span className="text-slate-400 text-xs w-3">{open ? "▾" : "▸"}</span>
                            <span className="w-3.5 h-3.5 rounded-sm shrink-0"
                              style={{ background: sw, boxShadow: isLightHex(sw) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                            <span className="font-semibold text-slate-800">{FAMILY_META[f].label}</span>
                            <span className="text-xs text-slate-400">
                              {models.length} model{models.length === 1 ? "" : "s"} · {st.colours.size} colour{st.colours.size === 1 ? "" : "s"}
                            </span>
                          </span>
                        </td>
                        <td className="py-2 px-2 text-right font-bold text-slate-800 tabular-nums">{st.units.toLocaleString()}</td>
                        <td className="py-2 px-2">
                          {/* the family's model split, as a mini version of its chart bar */}
                          <div className="flex h-3 w-full rounded-sm overflow-hidden">
                            {models.map(([m, u]) => (
                              <div key={m} title={`${m}: ${pctOf(u, st.units)}%`}
                                style={{ width: `${(u / st.units) * 100}%`, background: shadeFor(f, m),
                                  borderRight: "1px solid #FFFFFF" }}/>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 px-2 text-right text-slate-400">—</td>
                        <td className="py-2 pl-2 text-right font-semibold text-slate-700 tabular-nums">
                          {pctOf(st.units, familyTotal)}%
                        </td>
                      </tr>,
                      ...(open ? models.map(([m, u]) => {
                        const shade = shadeFor(f, m);
                        const modelTotal = familyModels.find(x => x.model === m)?.total ?? 0;
                        const shareFam = st.units ? u / st.units : 0;
                        return (
                          <tr key={`${f}–${m}`}
                            onMouseEnter={() => setHoveredFamModel(m)} onMouseLeave={() => setHoveredFamModel(null)}
                            className={`border-b border-slate-50 ${hoveredFamModel === m ? "bg-blue-50/50" : "hover:bg-slate-50/50"}`}>
                            <td className="py-1.5 pr-3 pl-10">
                              <span className="inline-flex items-center gap-2">
                                <span className="w-2.5 h-2.5 rounded-sm shrink-0"
                                  style={{ background: shade, boxShadow: isLightHex(shade) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                                <span className="text-slate-700">{m}</span>
                              </span>
                            </td>
                            <td className="py-1.5 px-2 text-right font-semibold text-brand-blue tabular-nums">{u.toLocaleString()}</td>
                            <td className="py-1.5 px-2">
                              <div className="flex items-center gap-2">
                                <div className="flex-1 h-2.5 bg-slate-100 rounded-sm overflow-hidden">
                                  <div className="h-full rounded-sm"
                                    style={{ width: `${shareFam * 100}%`, background: shade,
                                      boxShadow: isLightHex(shade) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                                </div>
                                <span className="text-xs font-semibold text-slate-700 tabular-nums w-12 text-right">
                                  {pctOf(u, st.units)}%
                                </span>
                              </div>
                            </td>
                            <td className="py-1.5 px-2 text-right text-slate-600 tabular-nums">{pctOf(u, modelTotal)}%</td>
                            <td className="py-1.5 pl-2 text-right text-slate-400 tabular-nums">{pctOf(u, familyTotal)}%</td>
                          </tr>
                        );
                      }) : []),
                    ];
                  })}
                  <tr className="border-t-2 border-slate-300 font-semibold">
                    <td className="py-2 pr-3 text-slate-700">All families</td>
                    <td className="py-2 px-2 text-right text-slate-800 tabular-nums">{familyTotal.toLocaleString()}</td>
                    <td className="py-2 px-2">
                      <div className="flex h-3 w-full rounded-sm overflow-hidden">
                        {familyKeys.map(f => (
                          <div key={f} title={`${FAMILY_META[f].label}: ${pctOf(familyStats[f].units, familyTotal)}%`}
                            style={{ width: `${(familyStats[f].units / familyTotal) * 100}%`,
                              background: FAMILY_META[f].swatch, borderRight: "1px solid #FFFFFF" }}/>
                        ))}
                      </div>
                    </td>
                    <td className="py-2 px-2 text-right text-slate-400">—</td>
                    <td className="py-2 pl-2 text-right text-slate-700 tabular-nums">100.0%</td>
                  </tr>
                </tbody>
              </table>
              <p className="text-[11px] text-slate-400 mt-2">
                Click a family row to expand or collapse it. <b>Share of family</b>: the model's part of that
                family's units (the chart bar). <b>Share of model</b>: how much of that model's own sales are in
                this family. <b>Share of all units</b>: against every sold unit.
              </p>
            </div>
          </div>
        )}

        {tab === "color" && colorView === "colour" && (
          <div className="space-y-5">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-1">Model Sales by Color — Stacked Units</h3>
              <p className="text-xs text-slate-400 mb-3">
                Sold VINs only (SlsVolQty sums to 1) · colour from the MCSI Color column ·
                hover a colour below to pick it out in the chart
              </p>

              {/* Legend: one tidy grid, biggest colour first, with units and share */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-4 gap-y-1 mb-4">
                {colorKeys.map(color => {
                  const hex = getColorHex(color);
                  const dim = hoveredColor !== null && hoveredColor !== color;
                  return (
                    <div key={color}
                      onMouseEnter={() => setHoveredColor(color)}
                      onMouseLeave={() => setHoveredColor(null)}
                      className={`flex items-center gap-2 px-2 py-1 rounded-md cursor-default transition-opacity ${
                        hoveredColor === color ? "bg-slate-100" : "hover:bg-slate-50"} ${dim ? "opacity-40" : ""}`}>
                      <span className="w-3.5 h-3.5 rounded-sm shrink-0"
                        style={{ background: hex, boxShadow: isLightHex(hex) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                      <span className="text-xs text-slate-700 truncate flex-1" title={color}>{color}</span>
                      <span className="text-xs font-semibold text-slate-800 tabular-nums">
                        {colorTotals[color].toLocaleString()}
                      </span>
                      <span className="text-[10px] text-slate-400 tabular-nums w-10 text-right">
                        {colorGrandTotal ? (colorTotals[color] / colorGrandTotal * 100).toFixed(1) : "0.0"}%
                      </span>
                    </div>
                  );
                })}
              </div>

              <ResponsiveContainer width="100%" height={Math.max(260, colorBarData.length * 42)}>
                <BarChart data={colorBarData} layout="vertical" margin={{ top: 5, right: 60, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
                  <YAxis type="category" dataKey="model" tick={{ fontSize: 9 }} width={210}/>
                  <Tooltip cursor={{ fill: "#F8FAFC" }} content={({ active, payload, label }) => {
                    if (!active || !payload) return null;
                    const items = payload
                      .filter(p => Number(p.value) > 0)
                      .sort((a, b) => Number(b.value) - Number(a.value));
                    const total = items.reduce((s, p) => s + Number(p.value), 0);
                    return (
                      <div className="bg-white border border-slate-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                        <div className="font-semibold text-slate-800 mb-1">{label}</div>
                        {items.map(p => {
                          const hex = getColorHex(String(p.name));
                          return (
                            <div key={String(p.name)} className="flex items-center gap-2 py-0.5">
                              <span className="w-2.5 h-2.5 rounded-sm shrink-0"
                                style={{ background: hex, boxShadow: isLightHex(hex) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                              <span className="text-slate-600 flex-1">{String(p.name)}</span>
                              <span className="font-semibold text-slate-800 tabular-nums ml-4">
                                {Number(p.value).toLocaleString()}
                              </span>
                            </div>
                          );
                        })}
                        <div className="flex justify-between border-t border-slate-100 mt-1 pt-1 text-slate-500">
                          <span>Total</span><span className="tabular-nums">{total.toLocaleString()}</span>
                        </div>
                      </div>
                    );
                  }}/>
                  {colorKeys.map(color => {
                    const hex = getColorHex(color);
                    return (
                      <Bar key={color} dataKey={color} stackId="a" name={color} fill={hex}
                        stroke={isLightHex(hex) ? "#94A3B8" : undefined} strokeWidth={isLightHex(hex) ? 1 : 0}
                        fillOpacity={hoveredColor !== null && hoveredColor !== color ? 0.15 : 1}/>
                    );
                  })}
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Breakdown table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">Model</th>
                    <th className="py-2 pr-3">Color</th>
                    <th className="py-2 pr-3 text-right">Units Sold</th>
                    <th className="py-2 text-right">Share within Model</th>
                  </tr>
                </thead>
                <tbody>
                  {by_color.map((r, i) => {
                    const modelTotal = by_color.filter(x => x.model === r.model).reduce((s, x) => s + x.units_sold, 0);
                    const sharePct = modelTotal ? (r.units_sold / modelTotal * 100).toFixed(1) : "0.0";
                    return (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                        <td className="py-2 pr-3 font-medium text-slate-800">{r.model}</td>
                        <td className="py-2 pr-3">
                          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-0.5 rounded-full font-medium"
                            style={pillStyle(r.color)}>
                            {r.color}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                        <td className="py-2 text-right text-slate-500">{sharePct}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── By Year ── */}
        {tab === "year" && (
          <div className="space-y-5">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Annual Sales Summary</h3>
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={by_year} margin={{ top: 5, right: 50, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                  <XAxis dataKey="year" tick={{ fontSize: 11 }}/>
                  <YAxis yAxisId="left"  tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                  <Tooltip formatter={(v: unknown, name: unknown) =>
                    [`${name === "Revenue LKR" ? "LKR " : ""}${fmt(Number(v))}`, String(name)]}/>
                  <Legend wrapperStyle={{ fontSize: 11 }}/>
                  <Bar  yAxisId="left"  dataKey="units_sold"   name="Units Sold"  fill="#4361EE" radius={[3,3,0,0]}/>
                  <Line yAxisId="right" dataKey="revenue_lkr"  name="Revenue LKR" stroke="#F97316" strokeWidth={2} dot={{ r: 4 }}/>
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                    <th className="py-2 pr-3">Year</th>
                    <th className="py-2 pr-3 text-right">Units Sold</th>
                    <th className="py-2 pr-3 text-right">Avg / Month</th>
                    <th className="py-2 text-right">Revenue (LKR)</th>
                  </tr>
                </thead>
                <tbody>
                  {by_year.map(r => (
                    <tr key={r.year} className="border-b border-slate-50 hover:bg-slate-50/50">
                      <td className="py-2 pr-3 font-semibold text-slate-800">{r.year}</td>
                      <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right text-slate-500">{r.avg_monthly.toFixed(1)}</td>
                      <td className="py-2 text-right">{fmt(r.revenue_lkr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── RM / ASE / Geography ── */}
        {tab === "geo" && (
          <div className="space-y-4">
            {/* Sub-tab switcher */}
            <div className="flex gap-1 border-b border-slate-100 pb-2">
                {(["rm", "ase", "province", "district"] as const).map(s => (
                <button key={s} onClick={() => { setGeoSub(s); setGeoView("overview"); }}
                  className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                    geoSub === s ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"
                  }`}>
                  {s === "rm" ? "Regional Manager"
                   : s === "ase" ? "Area Sales Executive"
                   : s === "province" ? "By Province"
                   : "By District"}
                </button>
              ))}
              {/* view toggle */}
              <div className="ml-auto flex gap-1">
                {(["overview", "model", "model_color"] as const).map(v => (
                  <button key={v} onClick={() => setGeoView(v)}
                    className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors border ${
                      geoView === v
                        ? "bg-slate-700 text-white border-slate-700"
                        : "text-slate-400 border-slate-200 hover:bg-slate-50"
                    }`}>
                    {v === "overview" ? "Overview" : v === "model" ? "× Model" : "× Model × Color"}
                  </button>
                ))}
              </div>
            </div>

            {/* ── RM panel ── */}
            {geoView === "overview" && geoSub === "rm" && (
              <div className="space-y-4">
                <ResponsiveContainer width="100%" height={Math.max(180, by_rm.length * 36)}>
                  <BarChart data={[...by_rm].reverse()} layout="vertical" margin={{ top: 0, right: 80, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
                    <YAxis type="category" dataKey="rm" tick={{ fontSize: 10 }} width={90}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="units_sold" name="Units Sold" radius={[0, 4, 4, 0]}
                      label={{ position: "right", fontSize: 10 }}>
                      {[...by_rm].reverse().map((_, i) => <Cell key={i} fill={MODEL_COLORS[i % MODEL_COLORS.length]}/>)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                        <th className="py-2 pr-3">Regional Manager</th>
                        <th className="py-2 pr-3 text-right">Units Sold</th>
                        <th className="py-2 pr-3 text-right">Share %</th>
                        <th className="py-2 pr-3 text-right">Revenue (LKR)</th>
                        <th className="py-2 pr-3 text-right">Avg Rev / Unit</th>
                        <th className="py-2 pr-3 text-right">Dealers</th>
                        <th className="py-2 text-right">ASEs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {by_rm.map((r, i) => (
                        <tr key={r.rm} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="py-2 pr-3 flex items-center gap-2">
                            <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                              style={{ background: MODEL_COLORS[i % MODEL_COLORS.length] }}/>
                            <span className="font-medium text-slate-800">{r.rm}</span>
                          </td>
                          <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-slate-500">{r.share_pct.toFixed(1)}%</td>
                          <td className="py-2 pr-3 text-right">{fmt(r.revenue_lkr)}</td>
                          <td className="py-2 pr-3 text-right text-slate-400">{fmt(r.avg_revenue_per_unit)}</td>
                          <td className="py-2 pr-3 text-right text-slate-500">{r.dealer_count}</td>
                          <td className="py-2 text-right text-slate-500">{r.ase_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* ── ASE panel ── */}
            {geoView === "overview" && geoSub === "ase" && (
              <div className="space-y-4">
                <ResponsiveContainer width="100%" height={Math.max(220, by_ase.length * 34)}>
                  <BarChart data={[...by_ase].reverse()} layout="vertical" margin={{ top: 0, right: 80, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
                    <YAxis type="category" dataKey="ase" tick={{ fontSize: 10 }} width={100}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="units_sold" name="Units Sold" radius={[0, 4, 4, 0]}
                      label={{ position: "right", fontSize: 10 }}>
                      {[...by_ase].reverse().map((r, i) => (
                        <Cell key={i} fill={MODEL_COLORS[by_rm.findIndex(rm => rm.rm === r.rm) % MODEL_COLORS.length] ?? "#94A3B8"}/>
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                        <th className="py-2 pr-3">ASE</th>
                        <th className="py-2 pr-3">Regional Manager</th>
                        <th className="py-2 pr-3 text-right">Units Sold</th>
                        <th className="py-2 pr-3 text-right">Share %</th>
                        <th className="py-2 pr-3 text-right">Revenue (LKR)</th>
                        <th className="py-2 text-right">Dealers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {by_ase.map((r, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="py-2 pr-3 font-medium text-slate-800">{r.ase}</td>
                          <td className="py-2 pr-3">
                            <span className="text-xs px-2 py-0.5 rounded-full font-medium text-white"
                              style={{ background: MODEL_COLORS[by_rm.findIndex(rm => rm.rm === r.rm) % MODEL_COLORS.length] ?? "#94A3B8" }}>
                              {r.rm}
                            </span>
                          </td>
                          <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-slate-500">{r.share_pct.toFixed(1)}%</td>
                          <td className="py-2 pr-3 text-right">{fmt(r.revenue_lkr)}</td>
                          <td className="py-2 text-right text-slate-500">{r.dealer_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* ── Province panel ── */}
            {geoView === "overview" && geoSub === "province" && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-3">Units Sold by Province</h3>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={by_province} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                        <XAxis dataKey="province" tick={{ fontSize: 10 }}/>
                        <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                        <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                        <Bar dataKey="units_sold" radius={[4, 4, 0, 0]}>
                          {by_province.map((_, i) => <Cell key={i} fill={PROV_COLORS[i % PROV_COLORS.length]}/>)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-3">Revenue by Province (LKR)</h3>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={by_province} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                        <XAxis dataKey="province" tick={{ fontSize: 10 }}/>
                        <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                        <Tooltip formatter={(v: unknown) => `LKR ${fmt(Number(v))}`}/>
                        <Bar dataKey="revenue_lkr" name="Revenue" radius={[4, 4, 0, 0]}>
                          {by_province.map((_, i) => <Cell key={i} fill={PROV_COLORS[i % PROV_COLORS.length]}/>)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                        <th className="py-2 pr-3">Province</th>
                        <th className="py-2 pr-3 text-right">Units Sold</th>
                        <th className="py-2 pr-3 text-right">Share %</th>
                        <th className="py-2 pr-3 text-right">Revenue (LKR)</th>
                        <th className="py-2 text-right">Dealers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {by_province.map((r, i) => (
                        <tr key={r.province} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="py-2 pr-3 flex items-center gap-2">
                            <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                              style={{ background: PROV_COLORS[i % PROV_COLORS.length] }}/>
                            <span className="font-medium text-slate-800">{r.province}</span>
                          </td>
                          <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-slate-500">{r.share_pct.toFixed(1)}%</td>
                          <td className="py-2 pr-3 text-right">{fmt(r.revenue_lkr)}</td>
                          <td className="py-2 text-right text-slate-500">{r.dealer_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* ── District panel ── */}
            {geoView === "overview" && geoSub === "district" && (
              <div className="space-y-4">
                <ResponsiveContainer width="100%" height={Math.max(260, by_district.length * 28)}>
                  <BarChart data={[...by_district].reverse()} layout="vertical" margin={{ top: 0, right: 70, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
                    <YAxis type="category" dataKey="district" tick={{ fontSize: 9 }} width={100}/>
                    <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                    <Bar dataKey="units_sold" name="Units Sold" radius={[0, 4, 4, 0]}
                      label={{ position: "right", fontSize: 9 }}>
                      {[...by_district].reverse().map((r, i) => (
                        <Cell key={i} fill={PROV_COLORS[by_province.findIndex(p => p.province === r.province) % PROV_COLORS.length] ?? "#94A3B8"}/>
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                        <th className="py-2 pr-3">Province</th>
                        <th className="py-2 pr-3">District</th>
                        <th className="py-2 pr-3 text-right">Units Sold</th>
                        <th className="py-2 pr-3 text-right">Share %</th>
                        <th className="py-2 text-right">Revenue (LKR)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {by_district.map((r, i) => (
                        <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                          <td className="py-2 pr-3">
                            <span className="inline-flex items-center gap-1.5 text-xs">
                              <span className="w-2 h-2 rounded-full inline-block shrink-0"
                                style={{ background: PROV_COLORS[by_province.findIndex(p => p.province === r.province) % PROV_COLORS.length] ?? "#94A3B8" }}/>
                              {r.province}
                            </span>
                          </td>
                          <td className="py-2 pr-3 font-medium text-slate-800">{r.district}</td>
                          <td className="py-2 pr-3 text-right font-semibold text-brand-blue">{r.units_sold.toLocaleString()}</td>
                          <td className="py-2 pr-3 text-right text-slate-500">{r.share_pct.toFixed(1)}%</td>
                          <td className="py-2 text-right">{fmt(r.revenue_lkr)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* ── × Model panel (shared across all sub-tabs) ── */}
            {geoView === "model" && (() => {
              const level: GeoMatrixLevel | undefined = geoModel
                ? geoModel[geoSub as keyof GeoModelData]
                : undefined;
              if (!level || level.rows.length === 0)
                return <div className="py-12 text-center text-slate-400">Loading…</div>;
              const { models: gm, rows: gr } = level;
              const colMax: Record<string, number> = {};
              for (const m of gm) colMax[m] = Math.max(1, ...gr.map(r => r.totals[m] ?? 0));
              const entityLabel = geoSub === "rm" ? "Regional Manager"
                : geoSub === "ase" ? "ASE"
                : geoSub === "province" ? "Province"
                : "District";
              return (
                <div className="space-y-2">
                  <p className="text-xs text-slate-400">
                    {gr.length} {entityLabel}s × {gm.length} models · sorted by total units (desc)
                  </p>
                  <div className="overflow-x-auto">
                    <table className="text-xs w-full border-collapse">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase text-left">
                          <th className="py-2 px-2 font-semibold sticky left-0 bg-slate-50 z-10 min-w-[140px]">{entityLabel}</th>
                          <th className="py-2 px-2 font-semibold text-right min-w-[52px]">Total</th>
                          {gm.map(m => (
                            <th key={m} className="py-2 px-2 text-right font-semibold min-w-[70px]">{m}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {gr.map((r, ri) => (
                          <tr key={ri} className="border-b border-slate-100 hover:bg-slate-50/60">
                            <td className="py-1.5 px-2 font-medium text-slate-800 sticky left-0 bg-white z-10">{r.entity}</td>
                            <td className="py-1.5 px-2 text-right font-bold text-slate-800">{r.total.toLocaleString()}</td>
                            {gm.map(m => {
                              const v = r.totals[m] ?? 0;
                              const opacity = v === 0 ? 0 : 0.12 + 0.78 * (v / colMax[m]);
                              return (
                                <td key={m} className="py-1.5 px-2 text-right"
                                  style={{
                                    background: v > 0 ? `rgba(67,97,238,${opacity.toFixed(2)})` : "transparent",
                                    color: opacity > 0.55 ? "#fff" : v > 0 ? "#1E3A8A" : "#CBD5E1",
                                    fontWeight: v > 0 ? 600 : 400,
                                  }}>
                                  {v > 0 ? v.toLocaleString() : "—"}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}

            {/* ── × Model × Color stacked column chart ── */}
            {geoView === "model_color" && (() => {
              const level: GeoMatrixLevel | undefined = geoModelColor
                ? geoModelColor[geoSub as keyof GeoModelData]
                : undefined;
              if (!level || level.rows.length === 0)
                return <div className="py-12 text-center text-slate-400">Loading…</div>;
              const { models: combos, rows: cr } = level;
              const entityLabel = geoSub === "rm" ? "Regional Manager"
                : geoSub === "ase" ? "ASE"
                : geoSub === "province" ? "Province"
                : "District";

              // One column per entity; stacked by "Model – Color" combo
              // combos are already the stack keys; color extracted for fill
              const chartData = cr.map(r => {
                const d: Record<string, number | string> = { entity: r.entity };
                for (const combo of combos) d[combo] = r.totals[combo] ?? 0;
                return d;
              });

              // Per-combo fill: extract SAP color suffix from "Model – Color"
              const comboFill = (combo: string): string => {
                const sep = combo.indexOf(" – ");
                return getColorHex(sep >= 0 ? combo.slice(sep + 3) : combo);
              };

              // Custom tooltip — shows only the hovered model's colors (non-zero)
              const McColorTooltip = ({ active, payload, label }: {
                active?: boolean;
                payload?: Array<{ name: string; value: number; fill: string }>;
                label?: string;
              }) => {
                if (!active || !payload) return null;
                const entries = payload.filter(p => {
                  if (Number(p.value) <= 0) return false;
                  if (!hoveredModel) return true;
                  const sep = p.name.indexOf(" – ");
                  const model = sep >= 0 ? p.name.slice(0, sep) : p.name;
                  return model === hoveredModel;
                });
                if (entries.length === 0) return null;
                const modelTotal = entries.reduce((s, e) => s + Number(e.value), 0);
                return (
                  <div className="bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-xs max-w-[240px]">
                    <p className="font-bold text-slate-800 pb-1 mb-1 border-b border-slate-100">{label}</p>
                    {hoveredModel && (
                      <p className="font-semibold text-slate-600 mb-1.5">{hoveredModel}</p>
                    )}
                    {entries.map(e => {
                      const sep = e.name.indexOf(" – ");
                      const colorName = sep >= 0 ? e.name.slice(sep + 3) : e.name;
                      return (
                        <div key={e.name} className="flex items-center gap-1.5 py-0.5">
                          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: e.fill }}/>
                          <span className="text-slate-500 flex-1 truncate">{colorName}</span>
                          <span className="font-bold text-slate-800 ml-1">{Number(e.value).toLocaleString()}</span>
                        </div>
                      );
                    })}
                    {entries.length > 1 && (
                      <div className="flex justify-between mt-1.5 pt-1.5 border-t border-slate-100">
                        <span className="text-slate-400">Total</span>
                        <span className="font-bold text-slate-800">{modelTotal.toLocaleString()}</span>
                      </div>
                    )}
                  </div>
                );
              };

              // Unique models → determines how many sub-bars per entity group
              const modelSet = new Set<string>();
              for (const combo of combos) {
                const sep = combo.indexOf(" – ");
                modelSet.add(sep >= 0 ? combo.slice(0, sep) : combo);
              }
              const numModels = modelSet.size;
              const numEntities = cr.length;

              // Each entity group needs (numModels × barW) + groupGap px
              const BAR_W = 28;
              const GROUP_GAP = 20;
              const Y_AXIS_W = 52;
              const MARGIN_R = 24;
              const minChartW = numEntities * (numModels * BAR_W + GROUP_GAP) + Y_AXIS_W + MARGIN_R + 40;
              // Label area below x-axis (angled entity names)
              const maxLabelLen = Math.max(...cr.map(r => r.entity.length));
              const labelH = Math.min(100, Math.max(60, maxLabelLen * 5));
              const chartH = 380 + labelH;

              return (
                <div className="space-y-4">
                  <p className="text-xs text-slate-400">
                    {entityLabel} × Model × Color · {numEntities} entities · {numModels} models · {combos.length} color variants
                  </p>
                  <div className="bg-white rounded-xl shadow-sm p-4 overflow-x-auto">
                    <div style={{ minWidth: minChartW }}>
                      <ResponsiveContainer width="100%" height={chartH}>
                        <BarChart data={chartData} barCategoryGap="20%" barGap={2}
                          margin={{ top: 8, right: MARGIN_R, left: 8, bottom: labelH }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false}/>
                          <XAxis dataKey="entity" tick={{ fontSize: 11, fill: "#475569" }}
                            angle={-40} textAnchor="end" interval={0}/>
                          <YAxis tick={{ fontSize: 10 }} width={Y_AXIS_W}
                            tickFormatter={v => Number(v).toLocaleString()}/>
                          <Tooltip content={<McColorTooltip/>} cursor={false}/>
                          {combos.map(combo => {
                            const sep = combo.indexOf(" – ");
                            const model = sep >= 0 ? combo.slice(0, sep) : combo;
                            const dimmed = hoveredModel !== null && hoveredModel !== model;
                            return (
                              <Bar key={combo} dataKey={combo} name={combo} stackId={model}
                                maxBarSize={BAR_W} fill={comboFill(combo)}
                                legendType="none"
                                opacity={dimmed ? 0.2 : 1}
                                onMouseEnter={() => setHoveredModel(model)}
                                onMouseLeave={() => setHoveredModel(null)}/>
                            );
                          })}
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    {/* Custom model-only legend */}
                    {(() => {
                      const seen = new Set<string>();
                      const modelEntries: { model: string; fill: string }[] = [];
                      for (const combo of combos) {
                        const sep = combo.indexOf(" – ");
                        const model = sep >= 0 ? combo.slice(0, sep) : combo;
                        if (!seen.has(model)) {
                          seen.add(model);
                          modelEntries.push({ model, fill: comboFill(combo) });
                        }
                      }
                      return (
                        <div className="flex flex-wrap gap-x-5 gap-y-2 justify-center mt-3 pt-3 border-t border-slate-100">
                          {modelEntries.map(({ model, fill }) => (
                            <div key={model}
                              className={`flex items-center gap-1.5 cursor-default transition-opacity ${hoveredModel && hoveredModel !== model ? "opacity-30" : "opacity-100"}`}
                              onMouseEnter={() => setHoveredModel(model)}
                              onMouseLeave={() => setHoveredModel(null)}>
                              <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: fill }}/>
                              <span className="text-xs text-slate-700 font-medium">{model}</span>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>

                  {/* ── × Model × Color matrix table ── */}
                  {(() => {
                  // Build model groups: { model, colors[] } in combo order
                  const modelGroups: { model: string; colors: string[] }[] = [];
                  for (const combo of combos) {
                    const sep = combo.indexOf(" – ");
                    const m = sep >= 0 ? combo.slice(0, sep) : combo;
                    const c = sep >= 0 ? combo.slice(sep + 3) : combo;
                    const grp = modelGroups.find(g => g.model === m);
                    if (grp) grp.colors.push(c);
                    else modelGroups.push({ model: m, colors: [c] });
                  }
                  // Per-column max for heat-map intensity
                  const colMax: Record<string, number> = {};
                  for (const combo of combos)
                    colMax[combo] = Math.max(1, ...cr.map(r => r.totals[combo] ?? 0));

                  return (
                    <div className="bg-white rounded-xl shadow-sm overflow-x-auto">
                      <table className="text-xs w-full border-collapse">
                        <thead>
                          <tr className="text-left">
                            <th rowSpan={2}
                              className="py-2 px-2 font-semibold uppercase sticky left-0 bg-slate-100 z-10 min-w-[140px] border-b-2 border-slate-300 align-bottom">
                              {entityLabel}
                            </th>
                            <th rowSpan={2}
                              className="py-2 px-2 font-semibold uppercase text-right min-w-[52px] border-b-2 border-slate-300 align-bottom bg-slate-50">
                              Total
                            </th>
                            {modelGroups.map(g => (
                              <th key={g.model} colSpan={g.colors.length}
                                className="py-1.5 px-2 text-center font-bold text-slate-700 bg-slate-100 border-l-2 border-slate-300 border-b border-slate-200">
                                {g.model}
                              </th>
                            ))}
                          </tr>
                          <tr className="bg-slate-50 border-b-2 border-slate-300 text-slate-500">
                            {modelGroups.map(g =>
                              g.colors.map((color, ci) => (
                                <th key={`${g.model}–${color}`}
                                  className={`py-1.5 px-2 text-right font-medium min-w-[80px] ${ci === 0 ? "border-l-2 border-slate-300" : "border-l border-slate-100"}`}>
                                  <span className="inline-flex items-center justify-end gap-1">
                                    <span className="w-2 h-2 rounded-full inline-block shrink-0"
                                      style={{ background: getColorHex(color),
                                        boxShadow: isLightHex(getColorHex(color)) ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                                    <span className="text-[9px] uppercase">{color}</span>
                                  </span>
                                </th>
                              ))
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {cr.map((r, ri) => (
                            <tr key={ri} className="border-b border-slate-100 hover:bg-slate-50/60">
                              <td className="py-1.5 px-2 font-medium text-slate-800 sticky left-0 bg-white z-10">{r.entity}</td>
                              <td className="py-1.5 px-2 text-right font-bold text-slate-800">{r.total.toLocaleString()}</td>
                              {modelGroups.map(g =>
                                g.colors.map((color, ci) => {
                                  const combo = `${g.model} – ${color}`;
                                  const hex = getColorHex(color);
                                  const v = r.totals[combo] ?? 0;
                                  const opacity = v === 0 ? 0 : 0.12 + 0.78 * (v / colMax[combo]);
                                  const bg = v > 0
                                    ? `${hex}${Math.round(opacity * 255).toString(16).padStart(2, "0")}`
                                    : "transparent";
                                  return (
                                    <td key={combo}
                                      className={`py-1.5 px-2 text-right ${ci === 0 ? "border-l-2 border-slate-200" : "border-l border-slate-100"}`}
                                      style={{
                                        background: bg,
                                        color: opacity > 0.55 && !isLightHex(hex) ? "#fff" : v > 0 ? "#1E293B" : "#CBD5E1",
                                        fontWeight: v > 0 ? 600 : 400,
                                      }}>
                                      {v > 0 ? v.toLocaleString() : "—"}
                                    </td>
                                  );
                                })
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                  })()}
                </div>
              );
            })()}
          </div>
        )}

        {/* ── Dealer Performance ── */}
        {tab === "dealer" && (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-1 border-b border-slate-100 pb-2">
              {(["overview", "matrix"] as const).map(view => (
                <button key={view} type="button" onClick={() => setDealerView(view)}
                  aria-pressed={dealerView === view}
                  className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                    dealerView === view ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"
                  }`}>
                  {view === "overview" ? "Overview" : "Dealer × Model Sales Matrix"}
                </button>
              ))}
            </div>

            {dealerView === "overview" && (
              <>
            {/* Year filter + KPIs */}
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <p className="text-xs text-slate-500">Province → RM → ASE → Dealer hierarchy · Units sold &amp; revenue</p>
              {dealers && dealers.available_years.length > 0 && (
                <select
                  className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                  value={dlrYear ?? ""}
                  onChange={e => setDlrYear(e.target.value ? Number(e.target.value) : undefined)}
                >
                  <option value="">All years</option>
                  {dealers.available_years.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              )}
            </div>

            {dealers ? (
              <>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <KpiCard label="Total Dealers" value={dealers.total_dealers.toLocaleString()} color="blue" sub={dlrYear ? `Year ${dlrYear}` : "All years"}/>
                  <KpiCard label="Total Units"   value={fmt(dealers.total_units)}               color="green"/>
                  <KpiCard label="Total Revenue" value={`LKR ${fmt(dealers.total_revenue_lkr)}`} color="purple"/>
                </div>

                {/* Province bar */}
                <div className="bg-white rounded-xl shadow-sm p-5">
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">Units Sold by Province</h3>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={provinceBarData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                      <XAxis dataKey="province" tick={{ fontSize: 11 }}/>
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                      <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                      <Bar dataKey="units" name="Units Sold" radius={[4, 4, 0, 0]}>
                        {provinceBarData.map((d, i) => <Cell key={d.province} fill={PROV_COLORS[i % PROV_COLORS.length]}/>)}
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
                      value={dlrSearch}
                      onChange={e => setDlrSearch(e.target.value)}
                    />
                    <span className="text-xs text-slate-400">{filteredDealers.length} dealers</span>
                  </div>
                  <div className="max-h-[560px] overflow-auto rounded-md border border-slate-100"
                    role="region" aria-label="Dealer overview table" tabIndex={0}>
                    <table className="w-full min-w-[780px] text-sm">
                      <thead className="sticky top-0 z-20 bg-slate-50">
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
                        {filteredDealers.map((r, i) => (
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
                  </div>
                </div>

              </>
            ) : (
              <div className="flex items-center justify-center py-12 text-slate-400">Loading dealer data…</div>
            )}
              </>
            )}

            {/* Dealer × Model matrix */}
            {dealerView === "matrix" && (
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-700">Dealer × Model Sales Matrix</h3>
            {!dealerMatrix && (
              <p className="py-12 text-center text-sm text-slate-500">
                {dealerMatrixError ? "Unable to load dealer-model sales." : "Loading dealer-model sales…"}
              </p>
            )}
            {dealerMatrix && dealerMatrix.models.length === 0 && (
              <p className="py-12 text-center text-sm text-slate-500">No dealer-model sales available.</p>
            )}
            {dealerMatrix && dealerMatrix.models.length > 0 && (() => {
              const { models: dmModels, rows: dmRows } = dealerMatrix;
              const colMax: Record<string, number> = {};
              for (const m of dmModels) colMax[m] = Math.max(1, ...dmRows.map(r => r.totals[m] ?? 0));
              return (
                <>
                  <p className="text-xs text-slate-500">All years · {dmRows.length} dealers × {dmModels.length} models</p>
                  <div className="max-h-[560px] overflow-auto rounded-md border border-slate-100"
                    role="region" aria-label="Dealer by model sales matrix" tabIndex={0}>
                    <table className="text-xs w-full min-w-max border-collapse">
                      <thead className="sticky top-0 z-20 bg-slate-50">
                        <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase text-left">
                          <th className="py-2 px-2 font-semibold sticky left-0 bg-slate-50 z-30 min-w-[160px]">Dealer</th>
                          <th className="py-2 px-2 font-semibold min-w-[80px]">Province</th>
                          <th className="py-2 px-2 font-semibold min-w-[80px]">RM</th>
                          <th className="py-2 px-2 font-semibold min-w-[80px]">ASE</th>
                          <th className="py-2 px-2 font-semibold text-right min-w-[52px]">Total</th>
                          {dmModels.map(m => (
                            <th key={m} className="py-2 px-2 text-right font-semibold min-w-[70px]">{m}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dmRows.map((r, ri) => (
                          <tr key={ri} className="border-b border-slate-100 hover:bg-slate-50/60">
                            <td className="py-1.5 px-2 font-medium text-slate-800 sticky left-0 bg-white z-10 max-w-[200px] truncate" title={r.dealer}>
                              {r.dealer}
                            </td>
                            <td className="py-1.5 px-2 text-slate-500">{r.province}</td>
                            <td className="py-1.5 px-2 text-slate-500">{r.rm}</td>
                            <td className="py-1.5 px-2 text-slate-500">{r.ase}</td>
                            <td className="py-1.5 px-2 text-right font-bold text-slate-800">{r.total.toLocaleString()}</td>
                            {dmModels.map(m => {
                              const v = r.totals[m] ?? 0;
                              const opacity = v === 0 ? 0 : 0.12 + 0.78 * (v / colMax[m]);
                              return (
                                <td key={m} className="py-1.5 px-2 text-right"
                                  style={{
                                    background: v > 0 ? `rgba(67,97,238,${opacity.toFixed(2)})` : "transparent",
                                    color: opacity > 0.55 ? "#fff" : v > 0 ? "#1E3A8A" : "#CBD5E1",
                                    fontWeight: v > 0 ? 600 : 400,
                                  }}>
                                  {v > 0 ? v.toLocaleString() : "—"}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              );
            })()}
            </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
