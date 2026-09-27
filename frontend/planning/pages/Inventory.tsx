import { useMemo, useState } from 'react'
import { num, str } from '../api'
import { compact, compactLkr, dec, int, pct } from '../format'
import { useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, Tabs, TextInput } from '../components/ui'
import { Bars, Donut } from '../components/charts'

const TABS = [
  { id: 'stock', label: 'Stock position' },
  { id: 'policy', label: 'Safety stock & policy' },
  { id: 'sim', label: 'Simulation & gate' },
] as const

type Tab = (typeof TABS)[number]['id']

function StockTab() {
  const [search, setSearch] = useState('')
  const stock = useTable('stock_position', { sort: 'on_hand', desc: true, limit: 5000 })
  const plants = useTable('stock_by_plant', { sort: 'Unrestricted', desc: true })

  const rows = useMemo(() => {
    const all = stock.data ?? []
    if (!search.trim()) return all
    const q = search.trim().toUpperCase()
    return all.filter(
      (r) => str(r.active_sku_id).toUpperCase().includes(q) || str(r.description).toUpperCase().includes(q),
    )
  }, [stock.data, search])

  const onHand = rows.reduce((a, r) => a + num(r.on_hand), 0)
  const onOrder = rows.reduce((a, r) => a + num(r.on_order), 0)
  const back = rows.reduce((a, r) => a + num(r.backorders), 0)
  const zero = rows.filter((r) => num(r.on_hand) <= 0).length

  const network = (plants.data ?? []).reduce((a, r) => a + num(r.Unrestricted), 0)
  const pdc = num(plants.data?.find((r) => str(r.Plant) === 'W1B4')?.Unrestricted)

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="SKUs at the PDC" value={int(rows.length)} tone="blue" />
        <Kpi label="On hand" value={compact(onHand)} hint="units, plant W1B4" tone="green" />
        <Kpi label="On order" value={compact(onOrder)} hint="unresolved — see note" tone="red" />
        <Kpi label="Backorders" value={compact(back)} tone="amber" />
        <Kpi label="Zero-stock SKUs" value={int(zero)} tone="purple" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="Units by plant" subtitle={`PDC holds ${pct(network ? pdc / network : 0)} of network units`}>
          <Async state={plants}>
            {(p) => (
              <Bars
                data={p.slice(0, 10).map((r) => ({ plant: str(r.Plant), units: num(r.Unrestricted) }))}
                x="plant"
                series={[{ key: 'units', label: 'unrestricted units' }]}
                height={240}
                horizontal
              />
            )}
          </Async>
          <Note>
            Stock scope is the PDC only (<code>Plant == W1B4</code>). Branch stock is visibility, never
            inventory position — a branch unit cannot satisfy a replenishment decision taken centrally.
          </Note>
        </Card>

        <Card title="Inventory position" subtitle="IP = on hand + on order − backorders" className="xl:col-span-2">
          <div className="mb-3">
            <TextInput
              label="Search"
              value={search}
              onChange={setSearch}
              placeholder="part number or description"
              className="w-72"
            />
          </div>
          <Async state={stock}>
            {() => (
              <DataTable
                rows={rows}
                filename="stock_position"
                maxHeight="420px"
                dense
                initialSort={{ key: 'on_hand', desc: true }}
                columns={[
                  { key: 'active_sku_id', label: 'SKU' },
                  { key: 'description' },
                  { key: 'on_hand', align: 'right', render: (r) => int(num(r.on_hand)) },
                  { key: 'on_order', align: 'right', render: (r) => int(num(r.on_order)) },
                  { key: 'backorders', align: 'right', render: (r) => int(num(r.backorders)) },
                  { key: 'ip', label: 'IP', align: 'right', render: (r) => int(num(r.ip)) },
                  { key: 'storage_locations', label: 'locations' },
                ]}
              />
            )}
          </Async>
          <Note>
            <strong>on_order is zero across the board.</strong> The <code>On_Orders</code> export names months
            with no year and no arrival/raised flag, so nothing can be placed on a timeline. IP therefore
            collapses to on-hand and every order quantity downstream is overstated.
          </Note>
        </Card>
      </div>
    </>
  )
}

