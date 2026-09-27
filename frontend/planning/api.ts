import axios from 'axios'

// In dev the Vite server proxies /api -> :8090. In the built app the planning API serves
// this bundle itself, so every call is same-origin and the prefix is empty.
export const BASE = import.meta.env.DEV ? '/api' : ''

export const http = axios.create({ baseURL: BASE, timeout: 120_000 })

export type Row = Record<string, unknown>

export interface Page {
  total: number
  limit: number
  offset: number
  rows: Row[]
}

export interface TableInfo {
  table: string
  layer: string
  present: boolean
  rows: number
  columns: string[]
}

export interface TableFreshness {
  table: string
  layer: string
  present: boolean
  age_hours: number | null
}

export interface Health {
  status: string
  as_of: string | null
  tables: TableFreshness[]
}

export interface TableQuery {
  where?: string
  contains?: string
  sort?: string
  desc?: boolean
  limit?: number
  offset?: number
}

/** Read one published table. Nothing is computed server-side; this selects and pages. */
export async function readTable(name: string, q: TableQuery = {}): Promise<Page> {
  const { data } = await http.get<Page>(`/tables/${name}`, {
    params: { limit: 1000, ...q },
  })
  return data
}

export async function listTables(): Promise<TableInfo[]> {
  const { data } = await http.get<TableInfo[]>('/tables')
  return data
}

export async function getHealth(): Promise<Health> {
  const { data } = await http.get<Health>('/health')
  return data
}

export async function getJson<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const { data } = await http.get<T>(path, { params })
  return data
}

export async function postJson<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const { data } = await http.post<T>(path, null, { params })
  return data
}

export function num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function str(v: unknown, fallback = ''): string {
  return v === null || v === undefined ? fallback : String(v)
}
