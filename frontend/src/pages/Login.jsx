import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../services/api'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login uc-login-wrap">
      <div className="uc-login-card">
        <div className="uc-login-header">
          <div className="uc-logo-badge large">D</div>
          <h1 className="uc-login-title">DISPATCHER</h1>
          <div className="uc-login-subtitle">One sign-in for customers, electricians, and operations</div>
          <div className="uc-login-city-pill">
            <span className="dot active" /> Indian district and state selection
          </div>
        </div>

        <form className="uc-login-form" onSubmit={submit}>
          <div className="uc-input-group">
            <label>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="Enter your username"
              required
            />
          </div>

          <div className="uc-input-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••••••"
              required
            />
          </div>

          {error && <div className="alert error">{error}</div>}

          <button className="btn uc-btn-primary block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in to Dispatcher'}
          </button>

        </form>

        <div className="uc-login-trust-footer">
          <span>🛡️ 30-Day Guarantee</span>
          <span>•</span>
          <span>⚡ Flexible service scheduling</span>
          <span>•</span>
          <span>🔒 Verified Operations</span>
        </div>
      </div>
    </div>
  )
}
