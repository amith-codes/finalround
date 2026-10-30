import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { errorMessage } from '../services/api'
import { Modal } from './ui'

const LABELS = { customer: 'Customer', admin: 'Admin', electrician: 'Electrician' }

export default function RoleSwitcher() {
  const { user, switchRole } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectedRole, setSelectedRole] = useState(null)
  const [credentials, setCredentials] = useState({ username: user?.username || '', password: '' })
  const roles = (user?.roles || [user?.role]).filter((role) => LABELS[role])

  const selectRole = (role) => {
    if (role === user?.role) { setOpen(false); return }
    setCredentials({ username: user?.username || '', password: '' })
    setSelectedRole(role)
    setOpen(false)
  }

  const cancelSwitch = () => {
    if (busy) return
    setSelectedRole(null)
    setCredentials({ username: user?.username || '', password: '' })
  }

  const submitSwitch = async (event) => {
    event.preventDefault()
    if (!selectedRole) return
    setBusy(true)
    try {
      // Every workspace's home is /dashboard (the operations dashboard for Admin).
      await switchRole(selectedRole, credentials, () => {
        setSelectedRole(null)
        navigate('/dashboard', { replace: true })
      })
    } catch (error) {
      toast(errorMessage(error), 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!roles.length) return null
  return <div className="role-switcher">
    <button className="role-switcher-trigger" type="button" aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen((value) => !value)} disabled={busy}>
      <span className="role-switcher-icon" aria-hidden="true">▣</span>
      <span>{LABELS[user?.role] || 'Workspace'}</span>
      <span className="role-switcher-caret" aria-hidden="true">⌄</span>
    </button>
    {open && <div className="role-switcher-menu" role="menu" aria-label="Authorized workspaces">
      <span className="role-switcher-caption">Authorized views</span>
      {roles.map((role) => <button type="button" role="menuitem" key={role}
        className={role === user?.role ? 'role-switcher-option current' : 'role-switcher-option'}
        onClick={() => selectRole(role)} disabled={busy}>
        <span>{LABELS[role]}</span><span>{role === user?.role ? 'Current' : 'Switch'}</span>
      </button>)}
    </div>}
    {selectedRole && <Modal title={`Sign in to ${LABELS[selectedRole]}`} onClose={cancelSwitch}>
      <form className="stack role-switch-form" onSubmit={submitSwitch}>
        <p className="muted small">Re-enter your login ID and password to switch to this authorized workspace.</p>
        <label>Login ID<input autoComplete="username" required value={credentials.username}
          onChange={(event) => setCredentials((value) => ({ ...value, username: event.target.value }))} /></label>
        <label>Password<input type="password" autoComplete="current-password" required value={credentials.password}
          onChange={(event) => setCredentials((value) => ({ ...value, password: event.target.value }))} /></label>
        {user?.username === 'dispatcher' && <p className="muted small role-switch-demo">Local demo credentials: <b>dispatcher / dispatch123</b></p>}
        <div className="row gap end">
          <button type="button" className="btn" onClick={cancelSwitch} disabled={busy}>Cancel</button>
          <button className="btn primary" disabled={busy}>{busy ? 'Verifying…' : `Continue to ${LABELS[selectedRole]}`}</button>
        </div>
      </form>
    </Modal>}
  </div>
}
