"""Loads the current database state into an engine `Problem`."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Assignment, AvailabilityOverride, BookingDecline, BookingDetails, BookingOwner,
    Electrician, Job, ManualDispatchOverride,
)
from app.models.enums import SCHEDULABLE_STATUSES, JobStatus
from app.scheduling.types import Anchor, Interval, JobInput, PriorAssignment, Problem, TechInput

MAX_HORIZON_DAYS = 31


@dataclass
class ProblemContext:
    jobs: dict[int, Job]  # schedulable jobs
    electricians: dict[int, Electrician]
    locked_assignments: list[Assignment]  # in-progress work


def load_jobs(db: Session, statuses) -> list[Job]:
    return list(db.scalars(
        select(Job)
        .where(Job.status.in_(statuses))
        .options(
            selectinload(Job.required_skills),
            selectinload(Job.zone),
            selectinload(Job.assignments).selectinload(Assignment.electrician),
            selectinload(Job.booking_events),
        )
        .order_by(Job.id)
    ))


def load_electricians(db: Session, active_only: bool = True) -> list[Electrician]:
    q = select(Electrician).options(
        selectinload(Electrician.skills),
        selectinload(Electrician.zones),
            selectinload(Electrician.service_localities),
        selectinload(Electrician.shifts),
        selectinload(Electrician.unavailable_periods),
    ).order_by(Electrician.id)
    if active_only:
        q = q.where(Electrician.active.is_(True))
    return list(db.scalars(q))


def shift_instances(e: Electrician, first_day, last_day) -> list[Interval]:
    out = []
    day = first_day
    while day <= last_day:
        for s in e.shifts:
            if s.day_of_week == day.weekday():
                out.append(Interval(datetime.combine(day, s.start_time), datetime.combine(day, s.end_time)))
        day += timedelta(days=1)
    out.sort(key=lambda i: i.start)
    return out


def _anchors(db: Session, now: datetime) -> tuple[dict[int, Anchor], list[Assignment]]:
    anchors: dict[int, Anchor] = {}
    locked: list[Assignment] = []
    for job in load_jobs(db, [JobStatus.IN_PROGRESS.value]):
        a = job.active_assignment
        if a is None:
            continue
        locked.append(a)
        started = job.actual_start or a.start
        free_at = max(started + timedelta(minutes=job.duration_minutes), now)
        anchors[a.electrician_id] = Anchor(free_at, job.lat, job.lon, f"in-progress job {job.job_number}", started)

    # An electrician who finished a job today departs from that job's site, not from home.
    day_start = datetime.combine(now.date(), datetime.min.time())
    completed = db.scalars(
        select(Job)
        .where(Job.status == JobStatus.COMPLETED.value, Job.actual_end >= day_start, Job.actual_end <= now)
        .options(selectinload(Job.assignments))
        .order_by(Job.actual_end)
    )
    for job in completed:
        a = job.active_assignment
        if a is None or a.electrician_id in anchors and anchors[a.electrician_id].busy_from is not None:
            continue
        anchors[a.electrician_id] = Anchor(job.actual_end, job.lat, job.lon, f"completed job {job.job_number}")
    return anchors, locked


def build_problem(db: Session, now: datetime) -> tuple[Problem, ProblemContext]:
    jobs = load_jobs(db, list(SCHEDULABLE_STATUSES))
    electricians = load_electricians(db)
    customer_job_ids = set()
    if jobs:
        job_ids = [job.id for job in jobs]
        customer_job_ids.update(db.scalars(select(BookingOwner.job_id).where(BookingOwner.job_id.in_(job_ids))))
        customer_job_ids.update(db.scalars(select(BookingDetails.job_id).where(BookingDetails.job_id.in_(job_ids))))
    overrides = {o.electrician_id: o.is_available for o in db.scalars(select(AvailabilityOverride))}
    declines: dict[int, set[int]] = {}
    for d in db.scalars(select(BookingDecline).where(BookingDecline.job_id.in_([j.id for j in jobs]))):
        declines.setdefault(d.job_id, set()).add(d.electrician_id)
    manual_overrides = {o.job_id: o.electrician_id for o in db.scalars(
        select(ManualDispatchOverride).where(ManualDispatchOverride.active.is_(True),
                                            ManualDispatchOverride.job_id.in_([j.id for j in jobs])))}
    anchors, locked = _anchors(db, now)

    last_day = max((j.window_end.date() for j in jobs), default=now.date())
    last_day = min(max(last_day, now.date()), now.date() + timedelta(days=MAX_HORIZON_DAYS))
    first_day = now.date() - timedelta(days=1)  # catch shifts that started yesterday and are still in overtime

    techs = []
    horizon_start = datetime.combine(first_day, datetime.min.time())
    for e in electricians:
        techs.append(TechInput(
            id=e.id,
            name=e.name,
            skills=frozenset(s.code for s in e.skills),
            zones=frozenset(z.code for z in e.zones),
            home_lat=e.home_lat,
            home_lon=e.home_lon,
            shifts=shift_instances(e, first_day, last_day),
            unavailable=[Interval(p.start, p.end) for p in e.unavailable_periods if p.end > horizon_start],
            max_overtime=e.max_overtime_minutes or 0,
            anchor=anchors.get(e.id),
            localities=frozenset(x.locality for x in e.service_localities),
        ))
        if overrides.get(e.id) is False:
            techs[-1].unavailable.append(Interval(now, datetime.combine(last_day + timedelta(days=1), datetime.min.time())))

    job_inputs = []
    prior = {}
    for j in jobs:
        locality = j.booking_details.locality if j.booking_details else None
        if j.id in customer_job_ids and not (locality and locality.strip()):
            # Never let automatic dispatch treat a customer request with no known locality
            # as a city-wide job. Dispatch must resolve the location manually first.
            locality = "__customer_locality_missing__"
        job_inputs.append(JobInput(
            id=j.id,
            priority=j.priority,
            duration=j.duration_minutes,
            skills=frozenset(s.code for s in j.required_skills),
            zone=j.zone.code,
            lat=j.lat,
            lon=j.lon,
            window_start=j.window_start,
            window_end=j.window_end,
            sla_deadline=j.sla_deadline,
            label=j.job_number or "",
            locality=locality,
            excluded_tech_ids=frozenset(declines.get(j.id, set())),
            manual_tech_id=manual_overrides.get(j.id),
            zone_required=j.id not in customer_job_ids,
            skills_required=j.id not in customer_job_ids,
        ))
        a = j.active_assignment
        if a is not None:
            # Priors on deactivated electricians still count, so the change is reported as a reassignment.
            prior[j.id] = PriorAssignment(j.id, a.electrician_id, a.start, a.end)
        elif j.booking_events and j.booking_events[-1].action in {"disturbed", "cancel", "decline"}:
            # A disturbance releases the active row before recovery; retain its last slot
            # as the scheduler's prior so old -> replacement changes remain auditable.
            released = j.booking_events[-1]
            previous = next((row for row in reversed(j.assignments)
                             if row.electrician_id == released.old_electrician_id), None)
            if previous is not None:
                prior[j.id] = PriorAssignment(j.id, previous.electrician_id, previous.start, previous.end)

    problem = Problem(now=now, jobs=job_inputs, techs=techs, prior=prior)
    ctx = ProblemContext(
        jobs={j.id: j for j in jobs},
        electricians={e.id: e for e in load_electricians(db, active_only=False)},
        locked_assignments=locked,
    )
    return problem, ctx
