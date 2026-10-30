import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import JobForm from '../components/JobForm'
import { BeforeAfter, ChangesTable, MetricsCompare, UnassignedList } from '../components/RunReport'
import { Card, ErrorBox, Loading, useLoad } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, fromLocalInput, humanize, toLocalInput } from '../services/format'

const TABS = [
  ['electrician-unavailable', 'Electrician unavailable'],
  ['urgent-job', 'Urgent job arrives'],
  ['job-duration-change', 'Job duration changes'],
  ['job-cancel', 'Job cancelled'],
  ['job-completion', 'Job finished early / late'],
]

function JobPicker({ jobs, value, onChange, label = 'Job' }) {
  return (
    <label className="span2">{label}
      <select required value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select…</option>
        {jobs.map((j) => (
          <option key={j.id} value={j.id}>
            {j.job_number} · {j.title} · {humanize(j.status)}{j.assignment ? ` · ${j.assignment.electrician_name} ${fmtDateTime(j.assignment.start)}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function Disruptions() {
  const { version, bump } = useOutletContext()
  const toast = useToast()
  const [tab, setTab] = useState(TABS[0][0])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1); tomorrow.setHours(8, 0, 0, 0)
  const tomorrowEnd = new Date(tomorrow); tomorrowEnd.setHours(18)
  const [f, setF] = useState({
    electrician_id: '', start: toLocalInput(tomorrow), end: toLocalInput(tomorrowEnd), reason: '',
    job_id: '', new_duration_minutes: '', completed_at: toLocalInput(new Date()),
  })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const { data, error, loading } = useLoad(async () => {
    const [electricians, jobs, skills, zones, previous] = await Promise.all([
      Api.electricians(), Api.jobs({ status: 'pending,assigned,in_progress,unassigned' }), Api.skills(), Api.zones(), Api.overview(),
    ])
    return { electricians, jobs, skills, zones, previous: previous.latest_run }
  }, [version])

  const submit = async (kind, body) => {
    setBusy(true)
    try {
      const prev = data.previous
      const res = await Api.disrupt(kind, body)
      setResult({ ...res, previous: prev })
      toast(`Recovered: ${res.run.changes.length} change(s), ${res.run.metrics.unchanged} assignment(s) untouched`, 'success')
      bump()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) return <Loading />
  const inProgress = data.jobs.filter((j) => j.status === 'in_progress')
  const open = data.jobs.filter((j) => j.status !== 'in_progress')
  const selectedJob = data.jobs.find((j) => String(j.id) === String(f.job_id))

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Disruptions &amp; recovery</h1>
        <span className="muted">Each disruption is recorded, then the schedule is repaired immediately. Unaffected work stays put; in-progress and completed work is never moved.</span>
      </div>
      <ErrorBox error={error} />
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''}
                  onClick={() => { setTab(k); setF({ ...f, job_id: '' }) }}>{label}</button>
        ))}
      </div>
      <Card>
        {tab === 'electrician-unavailable' && (
          <form className="form" onSubmit={(e) => { e.preventDefault(); submit(tab, { electrician_id: Number(f.electrician_id), start: fromLocalInput(f.start), end: fromLocalInput(f.end), reason: f.reason || 'Unavailable' }) }}>
            <label className="span2">Electrician
              <select required value={f.electrician_id} onChange={set('electrician_id')}>
                <option value="">Select…</option>
                {data.electricians.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.employee_code}) · {e.skills.length} skills · {e.zones.join('/')}</option>)}
              </select>
            </label>
            <label>From<input type="datetime-local" required value={f.start} onChange={set('start')} /></label>
            <label>To<input type="datetime-local" required value={f.end} onChange={set('end')} /></label>
            <label className="span2">Reason<input value={f.reason} onChange={set('reason')} placeholder="e.g. Sick leave, van breakdown" /></label>
            <div className="span2 row end"><button className="btn primary" disabled={busy}>{busy ? 'Recovering…' : 'Record & recover'}</button></div>
          </form>
        )}
        {tab === 'urgent-job' && (
          <JobForm skills={data.skills} zones={data.zones} fixedPriority="urgent" submitLabel={busy ? 'Recovering…' : 'Create urgent job & recover'}
                   onSubmit={(body) => submit(tab, body)} />
        )}
        {tab === 'job-duration-change' && (
          <form className="form" onSubmit={(e) => { e.preventDefault(); submit(tab, { job_id: Number(f.job_id), new_duration_minutes: Number(f.new_duration_minutes), reason: f.reason || null }) }}>
            <JobPicker jobs={data.jobs} value={f.job_id} onChange={(v) => {
              const j = data.jobs.find((x) => String(x.id) === v)
              setF({ ...f, job_id: v, new_duration_minutes: j ? j.duration_minutes + 60 : '' })
            }} />
            <label>New duration (minutes)
              <input type="number" required min={5} max={720} step={5} value={f.new_duration_minutes} onChange={set('new_duration_minutes')} />
            </label>
            <label>Reason<input value={f.reason} onChange={set('reason')} placeholder="e.g. extra circuits found" /></label>
            {selectedJob && <div className="span2 muted small">Current duration {selectedJob.duration_minutes} min. {selectedJob.status === 'in_progress' ? 'Job is in progress — longer means it is running late; it stays with its electrician.' : ''}</div>}
            <div className="span2 row end"><button className="btn primary" disabled={busy}>{busy ? 'Recovering…' : 'Apply & recover'}</button></div>
          </form>
        )}
        {tab === 'job-cancel' && (
          <form className="form" onSubmit={(e) => { e.preventDefault(); submit(tab, { job_id: Number(f.job_id), reason: f.reason || 'Cancelled by customer' }) }}>
            <JobPicker jobs={open} value={f.job_id} onChange={(v) => setF({ ...f, job_id: v })} />
            <label className="span2">Reason<input value={f.reason} onChange={set('reason')} placeholder="Cancelled by customer" /></label>
            <div className="span2 row end"><button className="btn danger" disabled={busy}>{busy ? 'Recovering…' : 'Cancel job & recover'}</button></div>
          </form>
        )}
        {tab === 'job-completion' && (
          <form className="form" onSubmit={(e) => { e.preventDefault(); submit(tab, { job_id: Number(f.job_id), completed_at: fromLocalInput(f.completed_at) }) }}>
            {inProgress.length === 0 ? <div className="span2 muted">No job is in progress. Start an assigned job from the Jobs or Schedule page first.</div> : (
              <>
                <JobPicker jobs={inProgress} value={f.job_id} label="In-progress job" onChange={(v) => {
                  const j = inProgress.find((x) => String(x.id) === v)
                  const expected = j ? new Date(new Date(j.actual_start).getTime() + j.duration_minutes * 60000) : new Date()
                  setF({ ...f, job_id: v, completed_at: toLocalInput(expected) })
                }} />
                {selectedJob && (
                  <div className="span2 muted small">
                    Started {fmtDateTime(selectedJob.actual_start)}; expected to finish{' '}
                    {fmtDateTime(toLocalInput(new Date(new Date(selectedJob.actual_start).getTime() + selectedJob.duration_minutes * 60000)))}.
                    Pick an earlier time for an early finish or a later one for a late finish.
                  </div>
                )}
                <label>Completed at<input type="datetime-local" required value={f.completed_at} onChange={set('completed_at')} /></label>
                <div className="span2 row end"><button className="btn primary" disabled={busy}>{busy ? 'Recovering…' : 'Mark completed & recover'}</button></div>
              </>
            )}
          </form>
        )}
      </Card>

      {result && (
        <Card title="Recovery result">
          <div className="callout">
            <b>{humanize(result.disruption.type)}</b>{' '}
            {Object.entries(result.disruption).filter(([k, v]) => k !== 'type' && v != null && !(Array.isArray(v) && !v.length)).map(([k, v]) => (
              <span key={k} className="kv"><span className="muted">{humanize(k)}:</span> {Array.isArray(v) ? v.join(', ') : String(v)}</span>
            ))}
          </div>
          <div className="grid side">
            <MetricsCompare before={result.previous?.metrics} after={result.run.metrics}
                            beforeObjective={result.previous?.objective_score} afterObjective={result.run.objective_score} />
            <div>
              <h3>Electricians whose plan changed</h3>
              <BeforeAfter before={result.run.before_snapshot} after={result.run.after_snapshot} changes={result.run.changes} />
            </div>
          </div>
          <p className="muted small">{result.run.metrics.unchanged} assignment(s) were preserved unchanged; {result.run.metrics.in_progress_protected} in-progress job(s) were protected.</p>
          <h3>What changed and why</h3>
          <ChangesTable changes={result.run.changes} />
          <h3>Unassigned after recovery</h3>
          <UnassignedList items={result.run.unassigned} />
        </Card>
      )}
    </div>
  )
}
