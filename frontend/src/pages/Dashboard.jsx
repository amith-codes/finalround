import { useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import JobDetail from '../components/JobDetail'
import { BeforeAfter, ChangesTable, MetricsCompare } from '../components/RunReport'
import { Card, Empty, ErrorBox, Loading, PriorityBadge, Reasons, SlaBadge, Stat, StatusBadge, useLoad } from '../components/ui'
import { Api } from '../services/api'
import { fmtDateTime, humanize, isoDay, minutesLabel, PRIORITIES, STATUSES } from '../services/format'

export default function Dashboard() {
  const { version, bump } = useOutletContext()
  const [selected, setSelected] = useState(null)
  const today = isoDay(new Date())
  const [earningsPeriod, setEarningsPeriod] = useState({ start: `${today.slice(0, 8)}01`, end: today })
  const { data, error, loading } = useLoad(async () => {
    const [overview, sla, workload, comparison, portal, earnings] = await Promise.all([
      Api.overview(), Api.sla(), Api.workload(isoDay(new Date()), 4), Api.comparison(), Api.adminOverview(),
      Api.adminEarnings(earningsPeriod.start, earningsPeriod.end),
    ])
    return { overview, sla, workload, comparison, portal, earnings }
  }, [version, earningsPeriod])

  if (loading && !data) return <Loading what="Loading dashboard" />
  if (error) return <ErrorBox error={error} />
  const { overview: ov, sla, workload, comparison, portal, earnings } = data
  const run = comparison.run
  const s = ov.jobs_by_status
  const maxUtil = Math.max(100, ...workload.electricians.map((e) => e.utilisation_pct || 0))

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Operations dashboard</h1>
        <span className="muted">
          {ov.latest_run ? <>Last schedule {fmtDateTime(ov.latest_run.finished_at)} · <Link to={`/history/${ov.latest_run.id}`}>run details</Link></> : 'No schedule yet — press “Run scheduling”.'}
        </span>
      </div>
      <p className="small"><Link to="/customers">Manage customer accounts</Link></p>
      {ov.latest_failed_run && ov.latest_failed_run.started_at > (ov.latest_run?.started_at || '') && (
        <div className="alert error">
          Latest run {humanize(ov.latest_failed_run.status)}: {ov.latest_failed_run.error}. The previous schedule is still in effect.
        </div>
      )}

      <div className="stats">
        <Stat label="Open jobs" value={s.pending + s.assigned + s.unassigned + s.in_progress} />
        <Stat label="Assigned" value={s.assigned} tone="good" />
        <Stat label="In progress" value={s.in_progress} tone="info" />
        <Stat label="Unassigned" value={s.unassigned} tone={s.unassigned ? 'warn' : ''} hint={`${s.pending} pending, not yet scheduled`} />
        <Stat label="SLA overdue / late" value={`${sla.counts.overdue} / ${sla.counts.late}`} tone={sla.counts.overdue + sla.counts.late ? 'bad' : ''} />
        <Stat label="SLA at risk" value={sla.counts.at_risk} tone={sla.counts.at_risk ? 'warn' : ''} />
        <Stat label="Electricians on shift" value={`${(ov.electricians.on_shift || 0) + (ov.electricians.on_job || 0)} / ${ov.electricians.total}`}
              hint={`${ov.electricians.on_job || 0} on a job · ${ov.electricians.unavailable || 0} unavailable`} />
      </div>

      <div className="stats portal-admin-stats">
        <Stat label="Bookings in view" value={portal.bookings} />
        <Stat label="Booking value" value={`₹${Number(portal.payment_total).toFixed(2)}`} hint={`${portal.payment_status.pending} payments pending`} />
        <Stat label="Customers" value={portal.customers} />
        <Stat label="Electricians available" value={`${portal.available_electricians} / ${portal.electricians}`} tone="good" />
        <Stat label="Needs dispatch attention" value={portal.needs_attention} tone={portal.needs_attention ? 'warn' : 'good'} />
      </div>

      <Card title="Electrician earnings" actions={<span className="muted small">Gross service value for completed bookings</span>}>
        <div className="period-filter"><label>From<input type="date" value={earningsPeriod.start} onChange={(e) => setEarningsPeriod({ ...earningsPeriod, start: e.target.value })} /></label><label>To<input type="date" value={earningsPeriod.end} onChange={(e) => setEarningsPeriod({ ...earningsPeriod, end: e.target.value })} /></label></div>
        {!earnings.electricians.length ? <Empty>No completed booking earnings in this period.</Empty> : <div className="table-wrap"><table className="table compact"><thead><tr><th>Electrician</th><th>Completed bookings</th><th>Gross value</th></tr></thead><tbody>{earnings.electricians.map((item) => <tr key={item.electrician_id}><td><b>{item.electrician_name}</b><div className="muted small">{item.employee_code}</div></td><td>{item.bookings.length}<div className="muted small">{item.bookings.map((job) => job.job_number).join(', ')}</div></td><td>₹{Number(item.gross_earnings).toFixed(2)}</td></tr>)}</tbody></table></div>}
      </Card>

      <div className="grid two">
        <Card title="Jobs by status and priority">
          <table className="table compact matrix">
            <thead>
              <tr><th>Status</th>{PRIORITIES.map((p) => <th key={p}><PriorityBadge value={p} /></th>)}<th>Total</th></tr>
            </thead>
            <tbody>
              {STATUSES.map((st) => (
                <tr key={st}>
                  <td><StatusBadge value={st} /></td>
                  {PRIORITIES.map((p) => {
                    const n = ov.status_priority_matrix[st][p]
                    return <td key={p} className={n ? (st === 'unassigned' && (p === 'urgent' || p === 'high') ? 'hot' : '') : 'zero'}>{n}</td>
                  })}
                  <td className="strong">{s[st]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="SLA risk" actions={<span className="muted small">sorted by time to deadline</span>}>
          {[...sla.overdue, ...sla.late, ...sla.at_risk].length === 0 ? <Empty>No SLA risks.</Empty> : (
            <div className="table-wrap short">
              <table className="table compact">
                <thead><tr><th>Job</th><th>State</th><th>Deadline</th><th>Left</th></tr></thead>
                <tbody>
                  {[...sla.overdue, ...sla.late, ...sla.at_risk].map((j) => (
                    <tr key={j.id} className="clickable" onClick={() => setSelected(j.id)}>
                      <td><b>{j.job_number}</b> <PriorityBadge value={j.priority} /><div className="muted small">{j.title}</div></td>
                      <td><SlaBadge value={j.sla_state} /><div className="small muted">{humanize(j.status)}</div></td>
                      <td className="nowrap">{fmtDateTime(j.sla_deadline)}</td>
                      <td className={j.minutes_to_sla < 0 ? 'bad' : ''}>{minutesLabel(j.minutes_to_sla)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <div className="grid two">
        <Card title={`Unassigned jobs (${sla.unassigned.length})`} actions={<Link to="/jobs?status=unassigned">open in Jobs</Link>}>
          {sla.unassigned.length === 0 ? <Empty>Nothing unassigned.</Empty> : (
            <div className="unassigned-list scroll">
              {[...sla.unassigned].sort((a, b) => PRIORITIES.indexOf(a.priority) - PRIORITIES.indexOf(b.priority)).map((j) => (
                <div key={j.id} className="unassigned-item clickable" onClick={() => setSelected(j.id)}>
                  <div className="row gap wrap">
                    <b>{j.job_number}</b> <PriorityBadge value={j.priority} />
                    <span className={`badge feas-${j.feasibility}`}>{humanize(j.feasibility)}</span>
                    <span className="muted small">{j.zone_code} · {fmtDateTime(j.window_start)}</span>
                  </div>
                  <div className="small">{j.title}</div>
                  <Reasons reasons={(j.unassigned_reasons || []).filter((r) => r.code !== 'HISTORY').slice(0, 1)} />
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Electrician workload" actions={<span className="muted small">{workload.from} → {workload.to}</span>}>
          <div className="table-wrap short">
            <table className="table compact">
              <thead><tr><th>Electrician</th><th>Status</th><th>Jobs</th><th>Utilisation (work + travel / shift)</th></tr></thead>
              <tbody>
                {workload.electricians.map((e) => (
                  <tr key={e.electrician_id}>
                    <td><b>{e.name}</b><div className="muted small">{e.zones.join(' · ')}</div></td>
                    <td><span className={`badge avail-${e.status}`}>{humanize(e.status)}</span></td>
                    <td>{e.jobs}{e.urgent_or_high ? <span className="muted small"> ({e.urgent_or_high} hi)</span> : null}</td>
                    <td>
                      <div className="bar" title={`${e.work_minutes} min work, ${e.travel_minutes} min travel of ${e.shift_minutes} min shift`}>
                        <div className="bar-work" style={{ width: `${(100 * e.work_minutes / (e.shift_minutes || 1)) * 100 / maxUtil}%` }} />
                        <div className="bar-travel" style={{ width: `${(100 * e.travel_minutes / (e.shift_minutes || 1)) * 100 / maxUtil}%` }} />
                      </div>
                      <span className="small">{e.utilisation_pct ?? 0}%</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="legend small"><span className="sw work" /> work <span className="sw travel" /> travel</div>
        </Card>
      </div>

      {run ? (
        <Card title={`Latest run: before vs after (${humanize(run.trigger)})`}
              actions={<Link to={`/history/${run.id}`}>full audit record</Link>}>
          <div className="grid side">
            <MetricsCompare before={comparison.previous_metrics} after={run.metrics}
                            beforeObjective={comparison.previous_objective} afterObjective={run.objective_score} />
            <div>
              <h3>Electricians whose plan changed</h3>
              <BeforeAfter before={run.before_snapshot} after={run.after_snapshot} changes={run.changes} />
            </div>
          </div>
          <h3>Changes and reasons</h3>
          <ChangesTable changes={run.changes} />
        </Card>
      ) : <Card title="Latest run"><Empty>No scheduling run yet.</Empty></Card>}

      {selected && <JobDetail jobId={selected} onClose={() => setSelected(null)} onChanged={bump} />}
    </div>
  )
}
