import { useState } from 'react'
import { DAYS } from '../services/format'

function initialShifts(shifts) {
  return DAYS.map((_, d) => {
    const s = shifts?.find((x) => x.day_of_week === d)
    return { on: !!s, start: s?.start_time || '08:00', end: s?.end_time || '16:00' }
  })
}

export default function ElectricianForm({ electrician, skills, zones, onSubmit }) {
  const e = electrician
  const [f, setF] = useState({
    name: e?.name || '', phone: e?.phone || '', email: e?.email || '',
    home_lat: e?.home_lat ?? 12.9716, home_lon: e?.home_lon ?? 77.5946,
    max_overtime_minutes: e?.max_overtime_minutes ?? 0,
    // Keep existing dispatch qualifications when editing. New profiles inherit
    // the available values because these assignments are no longer configured here.
    skills: e?.skills || skills.map((skill) => skill.code),
    zones: e?.zones || zones.map((zone) => zone.code),
  })
  const [localitiesText, setLocalitiesText] = useState((e?.localities || []).join(', '))
  const [account, setAccount] = useState({ username: '', initial_password: '' })
  const [shifts, setShifts] = useState(initialShifts(e?.shifts))
  const [busy, setBusy] = useState(false)
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value })
  const setShift = (d, patch) => setShifts(shifts.map((s, i) => (i === d ? { ...s, ...patch } : s)))

  const submit = async (ev) => {
    ev.preventDefault()
    setBusy(true)
    try {
      await onSubmit({
        name: f.name, phone: f.phone || null, email: f.email || null,
        home_lat: Number(f.home_lat), home_lon: Number(f.home_lon),
        max_overtime_minutes: Number(f.max_overtime_minutes),
        localities: localitiesText.split(',').map((value) => value.trim()).filter(Boolean),
        skills: f.skills, zones: f.zones,
        ...(!e ? account : {}),
        shifts: shifts.map((s, d) => ({ ...s, d })).filter((s) => s.on)
          .map((s) => ({ day_of_week: s.d, start_time: s.start, end_time: s.end })),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form" onSubmit={submit}>
      <label className="span2">Name<input required minLength={2} value={f.name} onChange={set('name')} /></label>
      <label>Phone<input value={f.phone} onChange={set('phone')} /></label>
      <label>Email<input type="email" value={f.email} onChange={set('email')} /></label>
      {!e && <>
        <label>Electrician sign-in name<input required minLength={3} autoComplete="off" value={account.username} onChange={(event) => setAccount({ ...account, username: event.target.value })} /></label>
        <label>Initial password<input required minLength={8} type="password" autoComplete="new-password" value={account.initial_password} onChange={(event) => setAccount({ ...account, initial_password: event.target.value })} /></label>
      </>}
      <label>Home base latitude<input required type="number" step="any" value={f.home_lat} onChange={set('home_lat')} /></label>
      <label>Home base longitude<input required type="number" step="any" value={f.home_lon} onChange={set('home_lon')} /></label>
      <label>Max overtime (min/day)<input type="number" min={0} max={240} step={15} value={f.max_overtime_minutes} onChange={set('max_overtime_minutes')} /></label>
      <span />
      <label className="span2">Service localities<input placeholder="Hebbal, Mysuru, JP Nagar" value={localitiesText} onChange={(event) => setLocalitiesText(event.target.value)} /><small className="field-hint">Use the same locality names customers enter when booking. Automatic dispatch requires an exact locality match.</small></label>
      <fieldset className="span2">
        <legend>Weekly shifts</legend>
        <div className="shift-grid">
          {shifts.map((s, d) => (
            <div key={d} className={`shift-day ${s.on ? '' : 'off'}`}>
              <label className="check"><input type="checkbox" checked={s.on} onChange={(ev) => setShift(d, { on: ev.target.checked })} />{DAYS[d]}</label>
              <input type="time" value={s.start} disabled={!s.on} onChange={(ev) => setShift(d, { start: ev.target.value })} aria-label={`${DAYS[d]} start`} />
              <input type="time" value={s.end} disabled={!s.on} onChange={(ev) => setShift(d, { end: ev.target.value })} aria-label={`${DAYS[d]} end`} />
            </div>
          ))}
        </div>
      </fieldset>
      <div className="span2 row end">
        <button className="btn primary" disabled={busy}>{busy ? 'Saving…' : 'Save electrician'}</button>
      </div>
    </form>
  )
}
