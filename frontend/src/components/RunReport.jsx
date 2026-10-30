import { useMemo, useState } from 'react'
import { fmtDateTime, fmtTime, humanize } from '../services/format'
import { Empty, PriorityBadge, Reasons } from './ui'

const CHANGE_ORDER = ['reassigned', 'unassigned', 'retimed', 'assigned', 'removed']

function Delta({ before, after, lowerIsBetter = true }) {
  if (before == null || after == null) return <span>{after ?? '—'}</span>
  const d = Math.round((after - before) * 100) / 100
  const good = lowerIsBetter ? d < 0 : d > 0
  return (
    <span>
      {after}
      {d !== 0 && <small className={good ? 'good' : 'bad'}> ({d > 0 ? '+' : ''}{d})</small>}
    </span>
  )
}

export function MetricsCompare({ before, after, beforeObjective, afterObjective }) {
  const rows = [
    ['Objective score', beforeObjective, afterObjective, true],
    ['Assigned jobs', before?.assigned, after?.assigned, false],
    ['Unassigned jobs', before?.unassigned, after?.unassigned, true],
    ['Travel minutes', before?.travel_minutes, after?.travel_minutes, true],
    ['Late jobs (SLA)', before?.late_jobs, after?.late_jobs, true],
    ['Overtime minutes', before?.overtime_minutes, after?.overtime_minutes, true],
  ]
  return (
    <table className="table compact">
      <thead><tr><th>Metric</th><th>Before</th><th>After</th></tr></thead>
      <tbody>
        {rows.map(([label, b, a, lower]) => (
          <tr key={label}><td>{label}</td><td>{b ?? '—'}</td><td><Delta before={b} after={a} lowerIsBetter={lower} /></td></tr>
        ))}
      </tbody>
    </table>
  )
}

export function ChangesTable({ changes }) {
  const [filter, setFilter] = useState('all')
  const sorted = useMemo(() => [...(changes || [])].sort(
    (a, b) => CHANGE_ORDER.indexOf(a.change_type) - CHANGE_ORDER.indexOf(b.change_type)), [changes])
  if (!changes?.length) return <Empty>No assignments changed in this run.</Empty>
  const counts = sorted.reduce((acc, c) => ({ ...acc, [c.change_type]: (acc[c.change_type] || 0) + 1 }), {})
  const shown = filter === 'all' ? sorted : sorted.filter((c) => c.change_type === filter)
  return (
    <>
      <div className="chips">
        <button className={`chip ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>All {sorted.length}</button>
        {CHANGE_ORDER.filter((t) => counts[t]).map((t) => (
          <button key={t} className={`chip change-${t} ${filter === t ? 'on' : ''}`} onClick={() => setFilter(t)}>
            {humanize(t)} {counts[t]}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Job</th><th>Change</th><th>Before</th><th>After</th><th>Why</th></tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id}>
                <td>
                  <div className="strong">{c.job_number}</div>
                  <div className="muted small">{c.job_title}</div>
                  <PriorityBadge value={c.priority} />
                </td>
                <td><span className={`badge change-${c.change_type}`}>{humanize(c.change_type)}</span></td>
                <td className="nowrap">
                  {c.old_electrician_name ? <>{c.old_electrician_name}<div className="muted small">{fmtDateTime(c.old_start)}–{fmtTime(c.old_end)}</div></> : '—'}
                </td>
                <td className="nowrap">
                  {c.new_electrician_name ? <>{c.new_electrician_name}<div className="muted small">{fmtDateTime(c.new_start)}–{fmtTime(c.new_end)}</div></> : '—'}
                </td>
                <td className="reason">{c.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

/** Side-by-side lanes: what each affected electrician had before vs after. */
export function BeforeAfter({ before, after, changes }) {
  const affected = new Set()
  ;(changes || []).forEach((c) => {
    if (c.old_electrician_id) affected.add(c.old_electrician_id)
    if (c.new_electrician_id) affected.add(c.new_electrician_id)
  })
  const changedJobs = new Set((changes || []).map((c) => c.job_id))
  const group = (snap) => (snap || []).reduce((acc, s) => {
    if (affected.has(s.electrician_id)) (acc[s.electrician_id] ||= { name: s.electrician_name, items: [] }).items.push(s)
    return acc
  }, {})
  const b = group(before)
  const a = group(after)
  const ids = [...affected].sort((x, y) => x - y)
  if (!ids.length) return <Empty>No electrician's plan changed.</Empty>
  const lane = (g) => (g?.items || []).map((s) => (
    <div key={s.job_id} className={`snap prio-${s.priority} ${changedJobs.has(s.job_id) ? 'changed' : ''}`}>
      <span className="nowrap">{fmtDateTime(s.start)}–{fmtTime(s.end)}</span> <b>{s.job_number}</b> {s.status === 'in_progress' && '(in progress)'}
    </div>
  ))
  return (
    <div className="table-wrap">
      <table className="table before-after">
        <thead><tr><th>Electrician</th><th>Before</th><th>After</th></tr></thead>
        <tbody>
          {ids.map((id) => (
            <tr key={id}>
              <td className="strong">{(a[id] || b[id])?.name || `#${id}`}</td>
              <td>{lane(b[id]) }{!b[id] && <span className="muted">no jobs</span>}</td>
              <td>{lane(a[id])}{!a[id] && <span className="muted">no jobs</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function UnassignedList({ items }) {
  if (!items?.length) return <Empty>Every job was scheduled.</Empty>
  return (
    <div className="unassigned-list">
      {items.map((u) => (
        <div key={u.job_id} className="unassigned-item">
          <div className="row gap">
            <b>{u.job_number}</b>
            <PriorityBadge value={u.priority} />
            <span className={`badge feas-${u.classification}`}>{humanize(u.classification)}</span>
          </div>
          <div className="muted small">{u.title}</div>
          <Reasons reasons={u.reasons} />
        </div>
      ))}
    </div>
  )
}
