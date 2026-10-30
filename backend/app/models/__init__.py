"""ORM models. Importing this package registers every table on Base.metadata."""
from datetime import datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import JobStatus, RunStatus


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


electrician_skills = Table(
    "electrician_skills",
    Base.metadata,
    Column("electrician_id", ForeignKey("electricians.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)

electrician_zones = Table(
    "electrician_zones",
    Base.metadata,
    Column("electrician_id", ForeignKey("electricians.id", ondelete="CASCADE"), primary_key=True),
    Column("zone_id", ForeignKey("service_zones.id", ondelete="CASCADE"), primary_key=True),
)

job_skills = Table(
    "job_skills",
    Base.metadata,
    Column("job_id", ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)


class ServiceZone(Base):
    __tablename__ = "service_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)


class Electrician(Base):
    __tablename__ = "electricians"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))
    home_lat: Mapped[float] = mapped_column(Float)
    home_lon: Mapped[float] = mapped_column(Float)
    max_overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    skills: Mapped[list[Skill]] = relationship(secondary=electrician_skills, order_by="Skill.code")
    zones: Mapped[list[ServiceZone]] = relationship(secondary=electrician_zones, order_by="ServiceZone.code")
    shifts: Mapped[list["Shift"]] = relationship(
        back_populates="electrician", cascade="all, delete-orphan", order_by="(Shift.day_of_week, Shift.start_time)"
    )
    unavailable_periods: Mapped[list["UnavailablePeriod"]] = relationship(
        back_populates="electrician", cascade="all, delete-orphan", order_by="UnavailablePeriod.start"
    )
    service_localities: Mapped[list["ElectricianLocality"]] = relationship(
        back_populates="electrician", cascade="all, delete-orphan", order_by="ElectricianLocality.locality"
    )

    __table_args__ = (CheckConstraint("max_overtime_minutes >= 0", name="ck_overtime_nonneg"),)


class Shift(Base):
    """Recurring weekly working hours. day_of_week follows Python: Monday=0 .. Sunday=6."""

    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    electrician: Mapped[Electrician] = relationship(back_populates="shifts")

    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_shift_dow"),
        CheckConstraint("start_time < end_time", name="ck_shift_order"),
    )


class UnavailablePeriod(Base):
    __tablename__ = "unavailable_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    electrician: Mapped[Electrician] = relationship(back_populates="unavailable_periods")

    __table_args__ = (CheckConstraint("start < \"end\"", name="ck_unavailable_order"),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_number: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    customer_name: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(250))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    zone_id: Mapped[int] = mapped_column(ForeignKey("service_zones.id"), index=True)
    priority: Mapped[str] = mapped_column(String(10), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    sla_deadline: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value, index=True)
    # Latest scheduler verdict: "feasible" | "currently_infeasible" | "unassignable" | None (not yet scheduled).
    feasibility: Mapped[str | None] = mapped_column(String(30))
    unassigned_reasons: Mapped[list | None] = mapped_column(JSON)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    zone: Mapped[ServiceZone] = relationship()
    required_skills: Mapped[list[Skill]] = relationship(secondary=job_skills, order_by="Skill.code")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="job", order_by="Assignment.id")
    booking_details: Mapped["BookingDetails | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    booking_events: Mapped[list["BookingEvent"]] = relationship(back_populates="job", order_by="BookingEvent.id")

    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_job_duration"),
        CheckConstraint("window_start < window_end", name="ck_job_window"),
    )

    @property
    def active_assignment(self) -> "Assignment | None":
        for a in self.assignments:
            if a.is_active:
                return a
        return None


class SchedulingRun(Base):
    __tablename__ = "scheduling_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    previous_run_id: Mapped[str | None] = mapped_column(ForeignKey("scheduling_runs.id"))
    disruption: Mapped[dict | None] = mapped_column(JSON)
    jobs_considered: Mapped[list | None] = mapped_column(JSON)
    jobs_assigned: Mapped[list | None] = mapped_column(JSON)
    unassigned: Mapped[list | None] = mapped_column(JSON)
    before_snapshot: Mapped[list | None] = mapped_column(JSON)
    after_snapshot: Mapped[list | None] = mapped_column(JSON)
    objective_score: Mapped[float | None] = mapped_column(Float)
    objective_breakdown: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    algorithm_stats: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    changes: Mapped[list["ScheduleChange"]] = relationship(back_populates="run", order_by="ScheduleChange.id")


