import { useMemo, useState } from 'react'
import { num, str } from '../api'
import { compact, compactLkr, dec, int, pct } from '../format'
import { useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, Select, TextInput } from '../components/ui'
import { Bars, Donut, Quadrants } from '../components/charts'

const ADI_CUT = 1.32
const CV2_CUT = 0.49

function counts(rows: Record<string, unknown>[], key: string) {
  const m = new Map<string, number>()
  for (const r of rows) {
    const k = str(r[key], 'unset') || 'unset'
    m.set(k, (m.get(k) ?? 0) + 1)
  }
  return Array.from(m, ([name, skus]) => ({ name, skus })).sort((a, b) => b.skus - a.skus)
}

export default function Classification() {
  const [quadrant, setQuadrant] = useState('all')
  const [abc, setAbc] = useState('all')
  const [search, setSearch] = useState('')

  const state = useTable('sku_classification', { sort: 'annual_consumption_value', desc: true, limit: 20000 })
  const all = state.data ?? []

  const rows = useMemo(() => {
    let out = all
    if (quadrant !== 'all') out = out.filter((r) => str(r.quadrant) === quadrant)
    if (abc !== 'all') out = out.filter((r) => str(r.abc) === abc)
    if (search.trim()) {
      const q = search.trim().toUpperCase()
      out = out.filter(
        (r) => str(r.active_sku_id).toUpperCase().includes(q) || str(r.description).toUpperCase().includes(q),
      )
    }
    return out
  }, [all, quadrant, abc, search])

  const quadrantCounts = useMemo(() => counts(all, 'quadrant'), [all])
  const abcCounts = useMemo(() => counts(all, 'abc'), [all])
  const xyzCounts = useMemo(() => counts(all, 'xyz'), [all])
  const fsnCounts = useMemo(() => counts(all, 'fsn'), [all])
  const behaviourCounts = useMemo(() => counts(all, 'behaviour_class'), [all])

  const insufficient = all.filter((r) => r.insufficient_history === true).length
  const value = rows.reduce((a, r) => a + num(r.annual_consumption_value), 0)

  // 6,200 points render, but the scatter reads better on a sample; the counts above are
  // always the full population.
  const sample = useMemo(() => {
    const step = Math.max(1, Math.ceil(rows.length / 2500))
    return rows
      .filter((_, i) => i % step === 0)
      .map((r) => ({
        adi: Math.max(num(r.adi), 0.01),
        cv2: Math.max(num(r.cv2), 0.001),
        quadrant: str(r.quadrant, 'unset'),
      }))
      .filter((d) => Number.isFinite(d.adi) && Number.isFinite(d.cv2))
  }, [rows])

  const options = (list: { name: string }[], allLabel: string) => [
    { value: 'all', label: allLabel },
    ...list.map((c) => ({ value: c.name, label: c.name })),
  ]

  return (
    <>
      <PageHeader
        title="SKU Classification"
        subtitle="Step 06 — the routing key for everything downstream. The Syntetos-Boylan quadrant decides which forecast family and which safety-stock estimator a part gets; ABC/XYZ/FSN set the service target and the review attention."
      />

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-5">
        <Kpi label="SKUs classified" value={int(all.length)} tone="blue" />
        <Kpi label="In selection" value={int(rows.length)} hint="after the filters below" tone="slate" />
        <Kpi label="Annual consumption" value={compactLkr(value)} tone="green" />
        <Kpi label="Class A" value={int(abcCounts.find((c) => c.name === 'A')?.skus ?? 0)} tone="purple" />
        <Kpi
          label="Insufficient history"
          value={int(insufficient)}
          hint="too few months to classify safely"
          tone="amber"
        />
        <Kpi
          label="Criticality"
          value="unset"
          hint="an owner judgement, not derivable from any file"
          tone="red"
        />
      </div>

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Select
            label="Quadrant"
            value={quadrant}
            options={options(quadrantCounts, 'All quadrants')}
            onChange={setQuadrant}
            className="w-48"
          />
          <Select label="ABC" value={abc} options={options(abcCounts, 'All classes')} onChange={setAbc} className="w-40" />
          <TextInput
            label="Search part or description"
            value={search}
            onChange={setSearch}
            className="w-80"
            placeholder="e.g. FILTER"
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card
          title="Demand pattern quadrants"
          subtitle={`ADI cut ${ADI_CUT}, CV² cut ${CV2_CUT} · ${sample.length.toLocaleString()} of ${rows.length.toLocaleString()} plotted`}
          className="xl:col-span-2"
        >
          <Async state={state}>
            {() => (
              <Quadrants data={sample} xKey="adi" yKey="cv2" groupKey="quadrant" xCut={ADI_CUT} yCut={CV2_CUT} />
            )}
          </Async>
          <Note>
            Average demand interval on the x axis, squared coefficient of variation on the y. Smooth parts sit
            bottom-left and take a conventional forecast; lumpy parts sit top-right and must not be given a
            normal-theory safety stock. Both axes are log-scaled so the intermittent tail stays readable.
          </Note>
        </Card>

        <div className="space-y-5">
          <Card title="Quadrant mix">
            <Async state={state}>{() => <Donut data={quadrantCounts} nameKey="name" valueKey="skus" height={200} />}</Async>
          </Card>
          <Card title="Behaviour class" subtitle="rules-only in this build">
            <Async state={state}>
              {() => <Bars data={behaviourCounts} x="name" series={[{ key: 'skus', label: 'SKUs' }]} height={190} />}
            </Async>
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="ABC — by annual consumption value">
          <Async state={state}>{() => <Bars data={abcCounts} x="name" series={[{ key: 'skus', label: 'SKUs' }]} height={200} />}</Async>
        </Card>
        <Card title="XYZ — by demand variability">
          <Async state={state}>{() => <Bars data={xyzCounts} x="name" series={[{ key: 'skus', label: 'SKUs', color: '#7C3AED' }]} height={200} />}</Async>
        </Card>
        <Card title="FSN — fast, slow, non-moving">
          <Async state={state}>{() => <Bars data={fsnCounts} x="name" series={[{ key: 'skus', label: 'SKUs', color: '#06B6D4' }]} height={200} />}</Async>
        </Card>
      </div>

      <Card title="Classified parts" subtitle={`${rows.length.toLocaleString()} rows in the current selection`}>
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="sku_classification"
              maxHeight="520px"
              dense
              initialSort={{ key: 'annual_consumption_value', desc: true }}
              columns={[
                { key: 'active_sku_id', label: 'SKU' },
                { key: 'description' },
                { key: 'quadrant' },
                { key: 'behaviour_class', label: 'behaviour' },
                { key: 'abc', label: 'ABC' },
                { key: 'xyz', label: 'XYZ' },
                { key: 'fsn', label: 'FSN' },
                { key: 'adi', label: 'ADI', align: 'right', render: (r) => dec(num(r.adi), 2) },
                { key: 'cv2', label: 'CV²', align: 'right', render: (r) => dec(num(r.cv2), 3) },
                {
                  key: 'mean_monthly_demand',
                  label: 'μ/month',
                  align: 'right',
                  render: (r) => dec(num(r.mean_monthly_demand), 1),
                },
                {
                  key: 'annual_consumption_value',
                  label: 'annual value',
                  align: 'right',
                  render: (r) => compactLkr(num(r.annual_consumption_value)),
                },
                { key: 'months_observed', label: 'months', align: 'right' },
                { key: 'nonzero_months', label: 'non-zero', align: 'right' },
                { key: 'last_demand_month', label: 'last demand' },
              ]}
            />
          )}
        </Async>
        <Note>
          Known gap: <strong>behaviour class is rules-only</strong> in this build and{' '}
          <strong>criticality is unset</strong> — criticality is an owner judgement (does the bike stop
          without this part?) and is not derivable from any supplied file. Both feed the pooling in Step 08
          and the service target in Step 13, so setting them properly will move numbers.
        </Note>
      </Card>

      <div className="mt-5 text-xs text-slate-500">
        Total classified demand value across all {compact(all.length)} SKUs:{' '}
        {compactLkr(all.reduce((a, r) => a + num(r.annual_consumption_value), 0))} · coverage{' '}
        {pct(all.length ? rows.length / all.length : 0)} of SKUs in the current selection.
      </div>
    </>
  )
}
