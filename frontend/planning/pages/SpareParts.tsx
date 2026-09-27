import { useMemo, useState } from 'react'
import { num, str, type Row } from '../api'
import { compact, compactLkr, dec, int, pct } from '../format'
import { useTable } from '../hooks'
import {
  Async,
  Card,
  DataTable,
  Kpi,
  Note,
  PageHeader,
  PillToggles,
  Select,
  Tabs,
  TextInput,
} from '../components/ui'
import { Bars, Donut, Lines } from '../components/charts'

const SOURCES = [
  { id: 'orders', label: 'Orders (demand)' },
  { id: 'sales', label: 'Sales (billed)' },
  { id: 'supply', label: 'Supply & lead time' },
] as const
type Source = (typeof SOURCES)[number]['id']

const SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'performance', label: 'Performance' },
] as const
type Section = (typeof SECTIONS)[number]['id']

const PANELS = [
  { id: 'rm', label: 'RM' },
  { id: 'ase', label: 'ASE' },
  { id: 'province', label: 'Province' },
  { id: 'district', label: 'District' },
  { id: 'dealer', label: 'Dealer' },
] as const
type Panel = (typeof PANELS)[number]['id']

const CATEGORIES = [
  'MC Spare Parts',
  'Lubricant',
  'Battery',
  'Tyre',
  'OBM Spare Parts',
] as const

/* ------------------------------------------------------------------ orders */

