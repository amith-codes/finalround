import { useCallback, useEffect, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, humanize } from '../services/format'
import { Card, Empty, ErrorBox, Loading } from '../components/ui'

export default function CustomerBookings() {
  const toast = useToast()
  const [bookings, setBookings] = useState(null)
  const [history, setHistory] = useState({})
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const load = useCallback(async () => {
    try { setBookings(await Api.customerBookings()); setError(null) }
    catch (e) { setError(errorMessage(e)) }
  }, [])
  useEffect(() => { load(); const timer = setInterval(load, 20000); return () => clearInterval(timer) }, [load])

  const cancel = async (job) => {
    if (!window.confirm(`Cancel booking ${job.job_number}?`)) return
    setBusy(job.id)
    try { await Api.cancelCustomerBooking(job.id, 'Cancelled by customer'); toast('Booking cancelled', 'success'); await load() }
    catch (e) { toast(errorMessage(e), 'error') }
    finally { setBusy(null) }
  }
  const toggleHistory = async (id) => {
    if (history[id]) { setHistory((old) => ({ ...old, [id]: null })); return }
    try {
      const result = await Api.bookingHistory(id)
      setHistory((old) => ({ ...old, [id]: result }))
    }
    catch (e) { toast(errorMessage(e), 'error') }
  }

  if (!bookings && !error) return <Loading what="Loading your bookings" />
  return <div className="stack customer-portal-page">
    <div className="page-head"><div><h1>Your bookings</h1><p className="muted">Updates refresh automatically.</p></div><button className="btn" onClick={load}>Refresh</button></div>
    <ErrorBox error={error} />
    {bookings?.length === 0 ? <Card><Empty>You have no bookings yet. Choose a service to get started.</Empty></Card> : bookings?.map((job) => <Card key={job.id}>
      <div className="customer-booking-head">
        <div><span className="muted small">{job.job_number}</span><h2>{job.title}</h2></div>
        <span className={`badge st-${job.status}`}>{job.booking_action === 'accepted' ? 'Accepted' : humanize(job.status)}</span>
      </div>
      <div className="customer-booking-grid">
        <div><small>Appointment</small><b>{fmtDateTime(job.window_start)}</b></div>
        <div><small>Address</small><b>{job.address || 'Address on booking'}</b></div>
        <div><small>Electrician</small><b>{job.assignment?.electrician_name || (job.status === 'unassigned' ? 'Dispatcher is finding a local electrician' : 'Being matched')}</b></div>
        <div><small>Payment</small><b>{job.payment_status || 'Pending'} · ₹{Number(job.booking_amount || 0).toFixed(2)}</b></div>
      </div>
      {job.cancel_reason && <p className="muted small">Update: {job.cancel_reason}</p>}
      <div className="row gap wrap customer-booking-actions">
        <button className="btn small" onClick={() => toggleHistory(job.id)}>{history[job.id] ? 'Hide updates' : 'View updates'}</button>
        {['pending', 'assigned', 'unassigned'].includes(job.status) && <button className="btn small danger" disabled={busy === job.id} onClick={() => cancel(job)}>{busy === job.id ? 'Cancelling…' : 'Cancel booking'}</button>}
      </div>
      {history[job.id] && <div className="booking-audit">
        {history[job.id].assignments.length > 0 && <><h3>Assignment history</h3><ol className="booking-event-list">{history[job.id].assignments.map((assignment, index) => <li key={`${assignment.start}-${index}`}>
          <b>{assignment.electrician || 'Electrician assignment'}</b><span>{fmtDateTime(assignment.start)}</span>
          <small>{assignment.active ? 'Current assignment' : 'Previous assignment'}{assignment.explanation ? ` · ${assignment.explanation}` : ''}</small>
        </li>)}</ol></>}
        {history[job.id].events.length > 0 && <><h3>Booking updates</h3><ol className="booking-event-list">{history[job.id].events.map((event) => <li key={event.id}>
          <b>{humanize(event.action)}</b><span>{fmtDateTime(event.created_at)}</span>
          {event.reason && <small>{event.reason}</small>}
          {(event.old_electrician || event.new_electrician) && <small>{event.old_electrician || 'Dispatch'} → {event.new_electrician || 'Dispatch'}</small>}
        </li>)}</ol></>}
      </div>}
    </Card>)}
  </div>
}
