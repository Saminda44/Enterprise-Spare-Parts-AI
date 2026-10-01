import { Fragment, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { fetchOrderPlan, type OrderPlanData } from "../api/client";
import { KpiCard } from "../components/KpiCard";
import { useSegment, useCategory, SEGMENT_TEXT, CATEGORY_TEXT, withSegment } from "../api/segment";

function fmt(n: number) {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return Math.round(n).toLocaleString();
}
const qty = (n: number | null | undefined) =>
  n == null ? "—" : n >= 10 ? Math.round(n).toLocaleString() : n.toFixed(1);
const monthName = (ym: string) => {
  const [y, m] = ym.split("-").map(Number);
  return y && m ? new Date(y, m - 1, 1).toLocaleString("en-GB", { month: "short", year: "numeric" }) : ym;
};

const ABC_COLOR: Record<string, string> = { A: "#EF4444", B: "#FFC107", C: "#2CC56F" };
const MOVEMENT: Record<string, string> = { F: "Fast", S: "Slow", N: "Not moving" };
const POLICY_TEXT: Record<string, string> = {
  RS: "Top up monthly", RsS: "Reorder at a level", ON_DEMAND: "Order on demand", NO_STOCK: "Don't stock",
};

function Bars({ title, rows, total, colors }: {
  title: string; rows: { name: string; lines: number; value: number }[]; total: number; colors?: Record<string, string>;
}) {
  return (
    <div className="bg-white rounded-xl shadow-sm p-5">
      <h3 className="text-sm font-semibold text-slate-700 mb-3">{title}</h3>
      <div className="space-y-2">
        {rows.slice(0, 8).map(r => (
          <div key={r.name} className="flex items-center gap-2 text-xs">
            <span className="w-32 truncate text-slate-600" title={r.name}>{r.name}</span>
            <span className="flex-1 h-2.5 bg-slate-100 rounded-sm overflow-hidden">
              <span className="block h-full rounded-sm" style={{ width: `${total ? (r.value / total) * 100 : 0}%`, background: colors?.[r.name] ?? "#4361EE" }}/>
            </span>
            <span className="w-16 text-right tabular-nums text-slate-700">LKR {fmt(r.value)}</span>
            <span className="w-14 text-right tabular-nums text-slate-400">{r.lines.toLocaleString()} ln</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Orders() {
  const segment = useSegment();
  const category = useCategory();
  const [data,     setData]     = useState<OrderPlanData | null>(null);
  const [status,   setStatus]   = useState("to order");
  const [abc,      setAbc]      = useState("");
  const [system,   setSystem]   = useState("");
  const [search,   setSearch]   = useState("");
  const [page,     setPage]     = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const pageSize = 100;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      fetchOrderPlan({
        status: status || undefined, abc: abc || undefined, system: system || undefined,
        search: search || undefined, limit: pageSize, offset: page * pageSize,
      }).then(setData);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [status, abc, system, search, page]);
  useEffect(() => { setPage(0); setExpanded(null); }, [status, abc, system, search]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;

  const s = data.summary;
  const a = data.assumptions;
  const fill = (k: string) => `${Math.round((a.fill_targets[k] ?? 0) * 100)}%`;

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-800">
            {segment ? `${SEGMENT_TEXT[segment]} Spare Parts — ` : ""}Next Order — {monthName(data.cycle_month)}{category && <span className="text-brand-blue"> — {CATEGORY_TEXT[category]}</span>}
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Placed this month, arriving about <b>{monthName(data.expected_arrival)}</b> ({a.lead_time_months}-month import lead time).
            {segment === "obm" && " Yamaha outboard parts only (PN_Yamaha brand OB)."}
            {segment === "mc" && " Yamaha motorcycle parts only (PN_Yamaha brand YM, with Katana tyres)."}
          </p>
        </div>
        {data.buyer_ready && <a href={withSegment("/api/v1/policy/export.xlsx")} download
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-green-600 text-white hover:bg-green-700 font-medium">
          <Download size={13}/> Export order (Excel)
        </a>}
      </div>
      {!data.buyer_ready && <div role="alert" className="border border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <strong>Do not place this order.</strong> {data.hold_reason}
      </div>}

      {/* How the order is built */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {[
          ["1 · Forecast", "Each part's demand from its own order history, blended with the fleet (UIO) of the models it fits."],
          ["2 · Classification", `ABC sets the fill target (A ${fill("A")}, B ${fill("B")}, C ${fill("C")}); movement and demand pattern pick the stock policy.`],
          ["3 · Stock", "Current stock at the PDC plus stock already on order (Yamaha MC and OBM parts only)."],
          ["4 · Order", `Target level (${a.protection_interval_months}-month demand + safety stock) minus stock. Lines above 3× recent demand are held for a buyer.`],
        ].map(([t, d]) => (
          <div key={t} className="bg-white rounded-xl shadow-sm p-4">
            <p className="text-xs font-bold text-brand-blue">{t}</p>
            <p className="text-xs text-slate-500 mt-1">{d}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard label={data.buyer_ready ? "Lines to order" : "Candidate lines"} value={s.lines.toLocaleString()} sub={`${fmt(s.units)} units`} color="blue"/>
        <KpiCard label={data.buyer_ready ? "Order value" : "Candidate value"} value={`LKR ${fmt(s.value)}`} sub={data.buyer_ready ? "buyer review" : "on hold"} color="green"/>
        <KpiCard label="Held for review" value={`LKR ${fmt(s.held_value)}`} sub={`${s.held_lines.toLocaleString()} lines above 3× recent demand`} color="amber"/>
        <KpiCard label="Fleet-linked lines" value={s.fleet_linked_lines.toLocaleString()} sub={`${s.fleet_value_share_pct.toFixed(1)}% of order value from the fleet term`} color="purple"/>
        <KpiCard label="Stock on these lines" value={fmt(s.stock_on_hand + s.stock_on_order)} sub={`${fmt(s.stock_on_hand)} on hand + ${fmt(s.stock_on_order)} on order, for the parts being ordered`} color="teal"/>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Bars title="Order value by ABC class" rows={data.by_abc} total={s.value} colors={ABC_COLOR}/>
        <Bars title="Order value by system" rows={data.by_system} total={s.value}/>
        <Bars title="Order value by part type" rows={data.by_behaviour} total={s.value}/>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {[["to order", `To order ${s.lines.toLocaleString()}`], ["held for review", `Held for review ${s.held_lines.toLocaleString()}`], ["", "All proposed"]].map(([k, label]) => (
            <button key={k || "all"} onClick={() => setStatus(k)}
              className={`text-xs px-3 py-1.5 rounded-full border font-medium ${status === k ? "bg-slate-700 text-white border-slate-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
              {label}
            </button>
          ))}
          <select value={abc} onChange={e => setAbc(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs">
            <option value="">All ABC</option>
            {["A", "B", "C"].map(k => <option key={k} value={k}>{k} — fill {fill(k)}</option>)}
          </select>
          <select value={system} onChange={e => setSystem(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs">
            <option value="">All systems</option>
            {data.by_system.map(r => <option key={r.name} value={r.name}>{r.name}</option>)}
          </select>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search part or description…"
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px] focus:outline-none focus:ring-2 focus:ring-brand-blue/30"/>
        </div>
        <p className="text-xs text-slate-500">{data.total.toLocaleString()} lines · largest first · click a line to see how its quantity was worked out</p>
        <div className="max-h-[640px] overflow-auto border border-slate-100 rounded-lg">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 shadow-[0_1px_0_#E2E8F0]">
              <tr className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                <th className="py-2.5 pl-3 pr-2 w-6"></th>
                <th className="py-2.5 pr-3">Part</th>
                <th className="py-2.5 pr-3">Class</th>
                <th className="py-2.5 pr-3 text-right">Forecast<span className="block normal-case font-normal">per month</span></th>
                <th className="py-2.5 pr-3 text-right">Target level<span className="block normal-case font-normal">4-mo demand + safety</span></th>
                <th className="py-2.5 pr-3 text-right">Stock<span className="block normal-case font-normal">on hand + on order</span></th>
                <th className="py-2.5 pr-3 text-right text-slate-700">Order qty</th>
                <th className="py-2.5 pr-3 text-right">Value (LKR)</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => {
                const open = expanded === r.part_no;
                const held = r.status === "held for review";
                const q = held ? r.q_review : r.q_final;
                const val = held ? r.value_review : r.value;
                return (
                  <Fragment key={r.part_no}>
                    <tr onClick={() => setExpanded(open ? null : r.part_no)}
                      className={`cursor-pointer border-b border-slate-100 align-top ${open ? "bg-blue-50/60" : i % 2 ? "bg-slate-50/40 hover:bg-blue-50/40" : "hover:bg-blue-50/40"}`}>
                      <td className="py-2.5 pl-3 pr-2 text-slate-400 text-xs select-none">{open ? "▾" : "▸"}</td>
                      <td className="py-2.5 pr-3 min-w-[240px] max-w-[340px]">
                        <span className="font-mono text-xs text-slate-800">{r.part_no}</span>
                        <span className="block text-slate-700 line-clamp-2" title={r.description}>{r.description}</span>
                        {held && <span className="inline-block mt-0.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">Held for review — {r.flags}</span>}
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="w-5 h-5 rounded-full inline-flex items-center justify-center text-[10px] font-bold text-white" style={{ background: ABC_COLOR[r.abc] ?? "#94A3B8" }}>{r.abc}</span>
                          <span className="text-xs text-slate-600">{MOVEMENT[r.fsn] ?? r.fsn}</span>
                        </span>
                        <span className="block text-[11px] text-slate-400">{r.behaviour_class ?? "—"}{r.system && r.system !== "Unassigned" ? ` · ${r.system}` : ""}</span>
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">
                        {qty(r.forecast_month)}
                        <span className="block text-[11px] text-violet-600">{r.fleet_forecast != null ? `${Math.round(r.fleet_share * 100)}% from fleet` : <span className="text-slate-400">history only</span>}</span>
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">{qty(r.target_level)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">
                        {qty(r.position)}
                        {r.on_order > 0 && <span className="block text-[11px] text-pink-600">{qty(r.on_order)} on order</span>}
                      </td>
                      <td className={`py-2.5 pr-3 text-right tabular-nums font-bold ${held ? "text-amber-600" : "text-slate-900"}`}>{qty(q)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">{fmt(val)}</td>
                    </tr>
                    {open && (
                      <tr className="bg-blue-50/60 border-b border-slate-200">
                        <td/>
                        <td colSpan={7} className="pb-4 pr-3 pt-1">
                          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
                            <div>
                              <p className="font-semibold text-slate-700 mb-1">1 · Forecast</p>
                              <p className="text-slate-600">Own history: {qty(r.history_forecast)} / mo</p>
                              <p className="text-slate-600">Fleet (UIO): {r.fleet_forecast != null ? `${qty(r.fleet_forecast)} / mo` : "no model link"}</p>
                              <p className="text-slate-600">Blend: {Math.round(r.history_weight * 100)}% history → <b>{qty(r.forecast_month)} / mo</b></p>
                              <p className="text-slate-400">Sold last 6 months: {qty(r.recent_demand_6m)}</p>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-700 mb-1">2 · Classification</p>
                              <p className="text-slate-600">ABC {r.abc}{r.abc_source ? ` (from ${r.abc_source})` : ""} → fill target <b>{Math.round(r.fill_target * 100)}%</b></p>
                              <p className="text-slate-600">Movement: {MOVEMENT[r.fsn] ?? r.fsn} · pattern: {r.demand_category ?? "—"}</p>
                              <p className="text-slate-600">Policy: <b>{POLICY_TEXT[r.policy] ?? r.policy}</b></p>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-700 mb-1">3 · Stock</p>
                              <p className="text-slate-600">On hand: {qty(r.on_hand)}</p>
                              <p className="text-slate-600">On order: {qty(r.on_order)}</p>
                              <p className="text-slate-600">Position: <b>{qty(r.position)}</b></p>
                            </div>
                            <div>
                              <p className="font-semibold text-slate-700 mb-1">4 · Order</p>
                              <p className="text-slate-600">{a.protection_interval_months}-month demand {qty(r.protection_demand)} + safety stock {qty(r.safety_stock)} = target <b>{qty(r.target_level)}</b></p>
                              <p className="text-slate-600">Target − position = {qty(r.gap_to_target)}{r.eoq > r.gap_to_target ? `, raised to the economic quantity ${qty(r.eoq)}` : ""}</p>
                              <p className="text-slate-600">Order <b>{qty(q)}</b> × LKR {qty(r.unit_cost)} = LKR {fmt(val)}</p>
                              {held && <p className="text-amber-700 mt-1">Held: {r.flags}. A buyer confirms, trims or drops it.</p>}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex justify-between items-center text-xs text-slate-500">
          <span>{data.total ? `${page * pageSize + 1}-${Math.min((page + 1) * pageSize, data.total)} of ${data.total.toLocaleString()}` : "No lines"}</span>
          <div className="flex gap-2">
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="px-2 py-1 border rounded disabled:opacity-40" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </div>
        <p className="text-[11px] text-slate-400">
          Assumed until supplied: fill targets A {fill("A")} / B {fill("B")} / C {fill("C")}, holding cost {Math.round(a.holding_rate * 100)}% a year,
          order cost LKR {a.order_cost.toLocaleString()} per line, MOQ {a.moq} and pack size {a.pack_size}. Published On_Orders month interpretation:
          {" "}{a.on_order_interpretation === "arrival" ? "expected arrival" : a.on_order_interpretation}. Every quantity moves with these.
        </p>
      </div>
    </div>
  );
}
