import { useCallback, useEffect, useMemo, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, humanize } from '../services/format'
import { Card, Empty, ErrorBox, Loading } from '../components/ui'

const localDay = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const monthStart = () => { const d = new Date(); d.setDate(1); return localDay(d) }

function BookingCard({ job, offer, action }) {
  const [busy, setBusy] = useState(false)
  const run = async (kind) => {
    let reason = null
    if (['decline', 'cancel', 'customer_unavailable'].includes(kind)) {
      reason = window.prompt(kind === 'customer_unavailable' ? 'Why was the customer unavailable?' : `${humanize(kind)} reason:`)
      if (reason === null) return
      if (!reason.trim()) { window.alert('Enter a short reason to continue.'); return }
    }
    setBusy(true)
    try { await action(job.id, kind, reason); } catch { /* The dashboard shows the action error toast. */ }
    finally { setBusy(false) }
  }
  return <article className="electrician-booking-card">
    <div className="electrician-booking-title"><div><span className="muted small">{job.job_number} · {job.service_locality || job.district || job.zone_name}</span><h3>{job.title}</h3></div>
      <span className={`badge st-${job.status}`}>{humanize(job.status)}</span></div>
    <div className="customer-booking-grid">
      <div><small>Appointment</small><b>{fmtDateTime(job.window_start)}</b></div>
      <div><small>Customer</small><b>{job.customer_name || 'Customer'}</b></div>
      <div><small>Contact</small><b>{job.customer_phone || 'Not provided'}</b></div>
      <div><small>Location</small><b>{job.address || job.zone_name}</b></div>
      <div><small>Skills</small><b>{job.required_skills.map(humanize).join(', ')}</b></div>
    </div>
    <div className="row gap wrap customer-booking-actions">
      {offer ? <><button className="btn primary small" disabled={busy} onClick={() => run('accept')}>Accept booking</button><button className="btn small" disabled={busy} onClick={() => run('decline')}>Decline</button></> : <>
        {job.status === 'assigned' && job.booking_action !== 'accepted' && <button className="btn primary small" disabled={busy} onClick={() => run('accept')}>Accept</button>}
        {job.status === 'assigned' && <button className="btn small" disabled={busy} onClick={() => run('start')}>Start work</button>}
        {job.status === 'in_progress' && <button className="btn primary small" disabled={busy} onClick={() => run('complete')}>Mark completed</button>}
        {job.status === 'assigned' && <><button className="btn small" disabled={busy} onClick={() => run('customer_unavailable')}>Customer unavailable</button><button className="btn danger small" disabled={busy} onClick={() => run('cancel')}>Cancel assignment</button></>}
      </>}
    </div>
  </article>
}

export default function ElectricianPortal() {
  const toast = useToast()
  const [home, setHome] = useState(null)
  const [earnings, setEarnings] = useState(null)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState({ start: monthStart(), end: localDay(new Date()) })
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    try {
      const [bookings, totals] = await Promise.all([Api.electricianBookings(), Api.electricianEarnings(period.start, period.end)])
      setHome(bookings); setEarnings(totals); setError(null)
    } catch (e) { setError(errorMessage(e)) }
  }, [period])
  useEffect(() => { load(); const timer = setInterval(load, 30000); return () => clearInterval(timer) }, [load])

  const act = async (id, action, reason) => {
    try { await Api.electricianAction(id, action, reason); toast(`Booking ${action.replaceAll('_', ' ')}`, 'success'); await load() }
    catch (e) { toast(errorMessage(e), 'error'); throw e }
  }
  const duty = async (action) => {
    setBusy(true)
    try { const result = await Api.electricianDuty(action); toast(action.replace('_', ' '), 'success'); if (result.released_bookings) toast(`${result.released_bookings} booking(s) returned to dispatch`, 'info'); await load() }
    catch (e) { toast(errorMessage(e), 'error') }
    finally { setBusy(false) }
  }
  const shiftText = useMemo(() => home?.electrician?.shifts?.map((shift) => `${['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][shift.day_of_week]} ${shift.start_time}–${shift.end_time}`).join(' · ') || 'No weekly shifts listed', [home])
  if (!home && !error) return <Loading what="Loading electrician dashboard" />
  return <div className="stack electrician-portal">
    <div className="page-head"><div><h1>Electrician dashboard</h1><p className="muted">Your assignments, service areas and time on duty.</p></div><button className="btn" onClick={load}>Refresh</button></div>
    <ErrorBox error={error} />
    {home && <>
      <div className="stats electrician-stats">
        <div className="stat"><span>Availability</span><b>{home.availability.is_available ? home.electrician.current_status.replaceAll('_', ' ') : 'unavailable'}</b></div>
        <div className="stat"><span>Duty time · selected period</span><b>{Math.floor((earnings?.duty_minutes || 0) / 60)}h {(earnings?.duty_minutes || 0) % 60}m</b></div>
        <div className="stat"><span>Gross earnings · completed jobs</span><b>₹{Number(earnings?.gross_earnings || 0).toFixed(2)}</b></div>
      </div>
      <Card title="Duty and availability" actions={<span className={`badge avail-${home.electrician.current_status}`}>{humanize(home.electrician.current_status)}</span>}>
        <div className="duty-row"><div><b>{home.electrician.name}</b><small>{home.electrician.employee_code} · Service localities: {home.electrician.localities.join(', ') || 'None configured'}</small><small>Shifts: {shiftText}</small><small>Duty session: {home.on_duty ? 'Clocked in' : 'Clocked out'}</small></div>
          <div className="row gap wrap"><button className="btn small" disabled={busy || home.on_duty} onClick={() => duty('clock_in')}>Clock in</button><button className="btn small" disabled={busy || !home.on_duty} onClick={() => duty('clock_out')}>Clock out</button><button className={`btn small ${home.availability.is_available ? 'danger' : 'primary'}`} disabled={busy} onClick={() => duty(home.availability.is_available ? 'unavailable' : 'available')}>{home.availability.is_available ? 'Set unavailable' : 'Set available'}</button></div>
        </div>
      </Card>
      <Card title={`New bookings (${home.offers.length})`}>
        {!home.offers.length ? <Empty>No local bookings are waiting for your response.</Empty> : <div className="electrician-booking-list">{home.offers.map((job) => <BookingCard key={job.id} job={job} offer action={act} />)}</div>}
      </Card>
      <Card title={`Assigned and active (${home.assigned.length})`}>
        {!home.assigned.length ? <Empty>No assigned bookings.</Empty> : <div className="electrician-booking-list">{home.assigned.map((job) => <BookingCard key={job.id} job={job} action={act} />)}</div>}
      </Card>
      <Card title="Earnings by completed booking" actions={<span className="muted small">Gross booking value · INR</span>}>
        <div className="period-filter"><label>From<input type="date" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></label><label>To<input type="date" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></label></div>
        {!earnings?.bookings.length ? <Empty>No completed bookings in this period.</Empty> : <div className="table-wrap"><table className="table"><thead><tr><th>Booking</th><th>Completed</th><th>Service</th><th>Gross value</th></tr></thead><tbody>{earnings.bookings.map((job) => <tr key={job.id}><td><b>{job.job_number}</b></td><td>{fmtDateTime(job.actual_end)}</td><td>{job.title}</td><td>₹{Number(job.booking_amount || 0).toFixed(2)}</td></tr>)}</tbody></table></div>}
        <p className="muted small">Payout splits are not configured; totals use the booking service amount.</p>
      </Card>
    </>}
  </div>
}
