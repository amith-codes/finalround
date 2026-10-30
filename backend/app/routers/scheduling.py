from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Assignment, Electrician, Job, ScheduleChange, SchedulingRun
from app.models.enums import JobStatus, RunMode
from app.schemas import RunRequest
from app.services import job_service
from app.services.errors import not_found
from app.services.idempotency import idempotent
from app.services.scheduling_service import execute_run, latest_completed_run, scheduler_lock
from app.services.serializers import assignment_dict, change_dict, job_dict, run_detail, run_summary

router = APIRouter(prefix="/api/scheduling", tags=["scheduling"])


def electrician_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Electrician.id, Electrician.name)).all())


def run_response(db: Session, run: SchedulingRun) -> dict:
    run = db.scalar(select(SchedulingRun).where(SchedulingRun.id == run.id).options(selectinload(SchedulingRun.changes)))
    job_ids = {c.job_id for c in run.changes}
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(job_ids)))} if job_ids else {}
    return run_detail(run, electrician_names(db), jobs)


def _run(db: Session, key: str | None, body: RunRequest | None, mode: RunMode, endpoint: str, trigger: str):
    body = body or RunRequest()

    def handler():
        with scheduler_lock():
            run = execute_run(db, trigger=trigger, mode=mode, as_of=body.as_of)
        return run_response(db, run)

    return idempotent(db, key, endpoint, body.model_dump(mode="json"), handler)


@router.post("/run", summary="Schedule all open jobs, keeping still-feasible assignments (supports Idempotency-Key)")
def run_scheduling(body: RunRequest | None = None, db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return _run(db, idempotency_key, body, RunMode.INCREMENTAL, "POST /api/scheduling/run", "manual_run")


@router.post("/reoptimize", summary="Re-optimise: compare incremental vs from-scratch plans and keep the better one")
def reoptimize(body: RunRequest | None = None, db: Session = Depends(get_db),
               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return _run(db, idempotency_key, body, RunMode.REOPTIMIZE, "POST /api/scheduling/reoptimize", "reoptimize")


@router.get("/current", summary="The active schedule: assignments, in-progress work and unassigned jobs")
def current_schedule(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Assignment).join(Job)
        .where(Assignment.is_active.is_(True),
               Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]))
        .options(selectinload(Assignment.electrician), selectinload(Assignment.job).selectinload(Job.zone))
        .order_by(Assignment.electrician_id, Assignment.start)
    )
    assignments = []
    for a in rows:
        d = assignment_dict(a)
        d.update({"job_id": a.job_id, "job_number": a.job.job_number, "title": a.job.title,
                  "priority": a.job.priority, "status": a.job.status, "zone_code": a.job.zone.code})
        assignments.append(d)
    unassigned = [job_dict(j) for j in job_service.list_jobs(db, status=JobStatus.UNASSIGNED.value)]
    latest = latest_completed_run(db)
    return {"run": run_summary(latest) if latest else None, "assignments": assignments, "unassigned": unassigned}


@router.get("/history", summary="Scheduling runs, newest first")
def history(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    runs = db.scalars(select(SchedulingRun).order_by(SchedulingRun.started_at.desc()).limit(limit))
    return [run_summary(r) for r in runs]


@router.get("/runs/{run_id}", summary="Full audit record of one run, including changes vs the previous schedule")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(SchedulingRun, run_id)
    if run is None:
        raise not_found("Scheduling run", run_id)
    return run_response(db, run)


@router.get("/jobs/{job_id}", summary="Scheduling explanation and assignment history for one job")
def job_schedule(job_id: int, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    names = electrician_names(db)
    changes = db.scalars(select(ScheduleChange).where(ScheduleChange.job_id == job_id).order_by(ScheduleChange.id))
    return {
        "job": job_dict(job),
        "current_assignment": assignment_dict(job.active_assignment),
        "explanation": job.active_assignment.explanation if job.active_assignment else None,
        "feasibility": job.feasibility,
        "unassigned_reasons": job.unassigned_reasons,
        "assignment_history": [assignment_dict(a) for a in job.assignments],
        "changes": [change_dict(c, names, {job.id: job}) for c in changes],
    }
