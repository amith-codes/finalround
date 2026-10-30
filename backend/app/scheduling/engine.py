"""Scheduling + optimisation engine.

Algorithm (deterministic, see README "Scheduling algorithm"):

1. Eligibility filter - per job, the (electrician, shift) routes whose electrician meets the
   applicable skill and zone/locality rules and has a shift overlapping the job's time window.
   Customer bookings use service locality and do not require legacy skill or zone tags.
2. Keep pass (incremental mode) - previous assignments are re-validated in their original order
   on their original electrician. Still-feasible ones are kept, the rest become "displaced".
3. Construction - remaining jobs are inserted, most important first (priority, then fewest
   eligible routes, then earliest SLA), at the cheapest feasible position across all eligible
   routes (cheapest insertion).
4. Improvement - repeated rounds of (a) retrying unassigned jobs, (b) ejection: a higher
   priority unassigned job may displace a lower priority job which is then re-inserted
   elsewhere if possible, and (c) relocation of single jobs to a cheaper position. A move is
   applied only if it strictly lowers the global objective, so the loop terminates.
5. Reoptimise mode additionally builds a from-scratch schedule (no keep pass; change penalties
   still apply) and returns whichever of the two scores better.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.models.enums import PRIORITY_RANK
from app.scheduling.diagnosis import diagnose
from app.scheduling.locality import locality_key
from app.scheduling.routes import Evaluator, RouteKey, fmt
from app.scheduling.types import JobInput, Problem, SolveResult, TechInput, UnassignedJob, Visit

EPS = 1e-6
MAX_IMPROVEMENT_ROUNDS = 5
EJECTION_CANDIDATES = 12


@dataclass
class Solution:
    routes: dict[RouteKey, list[int]] = field(default_factory=dict)
    assigned: dict[int, RouteKey] = field(default_factory=dict)
    unassigned: set[int] = field(default_factory=set)
    notes: dict[int, str] = field(default_factory=dict)

    def copy(self) -> "Solution":
        return Solution(
            routes={k: list(v) for k, v in self.routes.items()},
            assigned=dict(self.assigned),
            unassigned=set(self.unassigned),
            notes=dict(self.notes),
        )

    def place(self, jid: int, key: RouteKey, seq: list[int]) -> None:
        self.routes[key] = seq
        self.assigned[jid] = key
        self.unassigned.discard(jid)


class Scheduler:
    def __init__(self, problem: Problem):
        self.p = problem
        self.ev = Evaluator(problem)
        self.jobs = self.ev.jobs
        self.eligible: dict[int, list[TechInput]] = {}
        self.keys: dict[int, list[RouteKey]] = {}
        for job in problem.jobs:
            techs = [t for t in problem.techs
                     if (not job.skills_required or job.skills <= t.skills)
                     and (not job.zone_required or job.zone in t.zones)]
            if job.manual_tech_id is not None:
                techs = [t for t in techs if t.id == job.manual_tech_id]
            else:
                techs = [t for t in techs if t.id not in job.excluded_tech_ids]
            if job.locality and job.manual_tech_id is None:
                key = locality_key(job.locality)
                techs = [t for t in techs if key and key in {locality_key(x) for x in t.localities}]
            techs.sort(key=lambda t: t.id)
            self.eligible[job.id] = techs
            self.keys[job.id] = [
                (t.id, i) for t in techs for i, s in enumerate(t.shifts) if self._shift_relevant(job, t, i)
            ]

    def _shift_relevant(self, job: JobInput, tech: TechInput, idx: int) -> bool:
        shift = tech.shifts[idx]
        hard_end = self.ev.hard_end((tech.id, idx))
        return shift.start < job.window_end and hard_end > job.window_start and hard_end > self.p.now

    # ------------------------------------------------------------------ helpers
    def rank(self, jid: int) -> int:
        return PRIORITY_RANK[self.jobs[jid].priority]

    def penalty(self, jid: int) -> float:
        return self.p.weights.unassigned_penalty(self.jobs[jid].priority)

    def order_key(self, jid: int):
        j = self.jobs[jid]
        return (-self.rank(jid), len(self.keys[jid]), j.sla_deadline, j.window_end, jid)

    def label(self, jid: int) -> str:
        return self.jobs[jid].label or f"#{jid}"

    def total(self, sol: Solution) -> float:
        routes = sum(self.ev.cost(k, s) for k, s in sol.routes.items() if s)
        return routes + sum(self.penalty(j) for j in sol.unassigned)

    def best_insertion(self, sol: Solution, jid: int) -> tuple[float, RouteKey, list[int]] | None:
        best = None
        for key in self.keys[jid]:
            seq = sol.routes.get(key, [])
            base = self.ev.cost(key, seq)
            for pos in range(len(seq) + 1):
                cand = seq[:pos] + [jid] + seq[pos:]
                e = self.ev.evaluate(key, cand)
                if not e.feasible:
                    continue
                delta = e.cost - base
                if best is None or delta < best[0] - EPS:
                    best = (delta, key, cand)
        return best

    # ------------------------------------------------------------- construction
    def keep_pass(self, sol: Solution) -> None:
        priors = sorted(self.p.prior.values(), key=lambda a: (a.tech_id, a.start, a.job_id))
        for pa in priors:
            jid = pa.job_id
            if jid not in self.jobs:
                continue
            tech = self.ev.techs.get(pa.tech_id)
            if tech is None or tech not in self.eligible[jid]:
                job = self.jobs[jid]
                if not job.skills_required and not job.zone_required:
                    sol.notes[jid] = (
                        f"Previous assignment was released; checking active electricians serving {job.locality}."
                    )
                else:
                    sol.notes[jid] = "Previous electrician is no longer eligible (inactive, skills or zone coverage changed)."
                sol.unassigned.add(jid)
                continue
            idx = next(
                (i for i, s in enumerate(tech.shifts) if s.start <= pa.start < self.ev.hard_end((tech.id, i))),
                None,
            )
            if idx is None:
                sol.notes[jid] = f"Previous slot {fmt(pa.start)} is no longer inside {tech.name}'s shifts."
                sol.unassigned.add(jid)
                continue
            key = (tech.id, idx)
            cand = sol.routes.get(key, []) + [jid]
            e = self.ev.evaluate(key, cand)
            if e.feasible:
                sol.place(jid, key, cand)
                sol.notes[jid] = "Kept: previous assignment is still feasible."
            else:
                why = e.fail_detail
                if e.fail_pushed_by_unavailable:
                    why = f"{tech.name} is unavailable; {why}"
                sol.notes[jid] = f"Previous slot with {tech.name} no longer feasible: {why}."
                sol.unassigned.add(jid)

    def construct(self, keep: bool) -> Solution:
        sol = Solution()
        if keep:
            self.keep_pass(sol)
        todo = [j.id for j in self.p.jobs if j.id not in sol.assigned]
        sol.unassigned.update(todo)
        for jid in sorted(todo, key=self.order_key):
            best = self.best_insertion(sol, jid)
            if best is not None:
                _, key, seq = best
                sol.place(jid, key, seq)
        return sol

    # -------------------------------------------------------------- improvement
    def try_ejection(self, sol: Solution, u: int) -> bool:
        """Make room for unassigned job u by moving one job v off a route.

        v is either re-inserted elsewhere or (if that is impossible) dropped; the global objective
        decides, so a higher-priority job is never dropped for a lower-priority one.
        """
        cands = []
        for key in self.keys[u]:
            seq = sol.routes.get(key, [])
            base = self.ev.cost(key, seq)
            for v in seq:
                reduced = [x for x in seq if x != v]
                best = None
                for pos in range(len(reduced) + 1):
                    cand = reduced[:pos] + [u] + reduced[pos:]
                    e = self.ev.evaluate(key, cand)
                    if e.feasible and (best is None or e.cost < best[0] - EPS):
                        best = (e.cost, cand)
                if best is not None:
                    cands.append((self.rank(v), best[0] - base, key, v, best[1]))
        if not cands:
            return False
        cands.sort(key=lambda c: (c[0], c[1], c[2], c[3]))

        chosen = None
        for _, route_delta, key, v, new_seq in cands[:EJECTION_CANDIDATES]:
            trial = sol.copy()
            trial.place(u, key, new_seq)
            del trial.assigned[v]
            trial.unassigned.add(v)
            reins = self.best_insertion(trial, v)
            delta = route_delta - self.penalty(u) + (reins[0] if reins else self.penalty(v))
            if delta < -EPS and (chosen is None or delta < chosen[0] - EPS):
                chosen = (delta, key, v, new_seq, reins)
        if chosen is None:
            return False

        _, key, v, new_seq, reins = chosen
        old_tech = self.ev.techs[key[0]].name
        sol.place(u, key, new_seq)
        del sol.assigned[v]
        sol.unassigned.add(v)
        if reins is not None:
            _, rkey, rseq = reins
            sol.place(v, rkey, rseq)
            sol.notes[u] = f"Placed with {old_tech} after moving job {self.label(v)} to another slot."
            sol.notes[v] = (
                f"Moved from {old_tech} to {self.ev.techs[rkey[0]].name} to make room for job {self.label(u)} "
                f"({self.jobs[u].priority} priority, few eligible electricians)."
            )
        else:
            sol.notes[u] = f"Placed with {old_tech} by displacing lower-priority job {self.label(v)}."
            sol.notes[v] = f"Displaced by higher-priority job {self.label(u)}; no other feasible slot."
        return True

    def try_relocate(self, sol: Solution, jid: int) -> bool:
        key = sol.assigned[jid]
        seq = sol.routes[key]
        reduced = [x for x in seq if x != jid]
        e_reduced = self.ev.evaluate(key, reduced)
        if not e_reduced.feasible:
            return False
        removal_delta = e_reduced.cost - self.ev.cost(key, seq)
        sol.routes[key] = reduced
        best = self.best_insertion(sol, jid)
        if best is not None and removal_delta + best[0] < -EPS:
            _, nkey, nseq = best
            sol.place(jid, nkey, nseq)
            gain = -(removal_delta + best[0])
            if nkey[0] != key[0]:
                sol.notes[jid] = (
                    f"Moved from {self.ev.techs[key[0]].name} to {self.ev.techs[nkey[0]].name}; "
                    f"lowers the objective by {gain:.0f}."
                )
            else:
                sol.notes[jid] = f"Re-sequenced on {self.ev.techs[key[0]].name}; lowers the objective by {gain:.0f}."
            return True
        sol.routes[key] = seq
        return False

    def improve(self, sol: Solution) -> int:
        rounds = 0
        for _ in range(MAX_IMPROVEMENT_ROUNDS):
            rounds += 1
            improved = False
            for jid in sorted(sol.unassigned, key=self.order_key):
                best = self.best_insertion(sol, jid)
                if best is not None:
                    sol.place(jid, best[1], best[2])
                    improved = True
            for jid in sorted(sol.unassigned, key=self.order_key):
                if jid in sol.unassigned and self.try_ejection(sol, jid):
                    improved = True
            for jid in sorted(sol.assigned):
                if self.try_relocate(sol, jid):
                    improved = True
            if not improved:
                break
        return rounds

    # --------------------------------------------------------------------- solve
    def solve(self, reoptimize: bool = False) -> SolveResult:
        t0 = time.perf_counter()
        stable = self.construct(keep=True)
        rounds = self.improve(stable)
        candidates = {"incremental": (self.total(stable), stable)}
        if reoptimize:
            fresh = self.construct(keep=False)
            self.improve(fresh)
            candidates["from_scratch"] = (self.total(fresh), fresh)
        chosen_name = min(candidates, key=lambda n: (candidates[n][0], n != "incremental"))
        sol = candidates[chosen_name][1]
        result = self._result(sol)
        result.stats = {
            "strategy": chosen_name,
            "candidate_objectives": {n: round(c[0], 2) for n, c in candidates.items()},
            "improvement_rounds": rounds,
            "route_evaluations": self.ev.evaluations,
            "runtime_ms": round((time.perf_counter() - t0) * 1000, 1),
            "jobs": len(self.p.jobs),
            "electricians": len(self.p.techs),
        }
        return result

    def _result(self, sol: Solution) -> SolveResult:
        w = self.p.weights
        visits: list[Visit] = []
        bd = {
            "travel_minutes": 0, "late_minutes": 0, "late_jobs": 0, "overtime_minutes": 0,
            "reassigned": 0, "retimed": 0,
            "travel_cost": 0.0, "late_cost": 0.0, "overtime_cost": 0.0, "change_cost": 0.0,
        }
        for key in sorted(sol.routes):
            seq = sol.routes[key]
            if not seq:
                continue
            e = self.ev.evaluate(key, seq)
            visits.extend(e.visits)
            bd["travel_minutes"] += e.travel
            bd["late_minutes"] += e.late_minutes
            bd["late_jobs"] += e.late_jobs
            bd["overtime_minutes"] += e.overtime
            bd["reassigned"] += e.reassigned
            bd["retimed"] += e.retimed
            bd["late_cost"] += e.late_cost
            bd["change_cost"] += e.change_cost
        bd["travel_cost"] = bd["travel_minutes"] * w.travel_per_minute
        bd["overtime_cost"] = bd["overtime_minutes"] * w.overtime_per_minute
        unassigned_by_priority: dict[str, int] = {}
        for jid in sol.unassigned:
            p = self.jobs[jid].priority
            unassigned_by_priority[p] = unassigned_by_priority.get(p, 0) + 1
        bd["unassigned_by_priority"] = unassigned_by_priority
        bd["unassigned_cost"] = sum(self.penalty(j) for j in sol.unassigned)
        total = bd["travel_cost"] + bd["late_cost"] + bd["overtime_cost"] + bd["change_cost"] + bd["unassigned_cost"]
        bd = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in bd.items()}
        bd["total"] = round(total, 2)

        explanations = {v.job_id: self._explain(v) + " " + sol.notes.get(v.job_id, "") for v in visits}
        explanations = {k: s.strip() for k, s in explanations.items()}
        unassigned = []
        for jid in sorted(sol.unassigned, key=self.order_key):
            classification, reasons = diagnose(self, sol, jid)
            if jid in sol.notes:
                reasons.append({"code": "HISTORY", "message": sol.notes[jid], "suggestion": None})
            unassigned.append(UnassignedJob(jid, classification, reasons))
        return SolveResult(visits, unassigned, round(total, 2), bd, explanations, dict(sol.notes), {})

    def _explain(self, v: Visit) -> str:
        job = self.jobs[v.job_id]
        tech = self.ev.techs[v.tech_id]
        n = len(self.eligible[v.job_id])
        skills = ", ".join(sorted(job.skills)) or "none"
        parts = [
            f"{tech.name} {fmt(v.start)}-{v.end:%H:%M}:",
            (f"has required skills ({skills}) and covers zone {job.zone};"
             if job.skills_required and job.zone_required else
             f"has required skills ({skills}) and serves {job.locality};"
             if job.skills_required else f"serves {job.locality} without legacy skill or zone tags;"),
            f"{v.travel_minutes} min travel from {v.travel_from};",
            f"best-cost choice among {n} eligible electrician{'s' if n != 1 else ''}.",
        ]
        if v.late_minutes:
            parts.append(f"Finishes {v.late_minutes} min after SLA deadline (no on-time slot available).")
        return " ".join(parts)


def solve(problem: Problem, reoptimize: bool = False) -> SolveResult:
    return Scheduler(problem).solve(reoptimize=reoptimize)
