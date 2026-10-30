"""Read-only aggregates for the dispatcher dashboard. `as_of` lets demos use a simulated clock."""
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Assignment, Job, SchedulingRun
from app.models.enums import JobStatus, Priority, RunStatus
from app.routers.scheduling import run_response
from app.services import job_service
from app.services.electrician_service import in_progress_by_electrician
from app.services.problem_builder import load_electricians, shift_instances
from app.services.scheduling_service import latest_completed_run, normalize_now
from app.services.serializers import electrician_status, job_dict, run_summary, sla_state

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _clock(as_of: datetime | None) -> datetime:
    return normalize_now(as_of)


@router.get("/overview")
def overview(as_of: datetime | None = None, db: Session = Depends(get_db)):
    now = _clock(as_of)
    jobs = job_service.list_jobs(db)
    by_status = Counter(j.status for j in jobs)
    by_priority = Counter(j.priority for j in jobs)
    matrix = {s.value: {p.value: 0 for p in Priority} for s in JobStatus}
    for j in jobs:
        matrix[j.status][j.priority] += 1
    sla = Counter(sla_state(j, now) for j in jobs)
    busy = in_progress_by_electrician(db)
    techs = load_electricians(db)
    availability = Counter(electrician_status(e, now, busy.get(e.id)) for e in techs)
    latest = latest_completed_run(db)
    failed = db.scalar(select(SchedulingRun).where(SchedulingRun.status.in_(
        [RunStatus.FAILED.value, RunStatus.INTERRUPTED.value])).order_by(SchedulingRun.started_at.desc()).limit(1))
    return {
        "as_of": now,
        "total_jobs": len(jobs),
        "jobs_by_status": {s.value: by_status.get(s.value, 0) for s in JobStatus},
        "jobs_by_priority": {p.value: by_priority.get(p.value, 0) for p in Priority},
        "status_priority_matrix": matrix,
        "sla": {k: v for k, v in sla.items() if k},
        "electricians": {"total": len(techs), **availability},
        "latest_run": run_summary(latest) if latest else None,
        "latest_failed_run": run_summary(failed) if failed else None,
    }


@router.get("/workload", summary="Per-electrician load for a date range (default: from today, 3 days)")
def workload(start: date | None = None, days: int = Query(default=3, ge=1, le=31),
             as_of: datetime | None = None, db: Session = Depends(get_db)):
    now = _clock(as_of)
    first = start or now.date()
    last = first + timedelta(days=days - 1)
    lo, hi = datetime.combine(first, datetime.min.time()), datetime.combine(last + timedelta(days=1), datetime.min.time())
    busy = in_progress_by_electrician(db)
    rows = db.scalars(
        select(Assignment).join(Job).where(
            Assignment.is_active.is_(True), Assignment.start >= lo, Assignment.start < hi,
            Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value, JobStatus.COMPLETED.value]))
        .options(selectinload(Assignment.job))
    )
    per: dict[int, list[Assignment]] = {}
    for a in rows:
        per.setdefault(a.electrician_id, []).append(a)
    out = []
    for e in load_electricians(db):
        shift_min = sum(int((s.end - s.start).total_seconds() // 60) for s in shift_instances(e, first, last))
        items = per.get(e.id, [])
        work = sum(int((a.end - a.start).total_seconds() // 60) for a in items)
        travel = sum(a.travel_minutes for a in items)
        out.append({
            "electrician_id": e.id, "name": e.name, "employee_code": e.employee_code,
            "status": electrician_status(e, now, busy.get(e.id)),
            "skills": [s.code for s in e.skills], "zones": [z.code for z in e.zones],
            "jobs": len(items),
            "urgent_or_high": sum(1 for a in items if a.job.priority in ("urgent", "high")),
            "work_minutes": work, "travel_minutes": travel, "shift_minutes": shift_min,
            "utilisation_pct": round(100 * (work + travel) / shift_min, 1) if shift_min else None,
            "late_jobs": sum(1 for a in items if a.late_minutes > 0),
        })
    return {"from": first, "to": last, "electricians": out}


@router.get("/sla", summary="Jobs that are overdue, late, at risk, or unassigned")
def sla(as_of: datetime | None = None, db: Session = Depends(get_db)):
    now = _clock(as_of)
    buckets: dict[str, list] = {"overdue": [], "late": [], "at_risk": [], "unassigned": []}
    for j in job_service.list_jobs(db, status="pending,assigned,in_progress,unassigned"):
        state = sla_state(j, now)
        d = job_dict(j, now)
        d["minutes_to_sla"] = int((j.sla_deadline - now).total_seconds() // 60)
        if state in ("overdue", "late", "at_risk"):
            buckets[state].append(d)
        if j.status == JobStatus.UNASSIGNED.value:
            buckets["unassigned"].append(d)
    for items in buckets.values():
        items.sort(key=lambda d: d["minutes_to_sla"])
    return {"as_of": now, "counts": {k: len(v) for k, v in buckets.items()}, **buckets}


@router.get("/schedule", summary="Timeline per electrician for one day (shifts, unavailability, jobs)")
def schedule(day: date | None = None, as_of: datetime | None = None, db: Session = Depends(get_db)):
    now = _clock(as_of)
    day = day or now.date()
    lo = datetime.combine(day, datetime.min.time())
    hi = lo + timedelta(days=1)
    rows = db.scalars(
        select(Assignment).join(Job).where(
            Assignment.is_active.is_(True), Assignment.start < hi, Assignment.end > lo,
            Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value, JobStatus.COMPLETED.value]))
        .options(selectinload(Assignment.job).selectinload(Job.zone))
        .order_by(Assignment.start)
    )
    per: dict[int, list] = {}
    for a in rows:
        j = a.job
        per.setdefault(a.electrician_id, []).append({
            "job_id": j.id, "job_number": j.job_number, "title": j.title, "priority": j.priority,
            "status": j.status, "zone_code": j.zone.code, "start": a.start, "end": a.end,
            "travel_minutes": a.travel_minutes, "travel_from": a.travel_from, "late_minutes": a.late_minutes,
            "sla_deadline": j.sla_deadline, "window_start": j.window_start, "window_end": j.window_end,
            "explanation": a.explanation, "sla_state": sla_state(j, now),
        })
    busy = in_progress_by_electrician(db)
    lanes = []
    for e in load_electricians(db):
        lanes.append({
            "electrician_id": e.id, "name": e.name, "zones": [z.code for z in e.zones],
            "skills": [s.code for s in e.skills],
            "status": electrician_status(e, now, busy.get(e.id)),
            "shifts": [{"start": s.start, "end": s.end, "overtime_until": s.end + timedelta(minutes=e.max_overtime_minutes)}
                       for s in shift_instances(e, day, day)],
            "unavailable": [{"start": p.start, "end": p.end, "reason": p.reason}
                            for p in e.unavailable_periods if p.start < hi and p.end > lo],
            "jobs": per.get(e.id, []),
        })
    return {"day": day, "as_of": now, "lanes": lanes}


@router.get("/comparison", summary="Before/after view of a run (default: latest completed run)")
def comparison(run_id: str | None = None, db: Session = Depends(get_db)):
    run = db.get(SchedulingRun, run_id) if run_id else latest_completed_run(db)
    if run is None:
        return {"run": None, "previous_metrics": None}
    prev = db.get(SchedulingRun, run.previous_run_id) if run.previous_run_id else None
    return {
        "run": run_response(db, run),
        "previous_run_id": prev.id if prev else None,
        "previous_metrics": prev.metrics if prev else None,
        "previous_objective": prev.objective_score if prev else None,
    }
