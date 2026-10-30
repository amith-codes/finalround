"""Executes scheduling runs: locking, loading, solving, persisting and auditing.

Concurrency: every run (and every disruption that triggers one) executes while holding a
process-wide lock, so runs are serialised and each one sees the previous run's result. A
second guard refuses to start while another process has a run row in "running" state that
is younger than STALE_RUN_MINUTES (covers multiple uvicorn workers sharing one SQLite file).

Failure handling: the run row is committed as "running" *before* solving. Solving and
persisting happen in one transaction; on any exception that transaction is rolled back (the
previous schedule stays intact) and the run row is marked "failed" with the error. Runs left
"running" by a crashed process are marked "interrupted" at startup (`mark_interrupted_runs`).
"""
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app import config
from app.models import Assignment, BookingEvent, Job, ScheduleChange, SchedulingRun
from app.models.enums import ChangeType, JobStatus, RunMode, RunStatus
from app.scheduling import solve
from app.services.errors import ApiError
from app.services.problem_builder import build_problem

log = logging.getLogger("dispatchgrid.scheduler")

_lock = threading.Lock()


@contextmanager
def scheduler_lock():
    if not _lock.acquire(timeout=config.SCHEDULER_LOCK_TIMEOUT_SECONDS):
        raise ApiError(409, "SCHEDULER_BUSY", "Another scheduling run is in progress; retry shortly.")
    try:
        yield
    finally:
        _lock.release()


def normalize_now(as_of: datetime | None) -> datetime:
    now = as_of or datetime.now()
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    return now.replace(second=0, microsecond=0)


def mark_interrupted_runs(db: Session) -> int:
    res = db.execute(
        update(SchedulingRun)
        .where(SchedulingRun.status == RunStatus.RUNNING.value)
        .values(status=RunStatus.INTERRUPTED.value, finished_at=datetime.now(),
                error="Process stopped before the run finished; schedule was not modified.")
    )
    db.commit()
    return res.rowcount or 0


def latest_completed_run(db: Session) -> SchedulingRun | None:
    return db.scalar(
        select(SchedulingRun)
        .where(SchedulingRun.status == RunStatus.COMPLETED.value)
        .order_by(SchedulingRun.started_at.desc(), SchedulingRun.finished_at.desc())
        .limit(1)
    )


def current_snapshot(db: Session) -> list[dict]:
    """Active assignments of jobs that are planned or in progress."""
    rows = db.scalars(
        select(Assignment)
        .join(Job)
        .where(Assignment.is_active.is_(True),
               Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]))
        .options(selectinload(Assignment.job), selectinload(Assignment.electrician))
        .order_by(Assignment.electrician_id, Assignment.start)
    )
    return [_snap(a.job, a.electrician_id, a.electrician.name, a.start, a.end) for a in rows]


def _snap(job: Job, eid: int, ename: str, start: datetime, end: datetime, status: str | None = None) -> dict:
    return {
        "job_id": job.id, "job_number": job.job_number, "title": job.title, "priority": job.priority,
        "status": status or job.status, "electrician_id": eid, "electrician_name": ename,
        "start": start.isoformat(), "end": end.isoformat(),
    }


def execute_run(
    db: Session,
    *,
    trigger: str,
    mode: RunMode = RunMode.INCREMENTAL,
    as_of: datetime | None = None,
    disruption: dict | None = None,
    extra_changes: list[dict] | None = None,
    before_snapshot: list[dict] | None = None,
) -> SchedulingRun:
    """Run the scheduler. Caller must hold `scheduler_lock()`."""
    now = normalize_now(as_of)
    stale_cutoff = datetime.now() - timedelta(minutes=config.STALE_RUN_MINUTES)
    other = db.scalar(select(SchedulingRun).where(
        SchedulingRun.status == RunStatus.RUNNING.value, SchedulingRun.started_at > stale_cutoff))
    if other is not None:
        raise ApiError(409, "SCHEDULER_BUSY", "Another scheduling run is in progress; retry shortly.",
                       {"run_id": other.id})

    prev = latest_completed_run(db)
    if before_snapshot is None:
        before_snapshot = current_snapshot(db)
    run = SchedulingRun(
        id=str(uuid.uuid4()), trigger=trigger, mode=mode.value, status=RunStatus.RUNNING.value,
        started_at=datetime.now(), as_of=now, previous_run_id=prev.id if prev else None,
        disruption=disruption,
    )
    db.add(run)
    db.commit()
    run_id = run.id

    try:
        problem, ctx = build_problem(db, now)
        result = solve(problem, reoptimize=mode == RunMode.REOPTIMIZE)
        _persist(db, run, problem, ctx, result, extra_changes or [], before_snapshot)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("Scheduling run %s failed", run_id)
        failed = db.get(SchedulingRun, run_id)
        failed.status = RunStatus.FAILED.value
        failed.finished_at = datetime.now()
        failed.error = f"{type(exc).__name__}: {exc}"
        db.commit()
        raise ApiError(500, "SCHEDULING_FAILED",
                       "Scheduling run failed; the previous schedule was left unchanged.",
                       {"run_id": run_id, "error": failed.error})
    db.refresh(run)
    return run


