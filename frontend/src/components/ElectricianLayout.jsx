import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import RoleSwitcher from './RoleSwitcher'

export default function ElectricianLayout() {
  const { user, logout } = useAuth()
  return <div className="shell electrician-shell">
    <header className="topbar electrician-topbar">
      <NavLink to="/dashboard" className="uc-brand-logo"><div className="uc-logo-badge">D</div><div className="uc-brand-text"><span className="brand-main">DISPATCHER</span><span className="brand-sub">Electrician workspace</span></div></NavLink>
      <nav className="nav electrician-nav"><NavLink to="/dashboard" className={({ isActive }) => isActive ? 'uc-nav-link active' : 'uc-nav-link'}>Booking requests</NavLink></nav>
      <div className="actions"><RoleSwitcher /><span className="muted small">{user?.display_name || user?.username}</span><button className="btn ghost" onClick={logout}>Sign out</button></div>
    </header>
    <main className="content"><Outlet /></main>
    <footer className="uc-footer"><div className="footer-wrap"><span>Dispatcher · Electrician workspace</span><span>Assigned customer requests</span></div></footer>
  </div>
}
