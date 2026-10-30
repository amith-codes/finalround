import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { BeforeAfter, ChangesTable, UnassignedList } from '../components/RunReport'
import { Card, Empty, ErrorBox, Loading, useLoad } from '../components/ui'
import { Api } from '../services/api'
import { fmtDateTime, humanize } from '../services/format'

function RunDetail({ runId }) {
  const { data: run, error, loading } = useLoad(() => Api.run(runId), [runId])
  if (loading && !run) return <Loading />
  if (error) return <ErrorBox error={error} />
  const bd = run.objective_breakdown || {}
  const stats = run.algorithm_stats || {}
  return (
    <div className="stack">
      <Card title={`Run ${run.id.slice(0, 8)} · ${humanize(run.trigger)}`}>
        <dl className="details">
          <dt>Status</dt><dd><span className={`badge run-${run.status}`}>{humanize(run.status)}</span>{run.error && <span className="bad"> {run.error}</span>}</dd>
          <dt>Started</dt><dd>{fmtDateTime(run.started_at)} (planning clock {fmtDateTime(run.as_of)})</dd>
          <dt>Mode</dt><dd>{humanize(run.mode)}{stats.strategy && <> · chose <b>{humanize(stats.strategy)}</b> plan</>}{stats.candidate_objectives && <span className="muted"> {JSON.stringify(stats.candidate_objectives)}</span>}</dd>
          <dt>Jobs</dt><dd>{run.jobs_considered?.length ?? 0} considered · {run.jobs_assigned?.length ?? 0} assigned · {run.unassigned?.length ?? 0} unassigned</dd>
          <dt>Objective</dt><dd><b>{run.objective_score ?? '—'}</b>
            {bd.total != null && <span className="muted"> = travel {bd.travel_cost} + lateness {bd.late_cost} + overtime {bd.overtime_cost} + changes {bd.change_cost} + unassigned {bd.unassigned_cost}</span>}
          </dd>
          <dt>Performance</dt><dd>{stats.runtime_ms ?? '—'} ms · {stats.route_evaluations ?? '—'} route evaluations · {stats.improvement_rounds ?? '—'} improvement rounds</dd>
          {run.disruption && <><dt>Disruption</dt><dd><code>{JSON.stringify(run.disruption)}</code></dd></>}
          <dt>Previous run</dt><dd>{run.previous_run_id ? <Link to={`/history/${run.previous_run_id}`}>{run.previous_run_id.slice(0, 8)}</Link> : '—'}</dd>
        </dl>
      </Card>
      {run.status === 'completed' && (
        <>
          <Card title="Before vs after"><BeforeAfter before={run.before_snapshot} after={run.after_snapshot} changes={run.changes} /></Card>
          <Card title={`Changes (${run.changes.length})`}><ChangesTable changes={run.changes} /></Card>
          <Card title={`Unassigned jobs (${run.unassigned.length})`}><UnassignedList items={run.unassigned} /></Card>
        </>
      )}
    </div>
  )
}

export default function History() {
  const { runId } = useParams()
  const { version } = useOutletContext()
  const navigate = useNavigate()
  const { data: runs, error, loading } = useLoad(() => Api.history(100), [version])

  return (
    <div className="stack">
      <div className="page-head"><h1>Scheduling history &amp; audit</h1></div>
      <ErrorBox error={error} />
      <div className="grid history">
        <Card title="Runs">
          {loading && !runs ? <Loading /> : !runs?.length ? <Empty>No runs yet.</Empty> : (
            <ul className="run-list">
              {runs.map((r) => (
                <li key={r.id} className={r.id === runId ? 'on' : ''} onClick={() => navigate(`/history/${r.id}`)}>
                  <div className="row gap">
                    <span className={`badge run-${r.status}`}>{humanize(r.status)}</span>
                    <b>{humanize(r.trigger)}</b>
                  </div>
                  <div className="muted small">{fmtDateTime(r.started_at)} · {r.id.slice(0, 8)}</div>
                  {r.metrics && (
                    <div className="small">
                      {r.metrics.assigned} assigned · {r.metrics.unassigned} unassigned ·{' '}
                      {r.metrics.changes.reassigned + r.metrics.changes.retimed + r.metrics.changes.assigned + r.metrics.changes.unassigned} changes
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div>{runId ? <RunDetail runId={runId} /> : <Card><Empty>Select a run to see its full audit record.</Empty></Card>}</div>
      </div>
    </div>
  )
}
