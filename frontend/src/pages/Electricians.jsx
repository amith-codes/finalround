import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import ElectricianForm from '../components/ElectricianForm'
import { Card, ErrorBox, Loading, Modal, useLoad } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { Api, errorMessage } from '../services/api'
import { DAYS, fmtDateTime, fromLocalInput, humanize, toLocalInput } from '../services/format'

function shiftSummary(shifts) {
  if (!shifts.length) return 'No shifts'
  const groups = {}
  shifts.forEach((s) => { (groups[`${s.start_time}–${s.end_time}`] ||= []).push(DAYS[s.day_of_week]) })
  return Object.entries(groups).map(([t, d]) => `${d.join(' ')} ${t}`).join('; ')
}

function Unavailability({ electrician, onChanged }) {
  const toast = useToast()
  const start = new Date(); start.setDate(start.getDate() + 1); start.setHours(8, 0, 0, 0)
  const end = new Date(start); end.setHours(17)
  const [f, setF] = useState({ start: toLocalInput(start), end: toLocalInput(end), reason: '' })

  const add = async (e) => {
    e.preventDefault()
    try {
      await Api.addUnavailability(electrician.id, { start: fromLocalInput(f.start), end: fromLocalInput(f.end), reason: f.reason || null })
      toast('Unavailability recorded — run scheduling (or use Disruptions to recover immediately)', 'success')
      onChanged()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }
  const remove = async (pid) => {
    try {
      await Api.deleteUnavailability(electrician.id, pid)
      onChanged()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="stack">
      {electrician.unavailable_periods.length ? (
        <ul className="plain">
          {electrician.unavailable_periods.map((p) => (
            <li key={p.id} className="row gap">
              <span>{fmtDateTime(p.start)} → {fmtDateTime(p.end)}</span>
              <span className="muted">{p.reason}</span>
              <button className="btn small ghost" onClick={() => remove(p.id)}>Remove</button>
            </li>
          ))}
        </ul>
      ) : <div className="muted">No upcoming unavailability.</div>}
      <form className="form" onSubmit={add}>
        <label>From<input type="datetime-local" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
        <label>To<input type="datetime-local" required value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>
        <label className="span2">Reason<input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="e.g. Training, leave" /></label>
        <div className="span2 row end"><button className="btn primary">Add period</button></div>
      </form>
    </div>
  )
}

export default function Electricians() {
  const { version, bump } = useOutletContext()
  const toast = useToast()
  const [showInactive, setShowInactive] = useState(false)
  const [modal, setModal] = useState(null) // {mode: 'create'|'edit'|'unavail', e?}
  const { data, error, loading, reload } = useLoad(async () => {
    const [electricians, skills, zones] = await Promise.all([Api.electricians(showInactive), Api.skills(), Api.zones()])
    return { electricians, skills, zones }
  }, [version, showInactive])

  const save = async (body) => {
    try {
      if (modal.mode === 'create') await Api.createElectrician(body)
      else await Api.updateElectrician(modal.e.id, body)
      toast('Electrician saved', 'success')
      setModal(null)
      bump()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const deactivate = async (e) => {
    if (!window.confirm(`Deactivate ${e.name}? Their planned jobs will be reassigned on the next run.`)) return
    try {
      const res = await Api.deleteElectrician(e.id)
      toast(`${e.name} deactivated; ${res.affected_job_ids.length} planned job(s) need reassignment`, 'success')
      bump()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }
  const reactivate = async (e) => {
    try {
      await Api.updateElectrician(e.id, { active: true })
      bump()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  if (loading && !data) return <Loading what="Loading electricians" />
  const current = modal?.e && data.electricians.find((x) => x.id === modal.e.id)

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Electricians</h1>
        <div className="row gap">
          <label className="check"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show inactive</label>
          <button className="btn primary" onClick={() => setModal({ mode: 'create' })}>Register electrician</button>
        </div>
      </div>
      <ErrorBox error={error} />
      <Card>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Electrician</th><th>Now</th><th>Skills</th><th>Zones</th><th>Shifts</th><th>Unavailable</th><th /></tr></thead>
            <tbody>
              {data.electricians.map((e) => (
                <tr key={e.id} className={e.active ? '' : 'inactive'}>
                  <td><b>{e.name}</b><div className="muted small">{e.employee_code} · OT {e.max_overtime_minutes} min</div></td>
                  <td><span className={`badge avail-${e.current_status}`}>{humanize(e.current_status)}</span></td>
                  <td className="tags">{e.skills.map((s) => <span key={s} className="tag">{humanize(s)}</span>)}</td>
                  <td>{e.zones.join(', ')}<div className="muted small">Localities: {e.localities.join(', ') || 'Not set'}</div><div className="muted small">Base {Number(e.home_lat).toFixed(4)}, {Number(e.home_lon).toFixed(4)}</div></td>
                  <td className="small">{shiftSummary(e.shifts)}</td>
                  <td className="small">
                    {e.unavailable_periods.map((p) => <div key={p.id}>{fmtDateTime(p.start)} → {fmtDateTime(p.end)}</div>)}
                  </td>
                  <td className="nowrap">
                    <button className="btn small" onClick={() => setModal({ mode: 'edit', e })}>Edit</button>{' '}
                    <button className="btn small" onClick={() => setModal({ mode: 'unavail', e })}>Availability</button>{' '}
                    {e.active
                      ? <button className="btn small danger" onClick={() => deactivate(e)}>Deactivate</button>
                      : <button className="btn small" onClick={() => reactivate(e)}>Reactivate</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {modal && modal.mode !== 'unavail' && (
        <Modal title={modal.mode === 'create' ? 'Register electrician' : `Edit ${modal.e.name}`} onClose={() => setModal(null)} wide>
          <ElectricianForm electrician={modal.e} skills={data.skills} zones={data.zones} onSubmit={save} />
        </Modal>
      )}
      {modal?.mode === 'unavail' && current && (
        <Modal title={`Availability — ${current.name}`} onClose={() => setModal(null)}>
          <Unavailability electrician={current} onChanged={reload} />
        </Modal>
      )}
    </div>
  )
}
