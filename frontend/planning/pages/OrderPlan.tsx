import { useMemo, useState } from 'react'
import { Download, X } from 'lucide-react'
import { BASE, num, str, type Page, type Row } from '../api'
import { compact, compactLkr, dec, int, lkr, pct } from '../format'
import { useEndpoint, useTable } from '../hooks'
import {
  Async,
  Badge,
  Card,
  DataTable,
  ErrorBox,
  Kpi,
  Loading,
  Note,
  PageHeader,
  Select,
  TextInput,
} from '../components/ui'
import { Bars } from '../components/charts'

interface Explain {
  active_sku_id: string
  forecast: Record<string, unknown>
  lead_time: Record<string, unknown>
  safety_stock: Record<string, unknown>
  policy: Record<string, unknown>
  inventory_position: Record<string, unknown>
  order: Record<string, unknown>
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1 border-b border-slate-100 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm text-slate-800 tabular-nums">{value}</span>
    </div>
  )
}

function ExplainPanel({ sku, onClose }: { sku: string; onClose: () => void }) {
  const state = useEndpoint<Explain>(`/parts/${encodeURIComponent(sku)}/explain`)
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white h-full overflow-y-auto shadow-xl">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-4 flex items-start justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-slate-500">Derivation</p>
            <h3 className="text-sm font-semibold text-slate-900">{sku}</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </div>
        <div className="p-5 space-y-5">
          {state.loading && <Loading />}
          {state.error && <ErrorBox message={state.error} />}
          {state.data && (
            <>
              <section>
                <p className="text-xs font-semibold text-slate-700 mb-1">1 · Forecast</p>
                <Field label="model" value={str(state.data.forecast.model)} />
                <Field label="quadrant" value={str(state.data.forecast.quadrant)} />
                <Field label="μ per month" value={dec(num(state.data.forecast.mu_month), 1)} />
                <Field label="μ over P (4 months)" value={dec(num(state.data.forecast.mu_p), 1)} />
                <Field label="σ over P" value={dec(num(state.data.forecast.sigma_p), 1)} />
                <Field label="parc-only estimate" value={state.data.forecast.parc_only ? 'yes' : 'no'} />
              </section>
              <section>
                <p className="text-xs font-semibold text-slate-700 mb-1">2 · Safety stock</p>
                <Field label="fill target" value={pct(num(state.data.safety_stock.fill_target))} />
                <Field label="z" value={dec(num(state.data.safety_stock.z), 3)} />
                <Field label="bracketing" value={dec(num(state.data.safety_stock.bracketing), 0)} />
                <Field label="normal approximation" value={dec(num(state.data.safety_stock.normal), 0)} />
                <Field label="empirical quantile" value={dec(num(state.data.safety_stock.empirical), 0)} />
                <Field
                  label="selected"
                  value={
                    <>
                      {dec(num(state.data.safety_stock.selected), 0)}{' '}
                      <Badge tone="blue">{str(state.data.safety_stock.strategy)}</Badge>
                    </>
                  }
                />
              </section>
              <section>
                <p className="text-xs font-semibold text-slate-700 mb-1">3 · Policy</p>
                <Field label="policy" value={str(state.data.policy.policy)} />
                <Field label="s (reorder point)" value={dec(num(state.data.policy.s), 0)} />
                <Field label="S (order-up-to)" value={dec(num(state.data.policy.S), 0)} />
                <Field label="reason" value={<span className="text-xs">{str(state.data.policy.trigger_reason)}</span>} />
              </section>
              <section>
                <p className="text-xs font-semibold text-slate-700 mb-1">4 · Inventory position</p>
                <Field label="on hand" value={int(num(state.data.inventory_position.on_hand))} />
                <Field label="on order" value={int(num(state.data.inventory_position.on_order))} />
                <Field label="backorders" value={int(num(state.data.inventory_position.backorders))} />
                <Field label="IP" value={int(num(state.data.inventory_position.ip))} />
              </section>
              <section>
                <p className="text-xs font-semibold text-slate-700 mb-1">5 · Order</p>
                <Field label="q raw" value={dec(num(state.data.order.q_raw), 0)} />
                <Field label="EOQ (floor only)" value={dec(num(state.data.order.eoq), 0)} />
                <Field label="after MOQ" value={dec(num(state.data.order.q_moq), 0)} />
                <Field label="after pack size" value={dec(num(state.data.order.q_pack), 0)} />
                <Field label="q final" value={<strong>{int(num(state.data.order.q_final))}</strong>} />
                <Field label="unit cost" value={lkr(num(state.data.order.unit_cost), 2)} />
                <Field label="line value" value={<strong>{lkr(num(state.data.order.value))}</strong>} />
              </section>
              <Note>
                Expected arrival {str(state.data.lead_time.expected_arrival)} on a{' '}
                {int(num(state.data.lead_time.lead_time_months))}-month lead. EOQ is a floor, never the order.
              </Note>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const ABC = [
  { value: '', label: 'All ABC' },
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'C', label: 'C' },
]

export default function OrderPlan() {
  const [abc, setAbc] = useState('')
  const [policy, setPolicy] = useState('')
  const [search, setSearch] = useState('')
  const [sku, setSku] = useState<string | null>(null)

  const policies = useTable('mart_policy_summary')
  const policyOptions = useMemo(
    () => [
      { value: '', label: 'All policies' },
      ...Array.from(new Set((policies.data ?? []).map((r) => str(r.policy)))).map((p) => ({
        value: p,
        label: p,
      })),
    ],
    [policies.data],
  )

  const proposal = useEndpoint<Page>('/orders/proposal', {
    limit: 5000,
    ...(abc ? { abc } : {}),
    ...(policy ? { policy } : {}),
  })

  const rows = useMemo(() => {
    const all = proposal.data?.rows ?? []
    if (!search.trim()) return all
    const q = search.trim().toUpperCase()
    return all.filter(
      (r) => str(r.active_sku_id).toUpperCase().includes(q) || str(r.description).toUpperCase().includes(q),
    )
  }, [proposal.data, search])

  const totalValue = rows.reduce((a, r) => a + num(r.value), 0)
  const totalUnits = rows.reduce((a, r) => a + num(r.q_final), 0)
  const onOrderZero = rows.length > 0 && rows.every((r) => num(r.on_order) === 0)

  const byReason = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) {
      const key = str(r.trigger_reason).startsWith('review cycle')
        ? 'review cycle (R,S)'
        : str(r.trigger_reason).includes('at or below')
          ? 'below reorder point (R,s,S)'
          : str(r.trigger_reason).slice(0, 40) || 'other'
      m.set(key, (m.get(key) ?? 0) + num(r.value))
    }
    return Array.from(m, ([reason, value]) => ({ reason, value: value / 1e6 })).sort((a, b) => b.value - a.value)
  }, [rows])

  const cycle = str(rows[0]?.cycle_month, '—')

  return (
    <>
      <PageHeader
        title="Monthly Order Proposal"
        subtitle="Step 14. One line per SKU that triggered this cycle, each carrying the reason it triggered. This is a recommendation — no endpoint sends it to SAP."
        right={
          <a
            href={`${BASE}/orders/proposal.csv`}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-blue text-white px-4 py-2 text-sm hover:bg-brand-blue/90"
          >
            <Download size={15} /> Download full cycle CSV
          </a>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Cycle" value={cycle} hint="cycle_month on every line" tone="slate" />
        <Kpi label="Lines" value={int(rows.length)} hint={`of ${int(num(proposal.data?.total))} in this cycle`} />
        <Kpi label="Order value" value={compactLkr(totalValue)} tone="green" />
        <Kpi label="Units" value={compact(totalUnits)} tone="purple" />
      </div>

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Select label="ABC class" value={abc} options={ABC} onChange={setAbc} className="w-36" />
          <Select label="Policy" value={policy} options={policyOptions} onChange={setPolicy} className="w-44" />
          <TextInput
            label="Search part or description"
            value={search}
            onChange={setSearch}
            placeholder="e.g. SPARK or 94701"
            className="w-72"
          />
          <div className="ml-auto text-xs text-slate-500">
            Click any row to see how its quantity was derived.
          </div>
        </div>
      </Card>

      {onOrderZero && (
        <div className="mb-5">
          <ErrorBox
            message={
              'Every line shows on_order = 0. The On_Orders months carry no year and no arrival flag, so ' +
              'inventory position collapses to on-hand and these quantities are overstated. Confirm the ' +
              'On_Orders interpretation before placing this order.'
            }
          />
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="Order value by trigger" subtitle="LKR M" className="xl:col-span-1">
          <Bars data={byReason} x="reason" series={[{ key: 'value', label: 'LKR M' }]} height={220} horizontal />
        </Card>
        <Card title="Proposal lines" subtitle="sorted by line value" className="xl:col-span-2">
          <Async state={proposal}>
            {() => (
              <DataTable
                rows={rows}
                filename={`monthly_order_${cycle}`}
                maxHeight="560px"
                dense
                initialSort={{ key: 'value', desc: true }}
                columns={[
                  {
                    key: 'active_sku_id',
                    label: 'SKU',
                    render: (r: Row) => (
                      <button
                        onClick={() => setSku(str(r.active_sku_id))}
                        className="text-brand-blue hover:underline font-medium"
                      >
                        {str(r.active_sku_id)}
                      </button>
                    ),
                  },
                  { key: 'description' },
                  { key: 'abc_class', label: 'ABC' },
                  { key: 'policy' },
                  { key: 'ip', label: 'IP', align: 'right', render: (r) => int(num(r.ip)) },
                  { key: 'rol', label: 'ROL', align: 'right', render: (r) => int(num(r.rol)) },
                  { key: 'S', label: 'S', align: 'right', render: (r) => int(num(r.S)) },
                  { key: 'ss', label: 'SS', align: 'right', render: (r) => int(num(r.ss)) },
                  { key: 'q_final', label: 'ROQ', align: 'right', render: (r) => int(num(r.q_final)) },
                  { key: 'value', label: 'value', align: 'right', render: (r) => compactLkr(num(r.value)) },
                  { key: 'expected_arrival', label: 'arrival' },
                  { key: 'trigger_reason', label: 'reason' },
                ]}
              />
            )}
          </Async>
        </Card>
      </div>

      {sku && <ExplainPanel sku={sku} onClose={() => setSku(null)} />}
    </>
  )
}
