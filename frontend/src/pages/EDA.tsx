import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  Legend, PieChart, Pie,
} from "recharts";
import {
  fetchOrdersEda, fetchSalesEda,
  type OrdersEdaData, type SalesEdaData,
  type DealerType, type McCategoryType,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { SkuClassificationTab } from "../components/SkuClassificationTab";
import { InventoryStatusTab } from "../components/InventoryStatusTab";
import { TimePicker, filterByRange, type TimeRange, YearPicker, filterByYear, getYears, monthLabel } from "../components/TimePicker";

const CAT_COLORS = ["#EF4444","#F97316","#FFC107","#4361EE","#2CC56F","#7C3AED","#94A3B8"];
// MC – Lubricant, Battery, Tyre, Spare Parts, OBM
const SEG_PALETTE = ["#F97316","#3B82F6","#22C55E","#8B5CF6","#06B6D4"];

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

function RetBadge({ pct }: { pct: number }) {
  const [bg, color] = pct > 10 ? ["#FEE2E2","#DC2626"] : pct > 5 ? ["#FEF9C3","#B45309"] : ["#F1F5F9","#64748B"];
  return <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold tabular-nums" style={{ background: bg, color }}>{pct.toFixed(1)}%</span>;
}

function FulfillBadge({ pct }: { pct: number }) {
  if (!pct) return <span className="text-slate-300 text-xs">—</span>;
  const [bg, color] = pct >= 80 ? ["#DCFCE7","#16A34A"] : pct >= 50 ? ["#FEF9C3","#B45309"] : ["#FEE2E2","#DC2626"];
  return <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold tabular-nums" style={{ background: bg, color }}>{pct.toFixed(1)}%</span>;
}

function ValueBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-1 mt-0.5">
      <div className="w-12 flex-shrink-0 bg-slate-100 rounded-full h-[3px]">
        <div className="h-[3px] rounded-full bg-brand-blue" style={{ width: `${Math.min(pct, 100)}%` }}/>
      </div>
      <span className="text-[10px] text-slate-400 tabular-nums">{pct.toFixed(1)}%</span>
    </div>
  );
}

type Tab = "orders" | "sales" | "classification" | "inventory";
type EdaSection = "overview" | "performance";
type EdaPanel   = "parts" | "dealers" | "rm" | "ase" | "province" | "district";

const SECTION_TABS: { key: EdaSection; label: string }[] = [
  { key: "overview",    label: "Overview" },
  { key: "performance", label: "Performance" },
];
const PANEL_OPTIONS: { key: EdaPanel; label: string }[] = [
  { key: "parts",    label: "Spare Parts" },
  { key: "dealers",  label: "Dealers" },
  { key: "rm",       label: "RM" },
  { key: "ase",      label: "ASE" },
  { key: "province", label: "Province" },
  { key: "district", label: "District" },
];
const NO_PANELS: Set<EdaPanel> = new Set();

function togglePanel(set: Set<EdaPanel>, setSet: (s: Set<EdaPanel>) => void, key: EdaPanel) {
  const next = new Set(set);
  if (next.has(key)) next.delete(key); else next.add(key);
  setSet(next);
}

