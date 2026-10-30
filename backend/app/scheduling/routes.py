"""Route evaluation: turns an ordered list of jobs on one electrician-shift into concrete times.

A *route* is identified by (electrician_id, shift_index). Evaluating a route walks the jobs in
order, adding travel time, waiting for time windows, skipping around unavailable periods, and
checking every hard constraint. Results are memoised because the optimiser evaluates the same
sequences many times.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.scheduling.travel import travel_minutes
from app.scheduling.types import Interval, JobInput, Problem, TechInput, Visit

RouteKey = tuple[int, int]

# For these priorities the SLA deadline is a hard constraint: we would rather report the job as
# unassignable (so a dispatcher escalates it) than silently plan it late. Lower priorities may be
# scheduled late with a per-minute penalty.
HARD_SLA_PRIORITIES = frozenset({"urgent", "high"})


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


@dataclass
class RouteEval:
    feasible: bool
    visits: list[Visit] = field(default_factory=list)
    cost: float = 0.0
    travel: int = 0
    late_minutes: int = 0
    late_jobs: int = 0
    late_cost: float = 0.0
    overtime: int = 0
    change_cost: float = 0.0
    reassigned: int = 0
    retimed: int = 0
    # Populated when infeasible.
    fail_job: int | None = None
    fail_code: str | None = None  # window | shift | sla | unavailable | closed
    fail_detail: str = ""
    fail_travel: int = 0
    fail_end: datetime | None = None
    fail_pushed_by_unavailable: bool = False


def fmt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %H:%M")


class Evaluator:
    def __init__(self, problem: Problem):
        self.problem = problem
        self.now = problem.now
        self.w = problem.weights
        self.jobs: dict[int, JobInput] = {j.id: j for j in problem.jobs}
        self.techs: dict[int, TechInput] = {t.id: t for t in problem.techs}
        self.prior = problem.prior
        self._cache: dict[tuple[RouteKey, tuple[int, ...]], RouteEval] = {}
        self.evaluations = 0

    def shift(self, key: RouteKey) -> Interval:
        return self.techs[key[0]].shifts[key[1]]

    def hard_end(self, key: RouteKey) -> datetime:
        tech = self.techs[key[0]]
        return tech.shifts[key[1]].end + timedelta(minutes=tech.max_overtime)

    def start_point(self, key: RouteKey) -> tuple[datetime, float, float, str]:
        """Earliest departure time and location for a route."""
        tech = self.techs[key[0]]
        shift = tech.shifts[key[1]]
        depart = max(shift.start, self.now)
        lat, lon, label = tech.home_lat, tech.home_lon, "home base"
        a = tech.anchor
        if a is not None:
            began = a.busy_from or a.free_at
            if a.free_at > shift.start and began < self.hard_end(key):
                depart = max(depart, a.free_at)
                lat, lon, label = a.lat, a.lon, a.label
        return depart, lat, lon, label

    def cost(self, key: RouteKey, seq: list[int] | tuple[int, ...]) -> float:
        return self.evaluate(key, seq).cost

    def evaluate(self, key: RouteKey, seq: list[int] | tuple[int, ...]) -> RouteEval:
        tseq = tuple(seq)
        cached = self._cache.get((key, tseq))
        if cached is not None:
            return cached
        result = self._evaluate(key, tseq)
        self._cache[(key, tseq)] = result
        return result

    def _evaluate(self, key: RouteKey, seq: tuple[int, ...]) -> RouteEval:
        self.evaluations += 1
        tech = self.techs[key[0]]
        shift = tech.shifts[key[1]]
        hard_end = self.hard_end(key)
        w = self.w
        res = RouteEval(feasible=True)
        if not seq:
            return res

        depart, lat, lon, label = self.start_point(key)
        last_end = depart
        for jid in seq:
            job = self.jobs[jid]
            travel = travel_minutes(lat, lon, job.lat, job.lon)
            pushed: Interval | None = None
            guard = 0
            while True:
                start = max(depart + timedelta(minutes=travel), job.window_start)
                end = start + timedelta(minutes=job.duration)
                travel_begins = start - timedelta(minutes=travel)
                blocker = next((u for u in tech.unavailable if u.overlaps(travel_begins, end)), None)
                if blocker is None:
                    break
                depart = max(depart, blocker.end)
                pushed = blocker
                guard += 1
                if guard > 50:  # pathological data; treat as unavailable
                    break

            fail = None
            if end > job.window_end:
                fail = ("window", f"would finish {fmt(end)}, after the window closes at {fmt(job.window_end)}")
            elif end > hard_end:
                fail = ("shift", f"would finish {fmt(end)}, after {tech.name}'s shift ends at {fmt(hard_end)}")
            elif end > job.sla_deadline and job.priority in HARD_SLA_PRIORITIES:
                fail = ("sla", f"earliest finish {fmt(end)} misses the SLA deadline {fmt(job.sla_deadline)}")
            if fail is not None and pushed is not None:
                fail = (fail[0], f"unavailable {fmt(pushed.start)} - {fmt(pushed.end)}, so the job {fail[1]}")
            if fail is not None:
                res.feasible = False
                res.cost = float("inf")
                res.fail_job = jid
                res.fail_code, res.fail_detail = fail
                res.fail_travel = travel
                res.fail_end = end
                res.fail_pushed_by_unavailable = pushed is not None
                return res

            late = max(0, minutes(end - job.sla_deadline))
            res.visits.append(Visit(jid, tech.id, start, end, travel, label, late))
            res.travel += travel
            if late:
                res.late_minutes += late
                res.late_jobs += 1
                res.late_cost += late * w.late_penalty(job.priority)

            prior = self.prior.get(jid)
            if prior is not None:
                if prior.tech_id != tech.id:
                    res.change_cost += w.reassign
                    res.reassigned += 1
                elif abs(minutes(start - prior.start)) > w.retime_tolerance_minutes:
                    res.change_cost += w.retime
                    res.retimed += 1

            depart = end
            last_end = end
            lat, lon, label = job.lat, job.lon, f"job {job.label or jid}"

        res.overtime = max(0, minutes(last_end - shift.end))
        res.cost = (
            res.travel * w.travel_per_minute
            + res.late_cost
            + res.overtime * w.overtime_per_minute
            + res.change_cost
        )
        return res
