import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Api, getToken, setToken } from '../services/api'

const AuthContext = createContext(null)
const ROLE_ALIASES = { dispatcher: 'admin', administrator: 'admin' }

function normalizeAccess(user) {
  if (!user) return user
  const role = ROLE_ALIASES[user.role] || user.role
  const roles = [...new Set((user.roles || [user.role]).map((item) => ROLE_ALIASES[item] || item))]
  if (role && !roles.includes(role)) roles.push(role)
  return { ...user, role, roles }
}

export function AuthProvider({ children }) {
  const [token, setTok] = useState(getToken())
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!!getToken())

  const login = useCallback(async (username, password) => {
    const res = await Api.login(username, password)
    setToken(res.access_token)
    setTok(res.access_token)
    const current = normalizeAccess(await Api.me())
    setUser(current)
  }, [])

  // beforeApply runs once the server grants the role but before the workspace re-renders,
  // so callers can navigate while their component is still mounted.
  const switchRole = useCallback(async (role, credentials, beforeApply) => {
    const res = await Api.switchRole(role, credentials)
    beforeApply?.()
    setToken(res.access_token)
    setTok(res.access_token)
    const current = normalizeAccess(await Api.me())
    setUser(current)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setTok(null)
    setUser(null)
  }, [])

  useEffect(() => {
    const onLogout = () => setTok(null)
    window.addEventListener('dispatchgrid:logout', onLogout)
    return () => window.removeEventListener('dispatchgrid:logout', onLogout)
  }, [])

  useEffect(() => {
    let active = true
    if (!token) {
      setUser(null)
      setLoading(false)
      return () => { active = false }
    }
    setLoading(true)
    Api.me().then((response) => {
      const current = normalizeAccess(response)
      if (active) setUser(current)
    }).catch(() => {
      if (active) setUser(null)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [token])

  return <AuthContext.Provider value={{ token, user, loading, login, logout, switchRole }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
