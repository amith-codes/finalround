import { fmtTime, humanize } from '../services/format'

const START_HOUR = 7
const END_HOUR = 21
const SPAN = (END_HOUR - START_HOUR) * 60

function pct(iso, day) {
  const d = new Date(iso)
  const base = new Date(`${day}T00:00:00`)
  const mins = (d - base) / 60000 - START_HOUR * 60
  return Math.max(0, Math.min(100, (mins / SPAN) * 100))
}

function Block({ start, end, day, className, title, children, onClick }) {
  const left = pct(start, day)
  const width = Math.max(0.6, pct(end, day) - left)
  return (
    <div className={className} style={{ left: `${left}%`, width: `${width}%` }} title={title} onClick={onClick}
         role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}
         onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}>
      {children}
    </div>
  )
}

/** Gantt-style view: one lane per electrician with shifts, unavailability, travel and jobs. */
export default function Timeline({ day, lanes, onSelectJob, now }) {
  const hours = Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, i) => START_HOUR + i)
  const nowPct = now && now.slice(0, 10) === day ? pct(now, day) : null
  return (
    <div className="timeline">
      <div className="tl-row tl-header">
        <div className="tl-name">Electrician</div>
        <div className="tl-track">
          {hours.map((h) => (
            <span key={h} className="tl-hour" style={{ left: `${((h - START_HOUR) * 60 / SPAN) * 100}%` }}>{h}:00</span>
          ))}
        </div>
      </div>
      {lanes.map((lane) => (
        <div key={lane.electrician_id} className="tl-row">
          <div className="tl-name">
            <div className="strong">{lane.name}</div>
            <div className="muted small">{lane.zones.join(' · ')} · {lane.jobs.length} job{lane.jobs.length === 1 ? '' : 's'}</div>
          </div>
          <div className="tl-track">
            {hours.map((h) => (
              <span key={h} className="tl-grid" style={{ left: `${((h - START_HOUR) * 60 / SPAN) * 100}%` }} />
            ))}
            {!lane.shifts.length && <div className="tl-off">Off shift</div>}
            {lane.shifts.map((s, i) => (
              <span key={i}>
                <Block day={day} start={s.start} end={s.end} className="tl-shift" title={`Shift ${fmtTime(s.start)}–${fmtTime(s.end)}`} />
                {s.overtime_until !== s.end && (
                  <Block day={day} start={s.end} end={s.overtime_until} className="tl-overtime" title="Overtime allowance" />
                )}
              </span>
            ))}
            {lane.unavailable.map((u, i) => (
              <Block key={`u${i}`} day={day} start={u.start} end={u.end} className="tl-unavail"
                     title={`Unavailable ${fmtTime(u.start)}–${fmtTime(u.end)}: ${u.reason || ''}`}>
                <span>{u.reason || 'Unavailable'}</span>
              </Block>
            ))}
            {lane.jobs.map((j) => {
              const travelStart = new Date(new Date(j.start).getTime() - j.travel_minutes * 60000).toISOString()
              return (
                <span key={j.job_id}>
                  {j.travel_minutes > 0 && j.status === 'assigned' && (
                    <Block day={day} start={localIso(travelStart)} end={j.start} className="tl-travel"
                           title={`${j.travel_minutes} min travel from ${j.travel_from}`} />
                  )}
                  <Block day={day} start={j.start} end={j.end}
                         className={`tl-job prio-${j.priority} st-${j.status} ${j.late_minutes ? 'late' : ''}`}
                         title={`${j.job_number} ${j.title}\n${fmtTime(j.start)}–${fmtTime(j.end)} · ${humanize(j.priority)} · ${humanize(j.status)}`}
                         onClick={() => onSelectJob?.(j.job_id)}>
                    <span>{j.job_number.replace('JOB-', '#')}</span>
                  </Block>
                </span>
              )
            })}
            {nowPct != null && <span className="tl-now" style={{ left: `${nowPct}%` }} />}
          </div>
        </div>
      ))}
    </div>
  )
}

// toISOString() is UTC; convert back to naive local so pct() reads it consistently.
function localIso(utcIso) {
  const d = new Date(utcIso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`
}
