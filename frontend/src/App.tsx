import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Overview }       from "./pages/Overview";
import { BikeSales }      from "./pages/BikeSales";
import { McsiEDA }        from "./pages/McsiEDA";
import { UIO }            from "./pages/UIO";
import { UIOForecast }    from "./pages/UIOForecast";
import { EDA }            from "./pages/EDA";
import { OBMEDA }         from "./pages/OBMEDA";
import { PartMaster }     from "./pages/PartMaster";
import { Forecast }       from "./pages/Forecast";
import { Inventory }      from "./pages/Inventory";
import { Orders }         from "./pages/Orders";
import { Catalog }        from "./pages/Catalog";
import { Pipeline }               from "./pages/Pipeline";

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen w-full font-sans bg-surface overflow-hidden">
        <Sidebar />
        <main className="flex-1 flex flex-col overflow-hidden">
          <Routes>
            <Route path="/"               element={<Overview />} />
            <Route path="/bikes"          element={<BikeSales />} />
            <Route path="/mcsi-eda"       element={<McsiEDA />} />
            <Route path="/uio"            element={<UIO />} />
            <Route path="/uio-forecast"   element={<UIOForecast />} />
            <Route path="/eda"            element={<EDA />} />
            <Route path="/obm-eda"        element={<OBMEDA />} />
            <Route path="/parts"          element={<PartMaster />} />
            <Route path="/forecast"       element={<Forecast />} />
            <Route path="/inventory"      element={<Inventory />} />
            <Route path="/orders"         element={<Orders />} />
            <Route path="/catalog"        element={<Catalog />} />
            <Route path="/pipeline"               element={<Pipeline />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