def _persist(db, run, problem, ctx, result, extra_changes, before_snapshot) -> None:
    names = {e.id: e.name for e in ctx.electricians.values()}
    visits = {v.job_id: v for v in result.visits}

    for job in ctx.jobs.values():
        a = job.active_assignment
        if a is not None:
            a.is_active = False
    db.flush()

    after = []
    for v in sorted(result.visits, key=lambda x: (x.tech_id, x.start)):
        job = ctx.jobs[v.job_id]
        db.add(Assignment(
            job_id=v.job_id, electrician_id=v.tech_id, run_id=run.id, start=v.start, end=v.end,
            travel_minutes=v.travel_minutes, travel_from=v.travel_from, late_minutes=v.late_minutes,
            explanation=result.explanations.get(v.job_id), is_active=True,
        ))
        job.status = JobStatus.ASSIGNED.value
        job.feasibility = "feasible"
        job.unassigned_reasons = None
        after.append(_snap(job, v.tech_id, names.get(v.tech_id, "?"), v.start, v.end, JobStatus.ASSIGNED.value))
    for a in ctx.locked_assignments:
        after.append(_snap(a.job, a.electrician_id, names.get(a.electrician_id, "?"), a.start, a.end))
    after.sort(key=lambda s: (s["electrician_id"], s["start"]))

    unassigned_out = []
    for u in result.unassigned:
        job = ctx.jobs[u.job_id]
        job.status = JobStatus.UNASSIGNED.value
        job.feasibility = u.classification
        job.unassigned_reasons = u.reasons
        unassigned_out.append({
            "job_id": job.id, "job_number": job.job_number, "title": job.title, "priority": job.priority,
            "classification": u.classification, "reasons": u.reasons,
        })

    counts = {t.value: 0 for t in ChangeType}
    unchanged = 0
    for jid, job in ctx.jobs.items():
        prior = problem.prior.get(jid)
        v = visits.get(jid)
        note = result.notes.get(jid)
        if prior and v:
            if prior.tech_id != v.tech_id:
                ctype = ChangeType.REASSIGNED
            elif prior.start != v.start:
                ctype = ChangeType.RETIMED
            else:
                unchanged += 1
                continue
        elif prior:
            ctype = ChangeType.UNASSIGNED
        elif v:
            ctype = ChangeType.ASSIGNED
        else:
            continue
        reason = note
        if ctype == ChangeType.RETIMED and (not note or note.startswith("Kept")):
            delta = int((v.start - prior.start).total_seconds() // 60)
            reason = (f"Same electrician; start moved {'later' if delta > 0 else 'earlier'} by {abs(delta)} min "
                      "because preceding work on the route changed.")
        elif ctype == ChangeType.ASSIGNED and not note:
            reason = result.explanations.get(jid)
        elif ctype == ChangeType.UNASSIGNED:
            u = next(x for x in result.unassigned if x.job_id == jid)
            first = next((r["message"] for r in u.reasons if r["code"] != "HISTORY"), "")
            reason = " ".join(filter(None, [note, first]))
        counts[ctype.value] += 1
        db.add(ScheduleChange(
            run_id=run.id, job_id=jid, change_type=ctype.value,
            old_electrician_id=prior.tech_id if prior else None, new_electrician_id=v.tech_id if v else None,
            old_start=prior.start if prior else None, new_start=v.start if v else None,
            old_end=prior.end if prior else None, new_end=v.end if v else None, reason=reason,
        ))
        db.add(BookingEvent(
            job_id=jid, actor_role="system", action=ctype.value,
            from_status=JobStatus.ASSIGNED.value if prior else None,
            to_status=JobStatus.ASSIGNED.value if v else JobStatus.UNASSIGNED.value,
            old_electrician_id=prior.tech_id if prior else None,
            new_electrician_id=v.tech_id if v else None, reason=reason,
        ))
    for c in extra_changes:
        counts[c["change_type"]] = counts.get(c["change_type"], 0) + 1
        db.add(ScheduleChange(run_id=run.id, **c))

    bd = result.breakdown
    run.jobs_considered = sorted(ctx.jobs)
    run.jobs_assigned = sorted(visits)
    run.unassigned = unassigned_out
    run.before_snapshot = before_snapshot
    run.after_snapshot = after
    run.objective_score = result.objective
    run.objective_breakdown = bd
    run.algorithm_stats = result.stats
    run.metrics = {
        "jobs_considered": len(ctx.jobs),
        "assigned": len(visits),
        "unassigned": len(result.unassigned),
        "unassignable": sum(1 for u in result.unassigned if u.classification == "unassignable"),
        "currently_infeasible": sum(1 for u in result.unassigned if u.classification == "currently_infeasible"),
        "in_progress_protected": len(ctx.locked_assignments),
        "unchanged": unchanged,
        "changes": counts,
        "travel_minutes": bd["travel_minutes"],
        "late_jobs": bd["late_jobs"],
        "late_minutes": bd["late_minutes"],
        "overtime_minutes": bd["overtime_minutes"],
    }
    run.status = RunStatus.COMPLETED.value
    run.finished_at = datetime.now()
