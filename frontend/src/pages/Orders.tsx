import { Fragment, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { fetchOrderPlan, type IncomingMonth, type OrderPlanData, type OrderPlanRow } from "../api/client";
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

const shortMonth = (ym: string | null | undefined) => {
  if (!ym) return "—";
  const [y, m] = ym.split("-").map(Number);
  return y && m ? new Date(y, m - 1, 1).toLocaleString("en-GB", { month: "short" }) : ym;
};

function IncomingChips({ months }: { months: IncomingMonth[] }) {
  if (!months.length) return <span className="text-slate-400">nothing incoming</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {months.map(m => (
        <span key={m.month} className="px-1.5 py-0.5 rounded bg-pink-50 text-pink-700 tabular-nums">
          {shortMonth(m.month)} {qty(m.qty)}
        </span>
      ))}
    </span>
  );
}

const ADVICE_TONE: Record<string, string> = {
  release: "bg-green-100 text-green-700", trim: "bg-amber-100 text-amber-800",
  drop: "bg-slate-200 text-slate-600", review: "bg-violet-100 text-violet-700",
};

/** What a buyer should know about a line: its audit, its recommendation or why to expedite. */
function LineNote({ r }: { r: OrderPlanRow }) {
  if (r.status === "held for review" && r.recommendation) {
    return (
      <span>
        <span className={`inline-block text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${ADVICE_TONE[r.recommendation] ?? ""}`}>
          {r.recommendation}{r.recommendation === "trim" || r.recommendation === "release" ? ` ${qty(r.suggested_qty)}` : ""}
        </span>
        <span className="block text-[11px] text-slate-500 mt-0.5">{r.recommendation_reason}</span>
      </span>
    );
  }
  if (r.status === "expedite") {
    return <span className="text-[11px] font-medium text-red-600">Expedite: runs out {monthName(r.run_out_month ?? "")} before incoming stock lands</span>;
  }
  return (
    <span className="space-y-0.5 block">
      {r.needs_check && <span className="block text-[11px] text-amber-700">Check: {r.check_reasons}</span>}
      {r.expedite && <span className="block text-[11px] text-red-600">Runs out {monthName(r.run_out_month ?? "")} — expedite incoming</span>}
      {!r.needs_check && !r.expedite && <span className="text-[11px] text-green-700">OK</span>}
    </span>
  );
}

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
          ["3 · Stock", "PDC stock plus everything already on order (Yamaha MC and OBM parts only). Incoming stock is also followed month by month to flag parts that run out before it lands."],
          ["4 · Order", `Reorder level = 1 month of demand + buffer stock (buffer ≤ 3 months). If on hand + on order is at or below it, order enough to bring it back up (economic batch ≤ 3 months); it arrives about ${monthName(data.expected_arrival)}. Lines above 3× recent demand are held for a buyer, with a recommendation.`],
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
        <KpiCard label="Needs a second look" value={(s.check_lines ?? 0).toLocaleString()} sub={`LKR ${fmt(s.check_value ?? 0)} of the order — reasons on each line`} color="purple"/>
        <KpiCard label="Held for review" value={`LKR ${fmt(s.held_value)}`} sub={`${s.held_lines.toLocaleString()} lines · ${(s.held_recommendations ?? []).map(h => `${h.lines} ${h.recommendation}`).join(" · ")}`} color="amber"/>
        <KpiCard label="Expedite" value={(s.expedite_lines ?? 0).toLocaleString()} sub="parts that run out before their incoming stock lands" color="teal"/>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Bars title="Order value by ABC class" rows={data.by_abc} total={s.value} colors={ABC_COLOR}/>
        <Bars title="Order value by system" rows={data.by_system} total={s.value}/>
        <Bars title="Order value by part type" rows={data.by_behaviour} total={s.value}/>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {[["to order", `To order ${s.lines.toLocaleString()}`], ["check", `Needs check ${(s.check_lines ?? 0).toLocaleString()}`], ["held for review", `Held for review ${s.held_lines.toLocaleString()}`], ["expedite", `Expedite ${(s.expedite_lines ?? 0).toLocaleString()}`], ["", "All"]].map(([k, label]) => (
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
                <th className="py-2.5 pr-3 text-right" title="Safety stock held against forecast error over the lead time and review period">Buffer stock<span className="block normal-case font-normal">safety stock</span></th>
                <th className="py-2.5 pr-3 text-right" title="This month's reorder level: one month of demand + buffer stock. Order when on hand + on order is at or below it.">Reorder level<span className="block normal-case font-normal">{monthName(data.cycle_month)} · 1-mo demand + buffer</span></th>
                <th className="py-2.5 pr-3 text-right" title="PDC stock + everything on order">Stock<span className="block normal-case font-normal">on hand + on order</span></th>
                <th className="py-2.5 pr-3 text-right text-slate-700">Order qty</th>
                <th className="py-2.5 pr-3 text-right">Value (LKR)</th>
                <th className="py-2.5 pr-3 min-w-[220px]">Note</th>
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
                        {r.status === "expedite" && <span className="inline-block mt-0.5 text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700">Not ordered — expedite incoming</span>}
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
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">{qty(r.safety_stock)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">
                        {qty(r.reorder_level)}
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">
                        {qty(r.stock_checked)}
                        {r.on_order > 0 && <span className="block text-[11px] text-pink-600">{qty(r.on_order)} on order</span>}
                        {r.stock_checked != null && r.reorder_level != null && (r.stock_checked <= r.reorder_level
                          ? <span className="block text-[11px] text-red-600">at/below reorder level</span>
                          : <span className="block text-[11px] text-slate-400">above reorder level</span>)}
                      </td>
                      <td className={`py-2.5 pr-3 text-right tabular-nums font-bold ${held ? "text-amber-600" : "text-slate-900"}`}>{r.status === "expedite" ? "—" : qty(q)}</td>
                      <td className="py-2.5 pr-3 text-right tabular-nums text-slate-700">{r.status === "expedite" ? "—" : fmt(val)}</td>
                      <td className="py-2.5 pr-3"><LineNote r={r}/></td>
                    </tr>
                    {open && (
                      <tr className="bg-blue-50/60 border-b border-slate-200">
                        <td/>
                        <td colSpan={10} className="pb-4 pr-3 pt-1">
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
                              <p className="text-slate-600">On hand + on order: <b>{qty(r.stock_checked)}</b></p>
                              {r.recent_monthly_demand != null && <p className="text-slate-500">Recent orders: {qty(r.recent_monthly_demand)} / mo{r.last_order_month ? ` · last ordered ${monthName(r.last_order_month)}` : ""}</p>}
                              <p className="text-slate-600 mt-1">Incoming: <IncomingChips months={r.incoming_by_month ?? []}/></p>
                              {r.run_out_month
                                ? <p className={r.expedite ? "text-red-600" : "text-amber-700"}>Month by month, stock runs out in {monthName(r.run_out_month)}{r.expedite ? " — before incoming stock lands; consider expediting" : ""}</p>
                                : <p className="text-slate-600">Month by month, stock lasts until the new order lands</p>}
                              {r.stock_at_order_arrival != null && <p className="text-slate-400">Projected stock when this order lands: {qty(r.stock_at_order_arrival)}</p>}
                            </div>
                            <div>
                              <p className="font-semibold text-slate-700 mb-1">4 · Order</p>
                              <p className="text-slate-600">Buffer stock <b>{qty(r.safety_stock)}</b> (for the {Math.round(r.fill_target * 100)}% fill target)</p>
                              <p className="text-slate-600">Reorder level for {monthName(data.cycle_month)} = 1-month demand {qty(r.reorder_level - r.safety_stock)} + buffer {qty(r.safety_stock)} = <b>{qty(r.reorder_level)}</b></p>
                              <p className="text-slate-600">On hand {qty(r.on_hand)} + on order {qty(r.on_order)} = <b>{qty(r.stock_checked)}</b> — {r.stock_checked != null && r.stock_checked <= r.reorder_level ? "at or below the reorder level, so order" : "above the reorder level"}</p>
                              <p className="text-slate-600">Reorder level − stock = {qty(r.gap_to_target)}{r.eoq > r.gap_to_target ? `, raised to the economic batch ${qty(r.eoq)} (≤ 3 months)` : ""}; arrives about {monthName(r.landing_month ?? data.expected_arrival)}</p>
                              <p className="text-slate-600">Order <b>{qty(q)}</b> × LKR {qty(r.unit_cost)} = LKR {fmt(val)}</p>
                              {held && <p className="text-amber-700 mt-1">Held: {r.flags}. A buyer confirms, trims or drops it.</p>}
                            </div>
                          </div>
                          {(r.monthly_rol ?? []).length > 0 && (
                            <div className="mt-3 text-xs">
                              <p className="font-semibold text-slate-700 mb-1">
                                Reorder level month by month
                                <span className="font-normal text-slate-500"> — each month&apos;s stock (on the shelf + that month&apos;s arrivals, before this order) against that month&apos;s reorder level (1-month demand + buffer){r.reorder_due_month ? `; first at/below in ${monthName(r.reorder_due_month)}` : "; stays above it"}</span>
                              </p>
                              <table className="tabular-nums border border-slate-200 bg-white rounded">
                                <thead className="bg-slate-50 text-slate-500">
                                  <tr><th className="px-2 py-1 text-left font-medium">Month</th>{r.monthly_rol.map(m => <th key={m.month} className="px-3 py-1 text-right font-medium">{monthName(m.month)}{m.month === data.cycle_month ? " (now)" : ""}</th>)}</tr>
                                </thead>
                                <tbody className="text-slate-700">
                                  <tr><td className="px-2 py-1 text-slate-500">Stock at start</td>{r.monthly_rol.map(m => <td key={m.month} className="px-3 py-1 text-right">{qty(m.stock_start)}</td>)}</tr>
                                  <tr><td className="px-2 py-1 text-slate-500">Incoming</td>{r.monthly_rol.map(m => <td key={m.month} className="px-3 py-1 text-right text-pink-700">{m.incoming ? qty(m.incoming) : "—"}</td>)}</tr>
                                  <tr><td className="px-2 py-1 text-slate-500">Stock this month</td>{r.monthly_rol.map(m => <td key={m.month} className="px-3 py-1 text-right font-medium">{qty(m.position)}</td>)}</tr>
                                  <tr><td className="px-2 py-1 text-slate-500">Reorder level</td>{r.monthly_rol.map(m => <td key={m.month} className="px-3 py-1 text-right">{qty(m.rol)}</td>)}</tr>
                                  <tr><td className="px-2 py-1 text-slate-500">Vs reorder level</td>{r.monthly_rol.map(m => <td key={m.month} className={`px-3 py-1 text-right font-medium ${m.at_or_below ? "text-red-600" : "text-green-600"}`}>{m.at_or_below ? "at/below" : "above"}</td>)}</tr>
                                </tbody>
                              </table>
                              <p className="text-[11px] text-slate-400 mt-1">The forecast is one monthly rate, so each month&apos;s reorder level equals this month&apos;s; it is recalculated every monthly cycle from that month&apos;s stock, forecast and demand.</p>
                            </div>
                          )}
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
