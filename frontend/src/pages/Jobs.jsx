import { useMemo, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import JobDetail from '../components/JobDetail'
import JobForm from '../components/JobForm'
import { Card, ErrorBox, Loading, Modal, PriorityBadge, SlaBadge, StatusBadge, useLoad } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { fmtDateTime, fmtTime, humanize, PRIORITIES, STATUSES } from '../services/format'

export default function Jobs() {
  const { version, bump } = useOutletContext()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [locality, setLocality] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [modal, setModal] = useState(null) // {mode: 'create'|'edit', job?}
  const [selected, setSelected] = useState(null)
  const status = params.get('status') || ''
  const priority = params.get('priority') || ''
  const zone = params.get('zone') || ''

  const { data, error, loading } = useLoad(async () => {
    const [jobs, skills, zones] = await Promise.all([Api.jobs(), Api.skills(), Api.zones()])
    return { jobs, skills, zones }
  }, [version])

  const setFilter = (k, v) => {
    const next = new URLSearchParams(params)
    v ? next.set(k, v) : next.delete(k)
    setParams(next, { replace: true })
  }

  const rows = useMemo(() => {
    if (!data) return []
    const needle = q.trim().toLowerCase()
    return data.jobs.filter((j) =>
      (!status || j.status === status) && (!priority || j.priority === priority) && (!zone || j.zone_code === zone) &&
      (!locality || `${j.service_locality || ''} ${j.district || ''} ${j.state || ''}`.toLowerCase().includes(locality.toLowerCase())) &&
      (!dateFrom || j.window_start.slice(0, 10) >= dateFrom) && (!dateTo || j.window_start.slice(0, 10) <= dateTo) &&
      (!needle || `${j.job_number} ${j.title} ${j.customer_name} ${j.required_skills.join(' ')}`.toLowerCase().includes(needle)))
  }, [data, q, status, priority, zone, locality, dateFrom, dateTo])

  const save = async (body) => {
    try {
      if (modal.mode === 'create') {
        const job = await Api.createJob(body)
        toast(`${job.job_number} created — run scheduling to assign it`, 'success')
      } else {
        await Api.updateJob(modal.job.id, body)
        toast('Job updated', 'success')
      }
      setModal(null)
      bump()
    } catch (e) {
      toast(errorMessage(e), 'error')
    }
  }

  if (loading && !data) return <Loading what="Loading jobs" />
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Service jobs</h1>
        <button className="btn primary" onClick={() => setModal({ mode: 'create' })}>New job</button>
      </div>
      <ErrorBox error={error} />
      <Card>
        <div className="filters">
          <input type="search" placeholder="Search number, title, customer, skill…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Status">
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
          <select value={priority} onChange={(e) => setFilter('priority', e.target.value)} aria-label="Priority">
            <option value="">All priorities</option>
            {PRIORITIES.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
          </select>
          <select value={zone} onChange={(e) => setFilter('zone', e.target.value)} aria-label="Zone">
            <option value="">All zones</option>
            {data?.zones.map((z) => <option key={z.code} value={z.code}>{z.name}</option>)}
          </select>
          <input type="search" placeholder="Filter locality" value={locality} onChange={(e) => setLocality(e.target.value)} />
          <label className="filter-date">From<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></label>
          <label className="filter-date">To<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
          <span className="muted small">{rows.length} of {data?.jobs.length}</span>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>Job</th><th>Priority</th><th>Status</th><th>Zone · skills</th><th>Window</th><th>SLA</th><th>Assigned to</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((j) => (
                <tr key={j.id} className="clickable" onClick={() => setSelected(j.id)}>
                  <td><b>{j.job_number}</b><div className="small">{j.title}</div><div className="muted small">{j.customer_name}</div></td>
                  <td><PriorityBadge value={j.priority} /></td>
                  <td>
                    <StatusBadge value={j.status} />
                    {j.status === 'unassigned' && j.unassigned_reasons?.[0] && (
                      <div className="small muted reason-line" title={j.unassigned_reasons[0].message}>{humanize(j.unassigned_reasons[0].code)}</div>
                    )}
                  </td>
                  <td>{j.zone_code}<div className="muted small">{j.service_locality || j.district || 'No locality'}</div><div className="muted small">{j.required_skills.map(humanize).join(', ')}</div></td>
                  <td className="nowrap">{fmtDateTime(j.window_start)}<div className="muted small">to {fmtTime(j.window_end)} · {j.duration_minutes} min</div></td>
                  <td className="nowrap">{fmtDateTime(j.sla_deadline)}<div><SlaBadge value={j.sla_state} /></div></td>
                  <td className="nowrap">
                    {j.assignment ? <>{j.assignment.electrician_name}<div className="muted small">{fmtDateTime(j.assignment.start)}</div></> : <span className="muted">—</span>}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {['pending', 'assigned', 'unassigned'].includes(j.status) && (
                      <button className="btn small" onClick={() => setModal({ mode: 'edit', job: j })}>Edit</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {modal && (
        <Modal title={modal.mode === 'create' ? 'New service job' : `Edit ${modal.job.job_number}`} onClose={() => setModal(null)} wide>
          <JobForm job={modal.job} skills={data.skills} zones={data.zones} onSubmit={save}
                   submitLabel={modal.mode === 'create' ? 'Create job' : 'Save changes'} />
        </Modal>
      )}
      {selected && <JobDetail jobId={selected} onClose={() => setSelected(null)} onChanged={bump} />}
    </div>
  )
}
