import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { num, str, type Page } from '../api'
import { compact, int, pct } from '../format'
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
import { Bars } from '../components/charts'

const TABS = [
  { id: 'search', label: 'Search' },
  { id: 'supersession', label: 'Supersession' },
  { id: 'chains', label: 'Chains' },
] as const
type Tab = (typeof TABS)[number]['id']

interface Hit {
  part_no: string
  label: string
  description: string | null
  active_sku_id: string | null
}

interface SupersessionResponse {
  query: string
  found: boolean
  hits: Hit[]
}

const LABEL_TONE: Record<string, 'blue' | 'green' | 'slate' | 'amber'> = {
  QUERIED: 'blue',
  CURRENT: 'green',
  OLDER: 'slate',
  RELATED: 'amber',
}

function SearchTab() {
  const [q, setQ] = useState('')
  const [brand, setBrand] = useState('')
  const [group, setGroup] = useState('')
  const query = useDebounced(q)

  const master = useTable('part_master', { limit: 20000 })
  const all = master.data ?? []

  const brands = useMemo(
    () => Array.from(new Set(all.map((r) => str(r.brand)))).filter(Boolean).sort(),
    [all],
  )
  const groups = useMemo(
    () => Array.from(new Set(all.map((r) => str(r.material_group)))).filter(Boolean).sort(),
    [all],
  )

  const page = useEndpoint<Page>('/parts/search', {
    limit: 500,
    ...(query ? { q: query } : {}),
    ...(brand ? { brand } : {}),
    ...(group ? { group } : {}),
  })
  const rows = page.data?.rows ?? []

  const withModels = all.filter((r) => str(r.compatible_models)).length
  const chainHeads = all.filter((r) => r.is_chain_head === true).length

  const byBrand = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of all) m.set(str(r.brand, '—') || '—', (m.get(str(r.brand, '—') || '—') ?? 0) + 1)
    return Array.from(m, ([name, parts]) => ({ brand: name, parts }))
  }, [all])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-5">
        <Kpi label="Parts in master" value={compact(all.length)} tone="blue" />
        <Kpi label="Chain heads" value={compact(chainHeads)} hint="a part nothing supersedes" tone="slate" />
        <Kpi
          label="With model compatibility"
          value={compact(withModels)}
          hint={all.length ? pct(withModels / all.length) : undefined}
          tone="amber"
        />
        <Kpi label="Brands" value={int(brands.length)} tone="purple" />
        <Kpi label="Material groups" value={int(groups.length)} tone="teal" />
      </div>

      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <TextInput
            label="Search part number or description"
            value={q}
            onChange={setQ}
            placeholder="e.g. FILTER or 94701"
            className="w-80"
          />
          <Select
            label="Brand"
            value={brand}
            options={[{ value: '', label: 'All brands' }, ...brands.map((b) => ({ value: b, label: b }))]}
            onChange={setBrand}
            className="w-40"
          />
          <Select
            label="Material group"
            value={group}
            options={[{ value: '', label: 'All groups' }, ...groups.map((g) => ({ value: g, label: g }))]}
            onChange={setGroup}
            className="w-52"
          />
          <div className="ml-auto flex items-center gap-1.5 text-xs text-slate-500">
            <Search size={13} /> {int(num(page.data?.total))} matches · {rows.length} shown
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-5">
        <Card title="Parts by brand" className="xl:col-span-1">
          <Async state={master}>
            {() => <Bars data={byBrand} x="brand" series={[{ key: 'parts', label: 'parts' }]} height={240} horizontal />}
          </Async>
        </Card>
        <Card title="Part master" subtitle="one row per material, with the identity it resolves to" className="xl:col-span-3">
          <Async state={page}>
            {() => (
              <DataTable
                rows={rows}
                filename="part_master"
                dense
                maxHeight="480px"
                columns={[
                  { key: 'material' },
                  { key: 'active_sku_id', label: 'active SKU', render: (r) => <strong>{str(r.active_sku_id)}</strong> },
                  { key: 'description' },
                  { key: 'brand' },
                  { key: 'material_group', label: 'group' },
                  { key: 'material_type', label: 'type' },
                  { key: 'chain_depth', label: 'depth', align: 'right' },
                  { key: 'is_chain_head', label: 'head' },
                  { key: 'compatible_models', label: 'models' },
                ]}
              />
            )}
          </Async>
          <Note>
            <code>active_sku_id</code> is the one identity a part is planned under. Model compatibility comes
            from the PDF catalogues and covers only part of the master — a gap that limits how many parts can
            be tied to a fleet cohort.
          </Note>
        </Card>
      </div>
    </>
  )
}

