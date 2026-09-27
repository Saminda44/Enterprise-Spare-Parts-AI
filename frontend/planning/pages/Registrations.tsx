import { useMemo } from 'react'
import { num, str } from '../api'
import { compact, dec, int, pctPoints } from '../format'
import { useTable } from '../hooks'
import { Async, Badge, Card, DataTable, Kpi, Note, PageHeader } from '../components/ui'
import { Bars, Lines } from '../components/charts'

export default function Registrations() {
  const forecast = useTable('registration_forecast', { sort: 'forecast_units', desc: true, limit: 1000 })
  const scenarios = useTable('scenarios', { limit: 100 })
  const lag = useTable('scenario_demand', { sort: 'months_after_target', desc: false, limit: 100 })

  const rows = forecast.data ?? []
  const totalForecast = rows.reduce((a, r) => a + num(r.forecast_units), 0)

  const byFamily = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.family, '—'), (m.get(str(r.family, '—')) ?? 0) + num(r.forecast_units))
    return Array.from(m, ([family, units]) => ({ family, units })).sort((a, b) => b.units - a.units)
  }, [rows])

  const lagRows = lag.data ?? []
  const peak = lagRows.reduce(
    (best, r) => (num(r.delta_pct) > num(best?.delta_pct ?? -Infinity) ? r : best),
    lagRows[0],
  )
  const yearOne = lagRows.find((r) => num(r.months_after_target) === 12) ?? lagRows[0]
  const shift = num(scenarios.data?.find((r) => str(r.scenario) === 'upside')?.value)

  const lagChart = lagRows.map((r) => ({
    month: `+${int(num(r.months_after_target))}m`,
    base: num(r.base_parts_demand),
    upside: num(r.upside_parts_demand),
    delta_pct: num(r.delta_pct) * 100,
  }))

  const passes = num(yearOne?.delta_pct) > 0 && num(yearOne?.delta_pct) < num(peak?.delta_pct) + 1e-9

  return (
    <>
      <PageHeader
        title="MC Sales Forecast & Targets"
        subtitle="Step 11 — next period's motorcycle unit forecast by model, and the lag test that proves a unit target actually moves parts demand in the right direction, with the right delay."
        right={
          <Badge tone={passes ? 'green' : 'amber'}>
            lag test {passes ? 'PASS' : 'review'}
          </Badge>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="Forecast units" value={compact(totalForecast)} hint="next period, all models" tone="blue" />
        <Kpi label="Models forecast" value={int(rows.length)} tone="slate" />
        <Kpi
          label="Upside scenario"
          value={shift ? `${shift > 0 ? '+' : ''}${(shift * 100).toFixed(0)}%` : '—'}
          hint="applied to the unit target"
          tone="purple"
        />
        <Kpi
          label="Parts demand, year one"
          value={pctPoints(num(yearOne?.delta_pct) * 100)}
          hint="response to that unit shift"
          tone="green"
        />
        <Kpi
          label="Peak response"
          value={pctPoints(num(peak?.delta_pct) * 100)}
          hint={peak ? `at +${int(num(peak.months_after_target))} months` : undefined}
          tone="amber"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
        <Card title="Parts demand response to a unit-sales shift" subtitle="base vs upside, by months after the target">
          <Async state={lag}>
            {() => (
              <Lines
                data={lagChart}
                x="month"
                series={[
                  { key: 'base', label: 'Base parts demand' },
                  { key: 'upside', label: 'Upside parts demand', color: '#2CC56F' },
                ]}
                height={260}
              />
            )}
          </Async>
          <Note>
            A {shift ? `${(shift * 100).toFixed(0)}%` : 'unit'} lift in motorcycle sales produces{' '}
            {pctPoints(num(yearOne?.delta_pct) * 100)} more parts demand in year one, peaking at{' '}
            {pctPoints(num(peak?.delta_pct) * 100)}. That lag is the point: a bike sold today consumes almost
            no parts this month and its first service falls well after. A model that responded 1:1 and
            immediately would be wrong, and a flat response would mean the parc link is not wired up at all.
          </Note>
        </Card>

        <Card title="Added demand by lag" subtitle="percentage points above base">
          <Async state={lag}>
            {() => <Bars data={lagChart} x="month" series={[{ key: 'delta_pct', label: 'Δ %', color: '#7C3AED' }]} height={260} />}
          </Async>
          <Note>
            The added demand is measured against total fleet demand, not against the new cohort alone —
            comparing a cohort against itself would return 1:1 by construction and prove nothing.
          </Note>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <Card title="Forecast units by family" className="xl:col-span-1">
          <Async state={forecast}>
            {() => <Bars data={byFamily} x="family" series={[{ key: 'units', label: 'units' }]} height={260} horizontal />}
          </Async>
        </Card>

        <Card title="Unit forecast by model" subtitle="Step 11" className="xl:col-span-2">
          <Async state={forecast}>
            {() => (
              <DataTable
                rows={rows}
                filename="registration_forecast"
                dense
                maxHeight="300px"
                initialSort={{ key: 'forecast_units', desc: true }}
                columns={[
                  { key: 'Model', label: 'code' },
                  { key: 'model_name', label: 'model' },
                  { key: 'family' },
                  { key: 'forecast_units', label: 'forecast units', align: 'right', render: (r) => int(num(r.forecast_units)) },
                  { key: 'basis_years', label: 'basis years', align: 'right' },
                  { key: 'method' },
                ]}
              />
            )}
          </Async>
          <Note>
            The basis is the post-ban years only. Sri Lanka's 2021–2024 vehicle import ban left a genuine hole
            in the fleet, so averaging across it would forecast a market that did not exist.
          </Note>
        </Card>
      </div>

      <Card className="mt-5" title="Scenarios" subtitle="what is varied, and by how much">
        <Async state={scenarios}>
          {(rows2) => (
            <DataTable
              rows={rows2}
              dense
              columns={[
                { key: 'scenario' },
                { key: 'kind' },
                { key: 'parameter' },
                { key: 'value', align: 'right', render: (r) => dec(num(r.value), 3) },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}
