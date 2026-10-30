"""Plain data structures the scheduling engine works on.

The engine is deliberately independent of SQLAlchemy: `services.problem_builder` converts
database rows into these objects, and the engine returns a `SolveResult` that the service
layer persists. This keeps the algorithm unit-testable with hand-built fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and self.end > start


@dataclass(frozen=True)
class JobInput:
    id: int
    priority: str  # low | medium | high | urgent
    duration: int  # minutes
    skills: frozenset[str]
    zone: str
    lat: float
    lon: float
    window_start: datetime
    window_end: datetime
    sla_deadline: datetime
    label: str = ""
    locality: str | None = None
    excluded_tech_ids: frozenset[int] = field(default_factory=frozenset)
    manual_tech_id: int | None = None


@dataclass(frozen=True)
class Anchor:
    """Where/when an electrician becomes free because of work already started or finished."""

    free_at: datetime
    lat: float
    lon: float
    label: str
    busy_from: datetime | None = None  # start of the in-progress job (None for a completed job)


@dataclass
class TechInput:
    id: int
    name: str
    skills: frozenset[str]
    zones: frozenset[str]
    home_lat: float
    home_lon: float
    shifts: list[Interval]  # concrete shift instances inside the planning horizon
    unavailable: list[Interval] = field(default_factory=list)
    max_overtime: int = 0
    anchor: Anchor | None = None
    localities: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PriorAssignment:
    job_id: int
    tech_id: int
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Weights:
    """Objective weights (lower objective is better). See README "Objective function"."""

    unassigned: tuple[tuple[str, float], ...] = (("urgent", 10000.0), ("high", 3000.0), ("medium", 800.0), ("low", 200.0))
    late_per_minute: tuple[tuple[str, float], ...] = (("urgent", 50.0), ("high", 20.0), ("medium", 5.0), ("low", 2.0))
    travel_per_minute: float = 1.0
    overtime_per_minute: float = 3.0
    reassign: float = 60.0
    retime: float = 15.0
    retime_tolerance_minutes: int = 15

    def unassigned_penalty(self, priority: str) -> float:
        return dict(self.unassigned)[priority]

    def late_penalty(self, priority: str) -> float:
        return dict(self.late_per_minute)[priority]


@dataclass
class Problem:
    now: datetime
    jobs: list[JobInput]
    techs: list[TechInput]
    prior: dict[int, PriorAssignment] = field(default_factory=dict)
    weights: Weights = field(default_factory=Weights)


@dataclass(frozen=True)
class Visit:
    job_id: int
    tech_id: int
    start: datetime
    end: datetime
    travel_minutes: int
    travel_from: str
    late_minutes: int


@dataclass
class UnassignedJob:
    job_id: int
    classification: str  # "currently_infeasible" | "unassignable"
    reasons: list[dict]


@dataclass
class SolveResult:
    visits: list[Visit]
    unassigned: list[UnassignedJob]
    objective: float
    breakdown: dict
    explanations: dict[int, str]
    notes: dict[int, str]
    stats: dict
