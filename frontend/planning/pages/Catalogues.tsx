import { useMemo, useState } from 'react'
import { num, str } from '../api'
import { compact, dec, int, pct } from '../format'
import { useDebounced, usePagedTable, useTable } from '../hooks'
import { Async, Card, DataTable, Kpi, Note, PageHeader, Select, Tabs, TextInput } from '../components/ui'
import { Bars, Donut } from '../components/charts'

const TABS = [
  { id: 'layouts', label: 'PDF layouts' },
  { id: 'parts', label: 'Extracted parts' },
  { id: 'colours', label: 'Colour variants' },
] as const
type Tab = (typeof TABS)[number]['id']

function Layouts() {
  const state = useTable('catalogue_layouts', { sort: 'parts', desc: true, limit: 1000 })
  const rows = state.data ?? []

  const parts = rows.reduce((a, r) => a + num(r.parts), 0)
  const pages = rows.reduce((a, r) => a + num(r.pages), 0)
  const noParts = rows.filter((r) => num(r.parts) === 0).length
  const noColour = rows.filter((r) => num(r.colours) === 0).length

  const byLayout = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.layout, 'unknown'), (m.get(str(r.layout, 'unknown')) ?? 0) + 1)
    return Array.from(m, ([name, pdfs]) => ({ name, pdfs }))
  }, [rows])

  const byFolder = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(str(r.folder, '—'), (m.get(str(r.folder, '—')) ?? 0) + num(r.parts))
    return Array.from(m, ([folder, partsCount]) => ({ folder, parts: partsCount }))
      .sort((a, b) => b.parts - a.parts)
      .slice(0, 20)
  }, [rows])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="PDFs parsed" value={int(rows.length)} tone="blue" />
        <Kpi label="Pages read" value={compact(pages)} tone="slate" />
        <Kpi label="Parts extracted" value={compact(parts)} tone="green" />
        <Kpi label="PDFs yielding nothing" value={int(noParts)} hint="layout not recognised" tone="red" />
        <Kpi label="No colour table" value={int(noColour)} hint="variant assignment falls back to shared" tone="amber" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-5">
        <Card title="Layouts recognised">
          <Async state={state}>{() => <Donut data={byLayout} nameKey="name" valueKey="pdfs" height={240} />}</Async>
        </Card>
        <Card title="Parts by model folder" subtitle="top 20" className="xl:col-span-2">
          <Async state={state}>
            {() => <Bars data={byFolder} x="folder" series={[{ key: 'parts', label: 'parts' }]} height={280} horizontal />}
          </Async>
        </Card>
      </div>

      <Card title="Per-PDF extraction result" subtitle="with the warning that explains a thin result">
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="catalogue_layouts"
              dense
              maxHeight="480px"
              initialSort={{ key: 'parts', desc: true }}
              columns={[
                { key: 'pdf_file', label: 'file' },
                { key: 'folder' },
                { key: 'pages', align: 'right' },
                { key: 'layout' },
                { key: 'model_codes', label: 'model codes' },
                { key: 'colours', align: 'right' },
                { key: 'parts', align: 'right', render: (r) => int(num(r.parts)) },
                { key: 'confirmed_variants', label: 'confirmed variants' },
                { key: 'warnings' },
              ]}
            />
          )}
        </Async>
        <Note>
          PDFs are untrusted input: each is size-capped and parsed defensively, and a file that yields nothing
          is recorded as such rather than skipped. Known gap: only part of the set had a parseable
          applicable-colour table, so most rows resolve to <code>shared</code> and colour-variant assignment
          stays weak.
        </Note>
      </Card>
    </>
  )
}

