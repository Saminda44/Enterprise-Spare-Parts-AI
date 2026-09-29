import { useEffect, useState } from "react";
import { fetchSalesCheck, type SalesCheckData } from "../api/client";

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

/** Compare linked billed sales with the dealer orders used by the forecast. */
export function SalesCheckTab() {
  const [checkData,   setCheckData]   = useState<SalesCheckData | null>(null);
  const [checkFilter, setCheckFilter] = useState("");
  const [checkSearch, setCheckSearch] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchSalesCheck({ check: checkFilter || undefined, search: checkSearch || undefined, limit: 300 })
        .then(setCheckData).catch(() => setCheckData(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [checkFilter, checkSearch]);

  if (!checkData) return <div className="py-10 text-center text-slate-400">Loading…</div>;

  const order = ["consistent", "billed >1.5x confirmed", "billed well below confirmed", "ordered, no linked billing",
    "sold, never ordered", "service tool, sold not ordered", "no overlap in window"];
  const tone: Record<string, string> = {
    "consistent": "bg-green-100 text-green-700", "billed >1.5x confirmed": "bg-amber-100 text-amber-700",
    "billed well below confirmed": "bg-slate-100 text-slate-600", "ordered, no linked billing": "bg-slate-100 text-slate-500",
    "sold, never ordered": "bg-red-100 text-red-700", "service tool, sold not ordered": "bg-violet-100 text-violet-700",
    "no overlap in window": "bg-slate-50 text-slate-400",
  };
  const t = checkData.totals;
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl shadow-sm p-5 space-y-2">
        <h3 className="text-sm font-semibold text-slate-700">Order history vs linked billing</h3>
        <p className="text-xs text-slate-500">
          The forecast uses dealer <b>orders</b> (including lost sales) and the fleet (UIO) term. This comparison counts only
          billing lines linked to a part; invoices are not matched to individual orders, and the exports may cover different
          customers or months. Over {checkData.window?.start} to {checkData.window?.end}: ordered
          {" "}{fmt(t.ordered ?? 0)}, confirmed {fmt(t.confirmed ?? 0)}, billed {fmt(t.billed ?? 0)} units.
          {" "}A billed-to-confirmed ratio of 0.5–1.5× falls within the comparison band; it does not prove the transactions match.
        </p>
        <div className="flex flex-wrap gap-1.5 pt-1">
          <button onClick={() => setCheckFilter("")}
            className={`text-xs px-2.5 py-1 rounded-full border ${checkFilter === "" ? "bg-slate-700 text-white border-slate-700" : "border-slate-200 text-slate-600"}`}>
            All {Object.values(checkData.counts).reduce((s, v) => s + v, 0).toLocaleString()}
          </button>
          {order.filter(k => checkData.counts[k]).map(k => (
            <button key={k} onClick={() => setCheckFilter(k)}
              className={`text-xs px-2.5 py-1 rounded-full border ${checkFilter === k ? "bg-slate-700 text-white border-slate-700" : "border-slate-200 text-slate-600"}`}>
              {k} {checkData.counts[k].toLocaleString()}
            </button>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
        <input value={checkSearch} onChange={e => setCheckSearch(e.target.value)} placeholder="Search part or description…"
          className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs w-64 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"/>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500 uppercase">
                <th className="py-2 pr-3">Part</th><th className="py-2 pr-3">Description</th><th className="py-2 pr-3">Check</th>
                <th className="py-2 pr-3 text-right">Ordered</th><th className="py-2 pr-3 text-right">Confirmed</th>
                <th className="py-2 pr-3 text-right">Billed</th><th className="py-2 pr-3 text-right">Billed ÷ conf.</th>
                <th className="py-2 pr-3 text-right">Ordered / mo</th><th className="py-2 text-right">Forecast / mo</th>
              </tr>
            </thead>
            <tbody>
              {checkData.rows.map(r => (
                <tr key={r.part_no} className="border-b border-slate-50 hover:bg-slate-50/60">
                  <td className="py-1.5 pr-3 font-mono text-slate-700 whitespace-nowrap">{r.part_no}</td>
                  <td className="py-1.5 pr-3 text-slate-600 max-w-[220px] truncate" title={r.description}>{r.description}</td>
                  <td className="py-1.5 pr-3"><span className={`px-2 py-0.5 rounded-full whitespace-nowrap ${tone[r.check] ?? ""}`}>{r.check}</span></td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(r.ordered).toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(r.confirmed).toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(r.billed).toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{r.billed_to_confirmed != null ? r.billed_to_confirmed.toFixed(2) : "—"}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{r.ordered_per_month.toFixed(1)}</td>
                  <td className="py-1.5 text-right tabular-nums font-semibold text-brand-blue">{r.forecast_month != null ? r.forecast_month.toFixed(1) : "not forecast"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-slate-400">
          Sorted by the gap between billed and confirmed units. A high ratio may reflect export scope, timing or a
          description-based part match. Check the source records before changing a forecast.
        </p>
      </div>
    </div>
  );
}
