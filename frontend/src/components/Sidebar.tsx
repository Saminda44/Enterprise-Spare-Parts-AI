import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, TrendingUp, Package, ShoppingCart,
  BookOpen, FileText,
  Activity, Search, Terminal,
} from "lucide-react";
// ── Overview ──────────────────────────────────────────────────────────────
const NAV_OVERVIEW = [
  { to: "/", label: "Overview", Icon: LayoutDashboard },
];

// ── Motorcycles ───────────────────────────────────────────────────────────
const NAV_MOTO = [
  { to: "/mcsi-eda", label: "MC Analysis",            Icon: Search     },
  { to: "/bikes",    label: "MC Sales Forecast",      Icon: TrendingUp },
  { to: "/uio",      label: "UIO Snapshot",           Icon: Activity   },
];

// ── Spare Parts ───────────────────────────────────────────────────────────
const NAV_PARTS_ANALYSIS = [
  { to: "/eda",                     label: "Spare Parts Analysis",     Icon: Package       },
  { to: "/forecast",                label: "Demand Forecast",          Icon: TrendingUp    },
  { to: "/orders",                  label: "Order Plan",               Icon: ShoppingCart  },
];

const NAV_PARTS_DATA = [
  { to: "/parts",         label: "Part Master",          Icon: BookOpen   },
];

const NAV_PARTS_CATALOG = [
  { to: "/catalog",   label: "Catalogues",      Icon: FileText  },
  { to: "/pipeline",  label: "Pipeline Runner",  Icon: Terminal  },
];

function NavItem({ to, label, Icon }: { to: string; label: string; Icon: React.ElementType }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
          isActive ? "bg-brand-blue text-white" : "text-slate-300 hover:bg-white/10 hover:text-white"
        }`
      }
    >
      <Icon size={15}/>
      {label}
    </NavLink>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 pt-3 pb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
      {children}
    </p>
  );
}

function Divider() {
  return <div className="my-2 border-t border-white/10"/>;
}

export function Sidebar() {
  return (
    <aside className="w-60 h-screen bg-sidebar text-white flex flex-col shrink-0 overflow-hidden">
      {/* Logo */}
      <div className="px-6 py-4 border-b border-white/10 shrink-0">
        <p className="text-xs text-slate-400 font-medium uppercase tracking-widest">Yamaha Sri Lanka</p>
        <h1 className="text-base font-bold leading-tight mt-0.5">Inventory Optimisation</h1>
      </div>

      <nav className="flex-1 px-3 py-2 overflow-y-auto no-scrollbar">

        {/* ── 1. Overview ── */}
        <SectionLabel>Overview</SectionLabel>
        {NAV_OVERVIEW.map(n => <NavItem key={n.to} {...n}/>)}

        <Divider/>

        {/* ── 2. Motorcycles ── */}
        <SectionLabel>Motorcycles</SectionLabel>
        {NAV_MOTO.map(n => <NavItem key={n.to} {...n}/>)}

        <Divider/>

        {/* ── 3. Spare Parts ── */}
        <SectionLabel>Spare Parts</SectionLabel>

        {NAV_PARTS_ANALYSIS.map(n => <NavItem key={n.to} {...n}/>)}
        {NAV_PARTS_DATA.map(n => <NavItem key={n.to} {...n}/>)}
        {NAV_PARTS_CATALOG.map(n => <NavItem key={n.to} {...n}/>)}

      </nav>
    </aside>
  );
}
