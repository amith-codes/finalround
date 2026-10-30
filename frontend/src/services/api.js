import axios from 'axios'

const TOKEN_KEY = 'dispatchgrid.token'

export const getToken = () => {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export const setToken = (t) => {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch { /* storage blocked */ }
}

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config.url.includes('/auth/login') && !err.config.url.includes('/auth/switch-role')) {
      setToken(null)
      window.dispatchEvent(new Event('dispatchgrid:logout'))
    }
    return Promise.reject(err)
  },
)

/** Human-readable message from the backend's {error: {code, message, details}} envelope. */
export function errorMessage(err) {
  const e = err?.response?.data?.error
  if (!e) return err?.message || 'Request failed'
  if (e.code === 'VALIDATION_ERROR' && Array.isArray(e.details)) {
    return e.details.map((d) => `${d.field || 'request'}: ${d.message}`).join('; ')
  }
  return e.message
}

const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`)
const withKey = () => ({ headers: { 'Idempotency-Key': newKey() } })

export const Api = {
  login: (username, password) =>
    api.post('/auth/login', new URLSearchParams({ username, password })).then((r) => r.data),
  me: () => api.get('/auth/me').then((r) => r.data),
  switchRole: (role, credentials) => api.post('/auth/switch-role', { role, ...credentials }).then((r) => r.data),

  skills: () => api.get('/skills').then((r) => r.data),
  zones: () => api.get('/zones').then((r) => r.data),

  jobs: (params) => api.get('/jobs', { params }).then((r) => r.data),
  job: (id) => api.get(`/jobs/${id}`).then((r) => r.data),
  createJob: (body) => api.post('/jobs', body, withKey()).then((r) => r.data),
  updateJob: (id, body) => api.put(`/jobs/${id}`, body).then((r) => r.data),
  startJob: (id) => api.post(`/jobs/${id}/start`, {}).then((r) => r.data),
  cancelJob: (id, reason) => api.delete(`/jobs/${id}`, { params: { reason } }).then((r) => r.data),

  electricians: (includeInactive = false) =>
    api.get('/electricians', { params: { include_inactive: includeInactive } }).then((r) => r.data),
  createElectrician: (body) => api.post('/electricians', body).then((r) => r.data),
  updateElectrician: (id, body) => api.put(`/electricians/${id}`, body).then((r) => r.data),
  deleteElectrician: (id) => api.delete(`/electricians/${id}`).then((r) => r.data),
  removeElectrician: (id) => api.delete(`/electricians/${id}/remove`).then((r) => r.data),
  addUnavailability: (id, body) => api.post(`/electricians/${id}/unavailability`, body).then((r) => r.data),
  deleteUnavailability: (id, pid) => api.delete(`/electricians/${id}/unavailability/${pid}`).then((r) => r.data),

  runScheduling: () => api.post('/scheduling/run', {}, withKey()).then((r) => r.data),
  reoptimize: () => api.post('/scheduling/reoptimize', {}, withKey()).then((r) => r.data),
  current: () => api.get('/scheduling/current').then((r) => r.data),
  history: (limit = 50) => api.get('/scheduling/history', { params: { limit } }).then((r) => r.data),
  run: (id) => api.get(`/scheduling/runs/${id}`).then((r) => r.data),
  jobSchedule: (id) => api.get(`/scheduling/jobs/${id}`).then((r) => r.data),

  customerBookings: () => api.get('/portal/customer/bookings').then((r) => r.data),
  customerBookingPaymentQr: (jobId) => api.post(`/portal/customer/bookings/${jobId}/payment/qr`).then((r) => r.data),
  customerBookingPaymentStatus: (jobId) => api.get(`/portal/customer/bookings/${jobId}/payment/status`).then((r) => r.data),
  submitCustomerFeedback: (jobId, body) => api.post(`/portal/customer/bookings/${jobId}/feedback`, body).then((r) => r.data),
  submitCustomerComplaint: (jobId, body) => api.post(`/portal/customer/bookings/${jobId}/complaint`, body).then((r) => r.data),
  customerLocalities: (zoneCode) => api.get('/portal/customer/localities', { params: { zone_code: zoneCode } }).then((r) => r.data),
  customerElectricians: (params) => {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (key === 'required_skills') value.forEach((skill) => query.append(key, skill))
      else if (value !== undefined && value !== null && value !== '') query.set(key, value)
    })
    return api.get(`/portal/customer/electricians?${query.toString()}`).then((r) => r.data)
  },
  cancelCustomerBooking: (id, reason) => api.post(`/portal/customer/bookings/${id}/cancel`, null, { params: { reason } }).then((r) => r.data),
  paymentMethods: () => api.get('/portal/customer/payment-methods').then((r) => r.data),
  addPaymentMethod: (body) => api.post('/portal/customer/payment-methods', body).then((r) => r.data),
  removePaymentMethod: (id) => api.delete(`/portal/customer/payment-methods/${id}`).then((r) => r.data),
  setDefaultPaymentMethod: (id) => api.put(`/portal/customer/payment-methods/${id}/default`).then((r) => r.data),
  electricianBookings: () => api.get('/portal/electrician/bookings').then((r) => r.data),
  electricianAction: (id, action, reason, electrician_id) => api.post(`/portal/electrician/bookings/${id}/action`, {
    action, reason, ...(electrician_id ? { electrician_id } : {}),
  }).then((r) => r.data),
  electricianDuty: (action) => api.post('/portal/electrician/duty', { action }).then((r) => r.data),
  electricianEarnings: (start, end) => api.get('/portal/electrician/earnings', { params: { start, end } }).then((r) => r.data),
  bookingHistory: (id) => api.get(`/portal/bookings/${id}/history`).then((r) => r.data),
  adminOverview: (params) => api.get('/portal/admin/overview', { params }).then((r) => r.data),
  adminBookingActivity: (limit = 50) => api.get('/portal/admin/booking-activity', { params: { limit } }).then((r) => r.data),
  adminCustomers: () => api.get('/portal/admin/customers').then((r) => r.data),
  adminEarnings: (start, end) => api.get('/portal/admin/earnings', { params: { start, end } }).then((r) => r.data),
  createCustomer: (body) => api.post('/portal/admin/customers', body).then((r) => r.data),
  dispatchCandidates: (id) => api.get(`/portal/admin/dispatch-candidates/${id}`).then((r) => r.data),
  manualAssign: (id, electrician_id, reason) => api.post(`/portal/admin/bookings/${id}/assign`, { electrician_id, reason }).then((r) => r.data),
  updatePaymentStatus: (id, status) => api.put(`/portal/admin/bookings/${id}/payment-status`, { status }).then((r) => r.data),

  disrupt: (kind, body) => api.post(`/disruptions/${kind}`, body, withKey()).then((r) => r.data),

  overview: () => api.get('/dashboard/overview').then((r) => r.data),
  workload: (start, days = 3) => api.get('/dashboard/workload', { params: { start, days } }).then((r) => r.data),
  sla: () => api.get('/dashboard/sla').then((r) => r.data),
  schedule: (day) => api.get('/dashboard/schedule', { params: { day } }).then((r) => r.data),
  comparison: (runId) => api.get('/dashboard/comparison', { params: { run_id: runId } }).then((r) => r.data),
}