function OrdersOverview() {
  const [dealerType, setDealerType] = useState('all')
  const [category, setCategory] = useState('all')

  const fulfil = useTable('fulfilment_stats')
  const po = useTable('fulfilment_by_po', { limit: 20000 })
  const materials = useTable('orders_by_material', { sort: 'order_value', desc: true, limit: 5000 })
  const monthly = useTable('supply_reliability_monthly', { sort: 'month', desc: false, limit: 1000 })
  const returns = useTable('returns_summary')

  // Dealer Type is what splits the categories: MC carries Lubricant / Battery / Tyre /
  // MC Spare Parts, OBM carries OBM Spare Parts. Selecting a type narrows the list below.
  const availableCategories = useMemo(() => {
    if (dealerType === 'MC') return CATEGORIES.filter((c) => c !== 'OBM Spare Parts')
    if (dealerType === 'OBM') return ['OBM Spare Parts']
    return [...CATEGORIES]
  }, [dealerType])

  const effectiveCategory = availableCategories.includes(category) ? category : 'all'

  const monthlyRows = useMemo(() => {
    const src = (monthly.data ?? []).filter((r) => {
      const c = str(r.material_category)
      if (effectiveCategory !== 'all') return c === effectiveCategory
      return availableCategories.includes(c)
    })
    const m = new Map<string, { month: string; ordered: number; confirmed: number }>()
    for (const r of src) {
      const k = str(r.month)
      const cur = m.get(k) ?? { month: k, ordered: 0, confirmed: 0 }
      cur.ordered += num(r.ordered_quantity)
      cur.confirmed += num(r.confirmed_quantity)
      m.set(k, cur)
    }
    return Array.from(m.values())
      .sort((a, b) => a.month.localeCompare(b.month))
      .map((r) => ({ ...r, lost: r.ordered - r.confirmed }))
  }, [monthly.data, effectiveCategory, availableCategories])

  const ordered = (fulfil.data ?? []).reduce((a, r) => a + num(r.ordered_quantity), 0)
  const confirmed = (fulfil.data ?? []).reduce((a, r) => a + num(r.confirmed_quantity), 0)
  const lost = (fulfil.data ?? []).reduce((a, r) => a + num(r.lost_quantity), 0)
  const lines = (fulfil.data ?? []).reduce((a, r) => a + num(r.lines), 0)

  const orderValue = (materials.data ?? []).reduce((a, r) => a + num(r.order_value), 0)

  const poMix = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of po.data ?? []) m.set(str(r.po_class), (m.get(str(r.po_class)) ?? 0) + 1)
    return Array.from(m, ([po_class, orders]) => ({ po_class, orders }))
  }, [po.data])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-5">
        <Kpi label="Order lines" value={compact(lines)} hint="SD category C only" tone="blue" />
        <Kpi label="Ordered qty" value={compact(ordered)} tone="slate" />
        <Kpi label="Confirmed qty" value={compact(confirmed)} tone="green" />
        <Kpi label="Lost qty" value={compact(lost)} hint="ordered − confirmed, measured" tone="red" />
        <Kpi label="Fill rate" value={ordered ? pct(confirmed / ordered) : '—'} tone="purple" />
        <Kpi label="Order value" value={compactLkr(orderValue)} tone="teal" />
      </div>

      <Card className="mb-5" title="Category cascade" subtitle="Dealer type first, then the material category it carries">
        <div className="flex flex-wrap items-end gap-4">
          <Select
            label="Dealer type"
            value={dealerType}
            options={[
              { value: 'all', label: 'All dealer types' },
              { value: 'MC', label: 'MC' },
              { value: 'OBM', label: 'OBM' },
            ]}
            onChange={(v) => {
              setDealerType(v)
              setCategory('all')
            }}
            className="w-48"
          />
          <Select
            label="Material category"
            value={effectiveCategory}
            options={[
              { value: 'all', label: 'All categories' },
              ...availableCategories.map((c) => ({ value: c, label: c })),
            ]}
            onChange={setCategory}
            className="w-56"
          />
          <Note>
            The category is derived from the description on an MC line — <code>YAMALUBE</code> → Lubricant,{' '}
            <code>KARATE BATTERY</code> → Battery, <code>KATANA TYRE</code> → Tyre, otherwise MC Spare Parts.
            An OBM dealer line is always OBM Spare Parts.
          </Note>
        </div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card
          title="Ordered vs confirmed by month"
          subtitle={effectiveCategory === 'all' ? 'all selected categories' : effectiveCategory}
          className="xl:col-span-2"
        >
          <Async state={monthly}>
            {() => (
              <Lines
                data={monthlyRows}
                x="month"
                series={[
                  { key: 'ordered', label: 'Ordered' },
                  { key: 'confirmed', label: 'Confirmed', color: '#2CC56F' },
                  { key: 'lost', label: 'Lost', color: '#EF4444' },
                ]}
                height={280}
              />
            )}
          </Async>
          <Note>
            Demand is the ordered quantity, not the confirmed quantity. Lost sales are measured as{' '}
            <code>Order Quantity − Confirmed Quantity</code>, never inferred — treating confirmed as demand
            would bake today's stockouts into tomorrow's forecast.
          </Note>
        </Card>

        <div className="space-y-5">
          <Card title="Lines by fulfilment class">
            <Async state={fulfil}>
              {(rows) => <Donut data={rows} nameKey="fulfilment_class" valueKey="lines" height={210} />}
            </Async>
          </Card>
          <Card title="Purchase orders by class" subtitle={`${int(num(po.data?.length))} POs read`}>
            <Async state={po}>
              {() => <Bars data={poMix} x="po_class" series={[{ key: 'orders', label: 'POs' }]} height={200} />}
            </Async>
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <Card title="Returns" subtitle="SD document category H" className="xl:col-span-1">
          <Async state={returns}>
            {(rows) => {
              const r = rows[0] ?? {}
              return (
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Return lines</span>
                    <span className="tabular-nums">{int(num(r.return_lines))}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Return invoices</span>
                    <span className="tabular-nums">{int(num(r.return_invoices))}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Return quantity</span>
                    <span className="tabular-nums">{int(num(r.return_quantity))}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Return value</span>
                    <span className="tabular-nums">{compactLkr(num(r.return_value))}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">SKUs returned</span>
                    <span className="tabular-nums">{int(num(r.unique_skus_returned))}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Return rate (lines)</span>
                    <span className="tabular-nums">{pct(num(r.return_rate_lines), 2)}</span>
                  </div>
                </div>
              )
            }}
          </Async>
          <Note>
            Returns are held apart from demand. The C set is demand; H is a return and is reported, never
            netted into the forecast input.
          </Note>
        </Card>

        <Card title="Demand by part" subtitle="aggregated on active_sku_id" className="xl:col-span-2">
          <Async state={materials}>
            {(rows) => (
              <DataTable
                rows={rows}
                filename="orders_by_material"
                maxHeight="400px"
                dense
                initialSort={{ key: 'order_value', desc: true }}
                columns={[
                  { key: 'active_sku_id', label: 'SKU' },
                  { key: 'order_lines', label: 'lines', align: 'right' },
                  { key: 'ordered_quantity', label: 'ordered', align: 'right', render: (r) => int(num(r.ordered_quantity)) },
                  { key: 'confirmed_quantity', label: 'confirmed', align: 'right', render: (r) => int(num(r.confirmed_quantity)) },
                  { key: 'lost_quantity', label: 'lost', align: 'right', render: (r) => int(num(r.lost_quantity)) },
                  { key: 'order_value', label: 'value', align: 'right', render: (r) => compactLkr(num(r.order_value)) },
                  { key: 'fill_rate', label: 'fill', align: 'right', render: (r) => pct(num(r.fill_rate)) },
                ]}
              />
            )}
          </Async>
          <Note>
            One identity per part: rows are aggregated on <code>active_sku_id</code>, which resolves the
            supersession chain. Aggregating on the raw material number splits one physical part's demand
            across its old and new numbers and understates every forecast.
          </Note>
        </Card>
      </div>
    </>
  )
}

