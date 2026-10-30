import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import LocationPicker from './LocationPicker'
import RoleSwitcher from './RoleSwitcher'

const NAV_ITEMS = [
  ['/dashboard', '📊 Dashboard'],
  ['/cart?category=electrician_density', '⚡ Book Electrician'],
  ['/schedule', '🗓️ Schedule'],
  ['/jobs', '📋 Jobs'],
  ['/electricians', '👷 Electricians'],
  ['/disruptions', '⚡ Disruptions'],
  ['/history', '📜 Run history'],
]
NAV_ITEMS.push(['/customers', 'Customers'])
const ADMIN_NAV_PATHS = new Set(['/dashboard', '/electricians', '/history'])

export default function Layout() {
  const { logout, user } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(null)
  const [version, setVersion] = useState(0)
  const [currentLocation, setCurrentLocation] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('dispatcher.location') || 'null')
    } catch {
      return null
    }
  })
  const [globalSearch, setGlobalSearch] = useState('')
  const navItems = user?.role === 'customer'
    ? [['/cart?category=electrician_density', 'Book Electrician'], ['/cart', 'Cart']]
    : user?.role === 'admin'
      ? NAV_ITEMS.filter(([to]) => ADMIN_NAV_PATHS.has(to))
      : NAV_ITEMS

  const selectLocation = (location) => {
    setCurrentLocation(location)
    try {
      localStorage.setItem('dispatcher.location', JSON.stringify(location))
    } catch {
      // The selected location still works for the current session if storage is unavailable.
    }
    toast(`Service location set to ${location.district}, ${location.state}`, 'info')
  }

  const trigger = async (kind) => {
    setBusy(kind)
    try {
      const run = kind === 'run' ? await Api.runScheduling() : await Api.reoptimize()
      const m = run.metrics
      toast(
        `Optimization complete: ${m.assigned} assigned, ${m.unassigned} unassigned, ` +
          `${m.changes.reassigned + m.changes.retimed + m.changes.assigned} changes`,
        'success',
      )
      setVersion((v) => v + 1)
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    if (globalSearch.trim()) {
      navigate(`/cart?category=electrician_density&q=${encodeURIComponent(globalSearch.trim())}`)
    }
  }

  return (
    <div className="shell uc-theme">
      <div className="uc-top-ticker">
        <div className="ticker-wrap">
          <span>⚡ <b>Dispatcher Electrician Services</b> — Trusted professionals and simple online scheduling</span>
          <span className="ticker-badge">30-Day Post-Service Guarantee</span>
          <span className="ticker-badge">Verified Electricians</span>
        </div>
      </div>

      <header className="topbar uc-navbar">
        <div className="uc-nav-left">
          <NavLink to="/dashboard" className="uc-brand-logo">
            <div className="uc-logo-badge">D</div>
            <div className="uc-brand-text">
              <span className="brand-main">DISPATCHER</span>
              <span className="brand-sub">Electrician Services</span>
            </div>
          </NavLink>

          <LocationPicker location={currentLocation} onSelect={selectLocation} />
        </div>

        {/* Global Search Bar */}
        <form className="uc-global-search" onSubmit={handleSearchSubmit}>
          <span className="search-icon">🔍</span>
          <input
            type="search"
            placeholder="Search for 'fan repair', 'switchboard', 'MCB tripping', 'wiring'…"
            value={globalSearch}
            onChange={(e) => setGlobalSearch(e.target.value)}
          />
        </form>

        {/* Navigation Tabs */}
        <nav className="nav uc-nav-links">
          {navItems.map(([to, label]) => {
            const pathOnly = to.split('?')[0]
            const isCart = pathOnly === '/cart'
            const isCustomer = user?.role === 'customer'
            return (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => {
                  const currentPath = window.location.pathname
                  const active = isCustomer
                    ? currentPath === pathOnly && (to.includes('?category=')
                      ? window.location.search.includes('category=')
                      : !window.location.search.includes('category='))
                    : isActive || (isCart && (currentPath === '/' || currentPath === '/cart'))
                  return active ? 'uc-nav-link active' : 'uc-nav-link'
                }}
              >
                {label}
              </NavLink>
            )
          })}
        </nav>

        {/* Right Actions & Optimizer */}
        <div className="actions uc-nav-actions">
          {user?.role !== 'customer' && <>
          <button
            className="btn uc-btn-primary"
            disabled={!!busy}
            onClick={() => trigger('run')}
            title="Run scheduling engine to allocate jobs"
          >
            {busy === 'run' ? '⚡ Optimizing…' : '⚡ Run scheduling'}
          </button>
          <button
            className="btn uc-btn-outline"
            disabled={!!busy}
            onClick={() => trigger('reoptimize')}
            title="Re-optimize routes without disruption"
          >
            {busy === 'reoptimize' ? 'Re-optimising…' : 'Re-optimise'}
          </button>
          </>}
          <RoleSwitcher />
          <span className="muted small">{user?.display_name || user?.username}</span>
          <button className="btn ghost uc-btn-signout" onClick={logout} title="Sign out">
            Sign out
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="content uc-main-content">
        <Outlet context={{
          version,
          bump: () => setVersion((v) => v + 1),
          location: currentLocation,
          setLocation: selectLocation,
        }} />
      </main>

      <footer className="uc-footer">
        <div className="footer-wrap">
          <div className="footer-left">
            <span className="footer-brand"><b>Dispatcher</b> Electrician Services</span>
            <span className="dot">•</span>
            <span>{currentLocation ? `${currentLocation.district}, ${currentLocation.state}` : 'Choose a service district'}</span>
            <span className="dot">•</span>
            <span>Dispatcher workforce scheduling</span>
          </div>
          <div className="footer-right">
            <span>© 2026 Dispatcher. 30-Day Workmanship Warranty.</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
