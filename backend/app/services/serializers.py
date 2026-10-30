"""ORM -> JSON-ready dict conversion, plus derived fields (SLA state, electrician status)."""
from datetime import datetime, timedelta

from app.models import Assignment, Electrician, Job, ScheduleChange, SchedulingRun
from app.models.enums import JobStatus

SLA_AT_RISK_MINUTES = 60
UNSCHEDULED_RISK_HOURS = 4


def expected_end(job: Job) -> datetime | None:
    if job.status == JobStatus.IN_PROGRESS.value and job.actual_start:
        return job.actual_start + timedelta(minutes=job.duration_minutes)
    a = job.active_assignment
    if a is not None and job.status == JobStatus.ASSIGNED.value:
        return a.end
    return None


def sla_state(job: Job, now: datetime) -> str | None:
    """met | breached | overdue | late | at_risk | on_track | unscheduled | None (cancelled)."""
    if job.status == JobStatus.CANCELLED.value:
        return None
    if job.status == JobStatus.COMPLETED.value:
        return "met" if job.actual_end and job.actual_end <= job.sla_deadline else "breached"
    if job.sla_deadline < now:
        return "overdue"
    end = expected_end(job)
    if end is None:
        if job.sla_deadline - now < timedelta(hours=UNSCHEDULED_RISK_HOURS):
            return "at_risk"
        return "unscheduled"
    if end > job.sla_deadline:
        return "late"
    if job.sla_deadline - end < timedelta(minutes=SLA_AT_RISK_MINUTES):
        return "at_risk"
    return "on_track"


def assignment_dict(a: Assignment | None) -> dict | None:
    if a is None:
        return None
    return {
        "id": a.id,
        "electrician_id": a.electrician_id,
        "electrician_name": a.electrician.name if a.electrician else None,
        "run_id": a.run_id,
        "start": a.start,
        "end": a.end,
        "travel_minutes": a.travel_minutes,
        "travel_from": a.travel_from,
        "late_minutes": a.late_minutes,
        "explanation": a.explanation,
        "is_active": a.is_active,
    }


def job_dict(job: Job, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    latest_event = job.booking_events[-1] if job.booking_events else None
    return {
        "id": job.id,
        "job_number": job.job_number,
        "title": job.title,
        "description": job.description,
        "customer_name": job.customer_name,
        "address": job.address,
        "lat": job.lat,
        "lon": job.lon,
        "zone_code": job.zone.code if job.zone else None,
        "zone_name": job.zone.name if job.zone else None,
        "service_locality": job.booking_details.locality if job.booking_details else None,
        "district": job.booking_details.district if job.booking_details else None,
        "state": job.booking_details.state if job.booking_details else None,
        "service_category": job.booking_details.service_category if job.booking_details else None,
        "customer_phone": job.booking_details.customer_phone if job.booking_details else None,
        "booking_amount": job.booking_details.amount if job.booking_details else 0,
        "payment_status": job.booking_details.payment_status if job.booking_details else "pending",
        "booking_action": latest_event.action if latest_event else None,
        "booking_update_reason": latest_event.reason if latest_event else None,
        "priority": job.priority,
        "duration_minutes": job.duration_minutes,
        "required_skills": [s.code for s in job.required_skills],
        "window_start": job.window_start,
        "window_end": job.window_end,
        "sla_deadline": job.sla_deadline,
        "status": job.status,
        "feasibility": job.feasibility,
        "unassigned_reasons": job.unassigned_reasons,
        "actual_start": job.actual_start,
        "actual_end": job.actual_end,
        "cancel_reason": job.cancel_reason,
        "sla_state": sla_state(job, now),
        "assignment": assignment_dict(job.active_assignment),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def electrician_status(e: Electrician, now: datetime, in_progress_job_ids: set[int] | None = None) -> str:
    """on_job | unavailable | on_shift | off_shift | inactive."""
    if not e.active:
        return "inactive"
    if in_progress_job_ids:
        return "on_job"
    if any(p.start <= now < p.end for p in e.unavailable_periods):
        return "unavailable"
    t = now.time()
    if any(s.day_of_week == now.weekday() and s.start_time <= t < s.end_time for s in e.shifts):
        return "on_shift"
    return "off_shift"


def electrician_dict(e: Electrician, now: datetime | None = None, in_progress_job_ids: set[int] | None = None) -> dict:
    now = now or datetime.now()
    return {
        "id": e.id,
        "employee_code": e.employee_code,
        "name": e.name,
        "phone": e.phone,
        "email": e.email,
        "home_lat": e.home_lat,
        "home_lon": e.home_lon,
        "max_overtime_minutes": e.max_overtime_minutes,
        "active": e.active,
        "skills": [s.code for s in e.skills],
        "zones": [z.code for z in e.zones],
        "localities": [x.locality for x in e.service_localities],
        "shifts": [
            {"id": s.id, "day_of_week": s.day_of_week, "start_time": s.start_time.strftime("%H:%M"),
             "end_time": s.end_time.strftime("%H:%M")}
            for s in e.shifts
        ],
        "unavailable_periods": [
            {"id": p.id, "start": p.start, "end": p.end, "reason": p.reason}
            for p in e.unavailable_periods if p.end > now - timedelta(days=1)
        ],
        "current_status": electrician_status(e, now, in_progress_job_ids),
        "in_progress_job_ids": sorted(in_progress_job_ids or []),
    }


def change_dict(c: ScheduleChange, names: dict[int, str], jobs: dict[int, Job] | None = None) -> dict:
    job = jobs.get(c.job_id) if jobs else None
    return {
        "id": c.id,
        "job_id": c.job_id,
        "job_number": job.job_number if job else None,
        "job_title": job.title if job else None,
        "priority": job.priority if job else None,
        "change_type": c.change_type,
        "old_electrician_id": c.old_electrician_id,
        "old_electrician_name": names.get(c.old_electrician_id),
        "new_electrician_id": c.new_electrician_id,
        "new_electrician_name": names.get(c.new_electrician_id),
        "old_start": c.old_start,
        "new_start": c.new_start,
        "old_end": c.old_end,
        "new_end": c.new_end,
        "reason": c.reason,
    }


def run_summary(run: SchedulingRun) -> dict:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "mode": run.mode,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "as_of": run.as_of,
        "previous_run_id": run.previous_run_id,
        "objective_score": run.objective_score,
        "metrics": run.metrics,
        "disruption": run.disruption,
        "error": run.error,
    }


def run_detail(run: SchedulingRun, names: dict[int, str], jobs: dict[int, Job] | None = None) -> dict:
    d = run_summary(run)
    d.update({
        "jobs_considered": run.jobs_considered,
        "jobs_assigned": run.jobs_assigned,
        "unassigned": run.unassigned,
        "objective_breakdown": run.objective_breakdown,
        "algorithm_stats": run.algorithm_stats,
        "before_snapshot": run.before_snapshot,
        "after_snapshot": run.after_snapshot,
        "changes": [change_dict(c, names, jobs) for c in run.changes],
    })
    return d