class Assignment(Base):
    """A job placed on an electrician's timeline. Exactly one active row per scheduled job."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("scheduling_runs.id"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    travel_minutes: Mapped[int] = mapped_column(Integer, default=0)
    travel_from: Mapped[str | None] = mapped_column(String(80))
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped[Job] = relationship(back_populates="assignments")
    electrician: Mapped[Electrician] = relationship()

    __table_args__ = (
        CheckConstraint("start < \"end\"", name="ck_assignment_order"),
        Index("ix_assignment_active", "is_active", "electrician_id"),
    )


class ScheduleChange(Base):
    __tablename__ = "schedule_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scheduling_runs.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    change_type: Mapped[str] = mapped_column(String(20))
    old_electrician_id: Mapped[int | None] = mapped_column(ForeignKey("electricians.id"))
    new_electrician_id: Mapped[int | None] = mapped_column(ForeignKey("electricians.id"))
    old_start: Mapped[datetime | None] = mapped_column(DateTime)
    new_start: Mapped[datetime | None] = mapped_column(DateTime)
    old_end: Mapped[datetime | None] = mapped_column(DateTime)
    new_end: Mapped[datetime | None] = mapped_column(DateTime)
    reason: Mapped[str | None] = mapped_column(Text)

    run: Mapped[SchedulingRun] = relationship(back_populates="changes")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (UniqueConstraint("key", "endpoint", name="uq_idempotency_key_endpoint"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="dispatcher")


class UserProfile(Base):
    """Role-specific identity link; roles are assigned by a trusted administrator."""

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    electrician_id: Mapped[int | None] = mapped_column(ForeignKey("electricians.id", ondelete="SET NULL"), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))


class BookingOwner(Base):
    __tablename__ = "booking_owners"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class BookingDetails(Base):
    __tablename__ = "booking_details"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    locality: Mapped[str | None] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    service_category: Mapped[str | None] = mapped_column(String(80))
    customer_phone: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Float, default=0)
    payment_status: Mapped[str] = mapped_column(String(20), default="pending")

    job: Mapped[Job] = relationship(back_populates="booking_details")


class ElectricianLocality(Base):
    __tablename__ = "electrician_localities"

    id: Mapped[int] = mapped_column(primary_key=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), index=True)
    locality: Mapped[str] = mapped_column(String(120), index=True)
    electrician: Mapped[Electrician] = relationship(back_populates="service_localities")
    __table_args__ = (UniqueConstraint("electrician_id", "locality", name="uq_electrician_locality"),)


class BookingEvent(Base):
    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    old_electrician_id: Mapped[int | None] = mapped_column(ForeignKey("electricians.id"))
    new_electrician_id: Mapped[int | None] = mapped_column(ForeignKey("electricians.id"))
    reason: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    job: Mapped[Job] = relationship(back_populates="booking_events")


class BookingDecline(Base):
    __tablename__ = "booking_declines"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (UniqueConstraint("job_id", "electrician_id", name="uq_booking_decline"),)


class ManualDispatchOverride(Base):
    """Admin choice that lets one manually selected, otherwise-qualified technician bypass locality matching."""

    __tablename__ = "manual_dispatch_overrides"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id"), index=True)
    reason: Mapped[str] = mapped_column(String(250))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    brand: Mapped[str] = mapped_column(String(30))
    last4: Mapped[str] = mapped_column(String(4))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DutySession(Base):
    __tablename__ = "duty_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class AvailabilityOverride(Base):
    __tablename__ = "availability_overrides"

    electrician_id: Mapped[int] = mapped_column(ForeignKey("electricians.id", ondelete="CASCADE"), primary_key=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)


__all__ = [
    "AvailabilityOverride",
    "Assignment",
    "BookingDetails",
    "BookingDecline",
    "BookingEvent",
    "BookingOwner",
    "DutySession",
    "Electrician",
    "ElectricianLocality",
    "ManualDispatchOverride",
    "IdempotencyRecord",
    "Job",
    "ScheduleChange",
    "SchedulingRun",
    "ServiceZone",
    "Shift",
    "Skill",
    "UnavailablePeriod",
    "User",
    "UserProfile",
    "PaymentMethod",
    "electrician_skills",
    "electrician_zones",
    "job_skills",
]
