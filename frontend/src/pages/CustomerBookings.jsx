import { useCallback, useEffect, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, fmtWindow, humanize, rupees, stageLabel } from '../services/format'
import { Card, Empty, ErrorBox, Loading, Modal } from '../components/ui'

const STAGE_BADGE = {
  awaiting_dispatch: 'status-pending', awaiting_response: 'status-pending', accepted: 'status-assigned',
  reassignment_needed: 'status-unassigned', in_progress: 'status-in_progress', completed: 'status-completed', cancelled: 'status-cancelled',
}

/** Arrival from the dispatch schedule only; there is no live location feed, so never present it as live. */
function arrival(job) {
  const a = job.assignment
  switch (job.booking_stage) {
    case 'in_progress': return { label: 'Electrician on site', value: `Since ${fmtDateTime(job.actual_start)}` }
    case 'completed': return { label: 'Completed', value: fmtDateTime(job.actual_end) }
    case 'cancelled': return null
    case 'accepted': return a && { label: 'Scheduled arrival', value: fmtDateTime(a.start), note: 'Estimated from the dispatch schedule, including planned travel. Live tracking is not available.' }
    case 'awaiting_response': return a && { label: 'Proposed arrival', value: fmtDateTime(a.start), note: 'Confirmed once the electrician accepts.' }
    default: return { label: 'Arrival', value: 'Set once an electrician is assigned' }
  }
}

function FeedbackDialog({ job, busy, onClose, onSubmit }) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')

  const submit = (event) => {
    event.preventDefault()
    if (rating > 0) onSubmit({ rating, comment })
  }

  return <Modal title={`Rate your service · ${job.job_number}`} onClose={onClose}>
    <form className="stack feedback-form" onSubmit={submit}>
      <fieldset className="feedback-rating-fieldset">
        <legend>Your rating</legend>
        <div className="feedback-stars" role="group" aria-label="Choose a rating from one to five stars">
          {[1, 2, 3, 4, 5].map((value) => <button
            key={value}
            type="button"
            className={`feedback-star${rating >= value ? ' selected' : ''}`}
            aria-label={`${value} ${value === 1 ? 'star' : 'stars'}`}
            aria-pressed={rating === value}
            onClick={() => setRating(value)}
          >★</button>)}
        </div>
        <p className="muted small" aria-live="polite">{rating}/5 stars{rating === 0 ? ' · Select a rating to continue' : ''}</p>
      </fieldset>
      <label className="feedback-comment-label">Description / opinion <span>(optional)</span>
        <textarea rows={4} maxLength={2000} value={comment} onChange={(event) => setComment(event.target.value)}
          placeholder="Tell us about your service experience" />
      </label>
      <div className="row gap end">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || rating === 0}>{busy ? 'Submitting…' : 'Submit feedback'}</button>
      </div>
    </form>
  </Modal>
}

const COMPLAINT_OPTIONS = [
  ['service_not_done', 'Service not yet done'],
  ['incomplete_service', 'Incomplete service'],
  ['other_issue', 'Other issue'],
]

function ComplaintDialog({ job, busy, onClose, onSubmit }) {
  const [issueType, setIssueType] = useState('')
  const [description, setDescription] = useState('')
  const submit = (event) => {
    event.preventDefault()
    if (issueType) onSubmit({ issue_type: issueType, description })
  }

  return <Modal title={`Raise a complaint · ${job.job_number}`} onClose={onClose}>
    <form className="stack complaint-form" onSubmit={submit}>
      <fieldset className="complaint-options">
        <legend>What went wrong?</legend>
        {COMPLAINT_OPTIONS.map(([value, label]) => <label className="complaint-option" key={value}>
          <input type="radio" name="complaint-issue" value={value} required checked={issueType === value}
            onChange={(event) => setIssueType(event.target.value)} />
          <span>{label}</span>
        </label>)}
      </fieldset>
      <label className="feedback-comment-label">Description <span>(optional)</span>
        <textarea rows={4} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)}
          placeholder="Share any details that may help us resolve this issue" />
      </label>
      <div className="row gap end">
        <button type="button" className="btn" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || !issueType}>{busy ? 'Submitting…' : 'Submit complaint'}</button>
      </div>
    </form>
  </Modal>
}

const complaintLabel = (type) => COMPLAINT_OPTIONS.find(([value]) => value === type)?.[1] || 'Other issue'

