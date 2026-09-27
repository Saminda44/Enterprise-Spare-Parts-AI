import { useMemo, useState } from 'react'
import { num, str } from '../api'
import { compact, compactLkr, int, pct } from '../format'
import { usePagedTable, useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, Select, Tabs } from '../components/ui'
import { Bars } from '../components/charts'

const TABS = [
  { id: 'all', label: 'All exceptions' },
  { id: 'orders', label: 'Order rejects' },
  { id: 'catalogue', label: 'Catalogue rejects' },
] as const
type Tab = (typeof TABS)[number]['id']

function reasonCounts(rows: Record<string, unknown>[]) {
  const m = new Map<string, number>()
  for (const r of rows) m.set(str(r.reason, 'unknown'), (m.get(str(r.reason, 'unknown')) ?? 0) + 1)
  return Array.from(m, ([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count)
}

function AllExceptions() {
  const [source, setSource] = useState('')
  const [offset, setOffset] = useState(0)

  const summary = useTable('mart_exceptions', { limit: 20000 })
  const page = usePagedTable('mart_exceptions', {
    limit: 500,
    offset,
    ...(source ? { where: `source=${source}` } : {}),
  })

  const all = summary.data ?? []
  const sources = useMemo(() => Array.from(new Set(all.map((r) => str(r.source)))).filter(Boolean).sort(), [all])
  const reasons = useMemo(
    () => reasonCounts(source ? all.filter((r) => str(r.source) === source) : all).slice(0, 12),
    [all, source],
  )

  const rows = page.data?.rows ?? []
  const total = num(page.data?.total)
  const lostValue = all.reduce((a, r) => a + num(r['Net Price']) * num(r['Order Quantity (Item)']), 0)

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Rejected rows" value={compact(all.length)} hint="every one carries a reason" tone="red" />
        <Kpi label="Distinct reasons" value={int(reasonCounts(all).length)} tone="amber" />
        <Kpi label="Sources" value={int(sources.length)} tone="slate" />
        <Kpi label="Value at stake" value={compactLkr(lostValue)} hint="order quantity × net price" tone="purple" />
      </div>

      <Card className="mb-5" title="Why rows were rejected" subtitle="top reasons">
        <div className="mb-4">
          <Select
            label="Source"
            value={source}
            options={[{ value: '', label: 'All sources' }, ...sources.map((s) => ({ value: s, label: s }))]}
            onChange={(v) => {
              setSource(v)
              setOffset(0)
            }}
            className="w-64"
          />
        </div>
        <Async state={summary}>
          {() => <Bars data={reasons} x="reason" series={[{ key: 'count', label: 'rows' }]} height={Math.max(240, reasons.length * 26)} horizontal />}
        </Async>
        <Note>
          Nothing is dropped silently. A row that cannot be matched, parsed or classified is written to the
          exceptions table with a reason and a count, so the difference between the source row count and the
          modelled row count is always explainable.
        </Note>
      </Card>

      <Card
        title="Exception rows"
        subtitle={`${int(total)} rows · showing ${rows.length ? offset + 1 : 0}–${offset + rows.length}`}
        right={
          <div className="flex gap-2 text-xs">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 500))}
              className="px-3 py-1.5 rounded-md border border-slate-200 disabled:opacity-40 hover:border-slate-400"
            >
              Previous
            </button>
            <button
              disabled={offset + rows.length >= total}
              onClick={() => setOffset(offset + 500)}
              className="px-3 py-1.5 rounded-md border border-slate-200 disabled:opacity-40 hover:border-slate-400"
            >
              Next
            </button>
          </div>
        }
      >
        <Async state={page}>
          {() => (
            <DataTable
              rows={rows}
              filename="mart_exceptions"
              dense
              maxHeight="520px"
              columns={[
                { key: 'source' },
                { key: 'reason' },
                { key: 'Sales Document', label: 'document' },
                { key: 'Material' },
                { key: 'Material Description', label: 'description' },
                { key: 'Sold-To Party Name', label: 'dealer' },
                { key: 'Order Quantity (Item)', label: 'qty', align: 'right' },
                { key: 'Net Price', label: 'net price', align: 'right' },
                { key: 'pdf_file', label: 'pdf' },
                { key: 'part_no', label: 'part' },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function OrderRejects() {
  const summary = useTable('order_exceptions', { limit: 20000 })
  const all = summary.data ?? []
  const reasons = useMemo(() => reasonCounts(all), [all])
  const orders = useTable('orders_by_material', { limit: 20000 })
  const modelled = (orders.data ?? []).reduce((a, r) => a + num(r.order_lines), 0)

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Order lines rejected" value={compact(all.length)} tone="red" />
        <Kpi label="Order lines modelled" value={compact(modelled)} tone="green" />
        <Kpi
          label="Reject share"
          value={modelled + all.length ? pct(all.length / (modelled + all.length)) : '—'}
          tone="amber"
        />
        <Kpi label="Distinct reasons" value={int(reasons.length)} tone="slate" />
      </div>

      <Card className="mb-5" title="Rejection reasons">
        <Async state={summary}>
          {() => <Bars data={reasons} x="reason" series={[{ key: 'count', label: 'lines' }]} height={Math.max(220, reasons.length * 30)} horizontal />}
        </Async>
        <Note>
          The dominant reason is a material with no part-master match on any supersede column. Those lines are
          real demand that cannot be planned until the master covers the number — they are held here, not
          quietly discarded.
        </Note>
      </Card>

      <Card title="Rejected order lines">
        <Async state={summary}>
          {(rows) => (
            <DataTable
              rows={rows.slice(0, 2000)}
              filename="order_exceptions"
              dense
              maxHeight="520px"
              columns={[
                { key: 'Document Date', label: 'date' },
                { key: 'Sales Document', label: 'document' },
                { key: 'SD Document Category', label: 'cat' },
                { key: 'Material' },
                { key: 'Material Description', label: 'description' },
                { key: 'Sold-To Party Name', label: 'dealer' },
                { key: 'Order Quantity (Item)', label: 'ordered', align: 'right' },
                { key: 'Confirmed Quantity (Item)', label: 'confirmed', align: 'right' },
                { key: 'Net Price', label: 'net price', align: 'right' },
                { key: 'reason' },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

function CatalogueRejects() {
  const state = useTable('catalogue_exceptions', { limit: 20000 })
  const rows = state.data ?? []
  const reasons = useMemo(() => reasonCounts(rows), [rows])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-5">
        <Kpi label="Unresolved remarks" value={compact(rows.length)} tone="amber" />
        <Kpi label="Distinct reasons" value={int(reasons.length)} tone="slate" />
        <Kpi label="PDFs affected" value={int(new Set(rows.map((r) => str(r.pdf_file))).size)} tone="blue" />
      </div>

      <Card className="mb-5" title="Why a remark could not be resolved">
        <Async state={state}>
          {() => <Bars data={reasons} x="reason" series={[{ key: 'count', label: 'remarks' }]} height={Math.max(220, reasons.length * 30)} horizontal />}
        </Async>
      </Card>

      <Card title="Unresolved catalogue remarks">
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="catalogue_exceptions"
              dense
              maxHeight="520px"
              columns={[
                { key: 'pdf_file', label: 'file' },
                { key: 'part_no', label: 'part' },
                { key: 'remark' },
                { key: 'reason' },
              ]}
            />
          )}
        </Async>
      </Card>
    </>
  )
}

export default function Exceptions() {
  const [tab, setTab] = useState<Tab>('all')
  return (
    <>
      <PageHeader
        title="Exceptions"
        subtitle="Every row the pipeline could not use, with the reason it was set aside. The reject tables are the audit trail for the gap between what the source files contain and what the model plans on."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'all' && <AllExceptions />}
      {tab === 'orders' && <OrderRejects />}
      {tab === 'catalogue' && <CatalogueRejects />}
    </>
  )
}
