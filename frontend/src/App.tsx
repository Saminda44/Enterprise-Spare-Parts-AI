import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { RefreshBanner } from "./components/RefreshBanner";
import { SegmentRoute, type Segment } from "./api/segment";
import { Overview }       from "./pages/Overview";
import { BikeSales }      from "./pages/BikeSales";
import { McsiEDA }        from "./pages/McsiEDA";
import { UIO }            from "./pages/UIO";
import { VehicleLookup }  from "./pages/VehicleLookup";
import { UIOForecast }    from "./pages/UIOForecast";
import { EDA }            from "./pages/EDA";
import { PartMaster }     from "./pages/PartMaster";
import { Forecast }       from "./pages/Forecast";
import { Inventory }      from "./pages/Inventory";
import { Orders }         from "./pages/Orders";
import { Catalog }        from "./pages/Catalog";
import { Pipeline }               from "./pages/Pipeline";
import { Sources }                from "./pages/Sources";

const all = (el: React.ReactNode) => <SegmentRoute segment={null}>{el}</SegmentRoute>;
const seg = (s: Segment, el: React.ReactNode) => <SegmentRoute segment={s}>{el}</SegmentRoute>;

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen w-full font-sans bg-surface overflow-hidden">
        <Sidebar />
        <main className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <div className="md:hidden h-12 shrink-0 border-b border-slate-200 bg-white pl-14 pr-4 flex items-center">
            <span className="text-sm font-semibold text-slate-800">Inventory Optimisation</span>
          </div>
          <RefreshBanner />
          <Routes>
            <Route path="/"               element={all(<Overview />)} />
            <Route path="/bikes"          element={all(<BikeSales />)} />
            <Route path="/mcsi-eda"       element={all(<McsiEDA />)} />
            <Route path="/uio"            element={all(<UIO />)} />
            <Route path="/vehicle"        element={all(<VehicleLookup />)} />
            <Route path="/uio-forecast"   element={all(<UIOForecast />)} />
            {/* MC spare parts — part brand YM (and the few Katana tyres) */}
            <Route path="/eda"            element={<SegmentRoute segment="mc" categoryEnabled><EDA /></SegmentRoute>} />
            <Route path="/forecast"       element={seg("mc", <Forecast />)} />
            <Route path="/orders"         element={seg("mc", <Orders />)} />
            <Route path="/parts"          element={seg("mc", <PartMaster />)} />
            <Route path="/inventory"      element={seg("mc", <Inventory />)} />
            {/* OBM spare parts — part brand OB (Yamaha outboard) */}
            <Route path="/obm/eda"        element={seg("obm", <EDA />)} />
            <Route path="/obm/forecast"   element={seg("obm", <Forecast />)} />
            <Route path="/obm/orders"     element={seg("obm", <Orders />)} />
            <Route path="/obm/parts"      element={seg("obm", <PartMaster />)} />
            <Route path="/obm-eda"        element={<Navigate to="/obm/eda" replace />} />
            <Route path="/catalog"        element={all(<Catalog />)} />
            <Route path="/pipeline"       element={all(<Pipeline />)} />
            <Route path="/sources"        element={all(<Sources />)} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
