import { useEffect, useRef, useState } from 'react'
import { Loader2, Play, RefreshCw } from 'lucide-react'
import { getJson, postJson, type Health, type TableInfo } from '../api'
import { compact, dec, int } from '../format'
import { useEndpoint } from '../hooks'
import {
  Async,
  Badge,
  Card,
  DataTable,
  ErrorBox,
  Kpi,
  Note,
  PageHeader,
  TextInput,
} from '../components/ui'

interface StageRow {
  stage: string
  status: string
  rows_in?: number
  rows_out?: number
  rejected?: number
  elapsed?: number
  error?: string | null
  warnings?: string[]
}

interface RunStatus {
  run_id: string
  status: string
  report: {
    stages?: StageRow[]
    settings?: Record<string, unknown>
    error?: string
    [k: string]: unknown
  } | null
}

const STATUS_TONE: Record<string, 'green' | 'red' | 'amber' | 'slate'> = {
  ok: 'green',
  succeeded: 'green',
  failed: 'red',
  running: 'amber',
  skipped: 'slate',
}

export default function Pipeline() {
  const today = new Date().toISOString().slice(0, 10)
  const [asOf, setAsOf] = useState(today)
  const [run, setRun] = useState<RunStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const poll = useRef<number | null>(null)

  const health = useEndpoint<Health>('/health')
  const tables = useEndpoint<TableInfo[]>('/tables')

  useEffect(() => {
    return () => {
      if (poll.current) window.clearInterval(poll.current)
    }
  }, [])

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      const accepted = await postJson<{ run_id: string; status: string; detail: string }>('/runs/monthly', {
        as_of: asOf,
      })
      setRun({ run_id: accepted.run_id, status: accepted.status, report: null })
      if (poll.current) window.clearInterval(poll.current)
      poll.current = window.setInterval(async () => {
        try {
          const status = await getJson<RunStatus>(`/runs/${accepted.run_id}`)
          setRun(status)
          if (status.status !== 'running') {
            if (poll.current) window.clearInterval(poll.current)
            poll.current = null
            health.reload()
            tables.reload()
          }
        } catch {
          /* keep polling; a transient failure is not a run failure */
        }
      }, 4000)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err?.response?.data?.detail ?? err?.message ?? 'Could not start the run')
    } finally {
      setStarting(false)
    }
  }

  const stages = run?.report?.stages ?? []
  const missing = (tables.data ?? []).filter((t) => !t.present)

  return (
    <>
      <PageHeader
        title="Pipeline"
        subtitle="Run the monthly cycle and watch each stage report what it read, wrote and rejected. A stage that fails stops the run — nothing downstream is computed on a broken input."
        right={
          <button
            onClick={() => {
              health.reload()
              tables.reload()
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 hover:border-slate-400"
          >
            <RefreshCw size={14} /> Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi
          label="Service"
          value={health.data?.status ?? (health.loading ? '…' : 'unreachable')}
          hint={health.data?.as_of ?? undefined}
          tone={health.data?.status === 'ok' ? 'green' : 'red'}
        />
        <Kpi label="Tables published" value={int((tables.data ?? []).filter((t) => t.present).length)} tone="blue" />
        <Kpi label="Not yet produced" value={int(missing.length)} tone={missing.length ? 'amber' : 'green'} />
        <Kpi
          label="Rows served"
          value={compact((tables.data ?? []).reduce((a, t) => a + t.rows, 0))}
          tone="slate"
        />
      </div>

      <Card className="mb-5" title="Run the monthly cycle" subtitle="stock position → policy → order proposal">
        <div className="flex flex-wrap items-end gap-4">
          <TextInput label="As of (YYYY-MM-DD)" value={asOf} onChange={setAsOf} className="w-52" />
          <button
            onClick={start}
            disabled={starting || run?.status === 'running'}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-blue text-white px-4 py-2 text-sm hover:bg-brand-blue/90 disabled:opacity-50"
          >
            {starting || run?.status === 'running' ? (
              <Loader2 size={15} className="animate-spin" />
            ) : (
              <Play size={15} />
            )}
            {run?.status === 'running' ? 'Running…' : 'Start run'}
          </button>
          {run && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <span className="text-xs text-slate-400">run</span>
              <code className="text-xs">{run.run_id}</code>
              <Badge tone={STATUS_TONE[run.status] ?? 'slate'}>{run.status}</Badge>
            </div>
          )}
        </div>
        {error && (
          <div className="mt-4">
            <ErrorBox message={error} />
          </div>
        )}
        <Note>
          A full run takes minutes, so the endpoint returns a job id straight away and the work continues in
          the background; this page polls until it settles. The order proposal it produces is a
          recommendation — nothing here writes to SAP.
        </Note>
      </Card>

      {run?.report?.error && (
        <div className="mb-5">
          <ErrorBox message={String(run.report.error)} />
        </div>
      )}

      {stages.length > 0 && (
        <Card className="mb-5" title="Stage results" subtitle={`${stages.length} stage(s) in this run`}>
          <div className="space-y-2">
            {stages.map((s) => (
              <div key={s.stage} className="rounded-lg border border-slate-200 px-4 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Badge tone={STATUS_TONE[s.status] ?? 'slate'}>{s.status}</Badge>
                  <span className="font-medium text-slate-800 text-sm">{s.stage}</span>
                  <span className="text-xs text-slate-500 tabular-nums">
                    in {int(s.rows_in ?? 0)} · out {int(s.rows_out ?? 0)} · rejected {int(s.rejected ?? 0)} ·{' '}
                    {dec(s.elapsed ?? 0, 2)}s
                  </span>
                </div>
                {s.error && <p className="text-xs text-brand-red mt-2">{s.error}</p>}
                {(s.warnings ?? []).length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {(s.warnings ?? []).map((w, i) => (
                      <li key={i} className="text-xs text-slate-500 pl-3 border-l-2 border-amber-200">
                        {w}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Published tables" subtitle="what the service can serve, and how many rows each holds">
        <Async state={tables}>
          {(rows) => (
            <DataTable
              rows={rows as unknown as Record<string, unknown>[]}
              filename="published_tables"
              dense
              maxHeight="480px"
              initialSort={{ key: 'rows', desc: true }}
              columns={[
                { key: 'table' },
                { key: 'layer' },
                {
                  key: 'present',
                  render: (r) => (r.present ? <Badge tone="green">published</Badge> : <Badge tone="amber">missing</Badge>),
                },
                { key: 'rows', align: 'right', render: (r) => int(Number(r.rows)) },
                {
                  key: 'columns',
                  label: 'columns',
                  align: 'right',
                  render: (r) => (
                    <span className="text-xs">{Array.isArray(r.columns) ? r.columns.length : '—'}</span>
                  ),
                },
              ]}
            />
          )}
        </Async>
        <Note>
          Freshness is part of health: the service reports how long ago each mart was written, so a stale
          pipeline is visible rather than silently serving last month's numbers.
        </Note>
      </Card>
    </>
  )
}
