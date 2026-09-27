import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'
import Overview from './pages/Overview'
import OrderPlan from './pages/OrderPlan'
import Inventory from './pages/Inventory'
import SpareParts from './pages/SpareParts'
import Classification from './pages/Classification'
import Forecast from './pages/Forecast'
import UnitSales from './pages/UnitSales'
import Registrations from './pages/Registrations'
import Parc from './pages/Parc'
import PartMaster from './pages/PartMaster'
import Catalogues from './pages/Catalogues'
import Exceptions from './pages/Exceptions'
import Pipeline from './pages/Pipeline'

export default function App() {
  const location = useLocation()
  return (
    <Layout>
      <ErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/order-plan" element={<OrderPlan />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/spare-parts" element={<SpareParts />} />
          <Route path="/classification" element={<Classification />} />
          <Route path="/forecast" element={<Forecast />} />
          <Route path="/unit-sales" element={<UnitSales />} />
          <Route path="/registrations" element={<Registrations />} />
          <Route path="/parc" element={<Parc />} />
          <Route path="/parts" element={<PartMaster />} />
          <Route path="/catalogues" element={<Catalogues />} />
          <Route path="/exceptions" element={<Exceptions />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </Layout>
  )
}
