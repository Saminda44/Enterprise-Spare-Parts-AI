import { useMemo, useState } from 'react'
import { num, str } from '../api'
import { compact, compactLkr, lkr, int, pct } from '../format'
import { useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, PillToggles, Select, Tabs } from '../components/ui'
import { Bars, Donut, Lines } from '../components/charts'

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

const CUTS: Record<Panel, { table: string; key: string; label: string }> = {
  rm: { table: 'unit_sales_by_rm', key: 'rm', label: 'Regional manager' },
  ase: { table: 'unit_sales_by_ase', key: 'ase', label: 'Area sales executive' },
  province: { table: 'unit_sales_by_province', key: 'province', label: 'Province' },
  district: { table: 'unit_sales_by_district', key: 'district', label: 'District' },
  dealer: { table: 'unit_sales_by_dealer', key: 'dealer_name', label: 'Dealer' },
}

function Overview() {
  const [model, setModel] = useState('all')
  const byModel = useTable('unit_sales_by_model', { sort: 'units', desc: true })
  const monthly = useTable('unit_sales_monthly', { sort: 'month', desc: false, limit: 1000 })

  const models = byModel.data ?? []
  const totalUnits = models.reduce((a, r) => a + num(r.units), 0)
  const totalVins = models.reduce((a, r) => a + num(r.vins), 0)
  const totalValue = models.reduce((a, r) => a + num(r.net_sales), 0)

  const modelOptions = useMemo(
    () => [{ value: 'all', label: 'All models' }, ...models.map((r) => ({ value: str(r.model_name), label: str(r.model_name) }))],
    [models],
  )

  const trend = useMemo(() => {
    const src = (monthly.data ?? []).filter((r) => model === 'all' || str(r.model_name) === model)
    const m = new Map<string, { month: string; units: number; net_sales: number }>()
    for (const r of src) {
      const k = str(r.month)
      const cur = m.get(k) ?? { month: k, units: 0, net_sales: 0 }
      cur.units += num(r.units)
      cur.net_sales += num(r.net_sales)
      m.set(k, cur)
    }
    return Array.from(m.values()).sort((a, b) => a.month.localeCompare(b.month))
  }, [monthly.data, model])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="Units sold" value={compact(totalUnits)} hint="motorcycles, this extract" tone="blue" />
        <Kpi label="Distinct VINs" value={compact(totalVins)} tone="slate" />
        <Kpi label="Retail value" value={compactLkr(totalValue)} tone="green" />
        <Kpi
          label="Average price"
          value={totalUnits ? lkr(totalValue / totalUnits) : '—'}
          tone="purple"
        />
        <Kpi label="Models" value={int(models.length)} tone="teal" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card
          title="Units by month"
          subtitle={model === 'all' ? 'all models' : model}
          className="xl:col-span-2"
          right={<Select value={model} options={modelOptions} onChange={setModel} className="w-56" />}
        >
          <Async state={monthly}>
            {() => (
              <Lines
                data={trend}
                x="month"
                series={[
                  { key: 'units', label: 'Units' },
                  { key: 'net_sales', label: 'Retail value (LKR)', color: '#2CC56F' },
                ]}
                height={280}
              />
            )}
          </Async>
          <Note>
            Unit sales feed the parc, and the parc drives spare-parts demand. This extract covers part of a
            single year, so the monthly shape is a within-year pattern, not a trend — the window is read from
            the file, never hard-coded.
          </Note>
        </Card>

        <Card title="Share of units by model">
          <Async state={byModel}>
            {(rows) => <Donut data={rows} nameKey="model_name" valueKey="units" height={280} />}
          </Async>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Card title="Units by model">
          <Async state={byModel}>
            {(rows) => (
              <Bars
                data={rows.map((r) => ({ model: str(r.model_name), units: num(r.units) }))}
                x="model"
                series={[{ key: 'units', label: 'units' }]}
                height={Math.max(240, rows.length * 28)}
                horizontal
              />
            )}
          </Async>
        </Card>
        <Card title="Model detail" subtitle="units, VINs, value and realised average price">
          <Async state={byModel}>
            {(rows) => (
              <DataTable
                rows={rows}
                filename="unit_sales_by_model"
                dense
                maxHeight="340px"
                initialSort={{ key: 'units', desc: true }}
                columns={[
                  { key: 'model_name', label: 'model' },
                  { key: 'units', align: 'right', render: (r) => int(num(r.units)) },
                  { key: 'vins', label: 'VINs', align: 'right', render: (r) => int(num(r.vins)) },
                  { key: 'net_sales', label: 'value', align: 'right', render: (r) => compactLkr(num(r.net_sales)) },
                  { key: 'avg_price', label: 'avg price', align: 'right', render: (r) => lkr(num(r.avg_price)) },
                ]}
              />
            )}
          </Async>
          <Note>
            VIN count can exceed unit count where a VIN appears on more than one line; units is the sales
            measure and VINs is the identity count, and the two are reported separately rather than
            reconciled away.
          </Note>
        </Card>
      </div>
    </>
  )
}

function CutPanel({ panel }: { panel: Panel }) {
  const cut = CUTS[panel]
  const state = useTable(cut.table, { sort: 'units', desc: true, limit: 1000 })
  const rows = state.data ?? []
  const total = rows.reduce((a, r) => a + num(r.units), 0)

  return (
    <Card title={cut.label} subtitle={`${rows.length} rows · ${compact(total)} units`}>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Async state={state}>
          {() => (
            <Bars
              data={rows.slice(0, 15).map((r) => ({ name: str(r[cut.key], '—'), units: num(r.units) }))}
              x="name"
              series={[{ key: 'units', label: 'units' }]}
              height={Math.max(220, Math.min(rows.length, 15) * 24)}
              horizontal
            />
          )}
        </Async>
        <DataTable
          rows={rows}
          filename={cut.table}
          dense
          maxHeight="340px"
          initialSort={{ key: 'units', desc: true }}
          columns={[
            { key: cut.key, label: cut.label },
            { key: 'units', align: 'right', render: (r) => int(num(r.units)) },
            { key: 'net_sales', label: 'value', align: 'right', render: (r) => compactLkr(num(r.net_sales)) },
            {
              key: 'share',
              label: 'share',
              align: 'right',
              render: (r) => (total ? pct(num(r.units) / total) : '—'),
            },
          ]}
        />
      </div>
    </Card>
  )
}

function Performance() {
  const [active, setActive] = useState<Panel[]>(['province'])
  const toggle = (id: Panel) =>
    setActive((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))
  return (
    <>
      <Card className="mb-5" title="Breakdowns" subtitle="Pick any combination — each adds a panel below">
        <PillToggles options={PANELS} active={active} onToggle={toggle} />
        <Note>
          Geography is unusable on about 3.5% of VINs, where the recorded dealer is a head-office code rather
          than the selling branch. Those rows are kept and labelled, not dropped — dropping them would quietly
          shrink the parc.
        </Note>
      </Card>
      <div className="space-y-5">
        {active.map((p) => (
          <CutPanel key={p} panel={p} />
        ))}
      </div>
    </>
  )
}

export default function UnitSales() {
  const [section, setSection] = useState<Section>('overview')
  return (
    <>
      <PageHeader
        title="MC Analysis"
        subtitle="Step 09 — motorcycle unit sales by model, month and geography. This is the input to the vehicle parc, which is what makes a spare-parts forecast something other than an extrapolation of its own history."
        right={<Tabs tabs={SECTIONS} active={section} onChange={setSection} />}
      />
      {section === 'overview' ? <Overview /> : <Performance />}
    </>
  )
}
