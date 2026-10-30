import { useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import JobDetail from '../components/JobDetail'
import { Card, Empty, ErrorBox, Loading, Stat, useLoad } from '../components/ui'
import { Api } from '../services/api'
import { fmtDateTime, rupees, stageLabel } from '../services/format'

export default function Dashboard() {
  const { version, bump } = useOutletContext()
  const [selected, setSelected] = useState(null)
  const { data, error, loading, reload } = useLoad(async () => {
    const [overview, portal] = await Promise.all([Api.overview(), Api.adminOverview()])
    return { overview, portal }
  }, [version])

  if (loading && !data) return <Loading what="Loading dashboard" />
  if (error) return <ErrorBox error={error} />
  const { overview: ov, portal } = data

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Operations dashboard</h1>
        <button className="btn" onClick={reload} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
        <span className="muted">
          {ov.latest_run ? <>Last schedule {fmtDateTime(ov.latest_run.finished_at)} · <Link to={`/history/${ov.latest_run.id}`}>run details</Link></> : 'No schedule yet — press “Run scheduling”.'}
        </span>
      </div>
      <p className="small"><Link to="/customers">Manage customer accounts</Link></p>
      {ov.latest_failed_run && ov.latest_failed_run.started_at > (ov.latest_run?.started_at || '') && (
        <div className="alert error">
          Latest run {ov.latest_failed_run.status.replaceAll('_', ' ')}: {ov.latest_failed_run.error}. The previous schedule is still in effect.
        </div>
      )}

      <div className="stats admin-summary-stats">
        <Stat label="Orders received today" value={portal.orders_today} hint={`${portal.total_orders} orders in total`} />
        <Stat label="Registered electricians" value={portal.electricians}
              hint={`${portal.active_electricians} active · ${portal.inactive_electricians} inactive`} />
        <Stat label="Electricians available now" value={portal.available_electricians} tone={portal.available_electricians ? 'good' : 'warn'}
              hint="Active, on shift, not on a job or marked unavailable" />
        <Stat label="Orders pending dispatch" value={portal.pending_dispatch} tone={portal.pending_dispatch ? 'warn' : 'good'}
              hint="Open orders with no electrician assigned" />
      </div>

      <Card title="Electricians" actions={<Link to="/electricians?status=all">Manage all profiles</Link>}>
        <div className="row gap wrap admin-electrician-actions">
          <Link className="btn primary" to="/electricians?register=1">Register electrician</Link>
          <Link className="btn" to="/electricians?status=inactive">View inactive ({portal.inactive_electricians})</Link>
          <span className="muted small">Removing an electrician deactivates the profile; past bookings and history are kept.</span>
        </div>
      </Card>

      <Card title={`Bookings (${portal.bookings})`} actions={<Link to="/jobs">Open jobs</Link>}>
        {!portal.jobs.length ? <Empty>No bookings yet.</Empty> : <div className="table-wrap">
          <table className="table compact"><thead><tr><th>Customer</th><th>Service</th><th>Locality</th><th>Electrician</th><th>Appointment</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody>{portal.jobs.map((job) => <tr key={job.id} className="clickable" onClick={() => setSelected(job.id)}>
              <td><b>{job.customer_name || 'Customer'}</b><div className="muted small">{job.job_number}</div></td>
              <td>{job.title}</td><td>{job.service_locality || job.district || job.zone_name}</td>
              <td>{job.assignment?.electrician_name || 'Needs assignment'}</td><td className="nowrap">{fmtDateTime(job.window_start)}</td>
              <td className="nowrap">{rupees(job.booking_amount)}</td>
              <td><span className={`badge status-${job.status}`}>{stageLabel(job)}</span></td>
            </tr>)}</tbody>
          </table>
        </div>}
      </Card>

      {selected && <JobDetail jobId={selected} onClose={() => setSelected(null)} onChanged={bump} />}
    </div>
  )
}
