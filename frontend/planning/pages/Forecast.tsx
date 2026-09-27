import { useMemo, useState } from 'react'
import { num, str, type Page } from '../api'
import { compact, dec, int, pct } from '../format'
import { useDebounced, useEndpoint, useTable } from '../hooks'
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
  Tabs,
  TextInput,
} from '../components/ui'
import { Bars, Donut, Lines } from '../components/charts'

const TABS = [
  { id: 'selection', label: 'Model selection' },
  { id: 'forecast', label: 'Forecast over P' },
  { id: 'lambda', label: 'Parc λ curves' },
  { id: 'sku', label: 'Per-SKU' },
] as const
type Tab = (typeof TABS)[number]['id']

function Selection() {
  const registry = useTable('model_registry', { sort: 'parts', desc: true, limit: 1000 })
  const backtest = useTable('backtest_results', { sort: 'score', desc: false, limit: 20000 })
  const holdout = useTable('holdout_split')

  const rows = registry.data ?? []
  const inherited = rows.filter((r) => r.inherited === true).length
  const parts = rows.reduce((a, r) => a + num(r.parts), 0)

  const byModel = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.model), (m.get(str(r.model)) ?? 0) + num(r.parts))
    return Array.from(m, ([model, covered]) => ({ model, parts: covered })).sort((a, b) => b.parts - a.parts)
  }, [rows])

  const byMetric = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.metric), (m.get(str(r.metric)) ?? 0) + 1)
    return Array.from(m, ([name, skus]) => ({ name, skus }))
  }, [rows])

  const h = holdout.data?.[0]

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="Combinations" value={int(rows.length)} hint="quadrant × ABC × behaviour" tone="blue" />
        <Kpi label="Parts covered" value={compact(parts)} tone="slate" />
        <Kpi label="Inherited winners" value={int(inherited)} hint="too few parts to select on their own" tone="amber" />
        <Kpi label="Backtest rows" value={compact(num(backtest.data?.length))} tone="purple" />
        <Kpi
          label="Sealed holdout"
          value={h ? `${str(h.holdout_start)} +${int(num(h.holdout_months))}m` : '—'}
          hint={h ? `selection ${str(h.selection_start)} → ${str(h.selection_end)}` : undefined}
          tone="green"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="Parts by winning model" className="xl:col-span-2">
          <Async state={registry}>
            {() => <Bars data={byModel} x="model" series={[{ key: 'parts', label: 'parts' }]} height={260} horizontal />}
          </Async>
          <Note>
            Selection is a rolling-origin backtest, not a single split. MASE scores smooth and erratic parts,
            pinball loss scores intermittent and lumpy ones — MAPE is never used, because a month with zero
            demand makes it undefined and a near-zero month makes it explode.
          </Note>
        </Card>
        <Card title="Scoring metric">
          <Async state={registry}>{() => <Donut data={byMetric} nameKey="name" valueKey="skus" height={240} />}</Async>
        </Card>
      </div>

      <Card title="Winning model per combination" subtitle="with its runner-up, so a near-tie is visible">
        <Async state={registry}>
          {() => (
            <DataTable
              rows={rows}
              filename="model_registry"
              maxHeight="480px"
              dense
              initialSort={{ key: 'parts', desc: true }}
              columns={[
                { key: 'combination' },
                { key: 'quadrant' },
                { key: 'abc', label: 'ABC' },
                { key: 'behaviour_class', label: 'behaviour' },
                { key: 'model', render: (r) => <strong>{str(r.model)}</strong> },
                { key: 'score', align: 'right', render: (r) => dec(num(r.score), 4) },
                { key: 'runner_up' },
                { key: 'runner_up_score', label: 'runner-up score', align: 'right', render: (r) => dec(num(r.runner_up_score), 4) },
                { key: 'metric' },
                { key: 'parts', align: 'right' },
                {
                  key: 'inherited',
                  render: (r) => (r.inherited ? <Badge tone="amber">inherited</Badge> : <Badge tone="green">selected</Badge>),
                },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function ForecastTab() {
  const [quadrant, setQuadrant] = useState('all')
  const [search, setSearch] = useState('')
  const state = useTable('forecast_protection', { sort: 'mu_12m', desc: true, limit: 20000 })
  const all = state.data ?? []

  const rows = useMemo(() => {
    let out = all
    if (quadrant !== 'all') out = out.filter((r) => str(r.quadrant) === quadrant)
    if (search.trim()) {
      const q = search.trim().toUpperCase()
      out = out.filter((r) => str(r.active_sku_id).toUpperCase().includes(q))
    }
    return out
  }, [all, quadrant, search])

  const parcDriven = all.filter((r) => r.mu_month_parc !== null && r.mu_month_parc !== undefined).length
  const parcOnly = all.filter((r) => r.parc_only === true).length

  const quadrantOptions = useMemo(
    () => [
      { value: 'all', label: 'All quadrants' },
      ...Array.from(new Set(all.map((r) => str(r.quadrant)))).map((q) => ({ value: q, label: q })),
    ],
    [all],
  )

  const byMethod = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.method, 'unset'), (m.get(str(r.method, 'unset')) ?? 0) + 1)
    return Array.from(m, ([name, skus]) => ({ name, skus }))
  }, [rows])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="SKUs forecast" value={int(all.length)} tone="blue" />
        <Kpi label="In selection" value={int(rows.length)} tone="slate" />
        <Kpi label="With a parc λ estimate" value={int(parcDriven)} hint="fleet-driven, not history-only" tone="green" />
        <Kpi label="Parc-only" value={int(parcOnly)} hint="no usable order history" tone="amber" />
        <Kpi
          label="Protection interval"
          value="4 months"
          hint="P = L + R = 3 + 1"
          tone="purple"
        />
      </div>

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Select label="Quadrant" value={quadrant} options={quadrantOptions} onChange={setQuadrant} className="w-48" />
          <TextInput label="Search SKU" value={search} onChange={setSearch} className="w-72" />
          <div className="ml-auto">
            <Bars data={byMethod} x="name" series={[{ key: 'skus', label: 'SKUs' }]} height={90} />
          </div>
        </div>
      </Card>

      <Card title="Demand over the protection interval" subtitle="μ, σ and the p50 / p90 / p95 quantiles used for safety stock">
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="forecast_protection"
              maxHeight="560px"
              dense
              initialSort={{ key: 'mu_12m', desc: true }}
              columns={[
                { key: 'active_sku_id', label: 'SKU' },
                { key: 'model' },
                { key: 'quadrant' },
                { key: 'mu_month_baseline', label: 'μ/m history', align: 'right', render: (r) => dec(num(r.mu_month_baseline), 2) },
                {
                  key: 'mu_month_parc',
                  label: 'μ/m parc',
                  align: 'right',
                  render: (r) => (r.mu_month_parc === null || r.mu_month_parc === undefined ? '—' : dec(num(r.mu_month_parc), 2)),
                },
                { key: 'baseline_weight', label: 'weight', align: 'right', render: (r) => pct(num(r.baseline_weight), 0) },
                { key: 'mu_month', label: 'μ/m blended', align: 'right', render: (r) => dec(num(r.mu_month), 2) },
                { key: 'mu_p', label: 'μ over P', align: 'right', render: (r) => dec(num(r.mu_p), 1) },
                { key: 'sigma_p', label: 'σ over P', align: 'right', render: (r) => dec(num(r.sigma_p), 1) },
                { key: 'method' },
                { key: 'p50', align: 'right', render: (r) => dec(num(r.p50), 0) },
                { key: 'p90', align: 'right', render: (r) => dec(num(r.p90), 0) },
                { key: 'p95', align: 'right', render: (r) => dec(num(r.p95), 0) },
              ]}
            />
          )}
        </Async>
        <Note>
          The blended mean is a history baseline weighted against a parc-driven estimate. Where a part has no
          usable history the parc estimate carries it alone, which is the only way a slow-moving part tied to
          an ageing model gets a defensible number at all.
        </Note>
      </Card>
    </>
  )
}

