import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ElectricianLayout from './components/ElectricianLayout'
import { useAuth } from './context/AuthContext'
import Dashboard from './pages/Dashboard'
import CustomerHome from './pages/CustomerHome'
import CustomerBookings from './pages/CustomerBookings'
import Customers from './pages/Customers'
import Disruptions from './pages/Disruptions'
import Electricians from './pages/Electricians'
import ElectricianPortal from './pages/ElectricianPortal'
import History from './pages/History'
import Jobs from './pages/Jobs'
import Login from './pages/Login'
import PaymentMethods from './pages/PaymentMethods'
import Schedule from './pages/Schedule'
import ServiceCart from './pages/ServiceCart'

function CustomerApp() {
  return <Routes><Route element={<Layout />}>
    <Route index element={<Navigate to="/dashboard" replace />} />
    <Route path="dashboard" element={<CustomerHome />} />
    <Route path="cart" element={<ServiceCart />} />
    <Route path="bookings" element={<CustomerBookings />} />
    <Route path="payments" element={<PaymentMethods />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Route></Routes>
}

function ElectricianApp() {
  return <Routes><Route element={<ElectricianLayout />}>
    <Route index element={<Navigate to="/dashboard" replace />} />
    <Route path="dashboard" element={<ElectricianPortal />} />
    <Route path="jobs" element={<ElectricianPortal />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Route></Routes>
}

function AdminApp() {
  return <Routes><Route element={<Layout />}>
    <Route index element={<Navigate to="/dashboard" replace />} />
    <Route path="cart" element={<ServiceCart />} />
    <Route path="dashboard" element={<Dashboard />} />
    <Route path="schedule" element={<Schedule />} />
    <Route path="jobs" element={<Jobs />} />
    <Route path="electricians" element={<Electricians />} />
    <Route path="customers" element={<Customers />} />
    <Route path="disruptions" element={<Disruptions />} />
    <Route path="history" element={<History />} />
    <Route path="history/:runId" element={<History />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Route></Routes>
}

export default function App() {
  const { token, user, loading } = useAuth()
  if (!token) return <Login />
  if (loading) return <div className="portal-loading">Loading your Dispatcher workspace…</div>
  if (user?.role === 'customer') return <CustomerApp />
  if (user?.role === 'electrician') return <ElectricianApp />
  if (user?.role === 'admin') return <AdminApp />
  return <div className="portal-loading"><p>This account has no assigned Dispatcher role.</p></div>
}
