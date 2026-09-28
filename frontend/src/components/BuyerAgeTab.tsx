import { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import { fetchBuyerAge, type BuyerAgeData } from "../api/client";
import { KpiCard } from "./KpiCard";

const UNKNOWN = "Unknown age";
const BAND_COLORS = ["#06B6D4", "#4361EE", "#7C3AED", "#EC4899", "#F97316", "#FFC107", "#2CC56F", "#10B981"];

/** A swatch for an MCSI colour name (first colour word wins). */
function swatch(name: string): string {
  const u = name.toUpperCase();
  const map: [string, string][] = [
    ["BLACK", "#1E293B"], ["CYAN", "#06B6D4"], ["BLUE", "#4361EE"], ["PURPL", "#7C3AED"], ["GRAY", "#94A3B8"],
    ["GREY", "#94A3B8"], ["SILVER", "#CBD5E1"], ["WHITE", "#E2E8F0"], ["RED", "#EF4444"], ["ORANGE", "#F97316"],
    ["YELLOW", "#FFC107"], ["GREEN", "#2CC56F"], ["MAROON", "#9F1239"],
  ];
  return (map.find(([k]) => u.includes(k)) ?? ["", "#A8A29E"])[1];
}

/** Heat cell: share of the row's bikes in this band (darker = larger share). */
function Heat({ share, units }: { share: number; units: number }) {
  const alpha = Math.min(0.9, share / 45);
  return (
    <td className="px-2 py-1.5 text-center tabular-nums text-xs" title={`${units.toLocaleString()} bikes`}
      style={{ background: `rgba(67, 97, 238, ${alpha})`, color: alpha > 0.45 ? "white" : "#334155" }}>
      {units ? `${share.toFixed(0)}%` : <span className="text-slate-300">·</span>}
    </td>
  );
}

/** Buyer age at purchase against the models and colours bought (MCSI; counts only). */
export function BuyerAgeTab() {
  const [data, setData] = useState<BuyerAgeData | null>(null);
  const [model, setModel] = useState("");

  useEffect(() => { fetchBuyerAge().then(d => { setData(d); setModel(d.models[0]?.model ?? ""); }); }, []);

  const bands = useMemo(() => (data?.bands ?? []).filter(b => b.band !== UNKNOWN).map(b => b.band), [data]);
  const grid = useMemo(() => {
    const g = new Map<string, number>();
    for (const r of data?.cube ?? []) g.set(`${r.model}|${r.band}`, (g.get(`${r.model}|${r.band}`) ?? 0) + r.units);
    return g;
  }, [data]);
  const colours = useMemo(() => {
    const rows = new Map<string, Map<string, number>>();
    for (const r of data?.cube ?? []) {
      if (r.model !== model) continue;
      const row = rows.get(r.colour) ?? new Map<string, number>();
      row.set(r.band, (row.get(r.band) ?? 0) + r.units);
      rows.set(r.colour, row);
    }
    return [...rows.entries()]
      .map(([colour, row]) => ({ colour, row, known: bands.reduce((s, b) => s + (row.get(b) ?? 0), 0), total: [...row.values()].reduce((s, v) => s + v, 0) }))
      .sort((a, b) => b.total - a.total);
  }, [data, model, bands]);

  if (!data) return <div className="py-10 text-center text-slate-400">Loading…</div>;
  if (!data.models.length) return <div className="py-10 text-center text-slate-400">MCSI carries no buyer age.</div>;

  const t = data.totals;
  const models = data.models.filter(m => (m.units_with_age ?? 0) >= 20);
  const selected = data.models.find(m => m.model === model);
  const ageByModel = models
    .filter(m => m.median_age != null)
    .map(m => ({ name: m.label.replace(/\s*\([^)]*\)\s*$/, ""), median: m.median_age as number, model: m.model }))
    .sort((a, b) => a.median - b.median);
  const bandShare = (m: string, b: string, known: number) => (known ? ((grid.get(`${m}|${b}`) ?? 0) / known) * 100 : 0);

  return (
    <div className="space-y-5">
      <p className="text-xs text-slate-500">
        MCSI records each buyer's <b>age at purchase</b>. Crossing it with model and colour shows who buys what. Shares are within
        each row (a model's or a colour's buyers with a known age); hover a cell for the number of bikes. Only counts are shown —
        no customer details.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Median buyer age" value={t.median_age != null ? `${Math.round(t.median_age)} yrs` : "—"} sub="age at purchase, all models" color="blue"/>
        <KpiCard label="Buyers under 26" value={`${(t.under_26_pct ?? 0).toFixed(1)}%`} sub="of bikes with a known age" color="purple"/>
        <KpiCard label="Bikes with an age" value={t.units_with_age.toLocaleString()} sub={`of ${t.units.toLocaleString()} sold`} color="green"/>
        <KpiCard label="Age not recorded" value={(t.units - t.units_with_age).toLocaleString()} sub="'No order record' in MCSI" color="amber"/>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700">Buyers by age band</h3>
          <p className="text-xs text-slate-400 mb-2">All models · bikes with a known age</p>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={data.bands.filter(b => b.band !== UNKNOWN)} margin={{ top: 15, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="band" tick={{ fontSize: 10 }}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toLocaleString()}/>
              <Tooltip formatter={(v: unknown) => [Number(v).toLocaleString(), "Bikes"]}/>
              <Bar dataKey="units" radius={[4, 4, 0, 0]}>
                {bands.map((b, i) => <Cell key={b} fill={BAND_COLORS[i % BAND_COLORS.length]}/>)}
                <LabelList dataKey="share_pct" position="top" formatter={(v: unknown) => `${Number(v).toFixed(0)}%`} style={{ fontSize: 10, fill: "#64748B" }}/>
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-white rounded-xl shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700">Median buyer age by model</h3>
          <p className="text-xs text-slate-400 mb-2">Youngest buyers at the top · click a bar to see its colours below</p>
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={ageByModel} layout="vertical" margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
              <XAxis type="number" tick={{ fontSize: 10 }} domain={[0, "dataMax + 5"]}/>
              <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={150}/>
              <Tooltip formatter={(v: unknown) => [`${Number(v).toFixed(0)} years`, "Median age"]}/>
              <Bar dataKey="median" radius={[0, 3, 3, 0]} cursor="pointer"
                onClick={(d) => { const m = (d as unknown as { payload?: { model?: string } })?.payload?.model; if (m) setModel(m); }}>
                {ageByModel.map(r => <Cell key={r.model} fill={r.model === model ? "#0F172A" : "#4361EE"}/>)}
                <LabelList dataKey="median" position="right" formatter={(v: unknown) => `${Number(v).toFixed(0)}`} style={{ fontSize: 10, fill: "#475569" }}/>
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <h3 className="text-sm font-semibold text-slate-700">Model × buyer age</h3>
        <p className="text-xs text-slate-400 mb-3">Share of each model's buyers in each age band · click a model to see its colours</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr className="text-[11px] font-semibold text-slate-500 uppercase">
                <th className="py-2 pr-3 text-left">Model</th>
                <th className="py-2 px-2 text-right">Bikes</th>
                <th className="py-2 px-2 text-right">Median age</th>
                {bands.map(b => <th key={b} className="py-2 px-2 text-center normal-case">{b}</th>)}
              </tr>
            </thead>
            <tbody>
              {models.map(m => {
                const known = m.units_with_age ?? 0;
                return (
                  <tr key={m.model} onClick={() => setModel(m.model)}
                    className={`cursor-pointer ${m.model === model ? "outline outline-2 outline-slate-700" : "hover:bg-slate-50"}`}>
                    <td className="py-1.5 pr-3 text-slate-800 whitespace-nowrap">{m.label}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-slate-600">{m.units.toLocaleString()}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums font-semibold text-slate-800">{m.median_age != null ? Math.round(m.median_age) : "—"}</td>
                    {bands.map(b => <Heat key={b} share={bandShare(m.model, b, known)} units={grid.get(`${m.model}|${b}`) ?? 0}/>)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">Colour × buyer age — {selected?.label ?? ""}</h3>
            <p className="text-xs text-slate-400">Share of each colour's buyers in each age band</p>
          </div>
          <select value={model} onChange={e => setModel(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs">
            {models.map(m => <option key={m.model} value={m.model}>{m.label}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead>
              <tr className="text-[11px] font-semibold text-slate-500 uppercase">
                <th className="py-2 pr-3 text-left">Colour</th>
                <th className="py-2 px-2 text-right">Bikes</th>
                {bands.map(b => <th key={b} className="py-2 px-2 text-center normal-case">{b}</th>)}
              </tr>
            </thead>
            <tbody>
              {colours.map(c => (
                <tr key={c.colour}>
                  <td className="py-1.5 pr-3 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5 text-slate-700">
                      <span className="w-2.5 h-2.5 rounded-full ring-1 ring-slate-300" style={{ background: swatch(c.colour) }}/>
                      {c.colour}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-right tabular-nums text-slate-600">{c.total.toLocaleString()}</td>
                  {bands.map(b => <Heat key={b} share={c.known ? ((c.row.get(b) ?? 0) / c.known) * 100 : 0} units={c.row.get(b) ?? 0}/>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
