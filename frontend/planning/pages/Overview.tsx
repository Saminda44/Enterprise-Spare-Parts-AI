import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Boxes, Package, ShoppingCart, Target, TrendingUp, Wallet } from 'lucide-react'
import { num, type Row } from '../api'
import { compact, compactLkr, dec, pct } from '../format'
import { useTable } from '../hooks'
import { Async, Badge, Card, DataTable, Kpi, Note, PageHeader } from '../components/ui'
import { Bars, Lines } from '../components/charts'

function sum(rows: Row[] | null, key: string): number {
  return (rows ?? []).reduce((a, r) => a + num(r[key]), 0)
}

export default function Overview() {
  const gate = useTable('mart_service_and_stock')
  const policy = useTable('mart_policy_summary')
  const fulfil = useTable('fulfilment_stats')
  const salesKpis = useTable('sales_kpis')
  const salesMonthly = useTable('sales_monthly', { sort: 'month', desc: false })
  const units = useTable('unit_sales_by_model')
  const holdout = useTable('holdout_split')
  const lead = useTable('lead_time_stats')

  const selected = gate.data?.find((r) => r.arm === 'selected')
  const baseline = gate.data?.find((r) => r.arm === 'baseline')

  const orderValue = sum(policy.data, 'order_value')
  const skus = sum(policy.data, 'skus')
  const triggered = sum(policy.data, 'triggered')

  const ordered = sum(fulfil.data, 'ordered_quantity')
  const confirmed = sum(fulfil.data, 'confirmed_quantity')
  const fillHistoric = ordered > 0 ? confirmed / ordered : null

  const netSales = num(salesKpis.data?.[0]?.total_net_sales, NaN)
  const margin = num(salesKpis.data?.[0]?.total_margin, NaN)
  const totalUnits = sum(units.data, 'units')

  const gateChart = useMemo(
    () => [
      {
        measure: 'Fill rate (×100)',
        selected: num(selected?.fill_rate) * 100,
        baseline: num(baseline?.fill_rate) * 100,
      },
      {
        measure: 'Avg inventory (LKR M)',
        selected: num(selected?.average_inventory_value) / 1e6,
        baseline: num(baseline?.average_inventory_value) / 1e6,
      },
      {
        measure: 'Total cost (LKR M)',
        selected: num(selected?.total_cost) / 1e6,
        baseline: num(baseline?.total_cost) / 1e6,
      },
    ],
    [selected, baseline],
  )

  const verdict = String(selected?.verdict ?? '—')

  return (
    <>
      <PageHeader
        title="Planning Overview"
        subtitle="The monthly replenishment picture for the Yamaha spare-parts network, read straight from the published marts. Every figure here was computed in a pipeline step, not in this page."
        right={
          <div className="flex items-center gap-2">
            <Badge tone={verdict === 'PASS' ? 'green' : 'amber'}>Step 13 gate: {verdict}</Badge>
            {holdout.data?.[0] && (
              <Badge tone="slate">
                sealed holdout {String(holdout.data[0].holdout_start)} · {num(holdout.data[0].holdout_months)}m
              </Badge>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-6">
        <Kpi
          label="Monthly order value"
          value={compactLkr(orderValue)}
          hint={`${compact(triggered)} of ${compact(skus)} SKUs triggered`}
          tone="blue"
          icon={<ShoppingCart size={15} />}
        />
        <Kpi
          label="Achieved fill rate"
          value={selected ? pct(num(selected.fill_rate)) : '—'}
          hint={baseline ? `baseline ${pct(num(baseline.fill_rate))}` : undefined}
          tone="green"
          icon={<Target size={15} />}
        />
        <Kpi
          label="Avg inventory value"
          value={compactLkr(num(selected?.average_inventory_value))}
          hint={baseline ? `baseline ${compactLkr(num(baseline.average_inventory_value))}` : undefined}
          tone="amber"
          icon={<Boxes size={15} />}
        />
        <Kpi
          label="Historic fill rate"
          value={fillHistoric === null ? '—' : pct(fillHistoric)}
          hint="ordered vs confirmed, as observed"
          tone="purple"
          icon={<Package size={15} />}
        />
        <Kpi
          label="Billed revenue"
          value={compactLkr(netSales)}
          hint={Number.isFinite(margin) ? `margin ${compactLkr(margin)}` : undefined}
          tone="teal"
          icon={<Wallet size={15} />}
        />
        <Kpi
          label="Motorcycles sold"
          value={compact(totalUnits)}
          hint="drives the parc that drives demand"
          tone="slate"
          icon={<TrendingUp size={15} />}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card
          title="Step 13 acceptance gate"
          subtitle="Selected policy against the current baseline, on the sealed holdout"
          className="xl:col-span-2"
        >
          <Async state={gate}>
            {() => (
              <>
                <Bars
                  data={gateChart}
                  x="measure"
                  series={[
                    { key: 'selected', label: 'Selected policy', color: '#4361EE' },
                    { key: 'baseline', label: 'Baseline', color: '#94A3B8' },
                  ]}
                  height={230}
                />
                <Note>
                  The gate passes only when the selected policy beats the baseline on fill rate{' '}
                  <em>and</em> does not exceed it on average inventory value. Here fill rate rises from{' '}
                  {pct(num(baseline?.fill_rate))} to {pct(num(selected?.fill_rate))} while inventory rises from{' '}
                  {compactLkr(num(baseline?.average_inventory_value))} to{' '}
                  {compactLkr(num(selected?.average_inventory_value))} — a win on one axis only, which is a{' '}
                  <strong>frontier to show the owner</strong>, not a pass to claim.
                </Note>
              </>
            )}
          </Async>
        </Card>

        <Card title="Order value by policy" subtitle="Step 14, this cycle">
          <Async state={policy}>
            {(rows) => (
              <Bars
                data={rows.map((r) => ({
                  label: `${r.policy} ${r.abc_class}`,
                  order_value: num(r.order_value) / 1e6,
                }))}
                x="label"
                series={[{ key: 'order_value', label: 'LKR M' }]}
                height={230}
                horizontal
              />
            )}
          </Async>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
        <Card title="Billed revenue by month" subtitle="Step 04 — net sales and margin, LKR">
          <Async state={salesMonthly}>
            {(rows) => (
              <Lines
                data={rows.map((r) => ({
                  month: r.month,
                  net_sales: num(r.net_sales),
                  margin: num(r.margin),
                }))}
                x="month"
                series={[
                  { key: 'net_sales', label: 'Net sales' },
                  { key: 'margin', label: 'Margin', color: '#2CC56F' },
                ]}
              />
            )}
          </Async>
        </Card>

        <Card title="Policy mix" subtitle="Step 13 — SKUs and safety stock by policy and ABC class">
          <Async state={policy}>
            {(rows) => (
              <DataTable
                rows={rows}
                maxHeight="260px"
                dense
                columns={[
                  { key: 'policy' },
                  { key: 'abc_class', label: 'ABC' },
                  { key: 'skus', align: 'right' },
                  { key: 'triggered', align: 'right' },
                  {
                    key: 'safety_stock',
                    label: 'safety stock (units)',
                    align: 'right',
                    render: (r) => compact(num(r.safety_stock)),
                  },
                  {
                    key: 'order_value',
                    label: 'order value',
                    align: 'right',
                    render: (r) => compactLkr(num(r.order_value)),
                  },
                ]}
              />
            )}
          </Async>
        </Card>
      </div>

      <Card
        title="What these numbers assume"
        subtitle="Open items that move every figure above — none can be resolved from the supplied files"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3 text-sm text-slate-600">
          <div>
            <p className="font-medium text-slate-800">On-order quantity resolves to zero</p>
            <p className="text-xs mt-0.5">
              The <code>On_Orders</code> months carry no year and no arrival flag, so inventory position
              collapses to on-hand. With a 3-month lead and monthly review there can be three orders in
              flight — every order quantity on the{' '}
              <Link to="/order-plan" className="text-brand-blue hover:underline">
                monthly order
              </Link>{' '}
              is overstated until this is confirmed.
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-800">Replenishment lead time is assumed, not measured</p>
            <p className="text-xs mt-0.5">
              {lead.data?.[0] && (
                <>
                  The only measurable interval is dealer dispatch at{' '}
                  {dec(num(lead.data[0].mean_days), 1)} days — that is not the 3-month import lead. σ_L for
                  replenishment is unknown, so safety stock understates it.
                </>
              )}
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-800">Fill-rate targets and cost rates are defaults</p>
            <p className="text-xs mt-0.5">
              A 0.98 / 0.95 / 0.90 target by ABC class, a 20% annual holding rate and a 5,000 LKR order cost
              are planning assumptions carried in settings, not values from a source file.
            </p>
          </div>
          <div>
            <p className="font-medium text-slate-800">Survival is modelled, not observed</p>
            <p className="text-xs mt-0.5">
              There are no de-registration records, so the parc is projected under three Weibull scenarios.
              See{' '}
              <Link to="/parc" className="text-brand-blue hover:underline">
                UIO &amp; Parc
              </Link>
              .
            </p>
          </div>
        </div>
        <Note>
          Order proposals are recommendations. Nothing in this service writes to SAP — a human sends the
          order. All values are LKR; the network scope for stock is the PDC (plant W1B4) only.
        </Note>
      </Card>
    </>
  )
}
