import { useEffect, useMemo, useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList,
  BarChart, Bar, ComposedChart, Line, Legend,
} from "recharts";
import { fetchModelPrice, type ModelPriceData } from "../api/client";
import { KpiCard } from "./KpiCard";

const TYPE_COLOR: Record<string, string> = { Motorcycle: "#4361EE", Scooter: "#F97316" };
const lkr = (n: number) =>
  n >= 1_000_000_000 ? `${(n / 1_000_000_000).toFixed(2)}B` : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1_000 ? `${Math.round(n / 1_000)}K` : Math.round(n).toLocaleString();
const shortName = (label: string) => label.replace(/\s*\([^)]*\)\s*$/, "");

/** Model list price against units sold, discounts, price bands and the monthly picture. */
export function ModelPriceTab() {
  const [data, setData] = useState<ModelPriceData | null>(null);
  const [model, setModel] = useState<string>("");

  useEffect(() => { fetchModelPrice().then(d => { setData(d); setModel(d.models[0]?.model ?? ""); }); }, []);

  const monthly = useMemo(
    () => (data?.monthly ?? []).filter(r => r.model === model),
    [data, model],
  );

  if (!data) return <div className="py-10 text-center text-slate-400">Loading…</div>;
  if (!data.models.length) return <div className="py-10 text-center text-slate-400">No MCSI sales published yet.</div>;

  const t = data.totals;
  // The scatter shows models with a real sales history; one-off launches sit at the axis.
  const points = data.models.filter(m => m.units >= 10).map(m => ({
    ...m, name: shortName(m.label), x: m.list_price, y: m.units, z: m.revenue_lkr,
  }));
  const selected = data.models.find(m => m.model === model);

  return (
    <div className="space-y-5">
      <p className="text-xs text-slate-500">
        Each bike's <b>net sales value</b> in MCSI ({t.date_from} to {t.date_to}). A model's <b>list price</b> is the price most of
        its bikes sold at; a bike sold below it counts as <b>discounted</b>. Prices are set centrally and barely move month to month,
        so this is mainly a comparison <b>across models</b> — which price points sell.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Bikes sold" value={t.units.toLocaleString()} sub={`${t.date_from} → ${t.date_to}`} color="blue"/>
        <KpiCard label="Average price" value={`LKR ${lkr(t.avg_price)}`} sub="net sales per bike, all models" color="green"/>
        <KpiCard label="Revenue" value={`LKR ${lkr(t.revenue_lkr)}`} sub={`${data.models.length} models`} color="purple"/>
        <KpiCard label="Sold below list" value={t.discounted_units.toLocaleString()}
          sub={`${(t.units ? (t.discounted_units / t.units) * 100 : 0).toFixed(1)}% of bikes were discounted`} color="amber"/>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5 xl:col-span-2">
          <h3 className="text-sm font-semibold text-slate-700">List price vs bikes sold, by model</h3>
          <p className="text-xs text-slate-400 mb-2">Bubble size = revenue · colour = motorcycle / scooter · click a bubble to see its monthly trend</p>
          <ResponsiveContainer width="100%" height={330}>
            <ScatterChart margin={{ top: 20, right: 30, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis type="number" dataKey="x" name="List price" tick={{ fontSize: 10 }} tickFormatter={v => lkr(Number(v))}
                domain={["dataMin - 50000", "dataMax + 50000"]}
                label={{ value: "List price (LKR)", position: "insideBottom", offset: -10, fontSize: 11 }}/>
              <YAxis type="number" dataKey="y" name="Bikes sold" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}
                label={{ value: "Bikes sold", angle: -90, position: "insideLeft", fontSize: 11 }}/>
              <ZAxis type="number" dataKey="z" range={[80, 1400]} name="Revenue"/>
              <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const m = payload[0].payload as (typeof points)[number];
                return (
                  <div className="bg-white border border-slate-200 rounded-lg shadow px-3 py-2 text-xs space-y-0.5">
                    <p className="font-semibold text-slate-800">{m.label}</p>
                    <p>List price LKR {m.list_price.toLocaleString()}</p>
                    <p>{m.units.toLocaleString()} bikes ({m.unit_share_pct.toFixed(1)}%) · {m.units_per_month.toFixed(0)}/month</p>
                    <p>Revenue LKR {lkr(m.revenue_lkr)} ({m.revenue_share_pct.toFixed(1)}%)</p>
                    <p className="text-slate-400">{m.motorcycle_type ?? ""}{m.cc ? ` · ${m.cc} cc` : ""}</p>
                  </div>
                );
              }}/>
              <Scatter data={points} cursor="pointer"
                onClick={(p) => { const m = (p as unknown as { payload?: { model?: string } })?.payload?.model; if (m) setModel(m); }}>
                {points.map(p => (
                  <Cell key={p.model} fill={TYPE_COLOR[p.motorcycle_type ?? ""] ?? "#94A3B8"} fillOpacity={p.model === model ? 0.95 : 0.6}
                    stroke={p.model === model ? "#0F172A" : "none"} strokeWidth={2}/>
                ))}
                <LabelList dataKey="name" position="top" style={{ fontSize: 10, fill: "#475569" }}/>
              </Scatter>
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700">Bikes sold by price band</h3>
          <p className="text-xs text-slate-400 mb-2">Models grouped by list price</p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.bands} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="band" tick={{ fontSize: 9 }} interval={0}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
              <Tooltip formatter={(v: unknown) => [Number(v).toLocaleString(), "Bikes sold"]}/>
              <Bar dataKey="units" fill="#4361EE" radius={[4, 4, 0, 0]}/>
            </BarChart>
          </ResponsiveContainer>
          <div className="space-y-1 mt-2">
            {data.bands.map(b => (
              <div key={b.band} className="flex justify-between text-xs">
                <span className="text-slate-600">{b.band} <span className="text-slate-400">· {b.models} model{b.models === 1 ? "" : "s"}</span></span>
                <span className="tabular-nums text-slate-700">{b.unit_share_pct.toFixed(1)}% · LKR {lkr(b.revenue_lkr)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">Monthly bikes sold vs average price — {selected ? selected.label : ""}</h3>
            <p className="text-xs text-slate-400">Bars = bikes sold · line = average net price that month (dips = discounted bikes)</p>
          </div>
          <select value={model} onChange={e => setModel(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs">
            {data.models.map(m => <option key={m.model} value={m.model}>{m.label}</option>)}
          </select>
        </div>
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={monthly} margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
            <XAxis dataKey="period" tick={{ fontSize: 10 }}/>
            <YAxis yAxisId="u" tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
            <YAxis yAxisId="p" orientation="right" tick={{ fontSize: 10 }} tickFormatter={v => lkr(Number(v))}
              domain={["dataMin - 20000", "dataMax + 20000"]}/>
            <Tooltip formatter={(v: unknown, n: unknown) => [n === "Average price" ? `LKR ${Math.round(Number(v)).toLocaleString()}` : Number(v).toLocaleString(), String(n)]}/>
            <Legend wrapperStyle={{ fontSize: 11 }}/>
            <Bar yAxisId="u" dataKey="units" name="Bikes sold" fill="#4361EE" radius={[3, 3, 0, 0]}/>
            <Line yAxisId="p" dataKey="avg_price" name="Average price" stroke="#F97316" strokeWidth={2} dot={{ r: 2 }}/>
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Price and sales by model</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
                <th className="py-2.5 px-3">Model</th>
                <th className="py-2.5 pr-3">Type</th>
                <th className="py-2.5 pr-3 text-right">List price</th>
                <th className="py-2.5 pr-3 text-right">Avg realised</th>
                <th className="py-2.5 pr-3 text-right">Bikes sold</th>
                <th className="py-2.5 pr-3 text-right">Per month</th>
                <th className="py-2.5 pr-3 text-right">Revenue (LKR)</th>
                <th className="py-2.5 pr-3 text-right" title="Bikes sold below the list price, and their average discount">Discounted</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m, i) => (
                <tr key={m.model} onClick={() => setModel(m.model)}
                  className={`cursor-pointer border-b border-slate-100 ${m.model === model ? "bg-blue-50/60" : i % 2 ? "bg-slate-50/40 hover:bg-blue-50/40" : "hover:bg-blue-50/40"}`}>
                  <td className="py-2 px-3 text-slate-800">{m.label}<span className="block text-[11px] text-slate-400">{m.price_band} · {m.months_sold} months</span></td>
                  <td className="py-2 pr-3 text-xs text-slate-600 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full" style={{ background: TYPE_COLOR[m.motorcycle_type ?? ""] ?? "#94A3B8" }}/>
                      {m.motorcycle_type ?? "—"}{m.cc ? ` · ${m.cc} cc` : ""}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums font-semibold text-slate-800">{Math.round(m.list_price).toLocaleString()}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-600">{Math.round(m.avg_price).toLocaleString()}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-800">{m.units.toLocaleString()}<span className="block text-[11px] text-slate-400">{m.unit_share_pct.toFixed(1)}%</span></td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-600">{m.units_per_month.toFixed(0)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-800">{lkr(m.revenue_lkr)}<span className="block text-[11px] text-slate-400">{m.revenue_share_pct.toFixed(1)}%</span></td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-600">
                    {m.discounted_units > 0 ? <>{m.discounted_units.toLocaleString()} <span className="text-slate-400">({m.discounted_pct.toFixed(1)}%)</span>
                      <span className="block text-[11px] text-slate-400">avg LKR {Math.round(m.avg_discount).toLocaleString()} off</span></> : <span className="text-slate-300">none</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
