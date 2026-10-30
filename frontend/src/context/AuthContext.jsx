import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Api, getToken, setToken } from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setTok] = useState(getToken())
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!!getToken())

  const login = useCallback(async (username, password) => {
    const res = await Api.login(username, password)
    setToken(res.access_token)
    setTok(res.access_token)
    const current = await Api.me()
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
    Api.me().then((current) => {
      if (active) setUser(current)
    }).catch(() => {
      if (active) setUser(null)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [token])

  return <AuthContext.Provider value={{ token, user, loading, login, logout }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
