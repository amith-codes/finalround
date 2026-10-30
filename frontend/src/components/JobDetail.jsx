import { useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, fmtTime, humanize } from '../services/format'
import { Loading, Modal, PriorityBadge, Reasons, SlaBadge, StatusBadge, useLoad } from './ui'

export default function JobDetail({ jobId, onClose, onChanged }) {
  const toast = useToast()
  const { data, loading, reload } = useLoad(async () => {
    const [schedule, audit, candidates] = await Promise.all([
      Api.jobSchedule(jobId), Api.bookingHistory(jobId), Api.dispatchCandidates(jobId),
    ])
    return { ...schedule, audit, candidates }
  }, [jobId])
  const [busy, setBusy] = useState(false)
  const [candidateId, setCandidateId] = useState('')
  const [assignmentReason, setAssignmentReason] = useState('Local dispatch review')

  const act = async (fn, msg) => {
    setBusy(true)
    try {
      const res = await fn()
      toast(msg(res), 'success')
      await reload()
      onChanged?.()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  const job = data?.job
  const storedZoneReason = Boolean(job?.service_locality && data?.unassigned_reasons?.some(
    (reason) => reason.code === 'LOCALITY_COVERAGE' && /\bzone\s+\w+/i.test(reason.message || ''),
  ))
  return (
    <Modal title={job ? `${job.job_number} · ${job.title}` : 'Job'} onClose={onClose} wide>
      {loading && !data ? <Loading /> : job && (
        <div className="stack">
          <div className="row gap wrap">
            <StatusBadge value={job.status} /> <PriorityBadge value={job.priority} /> <SlaBadge value={job.sla_state} />
            {job.feasibility && job.feasibility !== 'feasible' && <span className={`badge feas-${job.feasibility}`}>{humanize(job.feasibility)}</span>}
          </div>
          <dl className="details">
            <dt>Customer</dt><dd>{job.customer_name || '—'} · {job.address || '—'}</dd>
            {!job.service_locality && <><dt>Zone</dt><dd>{job.zone_name} ({job.zone_code})</dd></>}
            {job.service_locality && <><dt>Service locality</dt><dd>{job.service_locality}, {job.district}, {job.state}</dd></>}
            <dt>Skills</dt><dd>{job.required_skills.map(humanize).join(', ')}</dd>
            <dt>Duration</dt><dd>{job.duration_minutes} min</dd>
            <dt>Time window</dt><dd>{fmtDateTime(job.window_start)} – {fmtDateTime(job.window_end)}</dd>
            <dt>SLA deadline</dt><dd>{fmtDateTime(job.sla_deadline)}</dd>
            {job.actual_start && <><dt>Started</dt><dd>{fmtDateTime(job.actual_start)}</dd></>}
            {job.actual_end && <><dt>Completed</dt><dd>{fmtDateTime(job.actual_end)}</dd></>}
            {job.cancel_reason && <><dt>Cancelled</dt><dd>{job.cancel_reason}</dd></>}
          </dl>

          {job.booking_amount > 0 && <div className="row gap wrap payment-status-control">
            <b>Payment ₹{Number(job.booking_amount).toFixed(2)}</b>
            <label>Payment status <select value={job.payment_status || 'pending'} disabled={busy} onChange={(event) => act(
              () => Api.updatePaymentStatus(job.id, event.target.value),
              (result) => `Payment marked ${result.payment_status}`,
            )}><option value="pending">Pending</option><option value="paid">Paid</option><option value="failed">Failed</option><option value="refunded">Refunded</option></select></label>
          </div>}

          {data.current_assignment && (
            <div className="callout">
              <div className="strong">
                {data.current_assignment.electrician_name} · {fmtDateTime(data.current_assignment.start)}–{fmtTime(data.current_assignment.end)}
              </div>
              <div className="small">{data.explanation}</div>
            </div>
          )}
          {job.status === 'unassigned' && data.unassigned_reasons && (
            <div>
              <h3>Why it is not scheduled</h3>
              {storedZoneReason
                ? <p className="muted small">This saved diagnostic came from an earlier zone-based run. Customer reassignment now uses the service locality.</p>
                : <Reasons reasons={data.unassigned_reasons} />}
            </div>
          )}

          {data.changes.length > 0 && (
            <div>
              <h3>Schedule history</h3>
              <ul className="timeline-list">
                {data.changes.map((c) => (
                  <li key={c.id}>
                    <span className={`badge change-${c.change_type}`}>{humanize(c.change_type)}</span>{' '}
                    {c.old_electrician_name || '—'} → {c.new_electrician_name || '—'}
                    {c.new_start && <span className="muted"> ({fmtDateTime(c.new_start)})</span>}
                    <div className="small muted">{job.service_locality && /\b(zone|zones|skills?)\b/i.test(c.reason || '')
                      ? 'Historical dispatch note from before customer reassignment used locality-based eligibility.'
                      : c.reason}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {['pending', 'assigned', 'unassigned'].includes(job.status) && <div className="dispatch-manual-box">
            <h3>Manual assignment</h3>
            <p className="muted small">{job.service_locality
              ? 'Customer bookings are matched by service locality; catalog skills and legacy zones do not restrict reassignment.'
              : 'Eligible electricians match the job skills and service zone.'}</p>
            <div className="row gap wrap">
              <select value={candidateId} onChange={(e) => setCandidateId(e.target.value)} aria-label="Choose an electrician">
                <option value="">Choose an electrician</option>
                {data.candidates.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.current_status} · {e.serves_locality ? 'local' : 'outside locality'}</option>)}
              </select>
              <input value={assignmentReason} onChange={(e) => setAssignmentReason(e.target.value)} placeholder="Assignment reason" />
              <button className="btn primary" disabled={busy || !candidateId || !assignmentReason.trim()} onClick={() => act(
                () => Api.manualAssign(job.id, Number(candidateId), assignmentReason),
                () => 'Booking assigned manually',
              )}>Assign / reassign</button>
            </div>
            {!data.candidates.length && <div className="muted small">{job.service_locality
              ? `No active electrician is registered for ${job.service_locality}.`
              : 'No active electrician matches this job’s skills and zone.'}</div>}
          </div>}

          {!!data.audit.events.length && <div><h3>Booking history</h3><ul className="timeline-list">{data.audit.events.map((event) => <li key={event.id}>
            <b>{humanize(event.action)}</b> · {event.actor || event.actor_role} <span className="muted">({fmtDateTime(event.created_at)})</span>
            {event.reason && <div className="small muted">{event.reason}</div>}
          </li>)}</ul></div>}

          <div className="row gap">
            {job.status === 'assigned' && (
              <button className="btn" disabled={busy} onClick={() => act(() => Api.startJob(job.id), () => 'Job started')}>
                Start job
              </button>
            )}
            {job.status === 'in_progress' && (
              <button className="btn" disabled={busy}
                      onClick={() => act(() => Api.disrupt('job-completion', { job_id: job.id }),
                        (r) => `Completed ${r.disruption.timing}; schedule recovered`)}>
                Mark completed
              </button>
            )}
            {['pending', 'assigned', 'unassigned'].includes(job.status) && (
              <button className="btn danger" disabled={busy}
                      onClick={() => act(() => Api.disrupt('job-cancel', { job_id: job.id, reason: 'Cancelled by dispatcher' }),
                        (r) => `Cancelled; ${r.run.changes.length} schedule change(s)`)}>
                Cancel job &amp; recover
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}