function PolicyTab() {
  const params = useTable('policy_params', { sort: 'safety_stock', desc: true, limit: 5000 })
  const selection = useTable('policy_selection', { limit: 5000 })
  const summary = useTable('mart_policy_summary')

  const byStrategy = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of params.data ?? []) {
      const k = str(r.ss_strategy, 'unknown')
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    return Array.from(m, ([strategy, skus]) => ({ strategy, skus }))
  }, [params.data])

  const byPolicy = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of selection.data ?? []) {
      const k = str(r.policy, 'unknown')
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    return Array.from(m, ([policy, skus]) => ({ policy, skus })).sort((a, b) => b.skus - a.skus)
  }, [selection.data])

  return (
    <>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="Safety-stock strategy" subtitle="which estimator won per SKU">
          <Async state={params}>{() => <Donut data={byStrategy} nameKey="strategy" valueKey="skus" />}</Async>
          <Note>
            Three estimators are computed for every SKU — a bracketing bound, the normal approximation and an
            empirical quantile. The strategy column records which one the quadrant routed to, so a lumpy part
            is never given a normal-theory number by default.
          </Note>
        </Card>
        <Card title="Policy assignment" subtitle="monthly-executable policies only">
          <Async state={selection}>
            {() => <Bars data={byPolicy} x="policy" series={[{ key: 'skus', label: 'SKUs' }]} height={240} />}
          </Async>
          <Note>
            Four policies: (R,S), (R,s,S), on-demand and no-stock. VMI, JIT and continuous review are out of
            scope — the review period is fixed at one month.
          </Note>
        </Card>
        <Card title="Summary by policy and class">
          <Async state={summary}>
            {(rows) => (
              <DataTable
                rows={rows}
                maxHeight="240px"
                dense
                columns={[
                  { key: 'policy' },
                  { key: 'abc_class', label: 'ABC' },
                  { key: 'skus', align: 'right' },
                  { key: 'triggered', align: 'right' },
                  { key: 'order_value', align: 'right', render: (r) => compactLkr(num(r.order_value)) },
                ]}
              />
            )}
          </Async>
        </Card>
      </div>

      <Card title="Per-SKU policy parameters" subtitle="fill target → z → safety stock → s, S, ROL">
        <Async state={params}>
          {(rows) => (
            <DataTable
              rows={rows}
              filename="policy_params"
              maxHeight="520px"
              dense
              initialSort={{ key: 'safety_stock', desc: true }}
              columns={[
                { key: 'active_sku_id', label: 'SKU' },
                { key: 'abc', label: 'ABC' },
                { key: 'quadrant' },
                { key: 'fill_target', align: 'right', render: (r) => pct(num(r.fill_target)) },
                { key: 'z', align: 'right', render: (r) => dec(num(r.z), 3) },
                { key: 'ss_bracketing', label: 'SS bracket', align: 'right', render: (r) => int(num(r.ss_bracketing)) },
                { key: 'ss_normal', label: 'SS normal', align: 'right', render: (r) => int(num(r.ss_normal)) },
                { key: 'ss_empirical', label: 'SS empirical', align: 'right', render: (r) => int(num(r.ss_empirical)) },
                { key: 'safety_stock', label: 'SS used', align: 'right', render: (r) => int(num(r.safety_stock)) },
                { key: 'ss_strategy', label: 'strategy' },
                { key: 'mu_p', label: 'μ over P', align: 'right', render: (r) => dec(num(r.mu_p), 1) },
                { key: 's', align: 'right', render: (r) => int(num(r.s)) },
                { key: 'S', align: 'right', render: (r) => int(num(r.S)) },
                { key: 'months_of_cover', label: 'cover (m)', align: 'right', render: (r) => dec(num(r.months_of_cover), 1) },
              ]}
            />
          )}
        </Async>
        <Note>
          The fill-rate target is solved for z through σ·G(z)/(d̄·R) ≤ 1−β, not read off a cycle-service-level
          table. Fill rate and cycle service level are different quantities and conflating them systematically
          over-stocks the fast movers.
        </Note>
      </Card>
    </>
  )
}

