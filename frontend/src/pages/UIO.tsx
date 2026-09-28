import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
  Legend, ComposedChart, Area, Line, PieChart, Pie, ReferenceArea,
} from "recharts";
import { fetchUioSnapshot, type UioSnapshot, type UioGroupRow } from "../api/client";
import { KpiCard } from "../components/KpiCard";

const TYPE_COLORS: Record<string, string> = { Motorcycle: "#4361EE", Scooter: "#F97316" };
const STATUS_COLORS: Record<string, string> = { Active: "#2CC56F", Inactive: "#94A3B8" };
const PALETTE = ["#4361EE", "#F97316", "#2CC56F", "#7C3AED", "#06B6D4", "#EF4444", "#FFC107", "#10B981", "#EC4899", "#94A3B8"];

// Sales Summery colour families to a swatch (first named colour wins for mixed families).
function familyHex(name: string): string {
  const u = name.toUpperCase();
  const map: [string, string][] = [
    ["BLACK", "#1E293B"], ["CYAN", "#06B6D4"], ["BLUE", "#4361EE"], ["GREY", "#94A3B8"], ["SILVER", "#CBD5E1"],
    ["RED", "#EF4444"], ["MAROON", "#9F1239"], ["WHITE", "#E2E8F0"], ["GREEN", "#2CC56F"], ["ORANGE", "#F97316"],
    ["YELLOW", "#FFC107"], ["GOLD", "#CA8A04"], ["PINK", "#EC4899"], ["BEIGE", "#D6C7A1"],
  ];
  const first = u.split("/")[0];
  return (map.find(([k]) => first.includes(k)) ?? map.find(([k]) => u.includes(k)) ?? ["", "#A8A29E"])[1];
}

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return Math.round(n).toLocaleString();
}
const num = (n: number) => Math.round(n).toLocaleString();

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
      <div>
        <h3 className="text-sm font-bold text-slate-800">{title}</h3>
        {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
      </div>
      {children}
    </div>
  );
}

function GroupBars({ rows, height }: { rows: UioGroupRow[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(180, rows.length * 30)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 40, left: 10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" horizontal={false}/>
        <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={fmt}/>
        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={130}/>
        <Tooltip formatter={(v: unknown, n: unknown) => [num(Number(v)), String(n)]}/>
        <Legend wrapperStyle={{ fontSize: 11 }}/>
        <Bar dataKey="registered" name="Registered since first year" fill="#CBD5E1" radius={[0, 3, 3, 0]}/>
        <Bar dataKey="uio" name="Estimated in operation" fill="#4361EE" radius={[0, 3, 3, 0]}/>
      </BarChart>
    </ResponsiveContainer>
  );
}

function SharePie({ rows, colors }: { rows: UioGroupRow[]; colors: Record<string, string> }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie data={rows} dataKey="uio" nameKey="name" innerRadius={45} outerRadius={75}
          label={(e: { name?: string; share_pct?: number }) => `${e.name} ${(e.share_pct ?? 0).toFixed(1)}%`} labelLine={false}>
          {rows.map((r, i) => <Cell key={r.name} fill={colors[r.name] ?? PALETTE[i % PALETTE.length]}/>)}
        </Pie>
        <Tooltip formatter={(v: unknown, n: unknown) => [num(Number(v)), String(n)]}/>
      </PieChart>
    </ResponsiveContainer>
  );
}

