// The backend speaks naive local ISO strings ("2026-10-31T09:00:00"), which Date parses as local time.

const pad = (n) => String(n).padStart(2, '0')

export const toDate = (s) => (s ? new Date(s) : null)

export function fmtTime(s) {
  const d = toDate(s)
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '—'
}

export function fmtDateTime(s) {
  const d = toDate(s)
  if (!d) return '—'
  return `${d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} ${fmtTime(s)}`
}

export function fmtDay(s) {
  const d = typeof s === 'string' ? new Date(`${s.slice(0, 10)}T00:00:00`) : s
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
}

/** yyyy-mm-dd for a Date in local time */
export function isoDay(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** value for <input type="datetime-local"> */
export function toLocalInput(d) {
  return `${isoDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromLocalInput(v) {
  return v ? (v.length === 16 ? `${v}:00` : v) : null
}

export function minutesLabel(m) {
  if (m == null) return '—'
  const h = Math.floor(Math.abs(m) / 60)
  const mm = Math.abs(m) % 60
  const s = h ? `${h}h ${pad(mm)}m` : `${mm}m`
  return m < 0 ? `-${s}` : s
}

export const humanize = (s) => (s ? s.replaceAll('_', ' ') : '')

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const PRIORITIES = ['urgent', 'high', 'medium', 'low']
export const STATUSES = ['pending', 'assigned', 'in_progress', 'completed', 'cancelled', 'unassigned']
