import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  fetchOrdersEda, fetchSalesEda,
  type OrdersEdaData, type SalesEdaData,
} from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { TimePicker, filterByRange, type TimeRange, YearPicker, filterByYear, getYears, monthLabel } from "../components/TimePicker";

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

type Tab = "orders" | "sales";

export function OBMEDA() {
  const [ordersData, setOrdersData] = useState<OrdersEdaData | null>(null);
  const [salesData,  setSalesData]  = useState<SalesEdaData  | null>(null);
  const [tab,         setTab]         = useState<Tab>("orders");
  const [ordersApiYear, setOrdersApiYear] = useState<number>(0); // 0 = latest (API resolves)
  const [ordersYear,  setOrdersYear]  = useState<number | "All">("All");
  const [ordersRange, setOrdersRange] = useState<TimeRange>("YTD");
  const [salesYear,   setSalesYear]   = useState<number>(0);
  const [salesRange,  setSalesRange]  = useState<TimeRange>("YTD");

  useEffect(() => {
    fetchOrdersEda("OBM", "ALL", ordersApiYear).then(d => {
      setOrdersData(d);
      if (ordersApiYear === 0 && d.data_year) setOrdersApiYear(d.data_year);
      const yrs = getYears(d.monthly_trend);
      if (yrs.length) setOrdersYear(yrs[0]);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ordersApiYear]);

  useEffect(() => {
    fetchSalesEda("OBM", "ALL", salesYear).then(d => {
      setSalesData(d);
      if (salesYear === 0 && d.data_year) setSalesYear(d.data_year);
      const yrs = getYears(d.monthly_trend);
      if (yrs.length) setSalesYear(d.data_year || (yrs[0] ?? 0));
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [salesYear]);

  const TABS = [
    { key: "orders" as Tab, label: "Orders Analysis (Steps 03-05)" },
    { key: "sales"  as Tab, label: "Sales Analysis (Step 04)"  },
  ];

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Outboard Motor (OBM) Parts EDA</h2>
        <p className="text-xs text-slate-500 mt-0.5">Steps 03-05 · OBM dealer orders &amp; sales performance · Separate from motorcycle spare parts</p>
      </div>

      {/* Global KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Purchase Orders"  value={ordersData ? fmt(ordersData.total_po)    : "…"} color="blue"/>
        <KpiCard label="Avg Fill Rate"    value={ordersData ? `${(ordersData.avg_fill_rate*100).toFixed(1)}%` : "…"} sub={`${ordersData?.fill_rate_lt1_count ?? 0} lines short-shipped`} color="green"/>
        <KpiCard label="OBM Net Revenue"  value={salesData  ? `LKR ${fmt(salesData.net_sale_value_lkr)}`  : "…"} sub="sales EDA · billed minus returns" color="purple"/>
        <KpiCard label="Avg Lead Time"    value={ordersData ? `${ordersData.avg_lead_time_days.toFixed(1)} days` : "…"} color="teal"/>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex gap-1 mb-5 border-b border-slate-100 pb-2">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-1.5 text-sm rounded-lg font-medium transition-colors ${tab === t.key ? "bg-brand-blue text-white" : "text-slate-500 hover:bg-slate-50"}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Orders EDA ── */}
        {tab === "orders" && (
          ordersData ? (
            <div className="space-y-5">
              {/* Year picker */}
              {ordersData.available_years.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">Year:</span>
                  <select
                    value={ordersApiYear}
                    onChange={e => setOrdersApiYear(Number(e.target.value))}
                    className="border border-slate-200 rounded-lg px-3 py-1 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                  >
                    {ordersData.available_years.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
              )}
              {/* Row 1 — value KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="Order Received"    value={`LKR ${fmt(ordersData.total_order_value_lkr)}`}              sub="All C-orders incl. cancelled/rejected"   color="blue"/>
                <KpiCard label="Total Sales"       value={`LKR ${fmt(ordersData.total_confirmed_value_lkr)}`}           sub="Confirmed delivery value (orders.xlsx)"  color="green"/>
                <KpiCard label="Order Fulfillment" value={`${ordersData.value_fill_rate_pct.toFixed(1)}%`}              sub="Confirmed value ÷ Order Received"        color="teal"/>
                <KpiCard label="Rejection Rate"    value={`${ordersData.rejection_rate_pct.toFixed(1)}%`}               sub="PO lines fully undelivered"              color="amber"/>
              </div>
              {/* Row 2 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="Qty Fill Rate"     value={`${(ordersData.avg_fill_rate * 100).toFixed(1)}%`}            sub={`${ordersData.fill_rate_lt1_count} lines short-shipped`} color="purple"/>
                <KpiCard label="Total POs"         value={ordersData.total_po_documents.toLocaleString()}               sub="Unique purchase order documents"         color="blue"/>
                <KpiCard label="Avg Dispatch LT"   value={`${ordersData.avg_lead_time_days.toFixed(1)} days`}           sub="Warehouse → dealer"                      color="teal"/>
                <KpiCard label="Return Value"      value={`LKR ${fmt(ordersData.total_return_value_lkr)}`}              sub="H-type return order value"               color="red"/>
              </div>
              {/* Row 3 */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <KpiCard label="Unfulfill Value"   value={`LKR ${fmt(ordersData.unfulfill_value_lkr)}`}                sub="Ordered but not confirmed"               color="amber"/>
                <KpiCard label="Sales Qty"         value={ordersData.sales_qty.toLocaleString('en-US', {maximumFractionDigits: 0})} sub="Confirmed units"            color="green"/>
                <KpiCard label="Unique SKU"        value={ordersData.unique_skus.toLocaleString()}                     sub="Materials ordered"                       color="teal"/>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-700">Monthly OBM Order Volume</h3>
                    <div className="flex items-center gap-2">
                      <YearPicker years={getYears(ordersData.monthly_trend)} value={ordersYear} onChange={setOrdersYear}/>
                      <TimePicker value={ordersRange} onChange={setOrdersRange}/>
                    </div>
                  </div>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={filterByRange(filterByYear(ordersData.monthly_trend, ordersYear), ordersRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                      <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                        tickFormatter={p => monthLabel(p, ordersYear !== "All")}/>
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={fmt}/>
                      <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()} labelFormatter={p => String(p)}/>
                      <Legend/>
                      <Bar dataKey="po_count"     fill="#4361EE" name="Purchase Orders" radius={[2,2,0,0]} stackId="a"/>
                      <Bar dataKey="return_count" fill="#EF4444" name="Returns"         radius={[2,2,0,0]} stackId="a"/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-2">Top OBM Dealers by Order Count</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={ordersData.top_dealers} layout="vertical" margin={{ top:0, right:40, left:5, bottom:0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
                      <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                      <YAxis type="category" dataKey="dealer" tick={{ fontSize: 9 }} width={160}/>
                      <Tooltip formatter={(v: unknown) => Number(v).toLocaleString()}/>
                      <Bar dataKey="order_count" fill="#06B6D4" name="Orders" radius={[0,3,3,0]}/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Rejection log */}
              {ordersData.rejections.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-2">Rejection Log — Fully Short-Shipped Lines</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                          <th className="py-2 pr-3">Material</th>
                          <th className="py-2 pr-3">Description</th>
                          <th className="py-2 pr-3">Customer</th>
                          <th className="py-2 pr-3">Date</th>
                          <th className="py-2 pr-3 text-right">Ordered</th>
                          <th className="py-2 pr-3 text-right">Lost</th>
                          <th className="py-2 text-right">Fill Rate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ordersData.rejections.map((r, i) => (
                          <tr key={i} className="border-b border-slate-50 hover:bg-red-50/20">
                            <td className="py-2 pr-3 font-mono text-xs text-slate-700">{r.material}</td>
                            <td className="py-2 pr-3 text-slate-600 max-w-[160px] truncate" title={r.description}>{r.description}</td>
                            <td className="py-2 pr-3 text-xs text-slate-500 max-w-[130px] truncate" title={r.customer}>{r.customer}</td>
                            <td className="py-2 pr-3 text-xs text-slate-400">{r.document_date}</td>
                            <td className="py-2 pr-3 text-right">{r.order_qty.toFixed(0)}</td>
                            <td className="py-2 pr-3 text-right text-red-600 font-semibold">{r.lost_qty.toFixed(0)}</td>
                            <td className="py-2 text-right">
                              <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                                style={{ background: r.fill_rate >= 0.99 ? "#DCFCE7" : r.fill_rate >= 0.8 ? "#FEF9C3" : "#FEE2E2", color: r.fill_rate >= 0.99 ? "#16A34A" : r.fill_rate >= 0.8 ? "#CA8A04" : "#DC2626" }}>
                                {(r.fill_rate * 100).toFixed(0)}%
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
          ) : <p className="text-slate-400 text-sm">Loading…</p>
        )}

        {/* ── Sales EDA ── */}
        {tab === "sales" && (
          salesData ? (
            <div className="space-y-5">
              {salesData.available_years.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">Year:</span>
                  <select
                    value={salesYear}
                    onChange={e => setSalesYear(Number(e.target.value))}
                    className="border border-slate-200 rounded-lg px-3 py-1 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                  >
                    {salesData.available_years.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
              )}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="OBM Revenue"    value={`LKR ${fmt(salesData.total_sale_value_lkr)}`}   sub={`${salesData.total_sale_lines.toLocaleString()} lines`}  color="purple"/>
                <KpiCard label="Return Value"   value={`LKR ${fmt(salesData.total_return_value_lkr)}`} sub={`${salesData.total_return_lines} lines`}                  color="red"/>
                <KpiCard label="Return Rate"    value={`${salesData.return_rate_pct.toFixed(1)}%`}      sub="value basis"                                              color="amber"/>
                <KpiCard label="Net Revenue"    value={`LKR ${fmt(salesData.net_sale_value_lkr)}`}     sub={`${salesData.unique_dealers} dealers`}                    color="green"/>
              </div>

              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-slate-700">Monthly OBM Sales vs Returns (LKR)</h3>
                  <div className="flex items-center gap-2">
                    <select
                      value={salesYear}
                      onChange={e => setSalesYear(Number(e.target.value))}
                      className="border border-slate-200 rounded-lg px-3 py-1 text-xs font-medium text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/30 cursor-pointer"
                    >
                      {salesData.available_years.map(y => <option key={y} value={y}>{y}</option>)}
                    </select>
                    <TimePicker value={salesRange} onChange={setSalesRange}/>
                  </div>
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={filterByRange(filterByYear(salesData.monthly_trend, salesYear), salesRange)} margin={{ top:5, right:10, left:0, bottom:5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
                    <XAxis dataKey="period" tick={{ fontSize: 10 }} interval={0}
                      tickFormatter={p => monthLabel(p, true)}/>
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
                    <Tooltip formatter={(v: unknown, n: unknown) => [`LKR ${fmt(Number(v))}`, String(n)]}/>
                    <Legend wrapperStyle={{ fontSize: 10 }}/>
                    <Bar dataKey="sale_value_lkr"   fill="#06B6D4" name="Sale Value"   radius={[2,2,0,0]}/>
                    <Bar dataKey="return_value_lkr" fill="#EF4444" name="Return Value" radius={[2,2,0,0]}/>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {salesData.dealer_perf.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-700 mb-1">OBM Dealer Performance</h3>
                  <div className="overflow-auto max-h-[360px]">
                    <table className="w-full text-xs border-collapse">
                      <thead className="sticky top-0 bg-white"><tr className="border-b border-slate-200">
                        <th className="text-left py-2 px-2 text-slate-500">#</th>
                        <th className="text-left py-2 px-2 text-slate-500">Dealer</th>
                        <th className="text-left py-2 px-2 text-slate-500">Province</th>
                        <th className="text-right py-2 px-2 text-slate-500">Sale Value (LKR)</th>
                        <th className="text-right py-2 px-2 text-slate-500">Ret %</th>
                        <th className="text-right py-2 px-2 text-slate-500">SKUs</th>
                      </tr></thead>
                      <tbody>
                        {salesData.dealer_perf.map((d, i) => (
                          <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                            <td className="py-1.5 px-2 text-slate-400">{i+1}</td>
                            <td className="py-1.5 px-2 font-medium text-slate-700 max-w-[200px] truncate">{d.dealer_name}</td>
                            <td className="py-1.5 px-2 text-slate-500">{d.province || "—"}</td>
                            <td className="py-1.5 px-2 text-right font-medium text-slate-700">{fmt(d.sale_value_lkr)}</td>
                            <td className="py-1.5 px-2 text-right text-slate-500">{d.return_rate_pct.toFixed(1)}%</td>
                            <td className="py-1.5 px-2 text-right text-slate-500">{d.unique_skus}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : <p className="text-slate-400 text-sm">Loading…</p>
        )}
      </div>
    </div>
  );
}
