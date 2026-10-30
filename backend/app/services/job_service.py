"""Job CRUD and the job status state machine."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Assignment, BookingDetails, Job, ServiceZone, Skill
from app.models.enums import JobStatus
from app.schemas import JobCreate, JobUpdate
from app.services.errors import ApiError, not_found

SERVICE_PRICES = {
    "uc_sw_replace": 89, "uc_sw_board_inst": 199, "uc_ac_power_point": 249,
    "uc_fan_repair": 149, "uc_fan_installation": 199, "uc_bldc_fan": 299,
    "uc_exhaust_fan": 179, "uc_tube_light": 99, "uc_chandelier_small": 499,
    "uc_downlight_cob": 129, "uc_mcb_tripping": 249, "uc_mcb_replacement": 169,
    "uc_db_board": 799, "uc_internal_wiring": 299, "uc_ev_charger": 699,
    "uc_inverter_setup": 449, "uc_solar_check": 799, "uc_video_doorbell": 349,
    "uc_smart_switch_wifi": 399, "uc_home_audit": 399, "uc_industrial_audit": 999,
    "uc_consultation_visit": 99,
}


def quote_booking(data: JobCreate) -> float:
    """Calculate the catalog amount on the server; never trust the browser's total."""
    if not data.service_items:
        return float(data.booking_amount)
    missing = sorted({item.id for item in data.service_items if item.id not in SERVICE_PRICES})
    if missing:
        raise ApiError(422, "UNKNOWN_SERVICE", f"Unknown service item(s): {', '.join(missing)}")
    subtotal = sum(SERVICE_PRICES[item.id] * item.quantity for item in data.service_items)
    visit_fee = 0 if subtotal >= 399 else 49
    coupon = (data.coupon_code or "").strip().upper()
    if coupon == "DISPATCH10":
        discount = int(subtotal * 0.1 + 0.5)
    elif coupon == "FIRST100":
        discount = min(100, subtotal)
    elif coupon:
        raise ApiError(422, "INVALID_COUPON", "This coupon code is not valid.")
    else:
        discount = 0
    return float(max(0, subtotal + visit_fee - discount))

# Transitions a user may request directly. ASSIGNED and UNASSIGNED are set only by the scheduler.
MANUAL_TRANSITIONS: dict[str, set[str]] = {
    JobStatus.PENDING.value: {JobStatus.CANCELLED.value},
    JobStatus.UNASSIGNED.value: {JobStatus.PENDING.value, JobStatus.CANCELLED.value},
    JobStatus.ASSIGNED.value: {JobStatus.PENDING.value, JobStatus.IN_PROGRESS.value, JobStatus.CANCELLED.value},
    JobStatus.IN_PROGRESS.value: {JobStatus.COMPLETED.value},
    JobStatus.COMPLETED.value: set(),
    JobStatus.CANCELLED.value: set(),
}

# Fields that may still be edited once work has started.
IN_PROGRESS_EDITABLE = {"title", "description", "customer_name", "duration_minutes", "status", "actual_end"}


def get_job(db: Session, job_id: int) -> Job:
    job = db.scalar(
        select(Job).where(Job.id == job_id).options(
            selectinload(Job.required_skills), selectinload(Job.zone),
            selectinload(Job.assignments).selectinload(Assignment.electrician),
        )
    )
    if job is None:
        raise not_found("Job", job_id)
    return job


def list_jobs(db: Session, status: str | None = None, priority: str | None = None, zone: str | None = None) -> list[Job]:
    q = select(Job).options(
        selectinload(Job.required_skills), selectinload(Job.zone),
        selectinload(Job.assignments).selectinload(Assignment.electrician),
    ).order_by(Job.id)
    if status:
        q = q.where(Job.status.in_(status.split(",")))
    if priority:
        q = q.where(Job.priority.in_(priority.split(",")))
    if zone:
        q = q.join(ServiceZone).where(ServiceZone.code == zone)
    return list(db.scalars(q))


def _zone(db: Session, code: str) -> ServiceZone:
    zone = db.scalar(select(ServiceZone).where(ServiceZone.code == code))
    if zone is None:
        raise ApiError(422, "UNKNOWN_ZONE", f"Service zone '{code}' does not exist")
    return zone


def _skills(db: Session, codes: list[str]) -> list[Skill]:
    skills = list(db.scalars(select(Skill).where(Skill.code.in_(codes))))
    missing = sorted(set(codes) - {s.code for s in skills})
    if missing:
        raise ApiError(422, "UNKNOWN_SKILL", f"Unknown skill code(s): {', '.join(missing)}", {"unknown": missing})
    return skills


