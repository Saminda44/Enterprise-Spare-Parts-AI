import { useMemo, useState } from 'react'
import { num, str, type Page } from '../api'
import { compact, dec, int, pct } from '../format'
import { useEndpoint, useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, Select, Tabs } from '../components/ui'
import { Areas, Bars, Lines } from '../components/charts'

const TABS = [
  { id: 'age', label: 'Age profile' },
  { id: 'scenarios', label: 'Scenarios' },
  { id: 'survival', label: 'Survival' },
  { id: 'explorer', label: 'UIO explorer' },
] as const
type Tab = (typeof TABS)[number]['id']

/** Age buckets read "0-1", "10-11" — sort on the lower bound, not as text. */
function bucketOrder(bucket: string): number {
  const first = Number.parseInt(bucket.split(/[^0-9]/)[0] ?? '', 10)
  return Number.isFinite(first) ? first : 999
}

function AgeProfile() {
  const hist = useTable('uio_age_histogram', { limit: 200 })
  // The age matrix stacks all three survival scenarios, so an unfiltered sum counts the
  // fleet three times over. The base arm is the centre case.
  const matrix = useTable('uio_age_matrix', { where: 'scenario=base', limit: 20000 })

  const rows = useMemo(
    () =>
      (hist.data ?? [])
        .map((r) => ({ age_bucket: str(r.age_bucket), units: num(r.units) }))
        .sort((a, b) => bucketOrder(a.age_bucket) - bucketOrder(b.age_bucket)),
    [hist.data],
  )

  const total = rows.reduce((a, r) => a + r.units, 0)
  const young = rows.filter((r) => bucketOrder(r.age_bucket) <= 2).reduce((a, r) => a + r.units, 0)
  const hole = rows.filter((r) => bucketOrder(r.age_bucket) >= 3 && bucketOrder(r.age_bucket) <= 5)
  const holeUnits = hole.reduce((a, r) => a + r.units, 0)

  const byYear = useMemo(() => {
    const m = new Map<number, { year: number; units: number; forecast: number }>()
    for (const r of matrix.data ?? []) {
      const y = num(r.year)
      const cur = m.get(y) ?? { year: y, units: 0, forecast: 0 }
      if (r.is_forecast === true) cur.forecast += num(r.units)
      else cur.units += num(r.units)
      m.set(y, cur)
    }
    return Array.from(m.values()).sort((a, b) => a.year - b.year)
  }, [matrix.data])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Units in operation" value={compact(total)} hint="across all age buckets" tone="blue" />
        <Kpi label="Aged 0–2 years" value={compact(young)} hint={total ? pct(young / total) : undefined} tone="green" />
        <Kpi
          label="Aged 3–5 years"
          value={compact(holeUnits)}
          hint="the import-ban hole"
          tone="red"
        />
        <Kpi label="Cohort rows" value={compact(num(matrix.data?.length))} hint="model × year × age" tone="slate" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Card title="Fleet age histogram" subtitle="units in operation by age bucket">
          <Async state={hist}>
            {() => <Bars data={rows} x="age_bucket" series={[{ key: 'units', label: 'units' }]} height={300} />}
          </Async>
          <Note>
            The dip at 3–5 years is the 2021–2024 vehicle import ban, and it is modelled as genuinely zero
            rather than smoothed away. It matters downstream: those bikes are not there to need parts now, and
            the bulge either side of the hole will age into and out of its service windows on a schedule a
            smoothed curve would get wrong.
          </Note>
        </Card>

        <Card title="Parc by year" subtitle="observed against forecast cohorts">
          <Async state={matrix}>
            {() => (
              <Areas
                data={byYear}
                x="year"
                series={[
                  { key: 'units', label: 'Observed' },
                  { key: 'forecast', label: 'Forecast', color: '#FFC107' },
                ]}
                height={300}
              />
            )}
          </Async>
        </Card>
      </div>
    </>
  )
}