function SimTab() {
  const sim = useTable('simulation_results', { sort: 'cost', desc: true, limit: 5000 })
  const gate = useTable('mart_service_and_stock')
  const holdout = useTable('holdout_split')

  const byPolicy = useMemo(() => {
    const m = new Map<string, { policy: string; skus: number; fill: number; cost: number; lost: number }>()
    for (const r of sim.data ?? []) {
      const k = str(r.policy, 'unknown')
      const cur = m.get(k) ?? { policy: k, skus: 0, fill: 0, cost: 0, lost: 0 }
      cur.skus += 1
      cur.fill += num(r.fill_rate)
      cur.cost += num(r.cost)
      cur.lost += num(r.lost_units)
      m.set(k, cur)
    }
    return Array.from(m.values()).map((v) => ({
      policy: v.policy,
      skus: v.skus,
      avg_fill: v.skus ? (v.fill / v.skus) * 100 : 0,
      cost_m: v.cost / 1e6,
      lost: v.lost,
    }))
  }, [sim.data])

  const broken = (sim.data ?? []).filter((r) => Math.abs(num(r.conservation_error)) > 1e-6).length

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        {(gate.data ?? []).map((r) => (
          <Kpi
            key={str(r.arm)}
            label={`${str(r.arm)} fill rate`}
            value={pct(num(r.fill_rate))}
            hint={`avg inventory ${compactLkr(num(r.average_inventory_value))}`}
            tone={str(r.arm) === 'selected' ? 'green' : 'slate'}
          />
        ))}
        <Kpi
          label="Holdout"
          value={`${str(holdout.data?.[0]?.holdout_start, '—')} +${int(num(holdout.data?.[0]?.holdout_months))}m`}
          hint="opened once in Step 13, never re-opened"
          tone="purple"
        />
        <Kpi
          label="Conservation errors"
          value={int(broken)}
          hint="simulated units that did not balance"
          tone={broken ? 'red' : 'green'}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
        <Card title="Simulated fill rate by policy" subtitle="mean across SKUs, holdout window">
          <Async state={sim}>
            {() => (
              <Bars data={byPolicy} x="policy" series={[{ key: 'avg_fill', label: 'avg fill %' }]} height={240} />
            )}
          </Async>
        </Card>
        <Card title="Simulated cost by policy" subtitle="LKR M">
          <Async state={sim}>
            {() => <Bars data={byPolicy} x="policy" series={[{ key: 'cost_m', label: 'LKR M', color: '#FFC107' }]} height={240} />}
          </Async>
        </Card>
      </div>

      <Card title="Per-SKU simulation" subtitle="one row per SKU and policy arm">
        <Async state={sim}>
          {(rows) => (
            <DataTable
              rows={rows}
              filename="simulation_results"
              maxHeight="480px"
              dense
              initialSort={{ key: 'cost', desc: true }}
              columns={[
                { key: 'active_sku_id', label: 'SKU' },
                { key: 'policy' },
                { key: 'fill_rate', align: 'right', render: (r) => pct(num(r.fill_rate)) },
                { key: 'cost', align: 'right', render: (r) => compactLkr(num(r.cost)) },
                { key: 'lost_units', align: 'right', render: (r) => int(num(r.lost_units)) },
                { key: 'orders_placed', align: 'right', render: (r) => int(num(r.orders_placed)) },
                { key: 'conservation_error', align: 'right', render: (r) => dec(num(r.conservation_error), 6) },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

export default function Inventory() {
  const [tab, setTab] = useState<Tab>('stock')
  return (
    <>
      <PageHeader
        title="Policy & Stock"
        subtitle="Steps 12 and 13 — what is on the shelf, what policy each SKU runs, and how the selected policy scored against the current baseline on the sealed holdout."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'stock' && <StockTab />}
      {tab === 'policy' && <PolicyTab />}
      {tab === 'sim' && <SimTab />}
    </>
  )
}