function Lambda() {
  const state = useTable('lambda_curves', { limit: 1000 })
  const rows = state.data ?? []
  const classes = useMemo(() => Array.from(new Set(rows.map((r) => str(r.behaviour_class)))), [rows])
  const [cls, setCls] = useState('')
  const active = cls || classes[0] || ''

  const curve = useMemo(
    () =>
      rows
        .filter((r) => str(r.behaviour_class) === active)
        .sort((a, b) => num(a.age) - num(b.age))
        .map((r) => ({
          age_band: str(r.age_band),
          lambda: num(r.lambda),
          ci_low: num(r.ci_low),
          ci_high: num(r.ci_high),
        })),
    [rows, active],
  )

  return (
    <>
      <Card
        className="mb-5"
        title="Parts consumed per vehicle-month, by fleet age"
        subtitle="Step 08 — λ(p,a), fitted by penalised NNLS with a smoothness penalty and pooled on behaviour class"
        right={
          <Select
            value={active}
            options={classes.map((c) => ({ value: c, label: c }))}
            onChange={setCls}
            className="w-56"
          />
        }
      >
        <Async state={state}>
          {() => (
            <Lines
              data={curve}
              x="age_band"
              series={[
                { key: 'lambda', label: 'λ' },
                { key: 'ci_high', label: 'CI high', color: '#CBD5E1' },
              ]}
              height={280}
            />
          )}
        </Async>
        <Note>
          Demand is modelled as D(p,t) = Σ UIO(m,a,t) · λ(p,a) · s(t) · k(p) — fleet size at each age times a
          consumption rate for that age. λ is constrained non-negative (a part cannot be un-consumed) and
          penalised for roughness, so the curve does not chase noise. Confidence intervals are wide wherever
          few parts pooled into the band; treat those bands as directional.
        </Note>
      </Card>

      <Card title="λ by class, band and age">
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="lambda_curves"
              maxHeight="440px"
              dense
              columns={[
                { key: 'behaviour_class', label: 'behaviour' },
                { key: 'age_band', label: 'age band' },
                { key: 'age', align: 'right' },
                { key: 'lambda', label: 'λ', align: 'right', render: (r) => dec(num(r.lambda), 6) },
                { key: 'std_error', label: 'std error', align: 'right', render: (r) => dec(num(r.std_error), 3) },
                { key: 'ci_low', label: 'CI low', align: 'right', render: (r) => dec(num(r.ci_low), 3) },
                { key: 'ci_high', label: 'CI high', align: 'right', render: (r) => dec(num(r.ci_high), 3) },
                { key: 'parts_pooled', label: 'parts pooled', align: 'right' },
                { key: 'months_fitted', label: 'months', align: 'right' },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function PerSku() {
  const [input, setInput] = useState('571901NAE')
  const sku = useDebounced(input.trim())
  const history = useEndpoint<Page>(sku ? `/demand/${encodeURIComponent(sku)}/history` : null, { limit: 240 })
  const forecast = useEndpoint<Page>(sku ? `/demand/${encodeURIComponent(sku)}/forecast` : null)

  const f = forecast.data?.rows?.[0]
  const series = useMemo(
    () =>
      (history.data?.rows ?? [])
        .slice()
        .sort((a, b) => str(a.month).localeCompare(str(b.month)))
        .map((r) => ({
          month: str(r.month),
          ordered: num(r.ordered_quantity),
          confirmed: num(r.confirmed_quantity),
          lost: num(r.lost_quantity),
          mu: f ? num(f.mu_month) : undefined,
        })),
    [history.data, f],
  )

  return (
    <>
      <Card className="mb-5">
        <TextInput
          label="Active SKU id"
          value={input}
          onChange={setInput}
          placeholder="e.g. 571901NAE"
          className="w-80"
        />
      </Card>

      {forecast.error && <ErrorBox message={forecast.error} />}
      {forecast.loading && <Loading />}

      {f && (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-4 mb-5">
          <Kpi label="Model" value={str(f.model)} tone="blue" />
          <Kpi label="Quadrant" value={str(f.quadrant)} tone="slate" />
          <Kpi label="μ per month" value={dec(num(f.mu_month), 1)} tone="green" />
          <Kpi label="μ over P" value={dec(num(f.mu_p), 1)} hint="4 months" tone="purple" />
          <Kpi label="σ over P" value={dec(num(f.sigma_p), 1)} hint={str(f.method)} tone="amber" />
          <Kpi label="p95" value={dec(num(f.p95), 0)} tone="teal" />
        </div>
      )}

      <Card title="Ordered, confirmed and lost by month" subtitle={sku || 'enter a SKU above'}>
        <Async state={history}>
          {() => (
            <Lines
              data={series}
              x="month"
              series={[
                { key: 'ordered', label: 'Ordered' },
                { key: 'confirmed', label: 'Confirmed', color: '#2CC56F' },
                { key: 'lost', label: 'Lost', color: '#EF4444' },
                { key: 'mu', label: 'Forecast μ/month', color: '#7C3AED' },
              ]}
              height={300}
            />
          )}
        </Async>
        <Note>
          The gap between ordered and confirmed is measured lost sale, not an estimate. A forecast fitted on
          confirmed quantity would learn the stockout rather than the demand.
        </Note>
      </Card>
    </>
  )
}

export default function Forecast() {
  const [tab, setTab] = useState<Tab>('selection')
  return (
    <>
      <PageHeader
        title="Demand Forecast"
        subtitle="Steps 07 and 08 — which model won for which kind of part, the demand it projects over the four-month protection interval, and the fleet-age consumption curves behind the parc-driven estimate."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'selection' && <Selection />}
      {tab === 'forecast' && <ForecastTab />}
      {tab === 'lambda' && <Lambda />}
      {tab === 'sku' && <PerSku />}
    </>
  )
}