function Scenarios() {
  const totals = useTable('uio_totals_by_scenario', { sort: 'year', desc: false, limit: 200 })
  const rows = totals.data ?? []
  const last = rows[rows.length - 1]

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Base" value={compact(num(last?.base))} hint={last ? `parc in ${int(num(last.year))}` : undefined} tone="blue" />
        <Kpi label="Long life" value={compact(num(last?.long_life))} hint="bikes survive longer" tone="green" />
        <Kpi label="Short life" value={compact(num(last?.short_life))} hint="bikes retire sooner" tone="amber" />
        <Kpi
          label="Spread"
          value={last && num(last.base) ? pct((num(last.long_life) - num(last.short_life)) / num(last.base)) : '—'}
          hint="long vs short, as a share of base"
          tone="purple"
        />
      </div>

      <Card title="Units in operation under three survival scenarios">
        <Async state={totals}>
          {() => (
            <Lines
              data={rows.map((r) => ({
                year: num(r.year),
                base: num(r.base),
                long_life: num(r.long_life),
                short_life: num(r.short_life),
              }))}
              x="year"
              series={[
                { key: 'base', label: 'Base' },
                { key: 'long_life', label: 'Long life', color: '#2CC56F' },
                { key: 'short_life', label: 'Short life', color: '#FFC107' },
              ]}
              height={320}
            />
          )}
        </Async>
        <Note>
          There are no de-registration records anywhere in the supplied files, so survival cannot be measured.
          Three Weibull scenarios are run instead and carried forward as a band rather than collapsed to a
          single number — the honest form of an assumption is a range.
        </Note>
      </Card>

      <Card className="mt-5" title="Parc by year and scenario">
        <Async state={totals}>
          {() => (
            <DataTable
              rows={rows}
              filename="uio_totals_by_scenario"
              dense
              maxHeight="360px"
              columns={[
                { key: 'year', align: 'right' },
                { key: 'base', align: 'right', render: (r) => int(num(r.base)) },
                { key: 'long_life', label: 'long life', align: 'right', render: (r) => int(num(r.long_life)) },
                { key: 'short_life', label: 'short life', align: 'right', render: (r) => int(num(r.short_life)) },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function Survival() {
  const curves = useTable('survival_curves', { limit: 1000 })
  const rows = curves.data ?? []

  const chart = useMemo(() => {
    const ages = Array.from(new Set(rows.map((r) => num(r.age)))).sort((a, b) => a - b)
    return ages.map((age) => {
      const out: Record<string, unknown> = { age }
      for (const s of ['base', 'long_life', 'short_life']) {
        const hit = rows.find((r) => num(r.age) === age && str(r.scenario) === s)
        if (hit) out[s] = num(hit.cumulative_survival)
      }
      return out
    })
  }, [rows])

  return (
    <>
      <Card title="Cumulative survival by age" subtitle="share of a cohort still on the road">
        <Async state={curves}>
          {() => (
            <Lines
              data={chart}
              x="age"
              series={[
                { key: 'base', label: 'Base' },
                { key: 'long_life', label: 'Long life', color: '#2CC56F' },
                { key: 'short_life', label: 'Short life', color: '#FFC107' },
              ]}
              height={320}
            />
          )}
        </Async>
        <Note>
          Survival is assumed, not observed. Everything the parc projects forward — and therefore every
          parc-driven forecast — inherits this assumption, so it is shown explicitly rather than buried in a
          coefficient.
        </Note>
      </Card>

      <Card className="mt-5" title="Survival table">
        <Async state={curves}>
          {() => (
            <DataTable
              rows={rows}
              filename="survival_curves"
              dense
              maxHeight="400px"
              columns={[
                { key: 'scenario' },
                { key: 'age', align: 'right' },
                {
                  key: 'conditional_survival',
                  label: 'conditional',
                  align: 'right',
                  render: (r) => dec(num(r.conditional_survival), 4),
                },
                {
                  key: 'cumulative_survival',
                  label: 'cumulative',
                  align: 'right',
                  render: (r) => dec(num(r.cumulative_survival), 4),
                },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function Explorer() {
  const [model, setModel] = useState('')
  const [year, setYear] = useState('')
  const [scenario, setScenario] = useState('')

  // The age matrix stacks all three survival scenarios, so an unfiltered sum counts the
  // fleet three times over. The base arm is the centre case.
  const matrix = useTable('uio_age_matrix', { where: 'scenario=base', limit: 20000 })
  const all = matrix.data ?? []

  const models = useMemo(() => Array.from(new Set(all.map((r) => str(r.model_name)))).sort(), [all])
  const years = useMemo(
    () =>
      Array.from(new Set(all.map((r) => num(r.year))))
        .sort((a, b) => a - b)
        .map(String),
    [all],
  )
  const scenarios = useMemo(() => Array.from(new Set(all.map((r) => str(r.scenario)))).filter(Boolean).sort(), [all])

  const query = useMemo(
    () => ({
      limit: 2000,
      ...(model ? { model } : {}),
      ...(year ? { year: Number(year) } : {}),
      ...(scenario ? { scenario } : {}),
    }),
    [model, year, scenario],
  )
  const page = useEndpoint<Page>('/parc/uio', query)
  const rows = page.data?.rows ?? []

  return (
    <>
      <Card className="mb-5" title="Filter the cohort matrix" subtitle="served by /parc/uio">
        <div className="flex flex-wrap items-end gap-4">
          <Select
            label="Model"
            value={model}
            options={[{ value: '', label: 'All models' }, ...models.map((m) => ({ value: m, label: m }))]}
            onChange={setModel}
            className="w-60"
          />
          <Select
            label="Year"
            value={year}
            options={[{ value: '', label: 'All years' }, ...years.map((y) => ({ value: y, label: y }))]}
            onChange={setYear}
            className="w-36"
          />
          <Select
            label="Scenario"
            value={scenario}
            options={[{ value: '', label: 'All scenarios' }, ...scenarios.map((s) => ({ value: s, label: s }))]}
            onChange={setScenario}
            className="w-44"
          />
          <div className="ml-auto text-xs text-slate-500">
            {int(num(page.data?.total))} rows match · {rows.length} shown
          </div>
        </div>
      </Card>

      <Card title="Units in operation, by model, year and age">
        <Async state={page}>
          {() => (
            <DataTable
              rows={rows}
              filename="uio_age_matrix"
              dense
              maxHeight="560px"
              initialSort={{ key: 'units', desc: true }}
              columns={[
                { key: 'model_name', label: 'model' },
                { key: 'family' },
                { key: 'status' },
                { key: 'year', align: 'right' },
                { key: 'cohort_year', label: 'cohort', align: 'right' },
                { key: 'age', align: 'right' },
                { key: 'age_bucket', label: 'bucket' },
                { key: 'units', align: 'right', render: (r) => dec(num(r.units), 1) },
                { key: 'is_forecast', label: 'forecast' },
                { key: 'is_estimated', label: 'estimated' },
                { key: 'scenario' },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

export default function Parc() {
  const [tab, setTab] = useState<Tab>('age')
  return (
    <>
      <PageHeader
        title="UIO & Parc"
        subtitle="Step 10 — the vehicle parc, built from unit sales cohorts aged forward under survival assumptions. Units in operation by age is what a parts forecast multiplies against, so the shape of this fleet is the shape of future demand."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'age' && <AgeProfile />}
      {tab === 'scenarios' && <Scenarios />}
      {tab === 'survival' && <Survival />}
      {tab === 'explorer' && <Explorer />}
    </>
  )
}