function Parts() {
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('')
  const [offset, setOffset] = useState(0)
  const q = useDebounced(search.trim())

  const page = usePagedTable('catalogue_parts', {
    limit: 500,
    offset,
    ...(q ? { contains: `part_no=${q}` } : {}),
    ...(kind ? { where: `part_kind=${kind}` } : {}),
  })
  const rows = page.data?.rows ?? []
  const total = num(page.data?.total)

  return (
    <>
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <TextInput
            label="Part number contains"
            value={search}
            onChange={(v) => {
              setSearch(v)
              setOffset(0)
            }}
            className="w-72"
          />
          <Select
            label="Part kind"
            value={kind}
            options={[
              { value: '', label: 'All kinds' },
              { value: 'shared', label: 'shared' },
              { value: 'colour', label: 'colour' },
            ]}
            onChange={(v) => {
              setKind(v)
              setOffset(0)
            }}
            className="w-44"
          />
          <div className="ml-auto flex items-center gap-3 text-xs text-slate-500">
            <span>
              {int(total)} rows · showing {offset + 1}–{offset + rows.length}
            </span>
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
        </div>
      </Card>

      <Card title="Catalogue parts" subtitle="one row per part occurrence, with the rule that classified it">
        <Async state={page}>
          {() => (
            <DataTable
              rows={rows}
              filename="catalogue_parts"
              dense
              maxHeight="560px"
              columns={[
                { key: 'pdf_file', label: 'file' },
                { key: 'folder' },
                { key: 'model_code', label: 'model' },
                { key: 'part_no', label: 'part' },
                { key: 'description' },
                { key: 'qty', align: 'right' },
                { key: 'part_kind', label: 'kind' },
                { key: 'colour_name', label: 'colour' },
                { key: 'rule_applied', label: 'rule' },
                { key: 'confidence', align: 'right', render: (r) => dec(num(r.confidence), 2) },
                { key: 'page', align: 'right' },
              ]}
            />
          )}
        </Async>
        <Note>
          Extraction confidence below 0.85 on a page is a stop-and-ask condition, not a silent pass. The{' '}
          <code>rule_applied</code> column names which colour rule fired, so any assignment can be traced back
          to the remark text it came from.
        </Note>
      </Card>
    </>
  )
}

function Colours() {
  const state = useTable('model_colour_variants', { limit: 1000 })
  const rows = state.data ?? []
  const confirmed = rows.filter((r) => r.confirmed === true).length
  const modelColour = rows.filter((r) => r.is_model_colour === true).length

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Variants found" value={int(rows.length)} tone="blue" />
        <Kpi label="Confirmed" value={int(confirmed)} hint={rows.length ? pct(confirmed / rows.length) : undefined} tone="green" />
        <Kpi label="Model colours" value={int(modelColour)} tone="purple" />
        <Kpi label="Distinct PDFs" value={int(new Set(rows.map((r) => str(r.pdf_file))).size)} tone="slate" />
      </div>

      <Card title="Model colour variants" subtitle="from each catalogue's applicable-colour table">
        <Async state={state}>
          {() => (
            <DataTable
              rows={rows}
              filename="model_colour_variants"
              dense
              maxHeight="520px"
              columns={[
                { key: 'pdf_file', label: 'file' },
                { key: 'model_code', label: 'model' },
                { key: 'colour_abbr', label: 'abbr' },
                { key: 'colour_name', label: 'colour' },
                { key: 'colour_code', label: 'code' },
                { key: 'is_model_colour', label: 'model colour' },
                { key: 'confirmed' },
              ]}
            />
          )}
        </Async>
        <Note>
          A colour abbreviation only becomes a variant when the PDF's own colour table confirms it. An
          <code> EXCEPT</code> remark inverts against that confirmed set rather than against every colour
          mentioned anywhere, which is what stops one stray abbreviation inventing a variant.
        </Note>
      </Card>
    </>
  )
}

export default function Catalogues() {
  const [tab, setTab] = useState<Tab>('layouts')
  return (
    <>
      <PageHeader
        title="Parts Catalogues"
        subtitle="Step 01 — the PDF parts books, parsed into parts, model codes and colour variants. This is where model compatibility comes from, which is what lets a part be tied to a fleet cohort at all."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'layouts' && <Layouts />}
      {tab === 'parts' && <Parts />}
      {tab === 'colours' && <Colours />}
    </>
  )
}
