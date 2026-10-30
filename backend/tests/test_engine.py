"""Unit tests for the pure scheduling engine (no database)."""
from datetime import datetime, timedelta

import pytest

from app.scheduling import Anchor, Interval, JobInput, PriorAssignment, Problem, TechInput, solve
from tests.helpers import assert_valid

DAY = datetime(2026, 11, 2)  # a Monday
NOW = DAY.replace(hour=6)
CEN = (12.9716, 77.5946)


def at(h, m=0):
    return DAY.replace(hour=h, minute=m)


def job(id, *, skills=("residential_wiring",), zone="CEN", prio="medium", dur=60, ws=8, we=17, sla=None,
        loc=CEN, **kw):
    ws_dt = at(*ws) if isinstance(ws, tuple) else at(ws)
    we_dt = at(*we) if isinstance(we, tuple) else at(we)
    return JobInput(id=id, priority=prio, duration=dur, skills=frozenset(skills), zone=zone, lat=loc[0], lon=loc[1],
                    window_start=ws_dt, window_end=we_dt, sla_deadline=sla or we_dt + timedelta(hours=2),
                    label=f"J{id}", **kw)


def tech(id, *, skills=("residential_wiring",), zones=("CEN",), home=CEN, shift=(8, 16), unavailable=(), ot=0, anchor=None):
    return TechInput(id=id, name=f"T{id}", skills=frozenset(skills), zones=frozenset(zones), home_lat=home[0],
                     home_lon=home[1], shifts=[Interval(at(shift[0]), at(shift[1]))],
                     unavailable=[Interval(a, b) for a, b in unavailable], max_overtime=ot, anchor=anchor)


def codes(result, jid):
    u = next(u for u in result.unassigned if u.job_id == jid)
    return u.classification, [r["code"] for r in u.reasons]


def test_never_overlaps_and_accounts_for_travel():
    far = (13.00, 77.62)
    jobs = [job(i, loc=CEN if i % 2 else far, dur=60) for i in range(1, 7)]
    p = Problem(NOW, jobs, [tech(1)])
    r = solve(p)
    assert_valid(p, r)
    assert len(r.visits) == 6


def test_missing_skill_is_unassignable_with_reason():
    p = Problem(NOW, [job(1, skills=("high_voltage",))], [tech(1)])
    r = solve(p)
    assert r.visits == []
    assert codes(r, 1) == ("unassignable", ["MISSING_SKILLS"])


def test_zone_eligibility_enforced():
    p = Problem(NOW, [job(1, zone="OUT")], [tech(1)])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["NO_ZONE_ELIGIBLE"])


def test_window_outside_working_hours():
    p = Problem(NOW, [job(1, ws=18, we=21)], [tech(1, shift=(8, 16))])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["SHIFT_CONSTRAINTS"])


def test_overtime_allowance_is_used_but_penalised():
    p = Problem(NOW, [job(1, ws=15, we=18, dur=90)], [tech(1, shift=(8, 16), ot=60)])
    r = solve(p)
    assert len(r.visits) == 1 and r.visits[0].end == at(16, 30)
    assert r.breakdown["overtime_minutes"] == 30


def test_unavailable_electrician_is_skipped():
    p = Problem(NOW, [job(1, ws=9, we=12, dur=60)],
                [tech(1, unavailable=[(at(8), at(13))]), tech(2)])
    r = solve(p)
    assert_valid(p, r)
    assert r.visits[0].tech_id == 2


def test_only_unavailable_electrician_gives_unavailable_reason():
    p = Problem(NOW, [job(1, ws=9, we=12, dur=60)], [tech(1, unavailable=[(at(8), at(13))])])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["ELECTRICIAN_UNAVAILABLE"])


def test_travel_time_can_make_job_unreachable():
    remote = (13.21, 77.71)  # ~30 km from the electrician's base
    p = Problem(NOW, [job(1, ws=8, we=9, dur=50, loc=remote)], [tech(1, shift=(8, 16))])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["TRAVEL_TIME"])


def test_hard_sla_for_urgent_jobs():
    p = Problem(NOW, [job(1, prio="urgent", ws=8, we=12, dur=60, sla=at(8, 30))], [tech(1)])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["SLA_UNACHIEVABLE"])


def test_low_priority_may_run_late_with_penalty():
    p = Problem(NOW, [job(1, prio="low", ws=8, we=12, dur=60, sla=at(8, 30))], [tech(1)])
    r = solve(p)
    assert len(r.visits) == 1 and r.visits[0].late_minutes > 0
    assert r.breakdown["late_jobs"] == 1


