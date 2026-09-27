/** Sri Lanka rupees. Never assume USD — the whole pipeline is priced in LKR. */
export function lkr(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `LKR ${v.toLocaleString('en-LK', { maximumFractionDigits: digits })}`
}

export function compactLkr(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) return `LKR ${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `LKR ${(v / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `LKR ${(v / 1e3).toFixed(0)}K`
  return `LKR ${v.toFixed(0)}`
}

export function compact(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return v.toLocaleString('en-LK', { maximumFractionDigits: 2 })
}

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return Math.round(v).toLocaleString('en-LK')
}

export function dec(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

/** Values already expressed as percent points, not a 0–1 share. */
export function pctPoints(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}%`
}

export function cell(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—'
    return Number.isInteger(v) ? v.toLocaleString('en-LK') : v.toFixed(3)
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}
