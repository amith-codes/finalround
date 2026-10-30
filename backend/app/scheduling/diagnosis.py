"""Explains why a job could not be scheduled.

Classification:
  * "unassignable"         - structurally impossible even with every calendar empty
                             (skills, zone, shifts, unavailability, SLA, travel, expired window).
  * "currently_infeasible" - an eligible electrician could do it on an empty calendar, but the
                             capacity is taken by work of equal or higher value.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from app.scheduling.routes import fmt, minutes
from app.scheduling.travel import haversine_km

if TYPE_CHECKING:
    from app.scheduling.engine import Scheduler, Solution

PRECEDENCE = [
    "WINDOW_TOO_SHORT",
    "WINDOW_EXPIRED",
    "MISSING_SKILLS",
    "NO_ZONE_ELIGIBLE",
    "SHIFT_CONSTRAINTS",
    "ELECTRICIAN_UNAVAILABLE",
    "SLA_UNACHIEVABLE",
    "TRAVEL_TIME",
    "NO_FEASIBLE_SLOT",
]


def _reason(code: str, message: str, suggestion: str | None, **details) -> dict:
    return {"code": code, "message": message, "suggestion": suggestion, "details": details or None}


def diagnose(s: "Scheduler", sol: "Solution", jid: int) -> tuple[str, list[dict]]:
    job = s.jobs[jid]
    now = s.p.now
    window_minutes = minutes(job.window_end - job.window_start)

    if job.duration > window_minutes:
        return "unassignable", [_reason(
            "WINDOW_TOO_SHORT",
            f"Job needs {job.duration} min but its time window is only {window_minutes} min.",
            "Widen the time window or correct the duration estimate.",
        )]
    latest_start = job.window_end - timedelta(minutes=job.duration)
    if latest_start < now:
        return "unassignable", [_reason(
            "WINDOW_EXPIRED",
            f"The time window closes {fmt(job.window_end)}; there is no longer time to complete the job.",
            "Agree a new time window with the customer.",
        )]

    techs = s.p.techs
    skilled = [t for t in techs if job.skills <= t.skills]
    if not skilled:
        best = max(techs, key=lambda t: (len(job.skills & t.skills), -t.id), default=None)
        missing = sorted(job.skills - best.skills) if best else sorted(job.skills)
        held = set().union(*(t.skills for t in techs)) if techs else set()
        nobody = sorted(job.skills - held)
        msg = f"No electrician holds every required skill ({', '.join(sorted(job.skills))})."
        if nobody:
            msg += f" Nobody holds: {', '.join(nobody)}."
        elif best:
            msg += f" Closest match {best.name} lacks: {', '.join(missing)}."
        return "unassignable", [_reason(
            "MISSING_SKILLS", msg,
            "Certify an electrician in the missing skill(s) or split the job into single-skill visits.",
            missing_skills=nobody or missing,
        )]

    zoned = [t for t in skilled if job.zone in t.zones]
    if not zoned:
        nearest = min(skilled, key=lambda t: (haversine_km(t.home_lat, t.home_lon, job.lat, job.lon), t.id))
        return "unassignable", [_reason(
            "NO_ZONE_ELIGIBLE",
            f"{len(skilled)} electrician(s) have the skills but none covers zone {job.zone}.",
            f"Add zone {job.zone} to a qualified electrician (nearest: {nearest.name}).",
            skilled_electricians=[t.id for t in skilled],
        )]

    if job.locality and job.manual_tech_id is None and not any(
        job.locality.strip().casefold() in {value.strip().casefold() for value in t.localities}
        for t in zoned
    ):
        return "unassignable", [_reason(
            "LOCALITY_COVERAGE",
            f"No qualified electrician is registered to serve {job.locality} in zone {job.zone}.",
            "Add this locality to a qualified electrician or assign the booking manually.",
            locality=job.locality,
        )]

    keys = s.keys[jid]
    if not keys:
        return "unassignable", [_reason(
            "SHIFT_CONSTRAINTS",
            f"None of the {len(zoned)} eligible electricians has a shift overlapping the window "
            f"{fmt(job.window_start)}-{job.window_end:%H:%M}.",
            "Move the time window into working hours or add a shift.",
        )]

    found: dict[str, dict] = {}
    capacity = False
    for key in keys:
        e = s.ev.evaluate(key, [jid])
        if e.feasible:
            capacity = True
            continue
        tech = s.ev.techs[key[0]]
        code = _classify_failure(e, job)
        if code not in found:
            found[code] = {"count": 0, "example": f"{tech.name}: {e.fail_detail}", "techs": []}
        found[code]["count"] += 1
        found[code]["techs"].append(tech.id)

    if capacity:
        blockers = set()
        for key in keys:
            for other in sol.routes.get(key, []):
                v = next((x for x in s.ev.evaluate(key, sol.routes[key]).visits if x.job_id == other), None)
                if v and v.start < job.window_end and v.end > job.window_start:
                    blockers.add(other)
        blocker_labels = [s.label(b) for b in sorted(blockers, key=s.order_key)[:5]]
        return "currently_infeasible", [_reason(
            "NO_FEASIBLE_SLOT",
            f"All {len(zoned)} eligible electrician(s) are fully booked during the window "
            f"{fmt(job.window_start)}-{job.window_end:%H:%M}"
            + (f" (occupied by {', '.join(blocker_labels)})." if blocker_labels else "."),
            "Widen the time window, allow overtime, raise the priority, or add capacity in this zone.",
            blocking_jobs=sorted(blockers),
        )]

    reasons = []
    for code in PRECEDENCE:
        if code in found:
            f = found[code]
            reasons.append(_reason(code, _MESSAGES[code](f["count"], f["example"]), _SUGGESTIONS[code],
                                   electricians=f["techs"]))
    return "unassignable", reasons


def _classify_failure(e, job) -> str:
    if e.fail_pushed_by_unavailable:
        return "ELECTRICIAN_UNAVAILABLE"
    if e.fail_code == "sla":
        return "SLA_UNACHIEVABLE"
    if e.fail_code == "window" and e.fail_travel > 0 and e.fail_end is not None:
        if e.fail_end - timedelta(minutes=e.fail_travel) <= job.window_end:
            return "TRAVEL_TIME"
    return "SHIFT_CONSTRAINTS"


_MESSAGES = {
    "SHIFT_CONSTRAINTS": lambda n, ex: f"Shift hours prevent completing the job inside its window ({n} electrician-shift(s); e.g. {ex}).",
    "ELECTRICIAN_UNAVAILABLE": lambda n, ex: f"Eligible electricians are unavailable during the window ({n} electrician-shift(s); e.g. {ex}).",
    "SLA_UNACHIEVABLE": lambda n, ex: f"The SLA deadline cannot be achieved by any eligible electrician (e.g. {ex}).",
    "TRAVEL_TIME": lambda n, ex: f"Eligible electricians cannot reach the site in time ({n} electrician-shift(s); e.g. {ex}).",
}

_SUGGESTIONS = {
    "SHIFT_CONSTRAINTS": "Move the window into working hours or allow overtime for an eligible electrician.",
    "ELECTRICIAN_UNAVAILABLE": "Reschedule the job or assign zone coverage to another qualified electrician.",
    "SLA_UNACHIEVABLE": "Escalate: renegotiate the SLA with the customer or dispatch an on-call electrician.",
    "TRAVEL_TIME": "Widen the window, or give zone coverage to an electrician based closer to the site.",
}
