import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { compact } from '../format'

export const PALETTE = [
  '#4361EE',
  '#2CC56F',
  '#FFC107',
  '#7C3AED',
  '#06B6D4',
  '#EF4444',
  '#F97316',
  '#0EA5E9',
  '#84CC16',
  '#EC4899',
]

const AXIS = { fontSize: 11, fill: '#64748B' }
const GRID = '#E2E8F0'

type Datum = Record<string, unknown>

interface Series {
  key: string
  label?: string
  color?: string
}

const tooltipStyle = {
  contentStyle: {
    borderRadius: 8,
    border: '1px solid #E2E8F0',
    fontSize: 12,
    boxShadow: '0 4px 12px rgba(15,23,42,0.08)',
  },
} as const

function fmt(v: unknown): string {
  return typeof v === 'number' ? compact(v) : String(v ?? '')
}

export function Bars({
  data,
  x,
  series,
  height = 260,
  horizontal = false,
  stacked = false,
}: {
  data: Datum[]
  x: string
  series: Series[]
  height?: number
  horizontal?: boolean
  stacked?: boolean
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={AXIS} tickFormatter={fmt} />
            <YAxis type="category" dataKey={x} tick={AXIS} width={140} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} tick={AXIS} interval="preserveStartEnd" />
            <YAxis tick={AXIS} tickFormatter={fmt} />
          </>
        )}
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => fmt(v)} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label ?? s.key}
            fill={s.color ?? PALETTE[i % PALETTE.length]}
            radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
            stackId={stacked ? 'a' : undefined}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Lines({
  data,
  x,
  series,
  height = 260,
}: {
  data: Datum[]
  x: string
  series: Series[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey={x} tick={AXIS} interval="preserveStartEnd" />
        <YAxis tick={AXIS} tickFormatter={fmt} />
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => fmt(v)} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label ?? s.key}
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

export function Areas({
  data,
  x,
  series,
  height = 260,
}: {
  data: Datum[]
  x: string
  series: Series[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
        <defs>
          {series.map((s, i) => (
            <linearGradient key={s.key} id={`g-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={s.color ?? PALETTE[i % PALETTE.length]} stopOpacity={0.35} />
              <stop offset="95%" stopColor={s.color ?? PALETTE[i % PALETTE.length]} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis dataKey={x} tick={AXIS} interval="preserveStartEnd" />
        <YAxis tick={AXIS} tickFormatter={fmt} />
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => fmt(v)} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label ?? s.key}
            stroke={s.color ?? PALETTE[i % PALETTE.length]}
            fill={`url(#g-${s.key})`}
            strokeWidth={2}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}

export function Donut({
  data,
  nameKey,
  valueKey,
  height = 260,
}: {
  data: Datum[]
  nameKey: string
  valueKey: string
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={data} dataKey={valueKey} nameKey={nameKey} innerRadius="52%" outerRadius="80%" paddingAngle={2}>
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip {...tooltipStyle} formatter={(v: unknown) => fmt(v)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
  )
}

/** ADI vs CV-squared, the Syntetos-Boylan routing plot. Log axes keep the lumpy tail readable. */
export function Quadrants({
  data,
  xKey,
  yKey,
  groupKey,
  xCut,
  yCut,
  height = 360,
}: {
  data: Datum[]
  xKey: string
  yKey: string
  groupKey: string
  xCut: number
  yCut: number
  height?: number
}) {
  const groups = Array.from(new Set(data.map((d) => String(d[groupKey] ?? 'unknown'))))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 16, bottom: 20, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
        <XAxis
          type="number"
          dataKey={xKey}
          name="ADI"
          scale="log"
          domain={['auto', 'auto']}
          tick={AXIS}
          tickFormatter={(v: number) => v.toFixed(1)}
          label={{ value: `ADI (cut ${xCut})`, position: 'insideBottom', offset: -8, fontSize: 11, fill: '#64748B' }}
        />
        <YAxis
          type="number"
          dataKey={yKey}
          name="CV²"
          scale="log"
          domain={['auto', 'auto']}
          tick={AXIS}
          tickFormatter={(v: number) => v.toFixed(2)}
          label={{ value: `CV² (cut ${yCut})`, angle: -90, position: 'insideLeft', fontSize: 11, fill: '#64748B' }}
        />
        <ZAxis range={[14, 14]} />
        <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: '3 3' }} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {groups.map((g, i) => (
          <Scatter
            key={g}
            name={g}
            data={data.filter((d) => String(d[groupKey] ?? 'unknown') === g)}
            fill={PALETTE[i % PALETTE.length]}
            fillOpacity={0.55}
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  )
}