export default function CustomerBookings() {
  const toast = useToast()
  const [bookings, setBookings] = useState(null)
  const [history, setHistory] = useState({})
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [feedbackJob, setFeedbackJob] = useState(null)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [complaintJob, setComplaintJob] = useState(null)
  const [complaintBusy, setComplaintBusy] = useState(false)
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

  const submitFeedback = async ({ rating, comment }) => {
    if (!feedbackJob) return
    setFeedbackBusy(true)
    try {
      const feedback = await Api.submitCustomerFeedback(feedbackJob.id, { rating, comment })
      setBookings((current) => current?.map((job) => job.id === feedbackJob.id ? { ...job, feedback } : job))
      setFeedbackJob(null)
      toast('Thank you for your feedback', 'success')
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setFeedbackBusy(false)
    }
  }

  const submitComplaint = async ({ issue_type, description }) => {
    if (!complaintJob) return
    setComplaintBusy(true)
    try {
      const complaint = await Api.submitCustomerComplaint(complaintJob.id, { issue_type, description })
      setBookings((current) => current?.map((job) => job.id === complaintJob.id ? { ...job, complaint } : job))
      setComplaintJob(null)
      toast('Your complaint has been submitted', 'success')
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setComplaintBusy(false)
    }
  }

  if (!bookings && !error) return <Loading what="Loading your bookings" />
  return <div className="stack customer-portal-page">
    <div className="page-head"><div><h1>Your bookings</h1><p className="muted">Updates refresh automatically.</p></div><button className="btn" onClick={load}>Refresh</button></div>
    <ErrorBox error={error} />
    {bookings?.length === 0 ? <Card><Empty>You have no bookings yet. Choose a service to get started.</Empty></Card> : bookings?.map((job) => <Card key={job.id}>
      <div className="customer-booking-head">
        <div><span className="muted small">{job.job_number}</span><h2>{job.title}</h2></div>
        <span className={`badge ${STAGE_BADGE[job.booking_stage] || `status-${job.status}`}`}>{stageLabel(job)}</span>
      </div>
      <div className="customer-booking-grid">
        <div><small>Appointment window</small><b>{fmtWindow(job.window_start, job.window_end)}</b></div>
        {arrival(job) && <div><small>{arrival(job).label}</small><b>{arrival(job).value}</b>{arrival(job).note && <small>{arrival(job).note}</small>}</div>}
        <div><small>Service address</small><b>{job.address || 'Address on booking'}</b></div>
        <div><small>Locality</small><b>{[job.service_locality, job.district, job.state].filter(Boolean).join(', ') || job.zone_name}</b></div>
        <div><small>Electrician</small><b>{job.assignment?.electrician_name || (job.booking_stage === 'reassignment_needed' ? 'Awaiting reassignment' : job.status === 'cancelled' ? '—' : 'Being matched')}</b></div>
        <div><small>Total (incl. visit fee and discounts)</small><b>{rupees(job.booking_amount)}</b><small>Payment {job.payment_status || 'pending'}</small></div>
      </div>
      {job.booking_stage === 'awaiting_response' && <p className="muted small">Your request has been sent. We’ll update this booking when the electrician responds.</p>}
      {job.booking_stage === 'reassignment_needed' && <p className="alert warning"><b>Electrician declined this request.</b>{job.booking_update_reason ? ` Reason: ${job.booking_update_reason}` : ' The request is back with dispatch for another available electrician.'}</p>}
      {job.booking_update_reason && job.request_status !== 'declined' && !job.cancel_reason && <p className="muted small">Latest update: {job.booking_update_reason}</p>}
      {job.cancel_reason && <p className="muted small">Latest update: {job.cancel_reason}</p>}
      <div className="row gap wrap customer-booking-actions">
        <button className="btn small" onClick={() => toggleHistory(job.id)}>{history[job.id] ? 'Hide updates' : 'View updates'}</button>
        {['pending', 'assigned', 'unassigned'].includes(job.status) && <button className="btn small danger" disabled={busy === job.id} onClick={() => cancel(job)}>{busy === job.id ? 'Cancelling…' : 'Cancel booking'}</button>}
        {job.booking_stage === 'completed' && !job.feedback && <button className="btn small primary" onClick={() => setFeedbackJob(job)}>Give feedback</button>}
        {!job.complaint && <button className="btn small" onClick={() => setComplaintJob(job)}>Raise a complaint</button>}
      </div>
      {job.feedback && <div className="customer-feedback-summary" role="status">
        <b>Thanks for your feedback</b>
        <span className="feedback-summary-stars" aria-label={`${job.feedback.rating} out of 5 stars`}>
          {'★'.repeat(job.feedback.rating)}{'☆'.repeat(5 - job.feedback.rating)}
        </span>
        <span>{job.feedback.rating}/5 stars</span>
        {job.feedback.comment && <p>{job.feedback.comment}</p>}
      </div>}
      {job.complaint && <div className="customer-complaint-summary" role="status">
        <b>Complaint submitted</b><span>{complaintLabel(job.complaint.issue_type)}</span>
        {job.complaint.description && <p>{job.complaint.description}</p>}
      </div>}
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
    {feedbackJob && <FeedbackDialog
      job={feedbackJob}
      busy={feedbackBusy}
      onClose={() => setFeedbackJob(null)}
      onSubmit={submitFeedback}
    />}
    {complaintJob && <ComplaintDialog
      job={complaintJob}
      busy={complaintBusy}
      onClose={() => setComplaintJob(null)}
      onSubmit={submitComplaint}
    />}
  </div>
}
