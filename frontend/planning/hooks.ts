import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getJson, readTable, type Page, type Row, type TableQuery } from './api'

export interface Async<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

function message(err: unknown): string {
  const e = err as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  const detail = e?.response?.data?.detail
  if (detail) return detail
  if (e?.response?.status === 404) return 'Not produced yet — run the pipeline.'
  return e?.message ?? 'Request failed'
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const run = useRef(fn)
  run.current = fn

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    run
      .current()
      .then((d) => {
        if (alive) setData(d)
      })
      .catch((e) => {
        if (alive) {
          setError(message(e))
          setData(null)
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, loading, error, reload }
}

/** One published table, already filtered, sorted and paged by the API. */
export function useTable(name: string, query: TableQuery = {}): Async<Row[]> {
  const key = JSON.stringify(query)
  const page = useAsync<Page>(async () => readTable(name, query), [name, key])
  const rows = useMemo(() => page.data?.rows ?? null, [page.data])
  return { data: rows, loading: page.loading, error: page.error, reload: page.reload }
}

/** The same read, keeping the row total for pagination controls. */
export function usePagedTable(name: string, query: TableQuery = {}): Async<Page> {
  const key = JSON.stringify(query)
  return useAsync<Page>(async () => readTable(name, query), [name, key])
}

export function useEndpoint<T>(path: string | null, params?: Record<string, unknown>): Async<T> {
  const key = JSON.stringify(params ?? {})
  return useAsync<T>(async () => {
    if (!path) return null as unknown as T
    return getJson<T>(path, params)
  }, [path, key])
}

/** Debounce a value so a search box does not fire a request per keystroke. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setOut(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return out
}
