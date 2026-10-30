import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import JobDetail from '../components/JobDetail'
import Timeline from '../components/Timeline'
import { Card, ErrorBox, Loading, useLoad } from '../components/ui'
import { Api } from '../services/api'
import { fmtDay, isoDay, toLocalInput } from '../services/format'

function shiftDay(day, n) {
  const d = new Date(`${day}T00:00:00`)
  d.setDate(d.getDate() + n)
  return isoDay(d)
}

export default function Schedule() {
  const { version, bump } = useOutletContext()
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1)
  const [day, setDay] = useState(isoDay(tomorrow))
  const [filter, setFilter] = useState('working')
  const [selected, setSelected] = useState(null)
  const { data, error, loading } = useLoad(() => Api.schedule(day), [day, version])

  const lanes = (data?.lanes || []).filter((l) =>
    filter === 'all' ? true : filter === 'busy' ? l.jobs.length > 0 : l.shifts.length > 0 || l.jobs.length > 0)
  const total = (data?.lanes || []).reduce((n, l) => n + l.jobs.length, 0)

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Schedule</h1>
        <div className="row gap wrap">
          <button className="btn" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day">‹</button>
          <input type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
          <button className="btn" onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day">›</button>
          <button className="btn ghost" onClick={() => setDay(isoDay(new Date()))}>Today</button>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Electricians to show">
            <option value="working">Working electricians</option>
            <option value="busy">With jobs only</option>
            <option value="all">All electricians</option>
          </select>
        </div>
      </div>
      <Card title={`${fmtDay(day)} — ${total} scheduled job${total === 1 ? '' : 's'}`}
            actions={<div className="legend small">
              <span className="sw prio-urgent" />urgent <span className="sw prio-high" />high <span className="sw prio-medium" />medium
              <span className="sw prio-low" />low <span className="sw travel" />travel <span className="sw unavail" />unavailable
              <span className="sw overtime" />overtime
            </div>}>
        {error && <ErrorBox error={error} />}
        {loading && !data ? <Loading /> : lanes.length ? (
          <Timeline day={day} lanes={lanes} onSelectJob={setSelected} now={toLocalInput(new Date())} />
        ) : <div className="empty">No electricians working on this day.</div>}
      </Card>
      {selected && <JobDetail jobId={selected} onClose={() => setSelected(null)} onChanged={bump} />}
    </div>
  )
}
