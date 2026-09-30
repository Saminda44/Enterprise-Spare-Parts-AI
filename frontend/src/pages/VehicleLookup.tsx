import { useEffect, useState } from "react";
import { Search, Bike, Receipt, MapPin, AlertTriangle } from "lucide-react";
import { fetchVehicleSearch, fetchVehicleDetail, type VehicleSearch, type VehicleDetail } from "../api/client";

const lkr = (n: number | null | undefined) => (n == null ? "—" : `LKR ${Math.round(n).toLocaleString()}`);
const STATUS_TONE: Record<string, string> = {
  sold: "bg-green-100 text-green-700", returned: "bg-red-100 text-red-700", unknown: "bg-slate-100 text-slate-500",
};

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className={`text-sm text-slate-800 ${mono ? "font-mono" : ""}`}>{value ?? "—"}</dd>
    </div>
  );
}

function Card({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
      <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2"><Icon size={15} className="text-brand-blue"/>{title}</h3>
      {children}
    </div>
  );
}

export function VehicleLookup() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<VehicleSearch | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<VehicleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (query.replace(/[^A-Za-z0-9]/g, "").length < 4) { setResults(null); return; }
      fetchVehicleSearch(query).then(r => {
        setResults(r);
        // One exact hit: open it straight away.
        if (r.rows.length === 1) setSelected(r.rows[0].vin);
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    setError(null);
    fetchVehicleDetail(selected).then(setDetail).catch(() => { setDetail(null); setError("Could not load this chassis number."); });
  }, [selected]);

  const d = detail;
  return (
    <div className="flex-1 p-6 space-y-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Vehicle Lookup</h2>
        <p className="text-xs text-slate-500 mt-1">
          Search a motorcycle by <b>chassis number (VIN)</b> or <b>batch number</b> — full or partial. Everything MCSI records about
          that bike and its model.
        </p>
      </div>

      <div className="bg-white rounded-xl shadow-sm p-5 space-y-3">
        <div className="relative max-w-xl mx-auto">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"/>
          <input autoFocus value={query} onChange={e => { setQuery(e.target.value); setSelected(null); }}
            placeholder="Chassis (e.g. last 6 characters of the VIN) or batch number…"
            className="w-full border border-slate-200 rounded-lg pl-9 pr-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-blue/30"/>
        </div>
        <p className="text-[11px] text-amber-700 flex items-center justify-center gap-1.5 text-center">
          <AlertTriangle size={12}/> Vehicle registration numbers are not in any supplied file (MCSI, orders or Sales Summery), so
          searching by vehicle number isn't possible yet. Supply a chassis-to-registration list and it can be added.
        </p>
        {results && (
          results.total === 0 ? (
            <p className="text-sm text-slate-500">No bike matches “{results.query}”.</p>
          ) : results.total > 1 && (
            <div className="overflow-x-auto">
              <p className="text-xs text-slate-500 mb-2">{results.total.toLocaleString()} matches{results.total > results.rows.length ? ` — showing the first ${results.rows.length}; type more characters to narrow it` : ""}</p>
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr className="text-left text-[11px] uppercase text-slate-500">
                    <th className="py-2 px-3">Chassis (VIN)</th><th className="py-2 pr-3">Batch</th><th className="py-2 pr-3">Model</th>
                    <th className="py-2 pr-3">Colour</th><th className="py-2 pr-3">Billed</th><th className="py-2 pr-3">Dealer</th><th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {results.rows.map(r => (
                    <tr key={r.vin} onClick={() => setSelected(r.vin)}
                      className={`cursor-pointer border-b border-slate-100 ${selected === r.vin ? "bg-blue-50" : "hover:bg-slate-50"}`}>
                      <td className="py-2 px-3 font-mono text-xs">{r.vin}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-slate-500">{r.batch}</td>
                      <td className="py-2 pr-3">{r.model}</td>
                      <td className="py-2 pr-3 text-slate-600">{r.colour}</td>
                      <td className="py-2 pr-3 text-slate-600 whitespace-nowrap">{r.first_billed}</td>
                      <td className="py-2 pr-3 text-slate-600">{r.dealer_name}</td>
                      <td className="py-2"><span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_TONE[r.status] ?? STATUS_TONE.unknown}`}>{r.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {d && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl shadow-sm p-5 flex flex-wrap items-center gap-4">
            <Bike size={28} className="text-brand-blue"/>
            <div className="flex-1 min-w-[260px]">
              <p className="font-mono text-lg font-bold text-slate-800">{d.vin}</p>
              <p className="text-sm text-slate-600">{d.identity.model} · {d.identity.colour} · {d.identity.motorcycle_type}{d.identity.cc ? ` · ${d.identity.cc} cc` : ""}</p>
            </div>
            <span className={`text-sm px-3 py-1 rounded-full font-medium ${STATUS_TONE[d.identity.status] ?? STATUS_TONE.unknown}`}>{d.identity.status}</span>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card title="The bike" icon={Bike}>
              <dl className="grid grid-cols-2 gap-3">
                <Field label="Chassis (VIN)" value={d.vin} mono/>
                <Field label="Batch number" value={d.identity.batch} mono/>
                <Field label="Model" value={d.identity.model}/>
                <Field label="Colour" value={d.identity.colour}/>
                <Field label="Type" value={d.identity.motorcycle_type}/>
                <Field label="Segment" value={d.identity.segment}/>
                <Field label="Age" value={d.identity.age_months != null ? `${d.identity.age_months} months since billing` : "—"}/>
                <Field label="Status" value={d.identity.status}/>
              </dl>
            </Card>
            <Card title="The sale" icon={Receipt}>
              <dl className="grid grid-cols-2 gap-3">
                <Field label="Billed" value={d.sale.first_billed === d.sale.last_billed ? d.sale.first_billed : `${d.sale.first_billed} → ${d.sale.last_billed}`}/>
                <Field label="Net price paid" value={lkr(d.sale.net_sales)}/>
                <Field label="Model list price" value={lkr(d.sale.list_price)}/>
                <Field label="Below list" value={d.sale.discount_vs_list != null && d.sale.discount_vs_list > 1 ? lkr(d.sale.discount_vs_list) : "none"}/>
                <Field label="Buyer age at purchase" value={d.sale.age_at_purchase != null ? `${d.sale.age_at_purchase}` : "not recorded"}/>
                <Field label="Buyer age today" value={d.sale.age_today != null ? `${d.sale.age_today}` : "not recorded"}/>
                <Field label="Customer ID" value={d.sale.customer_id} mono/>
              </dl>
            </Card>
            <Card title="Dealer & area" icon={MapPin}>
              <dl className="grid grid-cols-2 gap-3">
                <Field label="Dealer" value={d.sale.dealer_name}/>
                <Field label="Dealer code" value={d.sale.dealer_code} mono/>
                <Field label="Province" value={d.sale.province}/>
                <Field label="District" value={d.sale.district}/>
                <Field label="RM" value={d.sale.rm}/>
                <Field label="ASE" value={d.sale.ase}/>
              </dl>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card title="Its model in context" icon={Bike}>
              <dl className="grid grid-cols-2 gap-3">
                <Field label="Bikes of this model sold" value={d.model_context.bikes_sold.toLocaleString()}/>
                <Field label="Same model & colour" value={d.model_context.same_colour_sold.toLocaleString()}/>
                <Field label="This dealer, this model" value={d.model_context.dealer_bikes_of_model.toLocaleString()}/>
                <Field label="Model fleet in operation" value={d.model_context.fleet_in_operation != null ? Math.round(d.model_context.fleet_in_operation).toLocaleString() : "—"}/>
                <Field label="Registered since 2014" value={d.model_context.fleet_registered != null ? Math.round(d.model_context.fleet_registered).toLocaleString() : "—"}/>
                <Field label="Still running" value={d.model_context.fleet_surviving_pct != null ? `${d.model_context.fleet_surviving_pct.toFixed(1)}%` : "—"}/>
              </dl>
            </Card>
            <div className="lg:col-span-2">
              <Card title={`Billing history — ${d.billing.length} line${d.billing.length === 1 ? "" : "s"}`} icon={Receipt}>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                      <tr className="text-left text-[11px] uppercase text-slate-500">
                        <th className="py-2 px-3">Date</th><th className="py-2 pr-3">Document</th><th className="py-2 pr-3">Type</th>
                        <th className="py-2 pr-3 text-right">Qty</th><th className="py-2 pr-3 text-right">Price</th>
                        <th className="py-2 pr-3 text-right">Discount</th><th className="py-2 pr-3 text-right">Net</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.billing.map((b, i) => (
                        <tr key={i} className={`border-b border-slate-100 ${b.quantity < 0 ? "text-red-600" : ""}`}>
                          <td className="py-1.5 px-3 whitespace-nowrap">{b.date}</td>
                          <td className="py-1.5 pr-3 font-mono text-xs">{b.document}</td>
                          <td className="py-1.5 pr-3">{b.bill_type}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums">{b.quantity}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(b.sales_price).toLocaleString()}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums">{Math.round(b.discount).toLocaleString()}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums font-semibold">{Math.round(b.net_sales).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.billing.length > 1 && <p className="text-[11px] text-slate-400 mt-2">Negative quantities are reversals; the bike's status counts the net.</p>}
                </div>
              </Card>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
