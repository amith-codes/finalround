import { useState } from 'react'
import { fromLocalInput, humanize, PRIORITIES, toLocalInput } from '../services/format'

function defaults() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(9, 0, 0, 0)
  const end = new Date(d); end.setHours(13)
  const sla = new Date(d); sla.setHours(15)
  return {
    title: '', customer_name: '', address: '', description: '', zone_code: '', priority: 'medium',
    duration_minutes: 60, required_skills: [], lat: '', lon: '',
    window_start: toLocalInput(d), window_end: toLocalInput(end), sla_deadline: toLocalInput(sla),
  }
}

function fromJob(j) {
  return {
    ...j,
    window_start: j.window_start.slice(0, 16),
    window_end: j.window_end.slice(0, 16),
    sla_deadline: j.sla_deadline.slice(0, 16),
  }
}

/** Create / edit form. `fixedPriority` is used by the urgent-job disruption form. */
export default function JobForm({ job, skills, zones, onSubmit, submitLabel = 'Save', fixedPriority }) {
  const [f, setF] = useState(job ? fromJob(job) : { ...defaults(), ...(fixedPriority ? { priority: fixedPriority } : {}) })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const pickZone = (code) => {
    const z = zones.find((x) => x.code === code)
    // Default the site location to the zone centre so the form is quick to fill in.
    setF({ ...f, zone_code: code, lat: f.lat || z?.center_lat || '', lon: f.lon || z?.center_lon || '' })
  }
  const toggleSkill = (code) => setF({
    ...f,
    required_skills: f.required_skills.includes(code) ? f.required_skills.filter((s) => s !== code) : [...f.required_skills, code],
  })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await onSubmit({
        title: f.title, customer_name: f.customer_name || null, address: f.address || null,
        description: f.description || null, zone_code: f.zone_code, priority: f.priority,
        duration_minutes: Number(f.duration_minutes), required_skills: f.required_skills,
        lat: Number(f.lat), lon: Number(f.lon),
        window_start: fromLocalInput(f.window_start), window_end: fromLocalInput(f.window_end),
        sla_deadline: fromLocalInput(f.sla_deadline),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="span2">Title<input required minLength={3} value={f.title} onChange={set('title')} placeholder="e.g. Trace tripping RCD" /></label>
      <label>Customer<input value={f.customer_name || ''} onChange={set('customer_name')} /></label>
      <label>Address<input value={f.address || ''} onChange={set('address')} /></label>
      <label>Service zone
        <select required value={f.zone_code} onChange={(e) => pickZone(e.target.value)}>
          <option value="">Select…</option>
          {zones.map((z) => <option key={z.code} value={z.code}>{z.name} ({z.code})</option>)}
        </select>
      </label>
      <label>Priority
        <select value={f.priority} onChange={set('priority')} disabled={!!fixedPriority}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
        </select>
      </label>
      <label>Latitude<input required type="number" step="any" value={f.lat} onChange={set('lat')} /></label>
      <label>Longitude<input required type="number" step="any" value={f.lon} onChange={set('lon')} /></label>
      <label>Duration (minutes)<input required type="number" min={5} max={720} step={5} value={f.duration_minutes} onChange={set('duration_minutes')} /></label>
      <span />
      <label>Window start<input required type="datetime-local" value={f.window_start} onChange={set('window_start')} /></label>
      <label>Window end<input required type="datetime-local" value={f.window_end} onChange={set('window_end')} /></label>
      <label>SLA deadline<input required type="datetime-local" value={f.sla_deadline} onChange={set('sla_deadline')} /></label>
      <span />
      <fieldset className="span2">
        <legend>Required electrician skills</legend>
        <div className="checks">
          {skills.map((s) => (
            <label key={s.code} className="check">
              <input type="checkbox" checked={f.required_skills.includes(s.code)} onChange={() => toggleSkill(s.code)} />
              {s.name}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="span2">Notes<textarea rows={2} value={f.description || ''} onChange={set('description')} /></label>
      <div className="span2 row end">
        <button className="btn primary" disabled={busy || !f.required_skills.length}>{busy ? 'Saving…' : submitLabel}</button>
      </div>
    </form>
  )
}
