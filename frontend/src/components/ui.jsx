import { useCallback, useEffect, useState } from 'react'
import { errorMessage } from '../services/api'
import { humanize } from '../services/format'

/** Load data with loading/error state; reloads when deps change. */
export function useLoad(fn, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps)
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setData(await load())
      setError(null)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [load])
  useEffect(() => { reload() }, [reload])
  return { data, error, loading, reload, setData }
}

export function Loading({ what = 'Loading' }) {
  return <div className="muted pad">{what}…</div>
}

export function ErrorBox({ error }) {
  return error ? <div className="alert error">{error}</div> : null
}

export function Badge({ kind, value }) {
  if (!value) return null
  return <span className={`badge ${kind}-${value}`}>{humanize(value)}</span>
}

export const PriorityBadge = ({ value }) => <Badge kind="prio" value={value} />
export const StatusBadge = ({ value }) => <Badge kind="status" value={value} />
export const SlaBadge = ({ value }) => <Badge kind="sla" value={value} />

export function Stat({ label, value, tone, hint }) {
  return (
    <div className={`stat ${tone || ''}`}>
      <div className="stat-value">{value ?? '—'}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <h2>{title}</h2>
          <div className="card-actions">{actions}</div>
        </div>
      )}
      {children}
    </section>
  )
}

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

/** Modal that collects a required, non-empty reason before an action is sent. */
export function ReasonDialog({ title, prompt, confirmLabel = 'Submit', busy, onSubmit, onClose }) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)
  const empty = !reason.trim()
  const submit = (e) => {
    e.preventDefault()
    setTouched(true)
    if (!empty) onSubmit(reason.trim())
  }
  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label>{prompt}
          <textarea rows={3} maxLength={250} value={reason} autoFocus
                    onChange={(e) => setReason(e.target.value)} placeholder="e.g. Vehicle breakdown, outside my service hours" />
        </label>
        {touched && empty && <div className="alert error">A reason is required.</div>}
        <p className="muted small">The reason is saved to the booking history and shown to the customer and dispatch.</p>
        <div className="row gap end">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Back</button>
          <button className="btn danger" disabled={busy}>{busy ? 'Sending…' : confirmLabel}</button>
        </div>
      </form>
    </Modal>
  )
}

export function Reasons({ reasons }) {
  if (!reasons?.length) return null
  return (
    <ul className="reasons">
      {reasons.map((r, i) => (
        <li key={i} className={r.code === 'HISTORY' ? 'history' : ''}>
          {r.code !== 'HISTORY' && <span className="code">{humanize(r.code)}</span>}
          <span>{r.message}</span>
          {r.suggestion && <div className="suggestion">→ {r.suggestion}</div>}
        </li>
      ))}
    </ul>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}
