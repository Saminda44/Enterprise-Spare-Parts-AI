import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, TrendingUp, Package, ShoppingCart,
  BookOpen, FileText,
  Activity, Search, Terminal, ScanSearch, UploadCloud, Menu, X,
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
  { to: "/vehicle",  label: "Vehicle Lookup",         Icon: ScanSearch },
];

// ── Spare parts: one section per PN_Yamaha brand (YM → MC, OB → OBM) ──────
const NAV_MC_PARTS = [
  { to: "/eda",      label: "MC Spare Parts Analysis", Icon: Package      },
  { to: "/forecast", label: "Demand Forecast",         Icon: TrendingUp   },
  { to: "/orders",   label: "Order Plan",              Icon: ShoppingCart },
  { to: "/parts",    label: "MC Part Master",          Icon: BookOpen     },
];

const NAV_OBM_PARTS = [
  { to: "/obm/eda",      label: "OBM Spare Parts Analysis", Icon: Package      },
  { to: "/obm/forecast", label: "Demand Forecast",          Icon: TrendingUp   },
  { to: "/obm/orders",   label: "Order Plan",               Icon: ShoppingCart },
  { to: "/obm/parts",    label: "OBM Part Master",          Icon: BookOpen     },
];

const NAV_TOOLS = [
  { to: "/sources",   label: "Data Sources",    Icon: UploadCloud },
  { to: "/catalog",   label: "Catalogues",      Icon: FileText  },
  { to: "/pipeline",  label: "Pipeline Runner",  Icon: Terminal  },
];

function NavItem({ to, label, Icon }: { to: string; label: string; Icon: React.ElementType }) {
  return (
    <NavLink
      to={to}
      end
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
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => { setOpen(false); }, [location.pathname]);

  return (
    <>
      <button type="button" onClick={() => setOpen(value => !value)}
        className="md:hidden fixed left-3 top-2.5 z-50 grid h-8 w-8 place-items-center rounded bg-sidebar text-white"
        aria-label={open ? "Close navigation" : "Open navigation"}
        title={open ? "Close navigation" : "Open navigation"}>
        {open ? <X size={18}/> : <Menu size={18}/>}
      </button>
      {open && <button type="button" aria-label="Close navigation" onClick={() => setOpen(false)}
        className="md:hidden fixed inset-0 z-30 bg-slate-950/45"/>}
      <aside className={`fixed inset-y-0 left-0 z-40 w-60 h-screen bg-sidebar text-white flex flex-col shrink-0 overflow-hidden transition-transform md:static md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
      {/* Logo */}
      <div className="pl-14 pr-6 md:px-6 py-4 border-b border-white/10 shrink-0">
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

        {/* ── 3. MC spare parts ── */}
        <SectionLabel>MC Spare Parts</SectionLabel>
        {NAV_MC_PARTS.map(n => <NavItem key={n.to} {...n}/>)}

        <Divider/>

        {/* ── 4. OBM spare parts ── */}
        <SectionLabel>OBM Spare Parts</SectionLabel>
        {NAV_OBM_PARTS.map(n => <NavItem key={n.to} {...n}/>)}

        <Divider/>

        {/* ── 5. Tools ── */}
        <SectionLabel>Data &amp; Tools</SectionLabel>
        {NAV_TOOLS.map(n => <NavItem key={n.to} {...n}/>)}

      </nav>
      </aside>
    </>
  );
}