function SupersessionTab() {
  const [input, setInput] = useState('')
  const part = useDebounced(input.trim())
  const state = useEndpoint<SupersessionResponse>(part ? `/parts/${encodeURIComponent(part)}/supersession` : null)

  return (
    <>
      <Card className="mb-5" title="Resolve a part number" subtitle="enter any number in a chain — old or current">
        <TextInput label="Part number" value={input} onChange={setInput} placeholder="e.g. 94701-00254" className="w-80" />
      </Card>

      {part && state.loading && <Loading />}
      {state.error && <ErrorBox message={state.error} />}

      {state.data && (
        <Card
          title={state.data.found ? `Chain for ${state.data.query}` : `No match for ${state.data.query}`}
          subtitle={`${state.data.hits.length} related number(s)`}
        >
          {state.data.hits.length === 0 ? (
            <p className="text-sm text-slate-500 py-6 text-center">
              Nothing in the part master matches that number, in any supersede column.
            </p>
          ) : (
            <div className="space-y-2">
              {state.data.hits.map((h) => (
                <div
                  key={`${h.label}-${h.part_no}`}
                  className="flex items-center gap-4 px-4 py-3 rounded-lg border border-slate-200"
                >
                  <Badge tone={LABEL_TONE[h.label] ?? 'slate'}>{h.label}</Badge>
                  <span className="font-medium text-slate-800">{h.part_no}</span>
                  <span className="text-sm text-slate-500 flex-1">{h.description ?? '—'}</span>
                  {h.active_sku_id && (
                    <span className="text-xs text-slate-500">
                      plans as <strong className="text-slate-700">{h.active_sku_id}</strong>
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          <Note>
            A counter clerk types whichever number is printed on the box. Resolving it to the active SKU is
            what keeps one physical part's demand in one series instead of splitting it across every number it
            has ever carried.
          </Note>
        </Card>
      )}
    </>
  )
}

function ChainsTab() {
  const chains = useTable('supersession_chains', { sort: 'depth', desc: true, limit: 20000 })
  const rows = chains.data ?? []
  const deep = rows.filter((r) => num(r.depth) > 0)
  const disagree = rows.filter((r) => r.agrees_with_latest_ss === false)

  const byDepth = useMemo(() => {
    const m = new Map<number, number>()
    for (const r of rows) m.set(num(r.depth), (m.get(num(r.depth)) ?? 0) + 1)
    return Array.from(m, ([depth, parts]) => ({ depth: String(depth), parts })).sort(
      (a, b) => Number(a.depth) - Number(b.depth),
    )
  }, [rows])

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi label="Chains resolved" value={compact(rows.length)} tone="blue" />
        <Kpi label="Parts superseded" value={compact(deep.length)} hint="depth > 0" tone="purple" />
        <Kpi
          label="Disagrees with Latest SS"
          value={compact(disagree.length)}
          hint="walked chain vs the pre-resolved column"
          tone="amber"
        />
        <Kpi label="Cycles found" value="0" hint="A→B→A would fail the stage" tone="green" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <Card title="Chain depth distribution">
          <Async state={chains}>
            {() => <Bars data={byDepth} x="depth" series={[{ key: 'parts', label: 'parts' }]} height={260} />}
          </Async>
        </Card>
        <Card title="Resolved chains" className="xl:col-span-2">
          <Async state={chains}>
            {() => (
              <DataTable
                rows={rows}
                filename="supersession_chains"
                dense
                maxHeight="440px"
                initialSort={{ key: 'depth', desc: true }}
                columns={[
                  { key: 'material' },
                  { key: 'active_sku_id', label: 'active SKU' },
                  { key: 'latest_ss', label: 'Latest SS' },
                  { key: 'depth', align: 'right' },
                  { key: 'agrees_with_latest_ss', label: 'agrees' },
                  { key: 'chain' },
                ]}
              />
            )}
          </Async>
          <Note>
            <code>Latest SS</code> arrives pre-resolved in the source workbook and is verified against the
            walked chain, not recomputed over it. Where the two disagree the walked chain is reported
            alongside, so the discrepancy is visible rather than silently overwritten.
          </Note>
        </Card>
      </div>
    </>
  )
}

export default function PartMaster() {
  const [tab, setTab] = useState<Tab>('search')
  return (
    <>
      <PageHeader
        title="Part Master"
        subtitle="Step 02 — one identity per physical part. Every demand series, forecast and order line in this system is keyed on the active SKU that these chains resolve to."
        right={<Tabs tabs={TABS} active={tab} onChange={setTab} />}
      />
      {tab === 'search' && <SearchTab />}
      {tab === 'supersession' && <SupersessionTab />}
      {tab === 'chains' && <ChainsTab />}
    </>
  )
}
