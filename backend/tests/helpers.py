"""Constraint checker shared by engine and end-to-end tests."""
from datetime import timedelta

from app.scheduling.routes import HARD_SLA_PRIORITIES
from app.scheduling.travel import travel_minutes
from app.scheduling.types import Problem, SolveResult


def assert_valid(problem: Problem, result: SolveResult) -> None:
    jobs = {j.id: j for j in problem.jobs}
    techs = {t.id: t for t in problem.techs}
    seen = set()
    by_tech: dict[int, list] = {}
    for v in result.visits:
        assert v.job_id not in seen, f"job {v.job_id} scheduled twice"
        seen.add(v.job_id)
        by_tech.setdefault(v.tech_id, []).append(v)
        j, t = jobs[v.job_id], techs[v.tech_id]
        assert j.skills <= t.skills, f"job {j.id}: {t.name} lacks skills"
        assert j.zone in t.zones, f"job {j.id}: {t.name} does not cover zone {j.zone}"
        assert v.end - v.start == timedelta(minutes=j.duration)
        assert j.window_start <= v.start and v.end <= j.window_end, f"job {j.id} outside its time window"
        assert v.start >= problem.now, f"job {j.id} scheduled in the past"
        hard_end_ok = any(s.start <= v.start and v.end <= s.end + timedelta(minutes=t.max_overtime) for s in t.shifts)
        assert hard_end_ok, f"job {j.id} outside {t.name}'s working hours"
        for u in t.unavailable:
            assert not (u.start < v.end and u.end > v.start), f"job {j.id} overlaps {t.name}'s unavailability"
        if j.priority in HARD_SLA_PRIORITIES:
            assert v.end <= j.sla_deadline, f"{j.priority} job {j.id} misses its hard SLA"
        if t.anchor is not None and t.anchor.free_at > v.start:
            # Only allowed when the visit is on a different day's shift than the anchor.
            assert v.start.date() != t.anchor.free_at.date(), f"job {j.id} overlaps in-progress work"

    for tid, visits in by_tech.items():
        visits.sort(key=lambda v: v.start)
        for a, b in zip(visits, visits[1:]):
            assert a.end <= b.start, f"overlap on electrician {tid}: jobs {a.job_id} and {b.job_id}"
            if a.start.date() == b.start.date():
                ja, jb = jobs[a.job_id], jobs[b.job_id]
                gap = (b.start - a.end).total_seconds() / 60
                assert gap >= travel_minutes(ja.lat, ja.lon, jb.lat, jb.lon), \
                    f"no travel time between jobs {a.job_id} and {b.job_id}"

    unassigned = {u.job_id for u in result.unassigned}
    assert seen | unassigned == set(jobs), "every job must be either scheduled or explained"
    assert not (seen & unassigned)
    for u in result.unassigned:
        assert u.reasons, f"unassigned job {u.job_id} has no reason"
        assert u.classification in {"currently_infeasible", "unassignable"}
