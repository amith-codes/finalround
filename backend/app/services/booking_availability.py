"""Prevent customer requests from overlapping an electrician's existing bookings."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, Electrician, Job
from app.models.enums import JobStatus


def available_slot(
    db: Session,
    electrician: Electrician,
    *,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    ignore_job_id: int | None = None,
) -> tuple[datetime, datetime] | None:
    """Find a free time inside the requested window.

    Direct customer requests are not filtered by an electrician's skills, service
    area, shift or availability toggle. An overlapping assigned/in-progress job
    remains the one reason to offer another electrician.
    """
    if not electrician.active:
        return None
    duration = timedelta(minutes=duration_minutes)
    start = max(window_start, datetime.now().replace(second=0, microsecond=0))
    latest_start = window_end - duration
    if start > latest_start:
        return None

    conflicts_query = select(Assignment.start, Assignment.end).join(Job).where(
        Assignment.is_active.is_(True),
        Assignment.electrician_id == electrician.id,
        Job.status.in_([JobStatus.ASSIGNED.value, JobStatus.IN_PROGRESS.value]),
        Assignment.start < window_end,
        Assignment.end > start,
    ).order_by(Assignment.start)
    if ignore_job_id is not None:
        conflicts_query = conflicts_query.where(Assignment.job_id != ignore_job_id)

    for conflict_start, conflict_end in db.execute(conflicts_query):
        end = start + duration
        if end <= conflict_start:
            break
        if start < conflict_end and end > conflict_start:
            start = conflict_end
            if start > latest_start:
                return None
    return (start, start + duration) if start <= latest_start else None