const ORDER_CUTS: Record<Panel, { table: string; key: string; label: string }> = {
  rm: { table: 'orders_by_rm', key: 'RM', label: 'Regional manager' },
  ase: { table: 'orders_by_ase', key: 'ASE', label: 'Area sales executive' },
  province: { table: 'orders_by_province', key: 'Province', label: 'Province' },
  district: { table: 'orders_by_district', key: 'District', label: 'District' },
  dealer: { table: 'orders_by_dealer', key: 'Sold-To Party Name', label: 'Dealer' },
}

const SALES_CUTS: Record<Panel, { table: string; key: string; label: string }> = {
  rm: { table: 'sales_by_rm', key: 'RM', label: 'Regional manager' },
  ase: { table: 'sales_by_ase', key: 'ASE', label: 'Area sales executive' },
  province: { table: 'sales_by_province', key: 'Province', label: 'Province' },
  district: { table: 'sales_by_district', key: 'District', label: 'District' },
  dealer: { table: 'sales_by_dealer', key: 'payer_name', label: 'Dealer' },
}

function OrdersPanel({ panel }: { panel: Panel }) {
  const cut = ORDER_CUTS[panel]
  const state = useTable(cut.table, { sort: 'order_value', desc: true, limit: 1000 })
  const rows = state.data ?? []
  const top = rows.slice(0, 15)
  return (
    <Card title={cut.label} subtitle={`${rows.length} rows · ordered, lost and fill rate`}>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div>
          <Bars
            data={top.map((r) => ({
              name: str(r[cut.key], '—'),
              value: num(r.order_value) / 1e6,
            }))}
            x="name"
            series={[{ key: 'value', label: 'order value (LKR M)' }]}
            height={Math.max(220, top.length * 22)}
            horizontal
          />
        </div>
        <div>
          <DataTable
            rows={rows}
            filename={cut.table}
            maxHeight="360px"
            dense
            initialSort={{ key: 'order_value', desc: true }}
            columns={[
              { key: cut.key, label: cut.label },
              { key: 'order_lines', label: 'lines', align: 'right' },
              { key: 'ordered_quantity', label: 'ordered', align: 'right', render: (r) => int(num(r.ordered_quantity)) },
              { key: 'lost_quantity', label: 'lost', align: 'right', render: (r) => int(num(r.lost_quantity)) },
              { key: 'order_value', label: 'value', align: 'right', render: (r) => compactLkr(num(r.order_value)) },
              { key: 'fill_rate', label: 'fill', align: 'right', render: (r) => pct(num(r.fill_rate)) },
            ]}
          />
        </div>
      </div>
    </Card>
  )
}

function SalesPanel({ panel }: { panel: Panel }) {
  const cut = SALES_CUTS[panel]
  const state = useTable(cut.table, { sort: 'net_sales', desc: true, limit: 1000 })
  const rows = state.data ?? []
  const top = rows.slice(0, 15)
  return (
    <Card title={cut.label} subtitle={`${rows.length} rows · billed revenue and margin`}>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div>
          <Bars
            data={top.map((r) => ({
              name: str(r[cut.key], '—'),
              net: num(r.net_sales) / 1e6,
              margin: num(r.margin) / 1e6,
            }))}
            x="name"
            series={[
              { key: 'net', label: 'net sales (LKR M)' },
              { key: 'margin', label: 'margin (LKR M)', color: '#2CC56F' },
            ]}
            height={Math.max(220, top.length * 26)}
            horizontal
          />
        </div>
        <div>
          <DataTable
            rows={rows}
            filename={cut.table}
            maxHeight="360px"
            dense
            initialSort={{ key: 'net_sales', desc: true }}
            columns={[
              { key: cut.key, label: cut.label },
              { key: 'lines', align: 'right' },
              { key: 'quantity', align: 'right', render: (r) => int(num(r.quantity)) },
              { key: 'net_sales', label: 'net sales', align: 'right', render: (r) => compactLkr(num(r.net_sales)) },
              { key: 'margin', align: 'right', render: (r) => compactLkr(num(r.margin)) },
              {
                key: 'margin_pct',
                label: 'margin %',
                align: 'right',
                render: (r: Row) => (num(r.net_sales) ? pct(num(r.margin) / num(r.net_sales)) : '—'),
              },
            ]}
          />
        </div>
      </div>
    </Card>
  )
}

