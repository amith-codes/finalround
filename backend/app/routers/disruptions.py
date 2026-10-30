"""Disruption endpoints: record what happened, then immediately run incremental recovery.

Each disruption is applied and committed first (it is a real-world fact that must survive even
if re-planning fails), then a recovery run executes under the same scheduler lock. The keep
pass in the engine preserves every assignment that is still feasible; only affected work moves.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BookingEvent, ManualDispatchOverride
from app.models.enums import ChangeType, JobStatus, RunMode
from app.routers.scheduling import run_response
from app.schemas import (
    DurationChangeIn,
    ElectricianUnavailableIn,
    JobCancelIn,
    JobCompletionIn,
    UnavailableIn,
    UrgentJobIn,
    JobCreate,
)
from app.services import electrician_service, job_service
from app.services.errors import ApiError
from app.services.idempotency import idempotent
from app.services.scheduling_service import current_snapshot, execute_run, normalize_now, scheduler_lock

router = APIRouter(prefix="/api/disruptions", tags=["disruptions"])


def _recover(db: Session, key: str | None, endpoint: str, payload, as_of, trigger: str, apply):
    def handler():
        with scheduler_lock():
            before = current_snapshot(db)
            info, extra = apply()
            db.commit()
            run = execute_run(db, trigger=trigger, mode=RunMode.INCREMENTAL, as_of=as_of,
                              disruption=info, extra_changes=extra, before_snapshot=before)
        return {"disruption": info, "run": run_response(db, run)}

    return idempotent(db, key, endpoint, payload, handler)


def _removed_change(job, reason: str) -> list[dict]:
    a = job.active_assignment
    return [{
        "job_id": job.id, "change_type": ChangeType.REMOVED.value,
        "old_electrician_id": a.electrician_id if a else None, "new_electrician_id": None,
        "old_start": a.start if a else None, "old_end": a.end if a else None,
        "new_start": None, "new_end": None, "reason": reason,
    }]


@router.post("/electrician-unavailable")
def electrician_unavailable(body: ElectricianUnavailableIn, db: Session = Depends(get_db),
                            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def apply():
        e = electrician_service.get_electrician(db, body.electrician_id)
        if not e.active:
            raise ApiError(409, "ELECTRICIAN_INACTIVE", f"{e.name} is not active")
        electrician_service.add_unavailability(db, e, UnavailableIn(start=body.start, end=body.end, reason=body.reason))
        affected, protected = [], []
        for job in job_service.list_jobs(db, status="assigned,in_progress"):
            a = job.active_assignment
            if a is None or a.electrician_id != e.id:
                continue
            if job.status == JobStatus.IN_PROGRESS.value:
                protected.append(job.job_number)
            elif a.start < body.end and a.end > body.start:
                affected.append(job.job_number)
                manual = db.get(ManualDispatchOverride, job.id)
                if manual and manual.electrician_id == e.id:
                    manual.active = False
        info = {
            "type": "electrician_unavailable", "electrician_id": e.id, "electrician_name": e.name,
            "start": body.start.isoformat(), "end": body.end.isoformat(), "reason": body.reason,
            "directly_affected_jobs": affected, "protected_in_progress_jobs": protected,
        }
        return info, []

    return _recover(db, idempotency_key, "POST /api/disruptions/electrician-unavailable",
                    body.model_dump(mode="json"), body.as_of, "disruption:electrician_unavailable", apply)


@router.post("/urgent-job")
def urgent_job(body: UrgentJobIn, db: Session = Depends(get_db),
               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def apply():
        data = JobCreate(**body.model_dump(exclude={"as_of"}))
        job = job_service.create_job(db, data)
        info = {"type": "urgent_job", "job_id": job.id, "job_number": job.job_number,
                "priority": job.priority, "title": job.title}
        return info, []

    return _recover(db, idempotency_key, "POST /api/disruptions/urgent-job",
                    body.model_dump(mode="json"), body.as_of, "disruption:urgent_job", apply)


@router.post("/job-duration-change")
def job_duration_change(body: DurationChangeIn, db: Session = Depends(get_db),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def apply():
        job = job_service.get_job(db, body.job_id)
        if job.status in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
            raise ApiError(409, "JOB_LOCKED", f"Cannot change the duration of a {job.status} job.")
        old = job.duration_minutes
        job.duration_minutes = body.new_duration_minutes
        info = {"type": "job_duration_change", "job_id": job.id, "job_number": job.job_number,
                "old_duration_minutes": old, "new_duration_minutes": body.new_duration_minutes,
                "status": job.status, "reason": body.reason}
        if job.status == JobStatus.IN_PROGRESS.value and job.actual_start:
            info["new_expected_end"] = (job.actual_start + timedelta(minutes=job.duration_minutes)).isoformat()
            info["note"] = "Job is in progress: it stays with its electrician; later work on that route is re-planned."
        return info, []

    return _recover(db, idempotency_key, "POST /api/disruptions/job-duration-change",
                    body.model_dump(mode="json"), body.as_of, "disruption:job_duration_change", apply)


@router.post("/job-cancel")
def job_cancel(body: JobCancelIn, db: Session = Depends(get_db),
               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def apply():
        job = job_service.get_job(db, body.job_id)
        extra = _removed_change(job, f"Cancelled: {body.reason}") if job.active_assignment else []
        previous = job.status
        job_service.transition(db, job, JobStatus.CANCELLED.value, reason=body.reason)
        manual = db.get(ManualDispatchOverride, job.id)
        if manual:
            manual.active = False
        db.add(BookingEvent(job_id=job.id, actor_role="system", action="cancelled",
                            from_status=previous, to_status=job.status, reason=body.reason))
        info = {"type": "job_cancel", "job_id": job.id, "job_number": job.job_number, "reason": body.reason,
                "freed_electrician_id": extra[0]["old_electrician_id"] if extra else None}
        return info, extra

    return _recover(db, idempotency_key, "POST /api/disruptions/job-cancel",
                    body.model_dump(mode="json"), body.as_of, "disruption:job_cancel", apply)


@router.post("/job-completion", summary="Report an in-progress job finished (early or late)")
def job_completion(body: JobCompletionIn, db: Session = Depends(get_db),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    def apply():
        job = job_service.get_job(db, body.job_id)
        if job.status != JobStatus.IN_PROGRESS.value:
            raise ApiError(409, "JOB_NOT_IN_PROGRESS", f"Job {job.job_number} is {job.status}, not in progress.")
        completed_at = normalize_now(body.completed_at or body.as_of or datetime.now())
        expected = job.actual_start + timedelta(minutes=job.duration_minutes)
        delta = int((completed_at - expected).total_seconds() // 60)
        timing = "on time" if delta == 0 else (f"{-delta} min early" if delta < 0 else f"{delta} min late")
        extra = _removed_change(job, f"Completed {timing}.")
        previous = job.status
        job_service.transition(db, job, JobStatus.COMPLETED.value, at=completed_at)
        db.add(BookingEvent(job_id=job.id, actor_role="system", action="completed",
                            from_status=previous, to_status=job.status, reason=f"Completed {timing}."))
        info = {"type": "job_completion", "job_id": job.id, "job_number": job.job_number,
                "completed_at": completed_at.isoformat(), "expected_end": expected.isoformat(),
                "difference_minutes": delta, "timing": timing,
                "electrician_id": extra[0]["old_electrician_id"]}
        return info, extra

    return _recover(db, idempotency_key, "POST /api/disruptions/job-completion",
                    body.model_dump(mode="json"), body.as_of or body.completed_at, "disruption:job_completion", apply)
