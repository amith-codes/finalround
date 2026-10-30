"""Role scoped booking, customer payments and electrician work actions."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Assignment, AvailabilityOverride, BookingDecline, BookingDetails, BookingEvent,
    BookingOwner, DutySession, Electrician, Job, ManualDispatchOverride, PaymentMethod, User, UserProfile,
)
from app.models.enums import JobStatus, RunMode
from app.schemas import BookingActionIn, CustomerAccountIn, DutyActionIn, ManualAssignmentIn, PaymentMethodIn, PaymentStatusIn
from app.services.auth import hash_password, require_role
from app.services.electrician_service import get_electrician
from app.services.errors import ApiError, not_found
from app.services.job_service import get_job, transition
from app.services.problem_builder import load_electricians
from app.services.scheduling_service import execute_run, scheduler_lock
from app.services.serializers import electrician_dict, electrician_status, job_dict

router = APIRouter(prefix="/api/portal", tags=["role portals"])


def _profile(db: Session, user: User) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None or profile.electrician_id is None:
        raise ApiError(403, "ELECTRICIAN_PROFILE_MISSING", "This electrician account is not linked to an active electrician profile.")
    return profile


def _event(db: Session, job: Job, user: User, action: str, *, before: str | None = None,
           after: str | None = None, old_id: int | None = None, new_id: int | None = None,
           reason: str | None = None) -> None:
    db.add(BookingEvent(job_id=job.id, actor_user_id=user.id, actor_role=user.role,
                        action=action, from_status=before, to_status=after,
                        old_electrician_id=old_id, new_electrician_id=new_id, reason=reason))


def _clear_manual_override(db: Session, job_id: int, electrician_id: int | None = None) -> None:
    override = db.get(ManualDispatchOverride, job_id)
    if override and (electrician_id is None or override.electrician_id == electrician_id):
        override.active = False


def _localities(electrician: Electrician) -> set[str]:
    return {x.locality.strip().casefold() for x in electrician.service_localities}


def _eligible_local_offer(db: Session, job: Job, electrician: Electrician) -> bool:
    manual = db.get(ManualDispatchOverride, job.id)
    if manual and manual.active and manual.electrician_id != electrician.id:
        return False
    if db.scalar(select(BookingDecline.id).where(
        BookingDecline.job_id == job.id, BookingDecline.electrician_id == electrician.id)):
        return False
    if not electrician.active or not {s.code for s in job.required_skills}.issubset({s.code for s in electrician.skills}):
        return False
    if not any(z.id == job.zone_id for z in electrician.zones):
        return False
    if job.booking_details and job.booking_details.locality and \
            job.booking_details.locality.strip().casefold() not in _localities(electrician):
        return False
    override = db.get(AvailabilityOverride, electrician.id)
    if override and not override.is_available:
        return False
    now = datetime.now().replace(second=0, microsecond=0)
    day = job.window_start.date()
    while day <= job.window_end.date():
        for shift in electrician.shifts:
            if shift.day_of_week != day.weekday():
                continue
            start = max(job.window_start, datetime.combine(day, shift.start_time), now)
            end = start + timedelta(minutes=job.duration_minutes)
            if start >= job.window_end or end > datetime.combine(day, shift.end_time) or end > job.window_end:
                continue
            if any(p.start < end and p.end > start for p in electrician.unavailable_periods):
                continue
            conflict = db.scalar(select(Assignment.id).join(Job).where(
                Assignment.is_active.is_(True), Assignment.electrician_id == electrician.id,
                Assignment.job_id != job.id, Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]),
                Assignment.start < end, Assignment.end > start,
            ))
            if conflict is None:
                return True
        day += timedelta(days=1)
    return False


def _manual_assign(db: Session, job: Job, electrician: Electrician, reason: str, *,
                   require_locality: bool, user: User) -> Assignment:
    if job.status not in (JobStatus.PENDING.value, JobStatus.ASSIGNED.value, JobStatus.UNASSIGNED.value):
        raise ApiError(409, "BOOKING_LOCKED", "Only an open booking can be manually assigned.")
    before = job.status
    if not electrician.active:
        raise ApiError(409, "ELECTRICIAN_INACTIVE", "This electrician is inactive.")
    required = {s.code for s in job.required_skills}
    skills = {s.code for s in electrician.skills}
    if not required.issubset(skills):
        raise ApiError(409, "SKILL_MISMATCH", "The electrician does not have every skill required by this booking.")
    if not any(z.id == job.zone_id for z in electrician.zones):
        raise ApiError(409, "ZONE_MISMATCH", "The electrician is not assigned to this service zone.")
    if require_locality and job.booking_details and job.booking_details.locality:
        locality = job.booking_details.locality.strip().casefold()
        if locality not in _localities(electrician):
            raise ApiError(409, "LOCALITY_MISMATCH", f"This electrician does not serve {job.booking_details.locality}.")
    override = db.get(AvailabilityOverride, electrician.id)
    if override and not override.is_available:
        raise ApiError(409, "ELECTRICIAN_UNAVAILABLE", "The electrician is marked unavailable.")

    now = datetime.now().replace(second=0, microsecond=0)
    start = None
    end = None
    day = job.window_start.date()
    while day <= job.window_end.date():
        for shift in electrician.shifts:
            if shift.day_of_week != day.weekday():
                continue
            shift_start = datetime.combine(day, shift.start_time)
            shift_end = datetime.combine(day, shift.end_time)
            candidate = max(job.window_start, shift_start, now)
            candidate_end = candidate + timedelta(minutes=job.duration_minutes)
            if candidate < job.window_end and candidate_end <= min(job.window_end, shift_end):
                start, end = candidate, candidate_end
                break
        if start:
            break
        day += timedelta(days=1)
    if start is None:
        raise ApiError(409, "NO_SHIFT_SLOT", "This electrician has no available shift overlapping the booking time.")
    if any(p.start < end and p.end > start for p in electrician.unavailable_periods):
        raise ApiError(409, "ELECTRICIAN_UNAVAILABLE", "The electrician is unavailable during this booking.")
    conflict = db.scalar(select(Assignment).join(Job).where(
        Assignment.is_active.is_(True), Assignment.electrician_id == electrician.id,
        Assignment.job_id != job.id, Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]),
        Assignment.start < end, Assignment.end > start,
    ))
    if conflict:
        raise ApiError(409, "ELECTRICIAN_BUSY", "The electrician already has a booking during this time.")

    old = job.active_assignment
    old_id = old.electrician_id if old else None
    if old:
        old.is_active = False
    assignment = Assignment(job_id=job.id, electrician_id=electrician.id, start=start, end=end,
                            travel_minutes=0, explanation=f"Manual assignment: {reason}", is_active=True)
    db.add(assignment)
    job.status = JobStatus.ASSIGNED.value
    job.feasibility = "feasible"
    job.unassigned_reasons = None
    manual = db.get(ManualDispatchOverride, job.id)
    if user.role == "admin":
        if manual is None:
            manual = ManualDispatchOverride(job_id=job.id, electrician_id=electrician.id, reason=reason, active=True)
            db.add(manual)
        else:
            manual.electrician_id = electrician.id
            manual.reason = reason
            manual.active = True
    elif manual:
        manual.active = False
    _event(db, job, user, "manually_assigned" if user.role == "admin" else "accepted",
           before=before,
           after=JobStatus.ASSIGNED.value, old_id=old_id, new_id=electrician.id, reason=reason)
    db.flush()
    return assignment


def _dispatch_again(db: Session, trigger: str) -> None:
    db.commit()
    with scheduler_lock():
        execute_run(db, trigger=trigger, mode=RunMode.INCREMENTAL)


@router.get("/customer/bookings")
def customer_bookings(db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    jobs = db.scalars(select(Job).join(BookingOwner).where(BookingOwner.user_id == user.id)
                      .options(selectinload(Job.zone), selectinload(Job.required_skills),
                               selectinload(Job.assignments).selectinload(Assignment.electrician))
                      .order_by(Job.created_at.desc()))
    return [job_dict(j) for j in jobs]


@router.post("/customer/bookings/{job_id}/cancel")
def cancel_customer_booking(job_id: int, reason: str | None = Query(default=None),
                            db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    job = get_job(db, job_id)
    if db.scalar(select(BookingOwner.job_id).where(BookingOwner.job_id == job_id, BookingOwner.user_id == user.id)) is None:
        raise not_found("Booking", job_id)
    before = job.status
    transition(db, job, JobStatus.CANCELLED.value, reason=reason or "Cancelled by customer")
    _clear_manual_override(db, job.id)
    _event(db, job, user, "cancelled_by_customer", before=before, after=job.status, reason=reason)
    db.commit()
    return job_dict(get_job(db, job_id))


@router.get("/customer/payment-methods")
def payment_methods(db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    methods = db.scalars(select(PaymentMethod).where(PaymentMethod.user_id == user.id)
                         .order_by(PaymentMethod.is_default.desc(), PaymentMethod.id))
    return [{"id": x.id, "label": x.label, "brand": x.brand, "last4": x.last4,
             "is_default": x.is_default} for x in methods]


@router.post("/customer/payment-methods", status_code=201)
def add_payment_method(data: PaymentMethodIn, db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    existing = db.scalar(select(PaymentMethod.id).where(PaymentMethod.user_id == user.id))
    method = PaymentMethod(user_id=user.id, label=data.label, brand=data.brand, last4=data.last4,
                           is_default=data.is_default or not existing)
    if method.is_default:
        db.query(PaymentMethod).filter(PaymentMethod.user_id == user.id).update({PaymentMethod.is_default: False})
    db.add(method)
    db.commit()
    db.refresh(method)
    return {"id": method.id, "label": method.label, "brand": method.brand,
            "last4": method.last4, "is_default": method.is_default}


@router.delete("/customer/payment-methods/{method_id}")
def remove_payment_method(method_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    method = db.scalar(select(PaymentMethod).where(PaymentMethod.id == method_id, PaymentMethod.user_id == user.id))
    if method is None:
        raise not_found("Payment method", method_id)
    was_default = method.is_default
    db.delete(method)
    db.flush()
    if was_default:
        replacement = db.scalar(select(PaymentMethod).where(PaymentMethod.user_id == user.id).order_by(PaymentMethod.id))
        if replacement:
            replacement.is_default = True
    db.commit()
    return {"deleted": method_id}


@router.put("/customer/payment-methods/{method_id}/default")
def set_default_payment_method(method_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("customer"))):
    method = db.scalar(select(PaymentMethod).where(PaymentMethod.id == method_id, PaymentMethod.user_id == user.id))
    if method is None:
        raise not_found("Payment method", method_id)
    db.query(PaymentMethod).filter(PaymentMethod.user_id == user.id).update({PaymentMethod.is_default: False})
    method.is_default = True
    db.commit()
    return {"id": method.id, "is_default": True}


@router.get("/electrician/bookings")
def electrician_bookings(db: Session = Depends(get_db), user: User = Depends(require_role("electrician"))):
    profile = _profile(db, user)
    owned_ids = set(db.scalars(select(Assignment.job_id).where(
        Assignment.electrician_id == profile.electrician_id, Assignment.is_active.is_(True))))
    jobs = list(db.scalars(select(Job).where(Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]))
                           .options(selectinload(Job.zone), selectinload(Job.required_skills),
                                    selectinload(Job.assignments).selectinload(Assignment.electrician))))
    assigned = [job_dict(j) for j in jobs if j.id in owned_ids]
    offers = []
    electrician = get_electrician(db, profile.electrician_id)
    for j in db.scalars(select(Job).where(Job.status.in_([JobStatus.PENDING.value, JobStatus.UNASSIGNED.value]))
                        .options(selectinload(Job.zone), selectinload(Job.required_skills))):
        if _eligible_local_offer(db, j, electrician):
            offers.append(job_dict(j))
    offers.sort(key=lambda item: item["window_start"])
    override = db.get(AvailabilityOverride, electrician.id)
    available = override.is_available if override else True
    on_duty = db.scalar(select(DutySession.id).where(
        DutySession.electrician_id == electrician.id, DutySession.ended_at.is_(None))) is not None
    electrician_view = electrician_dict(electrician)
    if not available:
        electrician_view["current_status"] = "unavailable"
    return {"assigned": assigned, "offers": offers,
            "electrician": electrician_view,
            "availability": {"is_available": available}, "on_duty": on_duty}


@router.post("/electrician/bookings/{job_id}/action")
def electrician_booking_action(job_id: int, data: BookingActionIn, db: Session = Depends(get_db),
                               user: User = Depends(require_role("electrician"))):
    profile = _profile(db, user)
    electrician = get_electrician(db, profile.electrician_id)
    job = get_job(db, job_id)
    action = data.action
    before = job.status
    active = job.active_assignment
    if action == "accept":
        if job.status not in (JobStatus.ASSIGNED.value, JobStatus.PENDING.value, JobStatus.UNASSIGNED.value):
            raise ApiError(409, "BOOKING_NOT_AVAILABLE", "This booking is no longer awaiting an electrician response.")
        if active and active.electrician_id == electrician.id:
            _event(db, job, user, "accepted", before=before, after=before)
        elif job.status in (JobStatus.PENDING.value, JobStatus.UNASSIGNED.value):
            _manual_assign(db, job, electrician, "Accepted by electrician", require_locality=True, user=user)
        else:
            raise ApiError(409, "BOOKING_NOT_AVAILABLE", "This booking is assigned to another electrician or is no longer available.")
        db.commit()
        return job_dict(get_job(db, job_id))
    if action == "decline" and active is None and job.status in (JobStatus.PENDING.value, JobStatus.UNASSIGNED.value):
        if not _eligible_local_offer(db, job, electrician):
            raise ApiError(403, "BOOKING_NOT_ELIGIBLE", "This booking is not an available local offer for your profile.")
        if not data.reason:
            raise ApiError(422, "REASON_REQUIRED", "Add a short reason for declining this booking.")
        existing = db.scalar(select(BookingDecline.id).where(
            BookingDecline.job_id == job.id, BookingDecline.electrician_id == electrician.id))
        if existing is None:
            db.add(BookingDecline(job_id=job.id, electrician_id=electrician.id, reason=data.reason))
        _clear_manual_override(db, job.id, electrician.id)
        _event(db, job, user, "declined", before=before, after=before, old_id=electrician.id, reason=data.reason)
        _dispatch_again(db, "electrician_declined_offer")
        return job_dict(get_job(db, job_id))
    if not active or active.electrician_id != electrician.id:
        raise ApiError(403, "NOT_ASSIGNED", "You can only update bookings assigned to your electrician profile.")
    if action == "start":
        if job.status != JobStatus.ASSIGNED.value:
            raise ApiError(409, "INVALID_STATUS", "Only an assigned booking can be started.")
        transition(db, job, JobStatus.IN_PROGRESS.value)
        _event(db, job, user, "started", before=before, after=job.status)
    elif action == "complete":
        if job.status != JobStatus.IN_PROGRESS.value:
            raise ApiError(409, "INVALID_STATUS", "Start the booking before marking it complete.")
        transition(db, job, JobStatus.COMPLETED.value)
        _event(db, job, user, "completed", before=before, after=job.status)
        if job.booking_details:
            job.booking_details.payment_status = job.booking_details.payment_status or "pending"
    elif action in ("decline", "cancel", "customer_unavailable"):
        if job.status != JobStatus.ASSIGNED.value:
            raise ApiError(409, "INVALID_STATUS", "Only an assigned booking can be released to dispatch.")
        if action != "cancel" and not data.reason:
            raise ApiError(422, "REASON_REQUIRED", "Add a short reason for declining or marking the customer unavailable.")
        old_id = active.electrician_id
        active.is_active = False
        job.status = JobStatus.UNASSIGNED.value
        _clear_manual_override(db, job.id, old_id)
        job.cancel_reason = data.reason if action == "cancel" else None
        existing = db.scalar(select(BookingDecline.id).where(
            BookingDecline.job_id == job.id, BookingDecline.electrician_id == old_id))
        if existing is None:
            db.add(BookingDecline(job_id=job.id, electrician_id=old_id, reason=data.reason or action))
        _event(db, job, user, action, before=before, after=job.status,
               old_id=old_id, reason=data.reason)
        _dispatch_again(db, f"electrician_{action}")
        return job_dict(get_job(db, job_id))
    db.commit()
    return job_dict(get_job(db, job_id))


@router.post("/electrician/duty")
def electrician_duty(data: DutyActionIn, db: Session = Depends(get_db), user: User = Depends(require_role("electrician"))):
    electrician_id = _profile(db, user).electrician_id
    now = datetime.now().replace(second=0, microsecond=0)
    if data.action == "clock_in":
        open_session = db.scalar(select(DutySession).where(DutySession.electrician_id == electrician_id,
                                                            DutySession.ended_at.is_(None)))
        if open_session is None:
            db.add(DutySession(electrician_id=electrician_id, started_at=now))
        override = db.get(AvailabilityOverride, electrician_id)
        if override is None:
            db.add(AvailabilityOverride(electrician_id=electrician_id, is_available=True))
        else:
            override.is_available = True
        db.commit()
        return {"on_duty": True}
    if data.action == "clock_out":
        open_session = db.scalar(select(DutySession).where(DutySession.electrician_id == electrician_id,
                                                            DutySession.ended_at.is_(None)))
        if open_session:
            open_session.ended_at = now
        override = db.get(AvailabilityOverride, electrician_id)
        if override is None:
            override = AvailabilityOverride(electrician_id=electrician_id, is_available=False)
            db.add(override)
        else:
            override.is_available = False
        active_rows = list(db.scalars(select(Assignment).join(Job).where(
            Assignment.electrician_id == electrician_id, Assignment.is_active.is_(True),
            Job.status == JobStatus.ASSIGNED.value).options(selectinload(Assignment.job))))
        for assignment in active_rows:
            assignment.is_active = False
            assignment.job.status = JobStatus.UNASSIGNED.value
            _clear_manual_override(db, assignment.job_id, electrician_id)
            existing = db.scalar(select(BookingDecline.id).where(
                BookingDecline.job_id == assignment.job_id, BookingDecline.electrician_id == electrician_id))
            if existing is None:
                db.add(BookingDecline(job_id=assignment.job_id, electrician_id=electrician_id,
                                      reason="Electrician clocked out"))
            _event(db, assignment.job, user, "availability_cancelled_assignment",
                   before=JobStatus.ASSIGNED.value, after=JobStatus.UNASSIGNED.value,
                   old_id=electrician_id, reason="Electrician clocked out")
        if active_rows:
            _dispatch_again(db, "electrician_clocked_out")
            return {"on_duty": False, "released_bookings": len(active_rows)}
        db.commit()
        return {"on_duty": False, "released_bookings": 0}
    override = db.get(AvailabilityOverride, electrician_id)
    if override is None:
        override = AvailabilityOverride(electrician_id=electrician_id, is_available=True)
        db.add(override)
    override.is_available = data.action == "available"
    if not override.is_available:
        active_rows = list(db.scalars(select(Assignment).join(Job).where(
            Assignment.electrician_id == electrician_id, Assignment.is_active.is_(True),
            Job.status == JobStatus.ASSIGNED.value).options(selectinload(Assignment.job))))
        for assignment in active_rows:
            assignment.is_active = False
            assignment.job.status = JobStatus.UNASSIGNED.value
            _clear_manual_override(db, assignment.job_id, electrician_id)
            existing = db.scalar(select(BookingDecline.id).where(
                BookingDecline.job_id == assignment.job_id, BookingDecline.electrician_id == electrician_id))
            if existing is None:
                db.add(BookingDecline(job_id=assignment.job_id, electrician_id=electrician_id,
                                      reason="Electrician marked unavailable"))
            _event(db, assignment.job, user, "availability_cancelled_assignment",
                   before=JobStatus.ASSIGNED.value, after=JobStatus.UNASSIGNED.value,
                   old_id=electrician_id, reason="Electrician marked unavailable")
        if active_rows:
            _dispatch_again(db, "electrician_unavailable")
            return {"is_available": False, "released_bookings": len(active_rows)}
    db.commit()
    return {"is_available": override.is_available, "released_bookings": 0}


@router.get("/electrician/earnings")
def electrician_earnings(start: date | None = None, end: date | None = None,
                         db: Session = Depends(get_db), user: User = Depends(require_role("electrician"))):
    electrician_id = _profile(db, user).electrician_id
    start = start or date.today().replace(day=1)
    end = end or date.today()
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end + timedelta(days=1), time.min)
    rows = list(db.scalars(select(Job).join(Assignment).where(
        Assignment.electrician_id == electrician_id, Assignment.is_active.is_(True),
        Job.status == JobStatus.COMPLETED.value, Job.actual_end >= lo, Job.actual_end < hi)
        .options(selectinload(Job.booking_details), selectinload(Job.zone))))
    value = sum(j.booking_details.amount for j in rows if j.booking_details)
    sessions = list(db.scalars(select(DutySession).where(
        DutySession.electrician_id == electrician_id, DutySession.started_at < hi,
        func.coalesce(DutySession.ended_at, datetime.now()) >= lo)))
    minutes = sum(max(0, int((min(s.ended_at or datetime.now(), hi) - max(s.started_at, lo)).total_seconds() // 60))
                  for s in sessions)
    open_session = any(s.ended_at is None for s in sessions)
    return {"start": start, "end": end, "gross_earnings": round(value, 2),
            "currency": "INR", "duty_minutes": minutes, "on_duty": open_session,
            "bookings": [job_dict(j) for j in rows]}


@router.get("/admin/overview")
def admin_overview(locality: str | None = None, start: date | None = None, end: date | None = None,
                   db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    query = select(Job).options(selectinload(Job.booking_details), selectinload(Job.assignments),
                                selectinload(Job.zone)).order_by(Job.window_start.desc())
    if start:
        query = query.where(Job.window_start >= datetime.combine(start, time.min))
    if end:
        query = query.where(Job.window_start < datetime.combine(end + timedelta(days=1), time.min))
    if locality:
        query = query.join(BookingDetails).where(BookingDetails.locality.ilike(f"%{locality.strip()}%"))
    jobs = list(db.scalars(query))
    methods = list(db.scalars(select(BookingDetails).where(BookingDetails.job_id.in_([j.id for j in jobs])))) if jobs else []
    user_count = db.scalar(select(func.count(User.id)).where(User.role == "customer")) or 0
    electricians = load_electricians(db, active_only=False)
    in_progress = {eid for eid, _ in db.execute(select(Assignment.electrician_id, Assignment.job_id).join(Job).where(
        Assignment.is_active.is_(True), Job.status == JobStatus.IN_PROGRESS.value)).all()}
    now = datetime.now()
    overview = {"bookings": len(jobs), "assigned": sum(bool(j.active_assignment) for j in jobs),
                "needs_attention": sum(j.status == JobStatus.UNASSIGNED.value for j in jobs),
                "customers": user_count, "electricians": len(electricians),
                "available_electricians": sum(electrician_status(e, now, {x for x in in_progress if x == e.id}) == "on_shift"
                                              and (db.get(AvailabilityOverride, e.id) is None
                                                   or db.get(AvailabilityOverride, e.id).is_available)
                                              for e in electricians),
                "payment_total": round(sum(x.amount for x in methods), 2),
                "payment_status": {status: sum(x.payment_status == status for x in methods)
                                   for status in ("pending", "paid", "failed", "refunded")},
                "jobs": [job_dict(j) for j in jobs]}
    return overview


@router.get("/admin/customers")
def admin_customers(db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    users = db.scalars(select(User).where(User.role == "customer").order_by(User.username))
    profiles = {p.user_id: p for p in db.scalars(select(UserProfile))}
    counts = dict(db.execute(select(BookingOwner.user_id, func.count(BookingOwner.job_id))
                             .group_by(BookingOwner.user_id)).all())
    return [{"id": u.id, "username": u.username,
             "display_name": profiles[u.id].display_name if u.id in profiles and profiles[u.id].display_name else u.username,
             "booking_count": counts.get(u.id, 0)} for u in users]


@router.get("/admin/earnings")
def admin_earnings(start: date | None = None, end: date | None = None,
                   db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    start = start or date.today().replace(day=1)
    end = end or date.today()
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end + timedelta(days=1), time.min)
    rows = list(db.scalars(select(Job).join(Assignment).where(
        Assignment.is_active.is_(True), Job.status == JobStatus.COMPLETED.value,
        Job.actual_end >= lo, Job.actual_end < hi)
        .options(selectinload(Job.booking_details), selectinload(Job.assignments).selectinload(Assignment.electrician))))
    grouped: dict[int, dict] = {}
    for job in rows:
        assignment = job.active_assignment
        if not assignment:
            continue
        electrician = assignment.electrician
        item = grouped.setdefault(electrician.id, {"electrician_id": electrician.id,
                           "electrician_name": electrician.name, "employee_code": electrician.employee_code,
                           "gross_earnings": 0.0, "bookings": []})
        amount = job.booking_details.amount if job.booking_details else 0
        item["gross_earnings"] += amount
        item["bookings"].append({"job_id": job.id, "job_number": job.job_number,
                                 "title": job.title, "amount": amount, "completed_at": job.actual_end})
    for item in grouped.values():
        item["gross_earnings"] = round(item["gross_earnings"], 2)
    return {"start": start, "end": end, "currency": "INR", "electricians": sorted(
        grouped.values(), key=lambda item: (-item["gross_earnings"], item["electrician_name"]))}


@router.post("/admin/customers", status_code=201)
def create_customer(data: CustomerAccountIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if db.scalar(select(User.id).where(User.username == data.username)):
        raise ApiError(409, "USERNAME_EXISTS", "That sign-in name is already in use.")
    customer = User(username=data.username, password_hash=hash_password(data.password), role="customer")
    db.add(customer)
    db.flush()
    db.add(UserProfile(user_id=customer.id, display_name=data.display_name))
    db.commit()
    return {"id": customer.id, "username": customer.username, "role": customer.role,
            "display_name": data.display_name}


@router.get("/bookings/{job_id}/history")
def booking_history(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "customer", "electrician"))):
    job = get_job(db, job_id)
    if user.role == "customer":
        if db.scalar(select(BookingOwner.job_id).where(BookingOwner.job_id == job_id, BookingOwner.user_id == user.id)) is None:
            raise not_found("Booking", job_id)
    elif user.role == "electrician":
        profile = _profile(db, user)
        if not any(a.electrician_id == profile.electrician_id for a in job.assignments):
            raise not_found("Booking", job_id)
    events = list(db.scalars(select(BookingEvent).where(BookingEvent.job_id == job_id).order_by(BookingEvent.created_at)))
    users = {u.id: u.username for u in db.scalars(select(User))}
    electricians = {e.id: e.name for e in db.scalars(select(Electrician))}
    return {"events": [{"id": ev.id, "action": ev.action, "actor_role": ev.actor_role,
                        "actor": users.get(ev.actor_user_id), "from_status": ev.from_status,
                        "to_status": ev.to_status, "old_electrician": electricians.get(ev.old_electrician_id),
                        "new_electrician": electricians.get(ev.new_electrician_id),
                        "reason": ev.reason, "created_at": ev.created_at} for ev in events],
            "assignments": [{"electrician": a.electrician.name if a.electrician else None,
                             "start": a.start, "end": a.end, "active": a.is_active,
                             "explanation": a.explanation} for a in job.assignments]}


@router.post("/admin/bookings/{job_id}/assign")
def admin_assign(job_id: int, data: ManualAssignmentIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    job = get_job(db, job_id)
    electrician = db.scalar(select(Electrician).where(Electrician.id == data.electrician_id)
                            .options(selectinload(Electrician.skills), selectinload(Electrician.zones),
                                     selectinload(Electrician.shifts), selectinload(Electrician.unavailable_periods),
                                     selectinload(Electrician.service_localities)))
    if electrician is None:
        raise not_found("Electrician", data.electrician_id)
    _manual_assign(db, job, electrician, data.reason, require_locality=False, user=user)
    db.commit()
    return job_dict(get_job(db, job_id))


@router.put("/admin/bookings/{job_id}/payment-status")
def update_payment_status(job_id: int, data: PaymentStatusIn, db: Session = Depends(get_db),
                          user: User = Depends(require_role("admin"))):
    job = get_job(db, job_id)
    details = job.booking_details
    if details is None:
        details = BookingDetails(job_id=job.id, amount=0, payment_status=data.status)
        db.add(details)
    else:
        details.payment_status = data.status
    _event(db, job, user, "payment_status_changed", reason=f"Payment marked {data.status}")
    db.commit()
    return {"job_id": job.id, "payment_status": data.status}


@router.get("/admin/dispatch-candidates/{job_id}")
def dispatch_candidates(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    job = get_job(db, job_id)
    candidates = []
    for e in load_electricians(db, active_only=True):
        if {s.code for s in job.required_skills}.issubset({s.code for s in e.skills}) \
                and any(z.id == job.zone_id for z in e.zones):
            item = electrician_dict(e)
            item["serves_locality"] = not job.booking_details or not job.booking_details.locality \
                or job.booking_details.locality.strip().casefold() in _localities(e)
            candidates.append(item)
    return candidates
