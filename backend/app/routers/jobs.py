from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Assignment, BookingEvent, BookingOwner, ManualDispatchOverride, ServiceZone, UserProfile
from app.schemas import JobCreate, JobStart, JobUpdate
from app.services import job_service
from app.services.auth import require_role, require_user
from app.services.errors import ApiError, not_found
from app.services.idempotency import idempotent
from app.services.scheduling_service import execute_run, scheduler_lock
from app.models.enums import RunMode
from app.services.serializers import job_dict

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", status_code=201, summary="Create a service job (supports Idempotency-Key)")
def create_job(data: JobCreate, db: Session = Depends(get_db),
               idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
               user=Depends(require_user)):
    if user is not None and user.role not in ("admin", "customer"):
        raise ApiError(403, "FORBIDDEN", "Only customers and administrators can create bookings.")
    if user is not None and user.role == "customer" and not data.service_items:
        raise ApiError(422, "SERVICE_ITEMS_REQUIRED", "Select one or more catalog services before booking.")
    if user is not None and user.role == "customer":
        if not data.address or not data.service_locality or not data.district or not data.state:
            raise ApiError(422, "SERVICE_ADDRESS_REQUIRED", "Add the full service address, locality, district and state.")
        zones = list(db.scalars(select(ServiceZone)))
        if zones:
            nearest = min(zones, key=lambda z: (z.center_lat - data.lat) ** 2 + (z.center_lon - data.lon) ** 2)
            data = data.model_copy(update={"zone_code": nearest.code})
    def handler():
        job = job_service.create_job(db, data)
        if user and user.role == "customer":
            db.add(BookingOwner(job_id=job.id, user_id=user.id))
            db.add(BookingEvent(job_id=job.id, actor_user_id=user.id, actor_role="customer",
                                action="booking_created", to_status="pending"))
        db.commit()
        if user and user.role == "customer":
            with scheduler_lock():
                execute_run(db, trigger="customer_booking", mode=RunMode.INCREMENTAL)
        return job_dict(job_service.get_job(db, job.id))

    scope = f"POST /api/jobs user:{user.id if user else 'admin'}"
    return idempotent(db, idempotency_key, scope, data.model_dump(mode="json"), handler, 201)


@router.get("", summary="List jobs; filter by comma-separated status/priority and zone code")
def list_jobs(status: str | None = Query(default=None), priority: str | None = Query(default=None),
              zone: str | None = Query(default=None), db: Session = Depends(get_db),
              user=Depends(require_user)):
    jobs = job_service.list_jobs(db, status, priority, zone)
    if user is None or user.role == "admin":
        return [job_dict(j) for j in jobs]
    if user.role == "customer":
        owned = set(db.scalars(select(BookingOwner.job_id).where(BookingOwner.user_id == user.id)))
        return [job_dict(j) for j in jobs if j.id in owned]
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if not profile or profile.electrician_id is None:
        return []
    return [job_dict(j) for j in jobs if j.active_assignment and j.active_assignment.electrician_id == profile.electrician_id]


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user=Depends(require_user)):
    job = job_service.get_job(db, job_id)
    _check_visible(db, job_id, user, job)
    return job_dict(job)


@router.put("/{job_id}", summary="Update a job; status changes follow the job state machine")
def update_job(job_id: int, data: JobUpdate, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    job = job_service.get_job(db, job_id)
    job_service.update_job(db, job, data)
    db.commit()
    return job_dict(job_service.get_job(db, job_id))


@router.post("/{job_id}/start", summary="Mark an assigned job as in progress")
def start_job(job_id: int, data: JobStart | None = None, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    job = job_service.get_job(db, job_id)
    job_service.transition(db, job, "in_progress", at=data.started_at if data else None)
    db.commit()
    return job_dict(job_service.get_job(db, job_id))


@router.delete("/{job_id}", summary="Cancel a job (jobs are never hard-deleted)")
def cancel_job(job_id: int, reason: str | None = Query(default=None), db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    job = job_service.get_job(db, job_id)
    before = job.status
    job_service.transition(db, job, "cancelled", reason=reason or "Cancelled via API")
    manual = db.get(ManualDispatchOverride, job.id)
    if manual:
        manual.active = False
    db.add(BookingEvent(job_id=job.id, actor_user_id=user.id if user else None,
                        actor_role=user.role if user else "system", action="cancelled",
                        from_status=before, to_status=job.status, reason=reason or "Cancelled via API"))
    db.commit()
    return job_dict(job_service.get_job(db, job_id))


def _check_visible(db: Session, job_id: int, user, job=None):
    if user is None or user.role == "admin":
        return
    if user.role == "customer":
        owned = db.scalar(select(BookingOwner.job_id).where(
            BookingOwner.job_id == job_id, BookingOwner.user_id == user.id))
        if owned is None:
            raise not_found("Booking", job_id)
        return
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile and profile.electrician_id and job and job.active_assignment and job.active_assignment.electrician_id == profile.electrician_id:
        return
    raise not_found("Booking", job_id)