/** Overview / Performance — single-select, styled to match the page's top-level tab row. */
function SectionTabs({ value, onChange }: { value: EdaSection; onChange: (s: EdaSection) => void }) {
  return (
    <div className="flex gap-1 border-b border-slate-100 pb-2 flex-wrap">
      {SECTION_TABS.map(t => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${
            value === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"
          }`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Multi-select toggles shown under the Performance tab — each switches its panel on/off. */
function PanelToggles({ selected, onToggle }: { selected: Set<EdaPanel>; onToggle: (k: EdaPanel) => void }) {
  return (
    <div className="flex gap-1.5 flex-wrap items-center">
      {PANEL_OPTIONS.map(({ key, label }) => (
        <button key={key} type="button" aria-pressed={selected.has(key)} onClick={() => onToggle(key)}
          className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
            selected.has(key) ? "bg-slate-700 text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
          }`}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function EDA() {
  const [ordersData,       setOrdersData]       = useState<OrdersEdaData | null>(null);
  const [_ordersSalesData, setOrdersSalesData] = useState<SalesEdaData | null>(null);
  const [salesData,        setSalesData]        = useState<SalesEdaData | null>(null);
  const [searchParams] = useSearchParams();
  const initialTab = searchParams.get("tab");
  const [tab,             setTab]             = useState<Tab>(
    initialTab === "classification" || initialTab === "inventory" ? initialTab : "orders"
  );
  const [ordersDt,        setOrdersDt]        = useState<DealerType>("ALL");
  const [ordersMcCat,     setOrdersMcCat]     = useState<McCategoryType>("ALL");
  const [ordersApiYear,   setOrdersApiYear]   = useState<number>(0);  // 0 = latest year (API resolves)
  const [ordersYear,      setOrdersYear]      = useState<number | "All">("All");
  const [ordersRange,     setOrdersRange]     = useState<TimeRange>("YTD");
  const [ordersSection,   setOrdersSection]   = useState<EdaSection>("overview");
  const [ordersPanels,    setOrdersPanels]    = useState<Set<EdaPanel>>(new Set(["parts"]));
  const [salesDt,     setSalesDt]     = useState<DealerType>("ALL");
  const [salesMcCat,  setSalesMcCat]  = useState<string>("ALL");
  const [salesYear,   setSalesYear]   = useState<number>(0);   // 0 = latest year (API resolves)
  const [salesRange,  setSalesRange]  = useState<TimeRange>("YTD");
  const [salesSection, setSalesSection] = useState<EdaSection>("overview");
  const [salesPanels,  setSalesPanels]  = useState<Set<EdaPanel>>(new Set(["parts"]));
  const [salesPartSearch,   setSalesPartSearch]   = useState("");
  const [salesDealerSearch, setSalesDealerSearch] = useState("");

  // Panel toggles only take effect while the Performance tab is active.
  const activeOrdersPanels = ordersSection === "performance" ? ordersPanels : NO_PANELS;
  const activeSalesPanels  = salesSection  === "performance" ? salesPanels  : NO_PANELS;

  useEffect(() => {
    fetchOrdersEda(ordersDt, ordersMcCat, ordersApiYear).then(d => {
      setOrdersData(null);
      setOrdersData(d);
      // On first load (year=0) sync chart picker to the year the API resolved
      if (ordersApiYear === 0 && d.data_year) setOrdersApiYear(d.data_year);
      const yrs = getYears(d.monthly_trend);
      if (yrs.length) setOrdersYear(yrs[0]);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordersDt, ordersMcCat, ordersApiYear]);

  // Fetch companion sales data only when ALL/OBM is selected (staggered to avoid concurrent load)
  useEffect(() => {
    if (ordersDt === "ALL" || ordersDt === "OBM") {
      setOrdersSalesData(null);
      fetchSalesEda(ordersDt, "ALL").then(setOrdersSalesData);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordersDt]);

  useEffect(() => {
    setSalesData(null);
    fetchSalesEda(salesDt, salesMcCat, salesYear).then(d => {
      setSalesData(d);
      // On first load (year=0) sync the picker to the year the API resolved
      if (salesYear === 0 && d.data_year) setSalesYear(d.data_year);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [salesDt, salesMcCat, salesYear]);

  const TABS = [
    { key: "orders" as Tab, label: "Orders Analysis (Steps 03–05)" },
    { key: "sales"  as Tab, label: "Sales Analysis (Step 04)"  },
    { key: "classification" as Tab, label: "SKU Classification" },
    { key: "inventory"      as Tab, label: "Inventory Status"   },
  ];

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <h2 className="text-xl font-bold text-slate-800">Motorcycle Spare Parts EDA</h2>
      <p className="text-xs text-slate-500 -mt-4">Steps 03-06 and 12 - dealer demand, billed sales, classification and PDC inventory</p>

      {/* Global KPIs — the selected orders period, against the same months a year earlier */}
      {(() => {
        const pp = ordersData?.prior_period;
        const pct = (curr: number, prev: number | undefined) =>
          prev ? `${curr >= prev ? "+" : ""}${((curr / prev - 1) * 100).toFixed(1)}%` : null;
        const period = ordersData?.period_label ?? "";
        const vs = pp ? ` vs ${pp.label}` : "";
        const fillPts = ordersData && pp ? (ordersData.avg_fill_rate - pp.fill_rate) * 100 : null;
        return (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard label={`Order value · ${period}`}
              value={ordersData ? `LKR ${fmt(ordersData.total_order_value_lkr)}` : "…"}
              sub={ordersData && pp ? `${pct(ordersData.total_order_value_lkr, pp.ordered_value)}${vs}` : "all dealer orders (C)"} color="blue"/>
            <KpiCard label={`Order lines · ${period}`}
              value={ordersData ? ordersData.total_po.toLocaleString() : "…"}
              sub={ordersData ? `${ordersData.total_po_documents.toLocaleString()} order documents${pp ? ` · ${pct(ordersData.total_po, pp.order_lines)}${vs}` : ""}` : ""} color="teal"/>
            <KpiCard label={`Qty fill rate · ${period}`}
              value={ordersData ? `${(ordersData.avg_fill_rate * 100).toFixed(1)}%` : "…"}
              sub={ordersData ? `${fillPts != null ? `${fillPts >= 0 ? "+" : ""}${fillPts.toFixed(1)} pts${vs} · ` : ""}${fmt(ordersData.lost_quantity ?? 0)} units lost` : ""}
              color={fillPts != null && fillPts < 0 ? "red" : "green"}/>
            <KpiCard label={`Net revenue · ${salesData?.data_year ?? ""}`}
              value={salesData ? `LKR ${fmt(salesData.net_sale_value_lkr)}` : "…"}
              sub="billed minus returns (sales.xlsx — separate extract)" color="purple"/>
          </div>
        );
      })()}

      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex gap-1 mb-5 border-b border-slate-100 pb-2 flex-wrap">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${tab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Orders EDA ── */}
        {tab === "orders" && (
          <div className="space-y-5">
            {/* Year picker, section tabs, panel toggles + Spare Parts category filters */}
            <div className="space-y-2">
              {ordersData && ordersData.available_years.length > 0 && (
                <div className="flex gap-2 flex-wrap items-center">
                  <select
                    value={ordersApiYear}
                    onChange={e => setOrdersApiYear(Number(e.target.value))}
                    className="border border-slate-200 rounded-lg px-3 py-1 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                  >
                    {ordersData.available_years.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
              )}
              <SectionTabs value={ordersSection} onChange={setOrdersSection}/>
              {ordersSection === "performance" && (
                <>
                  <PanelToggles selected={ordersPanels} onToggle={k => togglePanel(ordersPanels, setOrdersPanels, k)}/>
                  {ordersPanels.has("parts") && (
                    <div className="flex gap-2 flex-wrap items-center">
                      <select
                        value={ordersDt}
                        onChange={e => { setOrdersDt(e.target.value as DealerType); setOrdersMcCat("ALL"); }}
                        className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                      >
                        <option value="ALL">All</option>
                        <option value="MC">MC</option>
                        <option value="OBM">OBM</option>
                      </select>

                      <select
                        value={ordersMcCat}
                        onChange={e => setOrdersMcCat(e.target.value as McCategoryType)}
                        disabled={ordersDt === "OBM"}
                        className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs font-medium text-purple-700 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer disabled:text-slate-400 disabled:bg-slate-50 disabled:cursor-default"
                      >
                        {ordersDt === "OBM" ? (
                          <option value="ALL">OBM Spare Parts</option>
                        ) : (
                          <>
                            <option value="ALL">{ordersDt === "MC" ? "All MC" : "All"}</option>
                            <option value="Lubricant">Lubricant</option>
                            <option value="Battery">Battery</option>
                            <option value="Tyre">Tyre</option>
                            <option value="SpareParts">Spare Parts</option>
                          </>
                        )}
                      </select>
                    </div>
                  )}
                </>
              )}
            </div>

          {ordersData ? (
            <div className="space-y-5">
              {/* ── ALL / OBM / MC (All + Spare Parts) — 11-KPI overview — renders first ── */}
              {ordersSection === "overview" && (
                ordersDt === "ALL" || ordersDt === "OBM" ||
                (ordersDt === "MC" && (ordersMcCat === "ALL" || ordersMcCat === "SpareParts"))
              ) && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <KpiCard label="Order Received"    value={`LKR ${fmt(ordersData.total_order_value_lkr)}`}              sub="All C-orders incl. cancelled/rejected"   color="blue"/>
                    <KpiCard label="Total Sales"       value={`LKR ${fmt(ordersData.total_confirmed_value_lkr)}`}           sub="Confirmed delivery value (orders.xlsx)"  color="green"/>
                    <KpiCard label="Order Fulfillment" value={`${ordersData.value_fill_rate_pct.toFixed(1)}%`}              sub="Confirmed value ÷ Order Received"        color="teal"/>
                    <KpiCard label="Rejection Rate"    value={`${ordersData.rejection_rate_pct.toFixed(1)}%`}               sub="PO lines fully undelivered"              color="amber"/>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <KpiCard label="Qty Fill Rate"     value={`${(ordersData.avg_fill_rate * 100).toFixed(1)}%`}            sub={`${ordersData.fill_rate_lt1_count} parts short-shipped`} color="purple"/>
                    <KpiCard label="Total POs"         value={ordersData.total_po_documents.toLocaleString()}               sub="Unique purchase order documents"         color="blue"/>
                    <KpiCard label="Avg Dispatch LT"   value={`${ordersData.avg_lead_time_days.toFixed(1)} days`}           sub="Warehouse → dealer"                      color="purple"/>
                    <KpiCard label="Return Value"      value={`LKR ${fmt(ordersData.total_return_value_lkr)}`}              sub="H-type return order value"               color="red"/>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <KpiCard label="Unfulfill Value"   value={`LKR ${fmt(ordersData.unfulfill_value_lkr)}`}                sub="Ordered but not confirmed"               color="amber"/>
                    <KpiCard label="Sales Qty"         value={ordersData.sales_qty.toLocaleString('en-US', {maximumFractionDigits: 0})} sub="Confirmed units"            color="green"/>
                    <KpiCard label="Unique SKU"        value={ordersData.unique_skus.toLocaleString()}                     sub="Materials ordered"                       color="teal"/>
                  </div>
                  {/* Monthly chart — only for ALL/OBM/SpareParts; MC ALL has its own chart+dealers block below */}
                  {!(ordersDt === "MC" && ordersMcCat === "ALL") && (
                    <div>
                      <div className="flex items-center justify-between mb-3">
                        <div>
                          <h3 className="text-sm font-semibold text-slate-700">Monthly Order Value (LKR)</h3>
                          <p className="text-xs text-slate-400 mt-0.5">Order Received vs Confirmed Sales</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <YearPicker years={getYears(ordersData.monthly_trend)} value={ordersYear} onChange={setOrdersYear}/>
                          <TimePicker value={ordersRange} onChange={setOrdersRange}/>
                        </div>
                      </div>
                      <ResponsiveContainer width="100%" height={200}>
                        <BarChart data={filterByRange(filterByYear(ordersData.monthly_trend, ordersYear), ordersRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                          <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0} tickFormatter={p => monthLabel(p, ordersYear !== "All")}/>
                          <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                          <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]} labelFormatter={p => String(p)}/>
                          <Legend wrapperStyle={{ fontSize: 10 }}/>
                          <Bar dataKey="total_value_lkr"     fill="#94A3B8" name="Order Received" radius={[2,2,0,0]}/>
                          <Bar dataKey="confirmed_value_lkr" fill="#4361EE" name="Total Sales"    radius={[2,2,0,0]}/>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              )}

              {/* ── MC ALL monthly chart — renders after KPIs ── */}
              {ordersSection === "overview" && ordersDt === "MC" && ordersMcCat === "ALL" && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700">Monthly Order Value (LKR)</h3>
                      <p className="text-xs text-slate-400 mt-0.5">Order Received vs Confirmed Sales</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <YearPicker years={getYears(ordersData.monthly_trend)} value={ordersYear} onChange={setOrdersYear}/>
                      <TimePicker value={ordersRange} onChange={setOrdersRange}/>
                    </div>
                  </div>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={filterByRange(filterByYear(ordersData.monthly_trend, ordersYear), ordersRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                      <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                        tickFormatter={p => monthLabel(p, ordersYear !== "All")}/>
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                      <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]} labelFormatter={p => String(p)}/>
                      <Legend wrapperStyle={{ fontSize: 10 }}/>
                      <Bar dataKey="total_value_lkr"     fill="#94A3B8" name="Order Received" radius={[2,2,0,0]}/>
                      <Bar dataKey="confirmed_value_lkr" fill="#4361EE" name="Total Sales"    radius={[2,2,0,0]}/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Rejection reasons pie — MC only */}
              {ordersSection === "overview" && ordersDt === "MC" && ordersMcCat === "ALL" && ordersData.rejection_reasons.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Rejection Reasons</h3>
                    <p className="text-xs text-slate-400 mb-3">Fully-rejected PO lines by reason code · share of total rejections</p>
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={ordersData.rejection_reasons.map(r => ({
                            name: r.reason || "Unspecified",
                            value: r.rejected_lines,
                            share: r.share_pct,
                          }))}
                          dataKey="value" cx="50%" cy="50%" outerRadius={85} innerRadius={36}
                          label={({ share }: any) => `${(share ?? 0).toFixed(0)}%`}
                          labelLine={true}
                        >
                          {ordersData.rejection_reasons.map((_, i) => (
                            <Cell key={i} fill={CAT_COLORS[i % CAT_COLORS.length]}/>
                          ))}
                        </Pie>
                        <Tooltip formatter={(v: unknown, _n: unknown, p: any) => [`${Number(v).toLocaleString()} lines · ${(p.payload?.share ?? 0).toFixed(1)}%`, p.payload?.name ?? ""]}/>
                        <Legend wrapperStyle={{ fontSize: 10 }}/>
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="flex flex-col gap-2 justify-center">
                    {ordersData.rejection_reasons.map((r, i) => (
                      <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-4 py-2">
                        <span className="flex items-center gap-2 text-xs text-slate-700">
                          <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: CAT_COLORS[i % CAT_COLORS.length] }}/>
                          {r.reason || "Unspecified"}
                        </span>
                        <span className="flex items-center gap-3 text-xs">
                          <span className="font-bold text-red-600">{r.rejected_lines.toLocaleString()} lines</span>
                          <span className="text-slate-400 w-10 text-right">{r.share_pct.toFixed(1)}%</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}


              {/* ══ Fulfillment Analysis (Qty & Value) ══════════════════════ */}
              {ordersSection === "overview" && ordersData.fulfillment && (
                <div className="pt-3 border-t border-slate-200 space-y-4">
                  <div>
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Fulfillment Analysis</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Order Quantity vs Confirmed Quantity · PO lines only ·{" "}
                      {ordersData.fulfillment.total_lines.toLocaleString()} lines across{" "}
                      {ordersData.fulfillment.total_docs.toLocaleString()} documents
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* ── Line-level ── */}
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700 mb-1">By Line</h3>
                      <p className="text-xs text-slate-400 mb-2">
                        Each order item line — Confirmed Qty vs Order Qty
                      </p>
                      {/* Stacked progress bar */}
                      <div className="flex h-5 rounded-full overflow-hidden mb-3 gap-0.5">
                        <div style={{ width: `${ordersData.fulfillment.fully_confirmed.pct_of_lines}%`, background: '#22C55E' }} className="h-full rounded-l-full"/>
                        <div style={{ width: `${ordersData.fulfillment.partially_confirmed.pct_of_lines}%`, background: '#F59E0B' }} className="h-full"/>
                        <div style={{ width: `${ordersData.fulfillment.fully_rejected.pct_of_lines}%`, background: '#EF4444' }} className="h-full rounded-r-full"/>
                      </div>
                      {[
                        { label: 'Fully Confirmed',     color: '#22C55E', bucket: ordersData.fulfillment.fully_confirmed,     sub: 'Conf ≥ Order' },
                        { label: 'Partially Confirmed', color: '#F59E0B', bucket: ordersData.fulfillment.partially_confirmed, sub: '0 < Conf < Order' },
                        { label: 'Fully Rejected',      color: '#EF4444', bucket: ordersData.fulfillment.fully_rejected,      sub: 'Conf = 0' },
                      ].map(({ label, color, bucket, sub }) => (
                        <div key={label} className="flex items-start gap-3 bg-slate-50 rounded-lg px-3 py-2.5 mb-1.5">
                          <span className="w-2.5 h-2.5 rounded-sm mt-0.5 flex-shrink-0" style={{ background: color }}/>
                          <div className="flex-1 min-w-0">
                            <div className="flex justify-between items-baseline">
                              <span className="text-xs font-semibold text-slate-700">{label}</span>
                              <span className="text-sm font-bold" style={{ color }}>{Number(bucket.pct_of_lines ?? 0).toFixed(2)}%</span>
                            </div>
                            <div className="text-xs text-slate-400 mt-0.5">{sub}</div>
                            <div className="grid grid-cols-3 gap-x-2 mt-1 text-xs">
                              <span className="text-slate-500">{bucket.lines.toLocaleString()} <span className="text-slate-400">lines</span></span>
                              <span className="text-slate-500">Ord <span className="font-medium text-slate-700">{Number(bucket.order_qty).toLocaleString('en-US', {maximumFractionDigits:0})}</span></span>
                              <span className="text-slate-500">Conf <span className="font-medium text-slate-700">{Number(bucket.confirmed_qty).toLocaleString('en-US', {maximumFractionDigits:0})}</span></span>
                            </div>
                            {bucket.confirmed_value_lkr > 0 && (
                              <div className="text-xs mt-0.5 text-slate-500">
                                Value <span className="font-semibold text-slate-700">LKR {fmt(bucket.confirmed_value_lkr)}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* ── Document-level ── */}
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700 mb-1">By Order Document</h3>
                      <p className="text-xs text-slate-400 mb-2">
                        Each Sales Document (PO) — all lines combined
                      </p>
                      <div className="flex h-5 rounded-full overflow-hidden mb-3 gap-0.5">
                        <div style={{ width: `${ordersData.fulfillment.docs_fully_filled_pct}%`, background: '#22C55E' }} className="h-full rounded-l-full"/>
                        <div style={{ width: `${ordersData.fulfillment.docs_partially_filled_pct}%`, background: '#F59E0B' }} className="h-full"/>
                        <div style={{ width: `${ordersData.fulfillment.docs_complete_zero_pct}%`, background: '#EF4444' }} className="h-full rounded-r-full"/>
                      </div>
                      {[
                        { label: 'Fully Filled',     color: '#22C55E', count: ordersData.fulfillment.docs_fully_filled,     pct: ordersData.fulfillment.docs_fully_filled_pct,     sub: 'All lines: Conf ≥ Order' },
                        { label: 'Partially Filled', color: '#F59E0B', count: ordersData.fulfillment.docs_partially_filled, pct: ordersData.fulfillment.docs_partially_filled_pct, sub: 'Some lines short-shipped or zero' },
                        { label: 'Complete Zero',    color: '#EF4444', count: ordersData.fulfillment.docs_complete_zero,    pct: ordersData.fulfillment.docs_complete_zero_pct,    sub: 'All lines: Conf = 0' },
                      ].map(({ label, color, count, pct, sub }) => (
                        <div key={label} className="flex items-start gap-3 bg-slate-50 rounded-lg px-3 py-2.5 mb-1.5">
                          <span className="w-2.5 h-2.5 rounded-sm mt-0.5 flex-shrink-0" style={{ background: color }}/>
                          <div className="flex-1">
                            <div className="flex justify-between items-baseline">
                              <span className="text-xs font-semibold text-slate-700">{label}</span>
                              <span className="text-sm font-bold" style={{ color }}>{Number(pct ?? 0).toFixed(2)}%</span>
                            </div>
                            <div className="text-xs text-slate-400 mt-0.5">{sub}</div>
                            <div className="mt-1 text-xs text-slate-500">
                              {count.toLocaleString()} <span className="text-slate-400">documents</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* ══ Return Orders Analysis ════════════════════════════════════ */}
              {ordersSection === "overview" && ordersData.total_returns > 0 && (
                <div className="pt-3 border-t border-slate-200 space-y-4">
                  <div>
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Return Orders Analysis</p>
                    <p className="text-xs text-slate-400 mt-0.5">H (Return Orders) + Cancelled C-orders · excluded from order value &amp; fill-rate calculations</p>
                  </div>

                  {/* Return KPI row */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <KpiCard label="Total Returns"      value={ordersData.total_returns.toLocaleString()}                    sub="Return order lines"       color="red"/>
                    <KpiCard label="Return Value (LKR)" value={`LKR ${fmt(ordersData.total_return_value_lkr)}`}             sub="Net value of return orders" color="amber"/>
                    <KpiCard label="Return Rate %"      value={`${ordersData.return_rate_value_pct.toFixed(1)}%`}           sub="Return ÷ Order value"     color="purple"/>
                  </div>

                  {/* Detailed breakdown — MC + ALL category only */}
                  {ordersDt === "MC" && ordersMcCat === "ALL" && (
                    <>
                      {/* Return reasons list */}
                      {ordersData.return_order_reasons.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold text-slate-700 mb-1">Return &amp; Cancellation Reasons</h3>
                          <p className="text-xs text-slate-400 mb-3">Top reasons across H returns + cancelled C-orders</p>
                          <div className="space-y-1.5">
                            {ordersData.return_order_reasons.slice(0, 8).map((r, i) => (
                              <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
                                <span className="flex items-center gap-2 text-xs text-slate-700 truncate max-w-[60%]" title={r.reason}>
                                  <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ background: CAT_COLORS[i % CAT_COLORS.length] }}/>
                                  {r.reason || "Unspecified"}
                                </span>
                                <span className="flex items-center gap-2 text-xs flex-shrink-0">
                                  <span className="font-bold text-red-600">{r.rejected_lines.toLocaleString()}</span>
                                  <span className="text-slate-400 w-10 text-right">{r.share_pct.toFixed(1)}%</span>
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* ══ Dealers view ══════════════════════════════════════════════ */}
              {activeOrdersPanels.has("dealers") && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {ordersData.top_dealers.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-2">Top Dealers by Order Value</h3>
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={ordersData.top_dealers} layout="vertical" margin={{ top:0, right:40, left:5, bottom:0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                            <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                            <YAxis type="category" dataKey="dealer" tick={{ fontSize: 9 }} width={140}/>
                            <Tooltip formatter={(v: unknown) => `LKR ${fmt(Number(v))}`}/>
                            <Bar dataKey="total_value_lkr" fill="#4361EE" name="Order Value (LKR)" radius={[0,3,3,0]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                    {ordersData.dealer_health_summary.total_dealers > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">Dealer Intelligence</h3>
                        <p className="text-xs text-slate-400 mb-3">Value tiers: A = top 80%, B = next 15%, C = bottom 5%</p>
                        <div className="grid grid-cols-2 gap-2">
                          {([
                            { label:"A-Tier Dealers", value: ordersData.dealer_health_summary.a_tier,     sub:"top 80% of value",    color:"green"  },
                            { label:"B-Tier Dealers", value: ordersData.dealer_health_summary.b_tier,     sub:"next 15% of value",   color:"teal"   },
                            { label:"C-Tier Dealers", value: ordersData.dealer_health_summary.c_tier,     sub:"bottom 5% of value",  color:"amber"  },
                            { label:"Dormant (90d)",  value: ordersData.dealer_health_summary.dormant_count, sub:"no orders last 90d", color:"red"  },
                          ] as const).map(({label,value,sub,color}) => (
                            <KpiCard key={label} label={label} value={value.toLocaleString()} sub={sub} color={color}/>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  {ordersData.dealer_perf.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">Dealer Performance <span className="text-xs font-normal text-slate-400 ml-1">(top 30 by order value · A=top 80% · B=next 15% · C=bottom 5%)</span></h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                                <th className="py-2 pr-3">Code</th>
                                <th className="py-2 pr-3">Dealer Name</th>
                                <th className="py-2 pr-2">Province</th>
                                <th className="py-2 pr-2">District</th>
                                <th className="py-2 pr-2">RM</th>
                                <th className="py-2 pr-2">ASE</th>
                                <th className="py-2 pr-2 text-right">PO Lines</th>
                                <th className="py-2 pr-2 text-right">Value (LKR)</th>
                                <th className="py-2 pr-2 text-right">Share %</th>
                                <th className="py-2 pr-2 text-right">Fill Rate</th>
                                <th className="py-2 pr-2 text-right">Return %</th>
                                <th className="py-2 text-center">Tier</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordersData.dealer_perf.map((r, i) => (
                                <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                                  <td className="py-1.5 pr-3 font-mono text-slate-500">{r.dealer_code}</td>
                                  <td className="py-1.5 pr-3 font-medium text-slate-700 max-w-[140px] truncate" title={r.dealer_name}>{r.dealer_name}</td>
                                  <td className="py-1.5 pr-2 text-slate-500">{r.province}</td>
                                  <td className="py-1.5 pr-2 text-slate-500">{r.district}</td>
                                  <td className="py-1.5 pr-2 text-slate-500 max-w-[80px] truncate" title={r.rm}>{r.rm}</td>
                                  <td className="py-1.5 pr-2 text-slate-500 max-w-[80px] truncate" title={r.ase}>{r.ase}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.po_lines.toLocaleString()}</td>
                                  <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.order_value_lkr)}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                                  <td className="py-1.5 pr-2 text-right">
                                    <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                      {r.fill_rate_pct.toFixed(1)}%
                                    </span>
                                  </td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.return_rate_pct.toFixed(1)}%</td>
                                  <td className="py-1.5 text-center">
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${r.dealer_tier==="A"?"bg-green-100 text-green-700":r.dealer_tier==="B"?"bg-blue-100 text-blue-700":"bg-amber-100 text-amber-700"}`}>{r.dealer_tier}</span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                </div>
              )}

              {/* ══ RM/ASE/Geography view ════════════════════════════════════ */}
              {(activeOrdersPanels.has("rm") || activeOrdersPanels.has("ase") || activeOrdersPanels.has("province") || activeOrdersPanels.has("district")) && (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {activeOrdersPanels.has("rm") && ordersData.rm_perf.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">RM Performance</h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                                <th className="py-2 pr-3">RM</th>
                                <th className="py-2 pr-2">Province</th>
                                <th className="py-2 pr-2 text-right">Dealers</th>
                                <th className="py-2 pr-2 text-right">Lines</th>
                                <th className="py-2 pr-2 text-right">Value</th>
                                <th className="py-2 pr-2 text-right">Fill</th>
                                <th className="py-2 pr-2 text-right">Return%</th>
                                <th className="py-2 text-right">Share</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordersData.rm_perf.map((r, i) => (
                                <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                                  <td className="py-1.5 pr-3 font-medium text-slate-700 max-w-[120px] truncate" title={r.rm}>{r.rm || "—"}</td>
                                  <td className="py-1.5 pr-2 text-slate-500">{r.province || "—"}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.unique_dealers}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.po_lines.toLocaleString()}</td>
                                  <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.order_value_lkr)}</td>
                                  <td className="py-1.5 pr-2 text-right">
                                    <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                      {r.fill_rate_pct.toFixed(1)}%
                                    </span>
                                  </td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.return_rate_pct.toFixed(1)}%</td>
                                  <td className="py-1.5 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {activeOrdersPanels.has("ase") && ordersData.ase_perf.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">ASE Performance</h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                                <th className="py-2 pr-3">ASE</th>
                                <th className="py-2 pr-2">RM</th>
                                <th className="py-2 pr-2 text-right">Dealers</th>
                                <th className="py-2 pr-2 text-right">Value</th>
                                <th className="py-2 text-right">Fill</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordersData.ase_perf.map((r, i) => (
                                <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                                  <td className="py-1.5 pr-3 font-medium text-slate-700 max-w-[120px] truncate" title={r.ase}>{r.ase || "—"}</td>
                                  <td className="py-1.5 pr-2 text-slate-500 max-w-[80px] truncate" title={r.rm}>{r.rm}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.unique_dealers}</td>
                                  <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.order_value_lkr)}</td>
                                  <td className="py-1.5 text-right">
                                    <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                      {r.fill_rate_pct.toFixed(1)}%
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Geography — District + Province */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {activeOrdersPanels.has("district") && ordersData.district_perf.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">District-Wise Performance</h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                                <th className="py-2 pr-3">Province</th>
                                <th className="py-2 pr-3">District</th>
                                <th className="py-2 pr-2 text-right">Dealers</th>
                                <th className="py-2 pr-2 text-right">Value</th>
                                <th className="py-2 pr-2 text-right">Share</th>
                                <th className="py-2 pr-2 text-right">Fill</th>
                                <th className="py-2 text-right">Return%</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordersData.district_perf.map((r, i) => (
                                <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                                  <td className="py-1.5 pr-3 text-slate-500">{r.province}</td>
                                  <td className="py-1.5 pr-3 font-medium text-slate-700">{r.district}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.unique_dealers}</td>
                                  <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.order_value_lkr)}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                                  <td className="py-1.5 pr-2 text-right">
                                    <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                      {r.fill_rate_pct.toFixed(1)}%
                                    </span>
                                  </td>
                                  <td className="py-1.5 text-right text-slate-500">{r.return_rate_pct.toFixed(1)}%</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                    {activeOrdersPanels.has("province") && ordersData.province_analysis.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">Province-Wise Performance</h3>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                                <th className="py-2 pr-3">Province</th>
                                <th className="py-2 pr-2 text-right">Dealers</th>
                                <th className="py-2 pr-2 text-right">Lines</th>
                                <th className="py-2 pr-2 text-right">Value</th>
                                <th className="py-2 pr-2 text-right">Share</th>
                                <th className="py-2 pr-2 text-right">Fill</th>
                                <th className="py-2 text-right">Return %</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordersData.province_analysis.map((r, i) => (
                                <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/50">
                                  <td className="py-1.5 pr-3 font-medium text-slate-700">{r.province}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.unique_dealers}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.po_lines.toLocaleString()}</td>
                                  <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.order_value_lkr)}</td>
                                  <td className="py-1.5 pr-2 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                                  <td className="py-1.5 pr-2 text-right">
                                    <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                      {r.fill_rate_pct.toFixed(1)}%
                                    </span>
                                  </td>
                                  <td className="py-1.5 text-right text-slate-500">{r.return_rate_pct.toFixed(1)}%</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Province order-value chart — pairs with the Province table above */}
                  {activeOrdersPanels.has("province") && ordersData.province_perf.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700 mb-1">Province Performance</h3>
                      <p className="text-xs text-slate-400 mb-2">Order value · value share % · fill rate % · dealer count</p>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={ordersData.province_perf} layout="vertical" margin={{ top:0, right:16, left:10, bottom:0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                          <XAxis type="number" tick={{ fontSize:10 }} tickFormatter={fmt}/>
                          <YAxis type="category" dataKey="province" tick={{ fontSize:10 }} width={100}/>
                          <Tooltip
                            formatter={(_v:unknown, _n:unknown, p:any) => {
                              const r = ordersData.province_perf[p.index];
                              return [`LKR ${fmt(r?.order_value_lkr ?? 0)} · ${r?.value_share_pct?.toFixed(1) ?? 0}% share · fill ${r?.fill_rate_pct?.toFixed(1) ?? 0}% · ${r?.dealer_count ?? 0} dealers`,""];
                            }}
                            labelFormatter={s => String(s)}
                          />
                          <Bar dataKey="order_value_lkr" name="Order Value (LKR)" fill="#4361EE" radius={[0,3,3,0]}
                            label={{ content: (p:any) => {
                              const r = ordersData.province_perf[p.index];
                              if (!r) return null;
                              return <text x={p.x+p.width+6} y={p.y+p.height/2+4} fontSize={9} fill="#64748B">{r.value_share_pct.toFixed(0)}% · {r.fill_rate_pct.toFixed(0)}%fr</text>;
                            }}}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              )}

              {/* ══ Per-Segment Analysis Tables ════════════════════════════════ */}
              {activeOrdersPanels.has("parts") && ordersData.part_analysis.length > 0 && (<>

                <div className="pt-3 border-t border-slate-200">
                  <div>
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Segment Analysis</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {ordersDt === "MC" && ordersMcCat !== "ALL" ? `MC – ${ordersMcCat === "SpareParts" ? "Spare Parts" : ordersMcCat}` : ordersDt === "OBM" ? "OBM Spare Parts" : ordersDt === "ALL" ? "All Spare Parts (MC + OBM)" : "All MC Spare Parts"}
                    </p>
                  </div>
                </div>

                {/* Parts sub-segment */}
                {(
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Part-Wise Analysis <span className="text-xs font-normal text-slate-400 ml-1">(top 30 by order value)</span></h3>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                            <th className="py-2 pr-3">Material</th>
                            <th className="py-2 pr-3">Description</th>
                            <th className="py-2 pr-2 text-right">Lines</th>
                            <th className="py-2 pr-2 text-right">Order Qty</th>
                            <th className="py-2 pr-2 text-right">Value (LKR)</th>
                            <th className="py-2 pr-2 text-right">Share %</th>
                            <th className="py-2 pr-2 text-right">Fill Rate</th>
                            <th className="py-2 text-right">Short Qty</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ordersData.part_analysis.map((r, i) => (
                            <tr key={i} className="border-b border-slate-50 hover:bg-blue-50/20">
                              <td className="py-1.5 pr-3 font-mono text-slate-700">{r.material}</td>
                              <td className="py-1.5 pr-3 text-slate-600 max-w-[200px] truncate" title={r.description}>{r.description}</td>
                              <td className="py-1.5 pr-2 text-right text-slate-500">{r.order_lines.toLocaleString()}</td>
                              <td className="py-1.5 pr-2 text-right text-slate-500">{r.order_qty.toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                              <td className="py-1.5 pr-2 text-right font-semibold text-slate-700">{fmt(r.total_value_lkr)}</td>
                              <td className="py-1.5 pr-2 text-right text-slate-500">{r.value_share_pct.toFixed(1)}%</td>
                              <td className="py-1.5 pr-2 text-right">
                                <span className="px-1.5 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=98?"#DCFCE7":r.fill_rate_pct>=90?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=98?"#16A34A":r.fill_rate_pct>=90?"#CA8A04":"#DC2626" }}>
                                  {r.fill_rate_pct.toFixed(1)}%
                                </span>
                              </td>
                              <td className="py-1.5 text-right text-red-500 font-medium">{r.short_qty > 0 ? r.short_qty.toLocaleString(undefined,{maximumFractionDigits:0}) : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

              </>)}

              {/* ══ MC Monthly Order Value by Category ════════════════════════ */}
              {ordersSection === "overview" && ordersDt === "MC" && ordersMcCat === "ALL" && ordersData.mc_monthly_category.length > 0 && (
                <div>
                  <div className="pt-3 border-t border-slate-200 mb-3">
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">MC Monthly Order Value by Category</p>
                    <p className="text-xs text-slate-400 mt-0.5">All MC purchase orders · monthly LKR value split by sub-category</p>
                  </div>
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={ordersData.mc_monthly_category} margin={{ top: 5, right: 16, left: 0, bottom: 40 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                      <XAxis dataKey="period" tick={{ fontSize: 9 }} angle={-35} textAnchor="end" interval={0}
                        tickFormatter={p => monthLabel(String(p), true)}/>
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                      <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]} labelFormatter={p => String(p)}/>
                      <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }}/>
                      <Bar dataKey="lubricant_lkr"  name="Lubricant"   stackId="a" fill={SEG_PALETTE[0]} radius={[0,0,0,0]}/>
                      <Bar dataKey="battery_lkr"    name="Battery"     stackId="a" fill={SEG_PALETTE[1]} radius={[0,0,0,0]}/>
                      <Bar dataKey="tyre_lkr"       name="Tyre"        stackId="a" fill={SEG_PALETTE[2]} radius={[0,0,0,0]}/>
                      <Bar dataKey="spare_parts_lkr" name="Spare Parts" stackId="a" fill={SEG_PALETTE[3]} radius={[2,2,0,0]}/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* ══ Fraud Alerts ══════════════════════════════════════════════ */}
              {activeOrdersPanels.has("dealers") && ordersData.fraud_alerts.length > 0 && (
                <div className="border border-red-200 bg-red-50 rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-red-600 font-bold text-sm">⚠ Concentration Alert</span>
                    <span className="text-xs text-red-400">Single dealer &gt;40% of monthly returns (CLAUDE.md §15)</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-xs text-red-500 uppercase border-b border-red-200">
                          <th className="py-1.5 pr-4">Month</th>
                          <th className="py-1.5 pr-4">Dealer Code</th>
                          <th className="py-1.5 pr-4">Dealer Name</th>
                          <th className="py-1.5 text-right">Return Share</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ordersData.fraud_alerts.map((a, i) => (
                          <tr key={i} className="border-b border-red-100">
                            <td className="py-1.5 pr-4 text-slate-600">{a.month}</td>
                            <td className="py-1.5 pr-4 font-mono text-slate-500">{a.dealer_code}</td>
                            <td className="py-1.5 pr-4 text-slate-600">{a.dealer_name}</td>
                            <td className="py-1.5 text-right font-bold text-red-600">{a.return_share_pct.toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* ══ Business Insights ══════════════════════════════════════════ */}
              {ordersSection === "overview" && ordersDt === "MC" && ordersMcCat === "ALL" && ordersData.category_mix.length > 0 && (<>

                <div className="pt-3 border-t border-slate-200">
                  <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Business Insights</p>
                  <p className="text-xs text-slate-400 mt-0.5">Computed across all segments (MC sub-categories + OBM) · {ordersData.period_label ?? ordersData.data_year}{ordersData.prior_period ? ` · compared with ${ordersData.prior_period.label}` : ""}</p>
                </div>

                {/* Row 1: Category Mix + YoY Growth */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Category Value Mix */}
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Category Value Mix</h3>
                    <p className="text-xs text-slate-400 mb-2">LKR order value by segment · {ordersData.period_label ?? ordersData.data_year}</p>
                    <ResponsiveContainer width="100%" height={170}>
                      <BarChart data={ordersData.category_mix} layout="vertical" margin={{ top:0, right:16, left:10, bottom:0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                        <XAxis type="number" tick={{ fontSize:10 }} tickFormatter={fmt}/>
                        <YAxis type="category" dataKey="segment" tick={{ fontSize:9 }} width={115}/>
                        <Tooltip formatter={(v:unknown) => `LKR ${fmt(Number(v))}`} labelFormatter={s => String(s)}/>
                        <Bar dataKey="value_lkr" name="Value (LKR)" radius={[0,3,3,0]}>
                          {ordersData.category_mix.map((_,i) => <Cell key={i} fill={SEG_PALETTE[i % SEG_PALETTE.length]}/>)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    <div className="mt-2 space-y-1">
                      {ordersData.category_mix.map((r,i) => (
                        <div key={r.segment} className="flex items-center justify-between text-xs">
                          <span className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-sm inline-block flex-shrink-0" style={{ background: SEG_PALETTE[i % SEG_PALETTE.length] }}/>
                            <span className="text-slate-600">{r.segment}</span>
                          </span>
                          <span className="text-slate-400">{r.value_share_pct.toFixed(1)}% · fill {r.fill_rate_pct.toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* YoY Growth */}
                  {ordersData.yoy_growth.length > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700 mb-1">Year-on-Year Growth</h3>
                      <p className="text-xs text-slate-400 mb-2">{ordersData.yoy_growth[0]?.year_prev ?? "Prev"} vs {ordersData.yoy_growth[0]?.year_curr ?? "Curr"} order value by segment · same months ({ordersData.yoy_growth[0]?.period ?? "full year"}) both years</p>
                      <ResponsiveContainer width="100%" height={170}>
                        <BarChart data={ordersData.yoy_growth} margin={{ top:0, right:10, left:0, bottom:32 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                          <XAxis dataKey="segment" tick={{ fontSize:8 }} angle={-20} textAnchor="end" interval={0} tickFormatter={s => String(s).replace("MC – ","")}/>
                          <YAxis tick={{ fontSize:10 }} tickFormatter={fmt}/>
                          <Tooltip formatter={(v:unknown) => `LKR ${fmt(Number(v))}`} labelFormatter={s => String(s)}/>
                          <Legend wrapperStyle={{ fontSize:10, paddingTop:4 }}/>
                          <Bar dataKey="value_year_prev" name={String(ordersData.yoy_growth[0]?.year_prev ?? "Prev")} fill="#94A3B8" radius={[2,2,0,0]}/>
                          <Bar dataKey="value_year_curr" name={String(ordersData.yoy_growth[0]?.year_curr ?? "Curr")} fill="#4361EE" radius={[2,2,0,0]}/>
                        </BarChart>
                      </ResponsiveContainer>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {ordersData.yoy_growth.map(r => (
                          <span key={r.segment} className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.yoy_pct >= 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                            {String(r.segment).replace("MC – ","")} {r.yoy_pct >= 0 ? "+" : ""}{r.yoy_pct.toFixed(1)}%
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Row 2: Pareto (Province chart + Dealer Intelligence moved to their toggle panels) */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {ordersData.pareto_summary.total_skus > 0 && (
                    <div>
                      <h3 className="text-sm font-semibold text-slate-700 mb-1">Pareto &amp; Category Cross</h3>
                      <p className="text-xs text-slate-400 mb-2">80/20 rule · multi-category dealer behaviour</p>
                      <div className="space-y-2">
                        <div className="bg-purple-50 rounded-xl px-4 py-3">
                          <p className="text-xs text-purple-600 font-semibold uppercase tracking-wide">Part Pareto (80% of value)</p>
                          <p className="text-2xl font-bold text-purple-800 mt-0.5">
                            {ordersData.pareto_summary.sku_80pct_count.toLocaleString()}
                            <span className="text-sm font-normal text-purple-400 ml-1">of {ordersData.pareto_summary.total_skus.toLocaleString()} SKUs</span>
                          </p>
                          <p className="text-xs text-purple-400">{((ordersData.pareto_summary.sku_80pct_count/ordersData.pareto_summary.total_skus)*100).toFixed(1)}% of parts → 80% of order value</p>
                        </div>
                        <div className="bg-blue-50 rounded-xl px-4 py-3">
                          <p className="text-xs text-blue-600 font-semibold uppercase tracking-wide">Dealer Pareto (80% of value)</p>
                          <p className="text-2xl font-bold text-blue-800 mt-0.5">
                            {ordersData.pareto_summary.dealer_80pct_count.toLocaleString()}
                            <span className="text-sm font-normal text-blue-400 ml-1">of {ordersData.pareto_summary.total_dealers.toLocaleString()} dealers</span>
                          </p>
                          <p className="text-xs text-blue-400">{((ordersData.pareto_summary.dealer_80pct_count/ordersData.pareto_summary.total_dealers)*100).toFixed(1)}% of dealers → 80% of revenue</p>
                        </div>
                        {ordersData.category_cross.total_mc_dealers > 0 && (
                          <div className="bg-teal-50 rounded-xl px-4 py-3 flex items-center justify-between">
                            <div>
                              <p className="text-xs text-teal-600 font-semibold uppercase tracking-wide">Multi-Category MC Dealers</p>
                              <p className="text-xl font-bold text-teal-800 mt-0.5">
                                {ordersData.category_cross.multi_category}
                                <span className="text-sm font-normal text-teal-400 ml-1">of {ordersData.category_cross.total_mc_dealers}</span>
                              </p>
                              <p className="text-xs text-teal-400">order across 2+ sub-categories</p>
                            </div>
                            <div className="text-right">
                              <p className="text-2xl font-bold text-amber-600">{ordersData.category_cross.single_category}</p>
                              <p className="text-xs text-teal-400">single-category</p>
                              <p className="text-xs text-amber-500 mt-0.5">cross-sell targets</p>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Row 4: Fill Rate Bands */}
                {ordersData.fill_rate_bands.length > 0 && (
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Fill Rate Bands by Segment</h3>
                    <p className="text-xs text-slate-400 mb-2">Count of dealers in each fill-rate band (per-dealer aggregate fill rate)</p>
                    <ResponsiveContainer width="100%" height={170}>
                      <BarChart data={ordersData.fill_rate_bands} layout="vertical" margin={{ top:0, right:20, left:10, bottom:0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                        <XAxis type="number" tick={{ fontSize:10 }} allowDecimals={false}/>
                        <YAxis type="category" dataKey="segment" tick={{ fontSize:9 }} width={115}/>
                        <Tooltip formatter={(v:unknown) => `${Number(v)} dealers`} labelFormatter={s => String(s)}/>
                        <Legend wrapperStyle={{ fontSize:10 }}/>
                        <Bar dataKey="above_98"      name="≥98%"   fill="#22C55E" stackId="a"/>
                        <Bar dataKey="between_95_98" name="95–98%" fill="#FCD34D" stackId="a"/>
                        <Bar dataKey="between_90_95" name="90–95%" fill="#F97316" stackId="a"/>
                        <Bar dataKey="below_90"      name="<90%"   fill="#EF4444" stackId="a" radius={[0,3,3,0]}/>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Row 5: Top Short-Shipped */}
                {ordersData.top_short_shipped.length > 0 && (
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">Top Short-Shipped Materials</h3>
                    <p className="text-xs text-slate-400 mb-3">Largest unmet demand gaps — procurement priority list</p>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                            <th className="py-2 pr-3">Material</th>
                            <th className="py-2 pr-3">Description</th>
                            <th className="py-2 pr-3 text-right">Short Qty</th>
                            <th className="py-2 pr-3 text-right">Fill Rate</th>
                            <th className="py-2 text-right">Times</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ordersData.top_short_shipped.map((r,i) => (
                            <tr key={i} className="border-b border-slate-50 hover:bg-red-50/20">
                              <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material}</td>
                              <td className="py-2 pr-3 text-xs text-slate-600 max-w-[200px] truncate" title={r.description}>{r.description}</td>
                              <td className="py-2 pr-3 text-right font-bold text-red-600">{r.short_qty.toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                              <td className="py-2 pr-3 text-right">
                                <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: r.fill_rate_pct>=95?"#DCFCE7":r.fill_rate_pct>=80?"#FEF9C3":"#FEE2E2", color: r.fill_rate_pct>=95?"#16A34A":r.fill_rate_pct>=80?"#CA8A04":"#DC2626" }}>
                                  {r.fill_rate_pct.toFixed(1)}%
                                </span>
                              </td>
                              <td className="py-2 text-right text-xs text-slate-400">{r.occurrences}×</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

              </>)}

            </div>
          ) : <p className="text-slate-400 text-sm py-8 text-center">Loading…</p>
          }
          </div>
        )}

        {/* ── Sales EDA ── */}
        {tab === "sales" && (
          <div className="space-y-5">
            {/* Section tabs, panel toggles + Spare Parts category filters */}
            <div className="space-y-2">
              <SectionTabs value={salesSection} onChange={setSalesSection}/>
              {salesSection === "performance" && (
                <>
                  <PanelToggles selected={salesPanels} onToggle={k => togglePanel(salesPanels, setSalesPanels, k)}/>
                  {salesPanels.has("parts") && (
                    <div className="flex gap-2 flex-wrap items-center">
                      <select
                        value={salesDt}
                        onChange={e => { setSalesDt(e.target.value as DealerType); setSalesMcCat("ALL"); }}
                        className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                      >
                        <option value="ALL">All</option>
                        <option value="MC">MC</option>
                        <option value="OBM">OBM</option>
                      </select>

                      <select
                        value={salesMcCat}
                        onChange={e => setSalesMcCat(e.target.value)}
                        disabled={salesDt === "OBM"}
                        className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs font-medium text-purple-700 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer disabled:text-slate-400 disabled:bg-slate-50 disabled:cursor-default"
                      >
                        {salesDt === "OBM" ? (
                          <option value="ALL">OBM Spare Parts</option>
                        ) : (
                          <>
                            <option value="ALL">{salesDt === "MC" ? "All MC" : "All"}</option>
                            <option value="Lubricant">Lubricant</option>
                            <option value="Battery">Battery</option>
                            <option value="Tyre">Tyre</option>
                            <option value="Spare Parts">Spare Parts</option>
                          </>
                        )}
                      </select>
                    </div>
                  )}
                </>
              )}
            </div>

            {salesData ? (
              <>
                {/* Year indicator */}
                {salesData.data_year > 0 && (
                  <div className="flex items-center justify-end border-b border-slate-100 pb-2">
                    <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-2.5 py-1 rounded-full">
                      {salesData.data_year}
                    </span>
                  </div>
                )}

                {/* ── Overview ── */}
                {salesSection === "overview" && (
                  <div className="space-y-5">
                    {/* KPI cards — row 1 */}
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                      <KpiCard label="Billed Revenue"   value={`LKR ${fmt(salesData.total_sale_value_lkr)}`}   sub="Gross billed sales (sales.xlsx)"                            color="purple"/>
                      <KpiCard label="Order Fulfillment" value={`${salesData.fulfillment_pct.toFixed(1)}%`}    sub="Confirmed fulfilled ÷ Order Received"                        color="green"/>
                      <KpiCard label="Return Rate"      value={`${salesData.return_rate_pct.toFixed(1)}%`}      sub="Returns ÷ Billed Revenue"                                   color="amber"/>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <KpiCard label="Net Revenue"      value={`LKR ${fmt(salesData.net_sale_value_lkr)}`}     sub="Billed revenue minus returns (sales.xlsx)"                   color="teal"/>
                      <KpiCard label="Return Value"     value={`LKR ${fmt(salesData.total_return_value_lkr)}`} sub={`${salesData.total_return_lines.toLocaleString()} lines`}    color="red"/>
                      <KpiCard label="Sale Qty"         value={salesData.total_sale_qty.toLocaleString('en-US',{maximumFractionDigits:0})}   sub="units sold"        color="blue"/>
                      <KpiCard label="Unique SKUs"      value={salesData.unique_parts.toLocaleString()}                                       sub="materials sold"     color="teal"/>
                    </div>

                    {/* Monthly trend */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <div className="flex items-center justify-between mb-3">
                          <div>
                            <h3 className="text-sm font-semibold text-slate-700">Monthly: Sales vs Returns (LKR)</h3>
                            <p className="text-xs text-slate-400 mt-0.5">Sale Value · Return Value</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <YearPicker years={salesData.available_years} value={salesYear} onChange={y => setSalesYear(typeof y === "number" ? y : salesData.data_year)}/>
                            <TimePicker value={salesRange} onChange={setSalesRange}/>
                          </div>
                        </div>
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={filterByRange(salesData.monthly_trend, salesRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                            <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                              tickFormatter={p => monthLabel(p, true)}/>
                            <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                            <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]} labelFormatter={p => String(p)}/>
                            <Legend wrapperStyle={{ fontSize: 10 }}/>
                            <Bar dataKey="sale_value_lkr"     fill="#7C3AED" name="Billed Revenue" radius={[2,2,0,0]}/>
                            <Bar dataKey="return_value_lkr"   fill="#EF4444" name="Return Value"    radius={[2,2,0,0]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>

                      {/* MC Category Mix (MC only) */}
                      {salesDt === "MC" && salesMcCat === "ALL" && salesData.mc_category_mix.length > 0 && (
                        <div>
                          <h3 className="text-sm font-semibold text-slate-700 mb-2">MC Sub-category Mix</h3>
                          <p className="text-xs text-slate-400 mb-3">Sale value share · Lubricant / Battery / Tyre / Spare Parts</p>
                          <ResponsiveContainer width="100%" height={220}>
                            <BarChart data={salesData.mc_category_mix} layout="vertical" margin={{ top:0, right:50, left:5, bottom:0 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                              <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                              <YAxis type="category" dataKey="mc_category" tick={{ fontSize: 10 }} width={80}/>
                              <Tooltip formatter={(v: unknown) => `LKR ${fmt(Number(v))}`}/>
                              <Bar dataKey="sale_value_lkr" radius={[0,3,3,0]}>
                                {salesData.mc_category_mix.map((c, i) => (
                                  <Cell key={c.mc_category} fill={CAT_COLORS[i % CAT_COLORS.length]}/>
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                          {/* share + return rate table */}
                          <div className="mt-2 space-y-1">
                            {salesData.mc_category_mix.map((c, i) => (
                              <div key={c.mc_category} className="flex items-center justify-between bg-slate-50 rounded px-3 py-1.5">
                                <span className="flex items-center gap-2 text-xs text-slate-700">
                                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: CAT_COLORS[i % CAT_COLORS.length] }}/>
                                  {c.mc_category}
                                </span>
                                <span className="flex gap-3 text-xs">
                                  <span className="font-bold text-slate-700">LKR {fmt(c.sale_value_lkr)}</span>
                                  <span className="text-slate-400 w-10 text-right">{c.value_share_pct.toFixed(1)}%</span>
                                  <span className="text-red-500 w-16 text-right">ret {c.return_rate_pct.toFixed(1)}%</span>
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* MC monthly by category (stacked bar) */}
                    {salesDt === "MC" && salesMcCat === "ALL" && salesData.mc_monthly_category.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">MC Monthly Sales by Sub-category</h3>
                        <p className="text-xs text-slate-400 mb-3">Stacked by Lubricant · Battery · Tyre · Spare Parts</p>
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={filterByRange(salesData.mc_monthly_category, salesRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                            <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                              tickFormatter={p => monthLabel(p, true)}/>
                            <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                            <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]}/>
                            <Legend wrapperStyle={{ fontSize: 10 }}/>
                            <Bar dataKey="lubricant_lkr"   fill={CAT_COLORS[0]} name="Lubricant"    stackId="mc" radius={[0,0,0,0]}/>
                            <Bar dataKey="battery_lkr"     fill={CAT_COLORS[1]} name="Battery"      stackId="mc"/>
                            <Bar dataKey="tyre_lkr"        fill={CAT_COLORS[2]} name="Tyre"         stackId="mc"/>
                            <Bar dataKey="spare_parts_lkr" fill={CAT_COLORS[3]} name="Spare Parts"  stackId="mc" radius={[2,2,0,0]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}

                  </div>
                )}

                {/* ── Parts analysis ── */}
                {activeSalesPanels.has("parts") && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Part-wise Sales Analysis</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.unique_parts.toLocaleString()} total SKUs · top 300 by sale value</p>
                      </div>
                      <input
                        type="search" placeholder="Filter by part…" value={salesPartSearch}
                        onChange={e => setSalesPartSearch(e.target.value)}
                        className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 w-48 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                      />
                    </div>
                    {(() => {
                      const totalSale = salesData.part_analysis.reduce((s, p) => s + p.sale_value_lkr, 0) || 1;
                      const rows = salesData.part_analysis
                        .filter(p => !salesPartSearch || p.material.toLowerCase().includes(salesPartSearch.toLowerCase()));
                      return (
                        <div className="overflow-auto max-h-[560px] rounded-lg border border-slate-100">
                          <table className="w-full text-xs border-collapse">
                            <thead className="sticky top-0 z-10">
                              <tr className="bg-slate-50 border-b border-slate-200">
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium">Material</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Lines</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Qty</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret Qty</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Net Qty</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Net Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                              </tr>
                            </thead>
                            <tbody>
                              {rows.map((p, i) => (
                                <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                  <td className="py-2 px-3">
                                    <span className={`font-mono ${i < 3 ? "text-amber-500 font-bold" : i < 10 ? "text-slate-500 font-medium" : "text-slate-300"}`}>{i+1}</span>
                                  </td>
                                  <td className="py-2 px-3 max-w-[240px]">
                                    <span className="font-mono text-slate-700 truncate block" title={p.material}>{p.material}</span>
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums text-slate-500">{p.sale_lines.toLocaleString()}</td>
                                  <td className="py-2 px-3 text-right tabular-nums text-slate-600">{p.sale_qty.toLocaleString('en-US',{maximumFractionDigits:0})}</td>
                                  <td className="py-2 px-3 text-right">
                                    <div className="font-semibold text-slate-800 tabular-nums">{fmt(p.sale_value_lkr)}</div>
                                    <ValueBar pct={p.sale_value_lkr / totalSale * 100}/>
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums">
                                    {p.return_qty > 0 ? <span className="text-rose-500">{p.return_qty.toLocaleString('en-US',{maximumFractionDigits:0})}</span> : <span className="text-slate-200">—</span>}
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums">
                                    {p.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(p.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums text-slate-600">{p.net_qty.toLocaleString('en-US',{maximumFractionDigits:0})}</td>
                                  <td className="py-2 px-3 text-right">
                                    <span className="font-semibold text-emerald-700 tabular-nums">{fmt(p.net_value_lkr)}</span>
                                  </td>
                                  <td className="py-2 px-3 text-right"><RetBadge pct={p.return_rate_pct}/></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      );
                    })()}
                  </div>
                )}

                {/* ── Dealer performance ── */}
                {activeSalesPanels.has("dealers") && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700">Dealer Performance</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.unique_dealers} dealers · sorted by sale value</p>
                      </div>
                      <input
                        type="search" placeholder="Filter by dealer or province…" value={salesDealerSearch}
                        onChange={e => setSalesDealerSearch(e.target.value)}
                        className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 w-52 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
                      />
                    </div>
                    {(() => {
                      const totalSale = salesData.dealer_perf.reduce((s, d) => s + d.sale_value_lkr, 0) || 1;
                      const rows = salesData.dealer_perf
                        .filter(d => !salesDealerSearch ||
                          d.dealer_name.toLowerCase().includes(salesDealerSearch.toLowerCase()) ||
                          (d.province || "").toLowerCase().includes(salesDealerSearch.toLowerCase()));
                      return (
                        <div className="overflow-auto max-h-[560px] rounded-lg border border-slate-100">
                          <table className="w-full text-xs border-collapse">
                            <thead className="sticky top-0 z-10">
                              <tr className="bg-slate-50 border-b border-slate-200">
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium">Dealer</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Order Rec. (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Fulfill</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Return (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">SKUs</th>
                              </tr>
                            </thead>
                            <tbody>
                              {rows.map((d, i) => (
                                <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                  <td className="py-2 px-3">
                                    <span className={`font-mono ${i < 3 ? "text-amber-500 font-bold" : i < 10 ? "text-slate-500 font-medium" : "text-slate-300"}`}>{i+1}</span>
                                  </td>
                                  <td className="py-2 px-3 max-w-[220px]">
                                    <div className="font-medium text-slate-700 truncate" title={d.dealer_name}>{d.dealer_name}</div>
                                    <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                                      {d.province && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium">{d.province}</span>}
                                      {d.ase && <span className="text-[10px] text-slate-400 truncate max-w-[100px]" title={d.ase}>{d.ase}</span>}
                                    </div>
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums text-slate-400">{fmt(d.order_received_lkr)}</td>
                                  <td className="py-2 px-3 text-right">
                                    <div className="font-semibold text-slate-800 tabular-nums">{fmt(d.sale_value_lkr)}</div>
                                    <ValueBar pct={d.sale_value_lkr / totalSale * 100}/>
                                  </td>
                                  <td className="py-2 px-3 text-right"><FulfillBadge pct={d.fulfillment_pct}/></td>
                                  <td className="py-2 px-3 text-right"><RetBadge pct={d.return_rate_pct}/></td>
                                  <td className="py-2 px-3 text-right tabular-nums">
                                    {d.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(d.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                  </td>
                                  <td className="py-2 px-3 text-right tabular-nums text-slate-500">{d.unique_skus.toLocaleString()}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      );
                    })()}
                  </div>
                )}

                {/* ── Hierarchy (Province / RM / ASE / District) ── */}
                {(activeSalesPanels.has("province") || activeSalesPanels.has("rm") || activeSalesPanels.has("ase") || activeSalesPanels.has("district")) && (
                  <div className="space-y-5">
                    {/* Province */}
                    {activeSalesPanels.has("province") && (
                    <div className="rounded-lg border border-slate-100 overflow-hidden">
                      <div className="bg-slate-50 border-b border-slate-200 px-3 py-2.5">
                        <h3 className="text-sm font-semibold text-slate-700">Province Performance</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.province_perf.length} provinces · sorted by sale value</p>
                      </div>
                      {(() => {
                        const totalSale = salesData.province_perf.reduce((s, p) => s + p.sale_value_lkr, 0) || 1;
                        const sorted = [...salesData.province_perf].sort((a, b) => b.sale_value_lkr - a.sale_value_lkr);
                        return (
                          <table className="w-full text-xs border-collapse">
                            <thead>
                              <tr className="border-b border-slate-100">
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium">Province</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Dealers</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Return (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">SKUs</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sorted.map((p, i) => (
                                <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                  <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{i+1}</td>
                                  <td className="py-2.5 px-3 font-semibold text-slate-700">{p.province || "—"}</td>
                                  <td className="py-2.5 px-3 text-right tabular-nums text-slate-500">{p.dealer_count}</td>
                                  <td className="py-2.5 px-3 text-right">
                                    <div className="font-semibold text-slate-800 tabular-nums">{fmt(p.sale_value_lkr)}</div>
                                    <ValueBar pct={p.sale_value_lkr / totalSale * 100}/>
                                  </td>
                                  <td className="py-2.5 px-3 text-right tabular-nums">
                                    {p.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(p.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                  </td>
                                  <td className="py-2.5 px-3 text-right"><RetBadge pct={p.return_rate_pct}/></td>
                                  <td className="py-2.5 px-3 text-right tabular-nums text-slate-500">{p.unique_skus?.toLocaleString()}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        );
                      })()}
                    </div>
                    )}

                    {/* RM */}
                    {activeSalesPanels.has("rm") && (
                    <div className="rounded-lg border border-slate-100 overflow-hidden">
                      <div className="bg-slate-50 border-b border-slate-200 px-3 py-2.5">
                        <h3 className="text-sm font-semibold text-slate-700">Regional Manager (RM) Performance</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.rm_perf.length} RMs · sorted by sale value</p>
                      </div>
                      {(() => {
                        const totalSale = salesData.rm_perf.reduce((s, r) => s + r.sale_value_lkr, 0) || 1;
                        const sorted = [...salesData.rm_perf].sort((a, b) => b.sale_value_lkr - a.sale_value_lkr);
                        return (
                          <table className="w-full text-xs border-collapse">
                            <thead>
                              <tr className="border-b border-slate-100">
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                <th className="text-left py-2.5 px-3 text-slate-500 font-medium">RM</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Dealers</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Return (LKR)</th>
                                <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sorted.map((r, i) => (
                                <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                  <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{i+1}</td>
                                  <td className="py-2.5 px-3 font-medium text-slate-700">{r.rm || "—"}</td>
                                  <td className="py-2.5 px-3 text-right tabular-nums text-slate-500">{r.dealer_count}</td>
                                  <td className="py-2.5 px-3 text-right">
                                    <div className="font-semibold text-slate-800 tabular-nums">{fmt(r.sale_value_lkr)}</div>
                                    <ValueBar pct={r.sale_value_lkr / totalSale * 100}/>
                                  </td>
                                  <td className="py-2.5 px-3 text-right tabular-nums">
                                    {r.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(r.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                  </td>
                                  <td className="py-2.5 px-3 text-right"><RetBadge pct={r.return_rate_pct}/></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        );
                      })()}
                    </div>
                    )}

                    {/* ASE */}
                    {activeSalesPanels.has("ase") && (
                    <div className="rounded-lg border border-slate-100 overflow-hidden">
                      <div className="bg-slate-50 border-b border-slate-200 px-3 py-2.5">
                        <h3 className="text-sm font-semibold text-slate-700">Area Sales Executive (ASE) Performance</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.ase_perf.length} ASEs · sorted by sale value</p>
                      </div>
                      {(() => {
                        const totalSale = salesData.ase_perf.reduce((s, a) => s + a.sale_value_lkr, 0) || 1;
                        const sorted = [...salesData.ase_perf].sort((a, b) => b.sale_value_lkr - a.sale_value_lkr);
                        return (
                          <div className="overflow-auto max-h-[320px]">
                            <table className="w-full text-xs border-collapse">
                              <thead className="sticky top-0 bg-white z-10">
                                <tr className="border-b border-slate-100">
                                  <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                  <th className="text-left py-2.5 px-3 text-slate-500 font-medium">ASE</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Dealers</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Return (LKR)</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                                </tr>
                              </thead>
                              <tbody>
                                {sorted.map((a, i) => (
                                  <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                    <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{i+1}</td>
                                    <td className="py-2.5 px-3">
                                      <div className="font-medium text-slate-700">{a.ase || "—"}</div>
                                      {a.rm && <div className="text-[10px] text-slate-400 mt-0.5">{a.rm}</div>}
                                    </td>
                                    <td className="py-2.5 px-3 text-right tabular-nums text-slate-500">{a.dealer_count}</td>
                                    <td className="py-2.5 px-3 text-right">
                                      <div className="font-semibold text-slate-800 tabular-nums">{fmt(a.sale_value_lkr)}</div>
                                      <ValueBar pct={a.sale_value_lkr / totalSale * 100}/>
                                    </td>
                                    <td className="py-2.5 px-3 text-right tabular-nums">
                                      {a.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(a.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                    </td>
                                    <td className="py-2.5 px-3 text-right"><RetBadge pct={a.return_rate_pct}/></td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        );
                      })()}
                    </div>
                    )}

                    {/* District sale-value chart — pairs with the District table below */}
                    {activeSalesPanels.has("district") && salesData.district_perf.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-slate-700 mb-1">District Sales Value (LKR)</h3>
                        <p className="text-xs text-slate-400 mb-3">Sale value by district · sorted descending</p>
                        <ResponsiveContainer width="100%" height={200}>
                          <BarChart
                            data={[...salesData.district_perf].sort((a, b) => b.sale_value_lkr - a.sale_value_lkr).slice(0, 25).map(d => ({
                              name: d.district || "—",
                              sale: d.sale_value_lkr,
                              order: d.order_received_lkr,
                            }))}
                            margin={{ top:5, right:10, left:0, bottom:40 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                            <XAxis dataKey="name" tick={{ fontSize: 9 }} angle={-40} textAnchor="end" interval={0}/>
                            <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                            <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]}/>
                            <Legend wrapperStyle={{ fontSize: 10 }}/>
                            <Bar dataKey="sale"  fill="#1D3461" name="Sale Value"      radius={[2,2,0,0]}/>
                            <Bar dataKey="order" fill="#94A3B8" name="Order Received"  radius={[2,2,0,0]}/>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}

                    {/* District */}
                    {activeSalesPanels.has("district") && (
                    <div className="rounded-lg border border-slate-100 overflow-hidden">
                      <div className="bg-slate-50 border-b border-slate-200 px-3 py-2.5">
                        <h3 className="text-sm font-semibold text-slate-700">District Performance</h3>
                        <p className="text-xs text-slate-400 mt-0.5">{salesData.district_perf.length} districts · sorted by sale value</p>
                      </div>
                      {(() => {
                        const totalSale = salesData.district_perf.reduce((s, d) => s + d.sale_value_lkr, 0) || 1;
                        const sorted = [...salesData.district_perf].sort((a, b) => b.sale_value_lkr - a.sale_value_lkr);
                        return (
                          <div className="overflow-auto max-h-[320px]">
                            <table className="w-full text-xs border-collapse">
                              <thead className="sticky top-0 bg-white z-10">
                                <tr className="border-b border-slate-100">
                                  <th className="text-left py-2.5 px-3 text-slate-500 font-medium w-8">#</th>
                                  <th className="text-left py-2.5 px-3 text-slate-500 font-medium">District</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Dealers</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Order Rec. (LKR)</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Sale Value (LKR)</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Return (LKR)</th>
                                  <th className="text-right py-2.5 px-3 text-slate-500 font-medium">Ret %</th>
                                </tr>
                              </thead>
                              <tbody>
                                {sorted.map((d, i) => (
                                  <tr key={i} className={`border-b border-slate-50 hover:bg-blue-50/30 transition-colors ${i % 2 === 1 ? "bg-slate-50/40" : ""}`}>
                                    <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{i+1}</td>
                                    <td className="py-2.5 px-3">
                                      <div className="font-medium text-slate-700">{d.district || "—"}</div>
                                      {d.province && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium mt-0.5 inline-block">{d.province}</span>}
                                    </td>
                                    <td className="py-2.5 px-3 text-right tabular-nums text-slate-500">{d.dealer_count}</td>
                                    <td className="py-2.5 px-3 text-right tabular-nums text-slate-400">{fmt(d.order_received_lkr ?? 0)}</td>
                                    <td className="py-2.5 px-3 text-right">
                                      <div className="font-semibold text-slate-800 tabular-nums">{fmt(d.sale_value_lkr)}</div>
                                      <ValueBar pct={d.sale_value_lkr / totalSale * 100}/>
                                    </td>
                                    <td className="py-2.5 px-3 text-right tabular-nums">
                                      {d.return_value_lkr > 0 ? <span className="text-rose-500">{fmt(d.return_value_lkr)}</span> : <span className="text-slate-200">—</span>}
                                    </td>
                                    <td className="py-2.5 px-3 text-right"><RetBadge pct={d.return_rate_pct}/></td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        );
                      })()}
                    </div>
                    )}
                  </div>
                )}
              </>
            ) : <p className="text-slate-400 text-sm py-6">Loading sales data…</p>}
          </div>
        )}

        {tab === "classification" && <SkuClassificationTab/>}
        {tab === "inventory"      && <InventoryStatusTab/>}

      </div>
    </div>
  );
}
