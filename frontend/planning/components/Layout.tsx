import { type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Activity,
  Bike,
  BookOpen,
  Boxes,
  FileWarning,
  Gauge,
  Layers,
  LayoutDashboard,
  Package,
  PlayCircle,
  ShoppingCart,
  Sigma,
  TrendingUp,
  Truck,
} from 'lucide-react'
import { useEndpoint } from '../hooks'
import type { Health } from '../api'

export interface NavItem {
  to: string
  label: string
  icon: ReactNode
}

const SIZE = 16

export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: 'Plan',
    items: [
      { to: '/', label: 'Overview', icon: <LayoutDashboard size={SIZE} /> },
      { to: '/order-plan', label: 'Monthly Order', icon: <ShoppingCart size={SIZE} /> },
      { to: '/inventory', label: 'Policy & Stock', icon: <Boxes size={SIZE} /> },
    ],
  },
  {
    group: 'Demand',
    items: [
      { to: '/spare-parts', label: 'Spare Parts Analysis', icon: <Package size={SIZE} /> },
      { to: '/classification', label: 'Classification', icon: <Layers size={SIZE} /> },
      { to: '/forecast', label: 'Demand Forecast', icon: <TrendingUp size={SIZE} /> },
    ],
  },
  {
    group: 'Fleet',
    items: [
      { to: '/unit-sales', label: 'MC Analysis', icon: <Bike size={SIZE} /> },
      { to: '/registrations', label: 'MC Sales Forecast', icon: <Truck size={SIZE} /> },
      { to: '/parc', label: 'UIO & Parc', icon: <Sigma size={SIZE} /> },
    ],
  },
  {
    group: 'Reference',
    items: [
      { to: '/parts', label: 'Part Master', icon: <Gauge size={SIZE} /> },
      { to: '/catalogues', label: 'Catalogues', icon: <BookOpen size={SIZE} /> },
      { to: '/exceptions', label: 'Exceptions', icon: <FileWarning size={SIZE} /> },
      { to: '/pipeline', label: 'Pipeline', icon: <PlayCircle size={SIZE} /> },
    ],
  },
]

function Freshness() {
  const health = useEndpoint<Health>('/health')
  const h = health.data
  const served = h?.tables ?? []
  const present = served.filter((t) => t.present).length
  const total = served.length
  const ok = h?.status === 'ok'
  return (
    <div className="px-4 py-3 mx-3 mb-3 rounded-lg bg-white/5 text-[11px] text-slate-400 leading-relaxed">
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`inline-block w-2 h-2 rounded-full ${
            health.loading ? 'bg-slate-500' : ok ? 'bg-brand-green' : 'bg-brand-red'
          }`}
        />
        <span className="text-slate-300 font-medium">
          {health.loading ? 'checking' : ok ? 'API healthy' : (h?.status ?? 'unreachable')}
        </span>
      </div>
      <div>
        {present}/{total} tables published
      </div>
      {h?.as_of && <div>{h.as_of}</div>}
    </div>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <aside className="w-60 shrink-0 bg-sidebar text-slate-300 flex flex-col overflow-y-auto no-scrollbar">
        <div className="px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-brand-blue" />
            <span className="text-white font-semibold text-sm leading-tight">Spare Parts Planning</span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Yamaha · AMW Sri Lanka · LKR</p>
        </div>

        <nav className="flex-1 py-3">
          {NAV.map((g) => (
            <div key={g.group} className="mb-3">
              <p className="px-5 py-1 text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
                {g.group}
              </p>
              {g.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 px-5 py-2 text-[13px] transition-colors border-l-2 ${
                      isActive
                        ? 'bg-white/10 text-white border-brand-blue'
                        : 'border-transparent text-slate-400 hover:text-white hover:bg-white/5'
                    }`
                  }
                >
                  {item.icon}
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <Freshness />
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-[1500px] mx-auto px-7 py-7">{children}</div>
      </main>
    </>
  )
}
