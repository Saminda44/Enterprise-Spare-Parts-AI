import { useMemo, useState, type ReactNode } from 'react'
import { AlertTriangle, ArrowDown, ArrowUp, Download, Inbox, Loader2 } from 'lucide-react'
import { cell } from '../format'
import type { Row } from '../api'

export function Card({
  title,
  subtitle,
  right,
  children,
  className = '',
}: {
  title?: ReactNode
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`bg-white rounded-xl border border-slate-200 shadow-sm ${className}`}>
      {(title || right) && (
        <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-3 border-b border-slate-100">
          <div>
            {title && <h3 className="text-sm font-semibold text-slate-800">{title}</h3>}
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  )
}

const TONES: Record<string, string> = {
  blue: 'text-brand-blue bg-brand-blue/10',
  green: 'text-brand-green bg-brand-green/10',
  amber: 'text-amber-600 bg-amber-500/10',
  red: 'text-brand-red bg-brand-red/10',
  purple: 'text-brand-purple bg-brand-purple/10',
  teal: 'text-brand-teal bg-brand-teal/10',
  slate: 'text-slate-600 bg-slate-500/10',
}

export function Kpi({
  label,
  value,
  hint,
  tone = 'blue',
  icon,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: keyof typeof TONES
  icon?: ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">{label}</p>
        {icon && <span className={`rounded-lg p-1.5 ${TONES[tone]}`}>{icon}</span>}
      </div>
      <p className="text-2xl font-semibold text-slate-900 mt-2 tabular-nums">{value}</p>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  )
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: keyof typeof TONES }) {
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string
  subtitle?: ReactNode
  right?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500 mt-1 max-w-3xl">{subtitle}</p>}
      </div>
      {right}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-1 gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-4 py-1.5 text-sm rounded-md transition-colors ${
            active === t.id
              ? 'bg-white text-slate-900 shadow-sm font-medium'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function PillToggles<T extends string>({
  options,
  active,
  onToggle,
}: {
  options: readonly { id: T; label: string }[]
  active: readonly T[]
  onToggle: (id: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = active.includes(o.id)
        return (
          <button
            key={o.id}
            onClick={() => onToggle(o.id)}
            className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
              on
                ? 'bg-brand-blue text-white border-brand-blue'
                : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'
            }`}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Select({
  label,
  value,
  options,
  onChange,
  className = '',
}: {
  label?: string
  value: string
  options: readonly { value: string; label: string }[]
  onChange: (v: string) => void
  className?: string
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      {label && (
        <span className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">{label}</span>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function TextInput({
  label,
  value,
  onChange,
  placeholder,
  className = '',
}: {
  label?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      {label && (
        <span className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">{label}</span>
      )}
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-blue/30"
      />
    </label>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 py-8 justify-center">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

export function Empty({ label = 'No rows' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 text-sm text-slate-400 py-10">
      <Inbox size={22} />
      {label}
    </div>
  )
}

/** Wraps the three states every data panel has, so no page repeats the ternary. */
export function Async<T>({
  state,
  children,
  emptyLabel,
}: {
  state: { data: T | null; loading: boolean; error: string | null }
  children: (data: T) => ReactNode
  emptyLabel?: string
}) {
  if (state.loading) return <Loading />
  if (state.error) return <ErrorBox message={state.error} />
  if (state.data === null) return <Empty label={emptyLabel} />
  if (Array.isArray(state.data) && state.data.length === 0) return <Empty label={emptyLabel} />
  return <>{children(state.data)}</>
}

export interface Column {
  key: string
  label?: string
  align?: 'left' | 'right'
  render?: (row: Row) => ReactNode
  width?: string
}

const CSV_ESCAPE = /["\n,]/

function csvField(value: unknown): string {
  const s = value === null || value === undefined ? '' : String(value)
  return CSV_ESCAPE.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

function toCsv(rows: Row[], columns: Column[]): string {
  const head = columns.map((c) => csvField(c.label ?? c.key)).join(',')
  const body = rows.map((r) => columns.map((c) => csvField(r[c.key])).join(','))
  return [head, ...body].join('\n')
}

export function DataTable({
  rows,
  columns,
  maxHeight = '520px',
  filename,
  initialSort,
  dense = false,
}: {
  rows: Row[]
  columns: Column[]
  maxHeight?: string
  filename?: string
  initialSort?: { key: string; desc: boolean }
  dense?: boolean
}) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(initialSort ?? null)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const { key, desc } = sort
    const out = [...rows]
    out.sort((a, b) => {
      const x = a[key]
      const y = b[key]
      if (x === null || x === undefined) return 1
      if (y === null || y === undefined) return -1
      if (typeof x === 'number' && typeof y === 'number') return desc ? y - x : x - y
      const sx = String(x)
      const sy = String(y)
      return desc ? sy.localeCompare(sx) : sx.localeCompare(sy)
    })
    return out
  }, [rows, sort])

  const download = () => {
    const blob = new Blob([toCsv(sorted, columns)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (filename ?? 'table') + '.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  if (rows.length === 0) return <Empty />

  const pad = dense ? 'px-3 py-1.5' : 'px-3 py-2'

  return (
    <div>
      {filename && (
        <div className="flex justify-end mb-2">
          <button
            onClick={download}
            className="inline-flex items-center gap-1.5 text-xs text-slate-600 hover:text-brand-blue"
          >
            <Download size={13} /> CSV ({sorted.length.toLocaleString()} rows shown)
          </button>
        </div>
      )}
      <div className="overflow-auto rounded-lg border border-slate-200" style={{ maxHeight }}>
        <table className="grid w-full text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 text-slate-600">
              {columns.map((c) => (
                <th
                  key={c.key}
                  style={c.width ? { width: c.width } : undefined}
                  onClick={() =>
                    setSort((s) =>
                      s && s.key === c.key ? { key: c.key, desc: !s.desc } : { key: c.key, desc: true },
                    )
                  }
                  className={`${pad} text-[11px] uppercase tracking-wide font-semibold border-b border-slate-200 cursor-pointer select-none whitespace-nowrap ${
                    c.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {c.label ?? c.key}
                    {sort?.key === c.key && (sort.desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i} className="odd:bg-white even:bg-slate-50/50 hover:bg-brand-blue/5">
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`${pad} border-b border-slate-100 text-slate-700 ${
                      c.align === 'right' ? 'text-right tabular-nums' : 'text-left'
                    }`}
                  >
                    {c.render ? c.render(r) : cell(r[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Column list straight from the table's own schema, for raw exploration panels. */
export function autoColumns(rows: Row[], limit = 12): Column[] {
  if (rows.length === 0) return []
  return Object.keys(rows[0])
    .slice(0, limit)
    .map((k) => ({
      key: k,
      align: typeof rows[0][k] === 'number' ? ('right' as const) : ('left' as const),
    }))
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-slate-500 leading-relaxed border-l-2 border-slate-200 pl-3 mt-3">{children}</p>
}