function Performance({ source }: { source: 'orders' | 'sales' }) {
  const [active, setActive] = useState<Panel[]>(['rm'])
  const toggle = (id: Panel) =>
    setActive((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  return (
    <>
      <Card className="mb-5" title="Breakdowns" subtitle="Pick any combination — each adds a panel below">
        <PillToggles options={PANELS} active={active} onToggle={toggle} />
      </Card>
      {active.length === 0 && (
        <Card>
          <p className="text-sm text-slate-500 text-center py-6">Select at least one breakdown above.</p>
        </Card>
      )}
      <div className="space-y-5">
        {active.map((p) =>
          source === 'orders' ? <OrdersPanel key={p} panel={p} /> : <SalesPanel key={p} panel={p} />,
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------- sales */

function SalesOverview() {
  const [search, setSearch] = useState('')
  const kpis = useTable('sales_kpis')
  const monthly = useTable('sales_monthly', { sort: 'month', desc: false })
  const materials = useTable('sales_by_material', { sort: 'net_sales', desc: true, limit: 20000 })

  const k = kpis.data?.[0] ?? {}
  const net = num(k.total_net_sales)
  const margin = num(k.total_margin)

  const rows = useMemo(() => {
    const all = materials.data ?? []
    if (!search.trim()) return all
    const q = search.trim().toUpperCase()
    return all.filter((r) => str(r.material_description).toUpperCase().includes(q))
  }, [materials.data, search])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-5">
        <Kpi label="Invoices" value={compact(num(k.total_invoices))} tone="blue" />
        <Kpi label="Lines" value={compact(num(k.total_lines))} tone="slate" />
        <Kpi label="Quantity" value={compact(num(k.total_quantity))} tone="purple" />
        <Kpi label="Net sales" value={compactLkr(net)} tone="green" />
        <Kpi label="Margin" value={compactLkr(margin)} hint={net ? `${pct(margin / net)} of net sales` : undefined} tone="teal" />
        <Kpi label="Return lines" value={compact(num(k.returns))} tone="red" />
      </div>

      <Card className="mb-5" title="Billed revenue and margin by month" subtitle="LKR">
        <Async state={monthly}>
          {(m) => (
            <Lines
              data={m.map((r) => ({ month: r.month, net_sales: num(r.net_sales), margin: num(r.margin) }))}
              x="month"
              series={[
                { key: 'net_sales', label: 'Net sales' },
                { key: 'margin', label: 'Margin', color: '#2CC56F' },
              ]}
              height={280}
            />
          )}
        </Async>
        <Note>
          Revenue is <code>Sales Pric + Discount</code>, with <code>Discount</code> stored negative; margin is
          that less <code>Cost</code>. This export ships two columns headed "Net Sales" — the one used here is
          picked by testing that identity{k.net_sales_column ? ` (resolved to ${str(k.net_sales_column)})` : ''}
          , because the other is net of Surcharge and turns revenue negative.
        </Note>
      </Card>

      <Card title="Billed sales by material" subtitle="keyed on description — this vintage carries no part number in sales">
        <div className="mb-3">
          <TextInput label="Search description" value={search} onChange={setSearch} className="w-80" />
        </div>
        <Async state={materials}>
          {() => (
            <DataTable
              rows={rows}
              filename="sales_by_material"
              maxHeight="440px"
              dense
              initialSort={{ key: 'net_sales', desc: true }}
              columns={[
                { key: 'material_description', label: 'description' },
                { key: 'lines', align: 'right' },
                { key: 'quantity', align: 'right', render: (r) => int(num(r.quantity)) },
                { key: 'net_sales', label: 'net sales', align: 'right', render: (r) => compactLkr(num(r.net_sales)) },
                { key: 'margin', align: 'right', render: (r) => compactLkr(num(r.margin)) },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

/* ------------------------------------------------------------------ supply */

function Supply() {
  const beta = useTable('supply_reliability', { sort: 'ordered_quantity', desc: true, limit: 20000 })
  const monthly = useTable('supply_reliability_monthly', { sort: 'month', desc: false, limit: 1000 })
  const lead = useTable('lead_time_stats')

  const rows = beta.data ?? []
  const shrunk = rows.filter((r) => r.shrunk === true).length

  const histogram = useMemo(() => {
    const bins = Array.from({ length: 10 }, (_, i) => ({
      bin: `${(i / 10).toFixed(1)}–${((i + 1) / 10).toFixed(1)}`,
      skus: 0,
    }))
    for (const r of rows) {
      const b = Math.min(9, Math.max(0, Math.floor(num(r.beta_hat) * 10)))
      bins[b].skus += 1
    }
    return bins
  }, [rows])

  const byCategory = useMemo(() => {
    const months = Array.from(new Set((monthly.data ?? []).map((r) => str(r.month)))).sort()
    return months.map((month) => {
      const out: Record<string, unknown> = { month }
      for (const c of CATEGORIES) {
        const hit = (monthly.data ?? []).find((r) => str(r.month) === month && str(r.material_category) === c)
        if (hit) out[c] = num(hit.beta_hat)
      }
      return out
    })
  }, [monthly.data])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="SKUs with β̂" value={int(rows.length)} tone="blue" />
        <Kpi label="Shrunk toward the pool" value={int(shrunk)} hint="thin history, borrowed strength" tone="amber" />
        {(lead.data ?? []).map((r) => (
          <Kpi
            key={str(r.scope)}
            label={`Lead time · ${str(r.scope)}`}
            value={`${dec(num(r.mean_days), 1)} d`}
            hint={str(r.source)}
            tone={str(r.scope) === 'REPLENISHMENT' ? 'red' : 'slate'}
          />
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
        <Card title="Supply reliability β̂" subtitle="confirmed ÷ ordered, shrunk toward the category pool">
          <Async state={beta}>
            {() => <Bars data={histogram} x="bin" series={[{ key: 'skus', label: 'SKUs' }]} height={260} />}
          </Async>
          <Note>
            β̂ measures how much of what is ordered actually arrives. It is reported here, but{' '}
            <strong>supply inflation (q ÷ β̂) is off by default</strong> — inflating the order because the
            supplier short-ships is a feedback loop that inflates again next cycle.
          </Note>
        </Card>

        <Card title="β̂ by month and category">
          <Async state={monthly}>
            {() => (
              <Lines
                data={byCategory}
                x="month"
                series={CATEGORIES.map((c) => ({ key: c, label: c }))}
                height={260}
              />
            )}
          </Async>
        </Card>
      </div>

      <Card title="Lead time, as measured" subtitle="Step 05">
        <Async state={lead}>
          {(rows2) => (
            <DataTable
              rows={rows2}
              dense
              columns={[
                { key: 'scope' },
                { key: 'source' },
                { key: 'mean_days', align: 'right', render: (r) => dec(num(r.mean_days), 2) },
                { key: 'std_days', align: 'right', render: (r) => dec(num(r.std_days), 2) },
                { key: 'p50_days', align: 'right', render: (r) => dec(num(r.p50_days), 1) },
                { key: 'p90_days', align: 'right', render: (r) => dec(num(r.p90_days), 1) },
                { key: 'lines', align: 'right' },
                { key: 'usable_share', align: 'right', render: (r) => pct(num(r.usable_share)) },
              ]}
            />
          )}
        </Async>
        <Note>
          <code>Delivery − Document</code> measures dealer dispatch, not the three-month import lead from
          India. It is the wrong clock for replenishment, so σ_L is unknown and safety stock understates the
          true lead-time risk. The replenishment row is a planning assumption, flagged as such.
        </Note>
      </Card>
    </>
  )
}

/* -------------------------------------------------------------------- page */

export default function SpareParts() {
  const [source, setSource] = useState<Source>('orders')
  const [section, setSection] = useState<Section>('overview')

  return (
    <>
      <PageHeader
        title="Spare Parts Analysis"
        subtitle="Steps 03, 04 and 05 — ordered demand, billed sales and the supply behaviour between them. Demand is what dealers ordered; billed sales is what was invoiced. They are different measures and are never mixed."
        right={<Tabs tabs={SOURCES} active={source} onChange={setSource} />}
      />

      {source !== 'supply' && (
        <div className="mb-5">
          <Tabs tabs={SECTIONS} active={section} onChange={setSection} />
        </div>
      )}

      {source === 'orders' && section === 'overview' && <OrdersOverview />}
      {source === 'orders' && section === 'performance' && <Performance source="orders" />}
      {source === 'sales' && section === 'overview' && <SalesOverview />}
      {source === 'sales' && section === 'performance' && <Performance source="sales" />}
      {source === 'supply' && <Supply />}
    </>
  )
}
