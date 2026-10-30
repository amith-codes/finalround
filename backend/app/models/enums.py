"""Domain vocabularies shared by models, schemas and the scheduling engine."""
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNASSIGNED = "unassigned"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


PRIORITY_RANK = {Priority.LOW.value: 1, Priority.MEDIUM.value: 2, Priority.HIGH.value: 3, Priority.URGENT.value: 4}

# Statuses the scheduler is allowed to (re)plan.
SCHEDULABLE_STATUSES = {JobStatus.PENDING.value, JobStatus.UNASSIGNED.value, JobStatus.ASSIGNED.value}
TERMINAL_STATUSES = {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RunMode(str, Enum):
    # Keep every still-feasible assignment, then place the rest.
    INCREMENTAL = "incremental"
    # Additionally build a from-scratch schedule and keep whichever scores better.
    REOPTIMIZE = "reoptimize"


class ChangeType(str, Enum):
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    REASSIGNED = "reassigned"
    RETIMED = "retimed"
    REMOVED = "removed"  # job left the schedule because it was cancelled/completed