export function UIO() {
  const [data, setData] = useState<UioSnapshot | null>(null);
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState("All");
  const [status, setStatus] = useState("All");

  useEffect(() => { fetchUioSnapshot().then(setData); }, []);

  const types = useMemo(() => [...new Set((data?.registrations ?? []).map(r => r.type))].sort(), [data]);

  if (!data) return <div className="flex-1 flex items-center justify-center text-slate-400">Loading…</div>;
  if (!data.as_of_year) return <div className="flex-1 flex items-center justify-center text-slate-400">No Sales Summery fleet published yet — run the pipeline.</div>;

  const { kpis } = data;
  // Registrations per year, one key per motorcycle type (the import-ban years are real zeros).
  const regYears = [...new Set(data.registrations.map(r => r.year))].sort((a, b) => a - b);
  const regData = regYears.map(y => {
    const row: Record<string, number> = { year: y };
    for (const r of data.registrations.filter(x => x.year === y)) row[r.type] = r.units;
    return row;
  });
  const banYears = regData.filter(r => types.every(t => (r[t] ?? 0) < 100)).map(r => r.year);
  const series = data.series.map(r => ({ ...r, band: [r.uio_low, r.uio_high] as [number, number] }));
  const buckets = [...new Map(data.age.map(a => [a.bucket, a.age_start])).entries()].sort((a, b) => a[1] - b[1]);
  const ageData = buckets.map(([bucket]) => {
    const row: Record<string, number | string> = { bucket };
    for (const a of data.age.filter(x => x.bucket === bucket)) row[a.type] = a.units;
    return row;
  });
  const colourTotal = data.colour.reduce((s, r) => s + r.units, 0);
  const families = ["All", ...data.by_family.map(f => f.name)];
  const shown = data.models.filter(m =>
    (family === "All" || m.family === family) &&
    (status === "All" || m.status === status) &&
    (!search || m.model.toLowerCase().includes(search.toLowerCase())));

  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Units in Operation (UIO)</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          From Sales Summery: every motorcycle registered {data.first_year}–{data.as_of_year}, and how many are estimated still
          on the road in {data.as_of_year} (Step 10 survival model — base curve, with short- and long-life curves as the range;
          no de-registration records exist, so this is an estimate, not a count).
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <KpiCard label={`Registered ${data.first_year}–${data.as_of_year}`} value={fmt(kpis.registered)} sub={`${num(kpis.registered)} units`} color="blue"/>
        <KpiCard label={`In operation ${data.as_of_year}`} value={fmt(kpis.uio)} sub={`range ${fmt(kpis.uio_low)}–${fmt(kpis.uio_high)}`} color="green"/>
        <KpiCard label="Still running" value={`${kpis.surviving_pct.toFixed(1)}%`} sub="of everything registered" color="teal"/>
        <KpiCard label="Active models' share" value={`${kpis.active_uio_pct.toFixed(1)}%`} sub={`${kpis.models_active} of ${kpis.models_total} models still sold`} color="purple"/>
        <KpiCard label="Average fleet age" value={`${kpis.avg_age.toFixed(1)} yrs`} sub="weighted by units in operation" color="amber"/>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Section title="Registrations by year" sub={`Sales Summery registrations (MC Analysis counts MCSI VINs; the two differ by under 0.2% a year) · new bikes entering the fleet, by motorcycle type${banYears.length ? ` · ${banYears[0]}–${banYears[banYears.length - 1]}: import ban, genuinely zero` : ""}`}>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={regData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="year" tick={{ fontSize: 10 }}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown, n: unknown) => [num(Number(v)), String(n)]}/>
              <Legend wrapperStyle={{ fontSize: 11 }}/>
              {banYears.length > 0 && (
                <ReferenceArea x1={banYears[0]} x2={banYears[banYears.length - 1]} fill="#FEE2E2" fillOpacity={0.6}
                  label={{ value: "Import ban", fontSize: 10, fill: "#B91C1C", position: "insideTop" }}/>
              )}
              {types.map(t => <Bar key={t} dataKey={t} stackId="t" fill={TYPE_COLORS[t] ?? "#94A3B8"}/>)}
            </BarChart>
          </ResponsiveContainer>
        </Section>

        <Section title="Units in operation over time" sub="Line = base survival estimate · band = short- to long-life curves · bars = registrations that year">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={series} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="year" tick={{ fontSize: 10 }}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown, n: unknown) => [Array.isArray(v) ? `${num(v[0])} – ${num(v[1])}` : num(Number(v)), String(n)]}/>
              <Legend wrapperStyle={{ fontSize: 11 }}/>
              <Bar dataKey="new_sales" name="Registrations" fill="#E2E8F0"/>
              <Area dataKey="band" name="Range (short–long life)" stroke="none" fill="#2CC56F" fillOpacity={0.15}/>
              <Line dataKey="uio" name="In operation (base)" stroke="#2CC56F" strokeWidth={2.5} dot={{ r: 2 }}/>
            </ComposedChart>
          </ResponsiveContainer>
        </Section>
      </div>

      <Section title={`Fleet by model family — ${data.as_of_year}`} sub="Grey = everything registered since the first year · blue = estimated still in operation">
        <GroupBars rows={data.by_family}/>
      </Section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Section title="By motorcycle type" sub="Share of units in operation">
          <SharePie rows={data.by_type} colors={TYPE_COLORS}/>
        </Section>
        <Section title="By status" sub="Inactive models are no longer sold but still run and need parts">
          <SharePie rows={data.by_status} colors={STATUS_COLORS}/>
        </Section>
        <Section title="By segment" sub="Units in operation">
          <GroupBars rows={data.by_segment} height={200}/>
        </Section>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Section title={`Fleet age — ${data.as_of_year}`} sub="Units in operation by age · the import-ban gap shows as missing ages — it is real, not a data error">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={ageData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9"/>
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} label={{ value: "age (years)", position: "insideBottom", offset: -2, fontSize: 10 }}/>
              <YAxis tick={{ fontSize: 10 }} tickFormatter={fmt}/>
              <Tooltip formatter={(v: unknown, n: unknown) => [num(Number(v)), String(n)]}/>
              <Legend wrapperStyle={{ fontSize: 11 }}/>
              {types.map(t => <Bar key={t} dataKey={t} stackId="a" fill={TYPE_COLORS[t] ?? "#94A3B8"}/>)}
            </BarChart>
          </ResponsiveContainer>
        </Section>

        <Section title="Registrations by colour family" sub={`All ${num(colourTotal)} registrations since ${data.first_year}`}>
          <div className="space-y-1.5">
            {data.colour.map(c => (
              <div key={c.name} className="flex items-center gap-2 text-xs">
                <span className="w-28 truncate text-slate-600" title={c.name}>{c.name}</span>
                <div className="flex-1 h-3 bg-slate-100 rounded-sm overflow-hidden">
                  <div className="h-full rounded-sm" style={{ width: `${(c.units / (data.colour[0]?.units || 1)) * 100}%`, background: familyHex(c.name),
                    boxShadow: familyHex(c.name) === "#E2E8F0" ? "inset 0 0 0 1px #94A3B8" : undefined }}/>
                </div>
                <span className="w-16 text-right tabular-nums font-semibold text-slate-700">{num(c.units)}</span>
                <span className="w-12 text-right tabular-nums text-slate-400">{colourTotal ? (c.units / colourTotal * 100).toFixed(1) : "0.0"}%</span>
              </div>
            ))}
          </div>
        </Section>
      </div>

      <Section title={`All models — ${shown.length} of ${data.models.length}`} sub="Every model code in Sales Summery with its registrations and estimated units in operation">
        <div className="flex flex-wrap items-center gap-2">
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search model…"
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-xs w-56 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"/>
          <select value={family} onChange={e => setFamily(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white">
            {families.map(f => <option key={f} value={f}>{f === "All" ? "All families" : f}</option>)}
          </select>
          <select value={status} onChange={e => setStatus(e.target.value)} className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white">
            {["All", "Active", "Inactive"].map(s => <option key={s} value={s}>{s === "All" ? "All statuses" : s}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto max-h-[560px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-slate-200 text-left text-slate-500 uppercase">
                <th className="py-2 pr-3">Model</th>
                <th className="py-2 pr-3">Family</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">Segment</th>
                <th className="py-2 pr-3 text-right">cc</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Sold</th>
                <th className="py-2 pr-3 text-right">Registered</th>
                <th className="py-2 pr-3 text-right text-green-700">In operation</th>
                <th className="py-2 pr-3 text-right">Range</th>
                <th className="py-2 pr-3 text-right">Still running</th>
                <th className="py-2 text-right">Avg age</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(m => (
                <tr key={m.model} className="border-b border-slate-50 hover:bg-slate-50/60">
                  <td className="py-1.5 pr-3 font-medium text-slate-800 whitespace-nowrap">{m.model}</td>
                  <td className="py-1.5 pr-3 text-slate-600">{m.family}</td>
                  <td className="py-1.5 pr-3">
                    <span className="inline-flex items-center gap-1 text-slate-600">
                      <span className="w-2 h-2 rounded-full" style={{ background: TYPE_COLORS[m.type] ?? "#94A3B8" }}/>{m.type}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-slate-500">{m.segment}</td>
                  <td className="py-1.5 pr-3 text-right text-slate-500">{m.cc != null ? Math.round(m.cc) : "—"}</td>
                  <td className="py-1.5 pr-3">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${m.status === "Active" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500"}`}>{m.status}</span>
                  </td>
                  <td className="py-1.5 pr-3 text-slate-500 whitespace-nowrap">{m.first_year ?? "—"}{m.last_year && m.last_year !== m.first_year ? `–${m.last_year}` : ""}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-700">{num(m.registered)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums font-semibold text-green-700">{num(m.uio)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-400 whitespace-nowrap">{num(m.uio_low)}–{num(m.uio_high)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-600">{m.surviving_pct != null ? `${m.surviving_pct.toFixed(1)}%` : "—"}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-600">{m.avg_age != null ? `${m.avg_age.toFixed(1)} y` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