def create_job(db: Session, data: JobCreate) -> Job:
    booking_amount = quote_booking(data)
    job = Job(
        title=data.title, description=data.description, customer_name=data.customer_name, address=data.address,
        lat=data.lat, lon=data.lon, zone_id=_zone(db, data.zone_code).id, priority=data.priority.value,
        duration_minutes=data.duration_minutes, window_start=data.window_start, window_end=data.window_end,
        sla_deadline=data.sla_deadline, status=JobStatus.PENDING.value,
    )
    job.required_skills = _skills(db, data.required_skills)
    db.add(job)
    db.flush()
    job.job_number = f"JOB-{job.id:05d}"
    if data.service_locality or data.district or data.state or data.booking_amount or data.service_category or data.customer_phone:
        job.booking_details = BookingDetails(
            locality=data.service_locality, district=data.district, state=data.state,
            service_category=data.service_category, customer_phone=data.customer_phone, amount=booking_amount,
        )
    return job


def deactivate_assignment(job: Job) -> Assignment | None:
    a = job.active_assignment
    if a is not None:
        a.is_active = False
    return a


def transition(db: Session, job: Job, target: str, *, at: datetime | None = None, reason: str | None = None) -> None:
    current = job.status
    if target == current:
        if current in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
            raise ApiError(409, "INVALID_STATUS_TRANSITION", f"Job is already {current}.",
                           {"from": current, "to": target, "allowed": []})
        return
    if target not in MANUAL_TRANSITIONS.get(current, set()):
        allowed = sorted(MANUAL_TRANSITIONS.get(current, set()))
        raise ApiError(
            409, "INVALID_STATUS_TRANSITION",
            f"Cannot change job status from '{current}' to '{target}'.",
            {"from": current, "to": target, "allowed": allowed},
        )
    at = at or datetime.now().replace(second=0, microsecond=0)
    if target == JobStatus.CANCELLED.value:
        deactivate_assignment(job)
        job.cancel_reason = reason or job.cancel_reason or "Cancelled"
    elif target == JobStatus.PENDING.value:
        deactivate_assignment(job)
    elif target == JobStatus.IN_PROGRESS.value:
        a = job.active_assignment
        if a is None:
            raise ApiError(409, "NOT_ASSIGNED", "Job has no active assignment to start.")
        busy = db.scalar(
            select(Job).join(Assignment).where(
                Job.status == JobStatus.IN_PROGRESS.value, Assignment.is_active.is_(True),
                Assignment.electrician_id == a.electrician_id, Job.id != job.id,
            )
        )
        if busy is not None:
            raise ApiError(409, "ELECTRICIAN_BUSY",
                           f"Electrician already has job {busy.job_number} in progress.")
        job.actual_start = at
    elif target == JobStatus.COMPLETED.value:
        if job.actual_start and at <= job.actual_start:
            raise ApiError(422, "INVALID_COMPLETION_TIME", "Completion time must be after the actual start time.")
        job.actual_end = at
        a = job.active_assignment
        if a is not None and job.actual_start:
            a.start, a.end = job.actual_start, at
    job.status = target


def update_job(db: Session, job: Job, data: JobUpdate) -> Job:
    fields = data.model_dump(exclude_unset=True)
    if job.status in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
        raise ApiError(409, "JOB_LOCKED", f"A {job.status} job cannot be modified.")
    if job.status == JobStatus.IN_PROGRESS.value:
        blocked = sorted(set(fields) - IN_PROGRESS_EDITABLE)
        if blocked:
            raise ApiError(409, "JOB_IN_PROGRESS", "Only descriptive fields and duration can change once work has started.",
                           {"blocked_fields": blocked})

    status = fields.pop("status", None)
    actual_start = fields.pop("actual_start", None)
    actual_end = fields.pop("actual_end", None)
    cancel_reason = fields.pop("cancel_reason", None)
    if "zone_code" in fields:
        job.zone_id = _zone(db, fields.pop("zone_code")).id
    if "required_skills" in fields:
        codes = fields.pop("required_skills")
        if len(set(codes)) != len(codes):
            raise ApiError(422, "VALIDATION_ERROR", "required_skills contains duplicates")
        job.required_skills = _skills(db, codes)
    if "priority" in fields:
        fields["priority"] = fields["priority"].value if hasattr(fields["priority"], "value") else fields["priority"]
    for k, v in fields.items():
        setattr(job, k, v)

    if job.window_end <= job.window_start:
        raise ApiError(422, "VALIDATION_ERROR", "window_end must be after window_start")
    if job.status != JobStatus.IN_PROGRESS.value and \
            (job.window_end - job.window_start).total_seconds() / 60 < job.duration_minutes:
        raise ApiError(422, "VALIDATION_ERROR", "time window is shorter than duration_minutes")
    if job.sla_deadline <= job.window_start:
        raise ApiError(422, "VALIDATION_ERROR", "sla_deadline must be after window_start")

    if status is not None:
        valid = {s.value for s in JobStatus}
        if status not in valid:
            raise ApiError(422, "VALIDATION_ERROR", f"Unknown status '{status}'", {"allowed": sorted(valid)})
        at = actual_end if status == JobStatus.COMPLETED.value else actual_start
        transition(db, job, status, at=at, reason=cancel_reason)
    return job