def test_competing_high_priority_jobs_one_slot():
    jobs = [job(1, prio="high", ws=10, we=12, dur=90), job(2, prio="high", ws=10, we=12, dur=90)]
    p = Problem(NOW, jobs, [tech(1)])
    r = solve(p)
    assert_valid(p, r)
    assert len(r.visits) == 1
    assert codes(r, 2 if r.visits[0].job_id == 1 else 1) == ("currently_infeasible", ["NO_FEASIBLE_SLOT"])


def test_higher_priority_displaces_lower_priority():
    prior = {1: PriorAssignment(1, 1, at(10), at(11, 30))}
    jobs = [job(1, prio="low", ws=10, we=12, dur=90), job(2, prio="urgent", ws=10, we=12, dur=90)]
    p = Problem(NOW, jobs, [tech(1)], prior=prior)
    r = solve(p)
    assert [v.job_id for v in r.visits] == [2]
    assert "displacing" in r.notes[2]


def test_specialist_freed_for_job_only_they_can_do():
    # T1 is the only one with high_voltage. A routine job that T2 could also do must not block it.
    jobs = [job(1, prio="high", ws=8, we=11, dur=120), job(2, prio="medium", skills=("high_voltage",), ws=8, we=10, dur=120)]
    techs = [tech(1, skills=("residential_wiring", "high_voltage")), tech(2, home=(12.99, 77.60))]
    p = Problem(NOW, jobs, techs)
    r = solve(p)
    assert_valid(p, r)
    assert {v.job_id: v.tech_id for v in r.visits} == {1: 2, 2: 1}


def test_existing_assignments_are_preserved_when_still_feasible():
    jobs = [job(i, ws=8, we=16, dur=60) for i in (1, 2, 3)]
    techs = [tech(1), tech(2)]
    first = solve(Problem(NOW, jobs, techs))
    prior = {v.job_id: PriorAssignment(v.job_id, v.tech_id, v.start, v.end) for v in first.visits}
    again = solve(Problem(NOW, jobs, techs, prior=prior))
    assert {(v.job_id, v.tech_id, v.start) for v in again.visits} == {(v.job_id, v.tech_id, v.start) for v in first.visits}
    assert again.breakdown["change_cost"] == 0


def test_in_progress_anchor_blocks_time_and_sets_start_location():
    anchor = Anchor(free_at=at(10), lat=CEN[0], lon=CEN[1], label="in-progress job X", busy_from=at(8))
    p = Problem(NOW, [job(1, ws=8, we=16, dur=60)], [tech(1, anchor=anchor)])
    r = solve(p)
    assert r.visits[0].start >= at(10)
    assert r.visits[0].travel_from == "in-progress job X"


def test_now_is_respected():
    p = Problem(at(12), [job(1, ws=8, we=16, dur=60)], [tech(1)])
    r = solve(p)
    assert r.visits[0].start >= at(12)


def test_expired_window():
    p = Problem(at(16, 30), [job(1, ws=8, we=16, dur=60)], [tech(1, shift=(8, 18))])
    r = solve(p)
    assert codes(r, 1) == ("unassignable", ["WINDOW_EXPIRED"])


@pytest.mark.parametrize("reoptimize", [False, True])
def test_deterministic(reoptimize):
    jobs = [job(i, prio=["low", "medium", "high"][i % 3], ws=8 + i % 4, we=16, dur=45 + (i % 3) * 15,
                loc=(12.95 + 0.005 * i, 77.58 + 0.004 * i)) for i in range(1, 25)]
    techs = [tech(t, home=(12.95 + 0.01 * t, 77.60)) for t in range(1, 5)]
    a = solve(Problem(NOW, jobs, techs), reoptimize=reoptimize)
    b = solve(Problem(NOW, jobs, techs), reoptimize=reoptimize)
    assert [(v.job_id, v.tech_id, v.start) for v in a.visits] == [(v.job_id, v.tech_id, v.start) for v in b.visits]
    assert_valid(Problem(NOW, jobs, techs), a)


def test_optimiser_beats_first_fit_on_travel():
    # Two clusters, two electricians based next to each one. A naive first-available assignment sends
    # electrician 1 across town; the optimiser should keep each electrician in their own cluster.
    west, east = (12.975, 77.525), (12.975, 77.665)
    jobs = [job(i, loc=west if i <= 3 else east, dur=60) for i in range(1, 7)]
    techs = [tech(1, home=west), tech(2, home=east)]
    r = solve(Problem(NOW, jobs, techs))
    assert {v.job_id for v in r.visits if v.tech_id == 1} == {1, 2, 3}
    assert {v.job_id for v in r.visits if v.tech_id == 2} == {4, 5, 6}
