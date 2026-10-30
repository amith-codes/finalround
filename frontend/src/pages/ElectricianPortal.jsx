import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtWindow } from '../services/format'
import { Card, Empty, ErrorBox, Loading, ReasonDialog } from '../components/ui'

function BookingRequest({ job, electrician, onAction }) {
  const [busy, setBusy] = useState(false)
  const [askingToDecline, setAskingToDecline] = useState(false)

  const act = async (action, reason = null) => {
    setBusy(true)
    try {
      await onAction(electrician.id, job.id, action, reason)
      setAskingToDecline(false)
    } catch {
      // The dashboard reports action errors in a toast.
    } finally {
      setBusy(false)
    }
  }

  const pending = job.booking_stage === 'awaiting_response'
  const action = pending ? 'accept' : job.status === 'assigned' ? 'start' : job.status === 'in_progress' ? 'complete' : null
  const actionLabel = action === 'accept' ? 'Accept booking'
    : action === 'start' ? 'In progress'
      : action === 'complete' ? 'Complete service' : null
  const statusLabel = pending ? 'Awaiting response'
    : job.status === 'assigned' ? 'Accepted'
      : job.status === 'in_progress' ? 'In progress' : job.status

  return <article className="electrician-booking-card">
    <div className="electrician-booking-title">
      <div>
        <span className="muted small">{job.job_number}</span>
        <h3>{job.title}</h3>
      </div>
      <span className={`badge status-${job.status === 'in_progress' ? 'in_progress' : pending ? 'pending' : 'assigned'}`}>{statusLabel}</span>
    </div>
    <p className="muted small"><b>Assigned to {electrician.name}</b> · {job.customer_name || 'A customer'} requested this service.</p>
    <div className="customer-booking-grid">
      <div><small>Customer</small><b>{job.customer_name || 'Customer'}</b></div>
      <div><small>Appointment</small><b>{fmtWindow(job.window_start, job.window_end)}</b></div>
      <div><small>Service location</small><b>{[job.service_locality, job.district, job.state].filter(Boolean).join(', ') || job.zone_name || 'See address'}</b></div>
      <div><small>Service address</small><b>{job.address || 'Address provided with booking'}</b></div>
    </div>
    {action && <div className="row gap wrap customer-booking-actions">
      <button className="btn primary small" disabled={busy} onClick={() => act(action)}>
        {busy ? 'Updating…' : actionLabel}
      </button>
      {pending && <button className="btn danger small" disabled={busy} onClick={() => setAskingToDecline(true)}>
        Decline
      </button>}
    </div>}
    {askingToDecline && <ReasonDialog
      title={`Decline booking · ${job.job_number}`}
      prompt="Why are you declining this booking?"
      confirmLabel="Decline booking"
      busy={busy}
      onClose={() => setAskingToDecline(false)}
      onSubmit={(reason) => act('decline', reason)}
    />}
  </article>
}

function CompletedService({ job }) {
  return <article className="electrician-booking-card">
    <div className="electrician-booking-title">
      <div><span className="muted small">{job.job_number}</span><h3>{job.title}</h3></div>
      <span className="badge status-completed">Completed</span>
    </div>
    <div className="customer-booking-grid">
      <div><small>Customer</small><b>{job.customer_name || 'Customer'}</b></div>
      <div><small>Completed</small><b>{job.actual_end ? new Date(job.actual_end).toLocaleString() : 'Completion time unavailable'}</b></div>
      <div><small>Service locality</small><b>{[job.service_locality, job.district, job.state].filter(Boolean).join(', ') || job.zone_name || 'See address'}</b></div>
    </div>
  </article>
}

export default function ElectricianPortal() {
  const toast = useToast()
  const [home, setHome] = useState(null)
  const [error, setError] = useState(null)
  const [historyOpen, setHistoryOpen] = useState({})
  const seenRequestIds = useRef(null)

  const load = useCallback(async () => {
    try {
      setHome(await Api.electricianBookings())
      setError(null)
    } catch (e) {
      setError(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [load])

  const panels = useMemo(() => home?.electricians || [], [home])
  const pendingRequests = useMemo(
    () => panels.flatMap((panel) => panel.assigned.map((job) => ({ job, electrician: panel.electrician }))),
    [panels],
  )

  useEffect(() => {
    if (!home) return
    const currentIds = new Set(pendingRequests.map(({ job, electrician }) => `${electrician.id}:${job.id}`))
    const previousIds = seenRequestIds.current
    const newRequests = pendingRequests.filter(({ job, electrician }) => !previousIds?.has(`${electrician.id}:${job.id}`))
    for (const { job, electrician } of newRequests) {
      toast(`${job.customer_name || 'A customer'} booked ${job.title} with ${electrician.name}`, 'info')
    }
    seenRequestIds.current = currentIds
  }, [home, pendingRequests, toast])

  const act = async (electricianId, jobId, action, reason) => {
    try {
      await Api.electricianAction(jobId, action, reason, home?.all_electricians ? electricianId : undefined)
      const messages = {
        accept: 'Booking accepted', decline: 'Booking declined',
        start: 'Booking marked in progress', complete: 'Service completed',
      }
      toast(messages[action] || 'Booking updated', 'success')
      await load()
    } catch (e) {
      toast(errorMessage(e), 'error')
      throw e
    }
  }

  if (!home && !error) return <Loading what="Loading electrician booking requests" />

  return <div className="stack electrician-portal">
    <div className="page-head">
      <div>
        <h1>Electrician dashboard</h1>
        <p className="muted">Customer requests appear under the electrician selected for the booking.</p>
      </div>
      <button className="btn" onClick={load}>Refresh</button>
    </div>
    <ErrorBox error={error} />
    {home && (panels.length === 0
      ? <Card><Empty>No active electricians are available.</Empty></Card>
      : <div className="stack">
        {panels.map((panel) => <Card
          key={panel.electrician.id}
          title={`Bookings for ${panel.electrician.name}${panel.electrician.phone ? ` · ${panel.electrician.phone}` : ' · Phone not listed'}`}
          actions={<button
            className="btn small"
            type="button"
            aria-expanded={!!historyOpen[panel.electrician.id]}
            onClick={() => setHistoryOpen((open) => ({ ...open, [panel.electrician.id]: !open[panel.electrician.id] }))}
          >History ({panel.completed_count ?? panel.history?.length ?? 0})</button>}
        >
          {!panel.assigned.length && !panel.active?.length
            ? <Empty>No current customer bookings for {panel.electrician.name}.</Empty>
            : <div className="electrician-booking-list">
              {panel.assigned.map((job) => <BookingRequest key={job.id} job={job} electrician={panel.electrician} onAction={act} />)}
              {(panel.active || []).map((job) => <BookingRequest key={job.id} job={job} electrician={panel.electrician} onAction={act} />)}
            </div>}
          {historyOpen[panel.electrician.id] && <div className="booking-audit">
            <h3>Completed services ({panel.completed_count ?? panel.history?.length ?? 0})</h3>
            {panel.history?.length
              ? <div className="electrician-booking-list">{panel.history.map((job) => <CompletedService key={job.id} job={job} />)}</div>
              : <Empty>No completed services yet.</Empty>}
          </div>}
        </Card>)}
      </div>)}
  </div>
}
