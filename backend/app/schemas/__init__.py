"""Request validation models. Responses are plain dicts built in services/serializers.py."""
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Priority

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _naive(dt: datetime | None) -> datetime | None:
    """All times are stored as naive local time of the dispatch centre."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0)


class NaiveTimes(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def _strip_tz(cls, v):
        return _naive(v) if isinstance(v, datetime) else v


# ----------------------------------------------------------------------------- jobs
class ServiceItemIn(BaseModel):
    model_config = _STRICT
    id: str = Field(pattern=r"^uc_[a-z0-9_]+$")
    quantity: int = Field(ge=1, le=20)


class JobCreate(NaiveTimes):
    model_config = _STRICT

    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    customer_name: str | None = Field(default=None, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=250)
    service_locality: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    service_category: str | None = Field(default=None, max_length=80)
    booking_amount: float = Field(default=0, ge=0, le=1000000)
    payment_method: Literal["razorpay_qr", "cash_on_service"] = "cash_on_service"
    service_items: list[ServiceItemIn] = Field(default_factory=list, max_length=20)
    coupon_code: str | None = Field(default=None, max_length=30)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    zone_code: str = Field(min_length=1, max_length=20)
    priority: Priority = Priority.MEDIUM
    duration_minutes: int = Field(gt=0, le=720)
    required_skills: list[str] = Field(min_length=1, max_length=10)
    requested_electrician_id: int | None = Field(default=None, gt=0)
    window_start: datetime
    window_end: datetime
    sla_deadline: datetime

    @model_validator(mode="after")
    def _check_times(self):
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if (self.window_end - self.window_start).total_seconds() / 60 < self.duration_minutes:
            raise ValueError("time window is shorter than duration_minutes")
        if self.sla_deadline <= self.window_start:
            raise ValueError("sla_deadline must be after window_start")
        if len(set(self.required_skills)) != len(self.required_skills):
            raise ValueError("required_skills contains duplicates")
        return self


class JobUpdate(NaiveTimes):
    model_config = _STRICT

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    customer_name: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=250)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    zone_code: str | None = None
    priority: Priority | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=720)
    required_skills: list[str] | None = Field(default=None, min_length=1, max_length=10)
    window_start: datetime | None = None
    window_end: datetime | None = None
    sla_deadline: datetime | None = None
    status: str | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=250)


class JobStart(NaiveTimes):
    model_config = _STRICT
    started_at: datetime | None = None


# ---------------------------------------------------------------------- electricians
class ShiftIn(BaseModel):
    model_config = _STRICT

    day_of_week: int = Field(ge=0, le=6, description="Monday=0 .. Sunday=6")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _order(self):
        if self.end_time <= self.start_time:
            raise ValueError("shift end_time must be after start_time (overnight shifts are not supported)")
        return self


class ElectricianCreate(BaseModel):
    model_config = _STRICT

    employee_code: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    home_lat: float = Field(ge=-90, le=90)
    home_lon: float = Field(ge=-180, le=180)
    max_overtime_minutes: int = Field(default=0, ge=0, le=240)
    active: bool = True
    localities: list[str] = Field(default_factory=list, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=30)
    zones: list[str] = Field(min_length=1, max_length=20)
    shifts: list[ShiftIn] = Field(default_factory=list, max_length=21)
    username: str | None = Field(default=None, min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.@-]+$")
    initial_password: str | None = Field(default=None, min_length=8, max_length=100)

    @model_validator(mode="after")
    def _no_overlapping_shifts(self):
        _check_shift_overlap(self.shifts)
        return self


class ElectricianUpdate(BaseModel):
    model_config = _STRICT

    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lon: float | None = Field(default=None, ge=-180, le=180)
    max_overtime_minutes: int | None = Field(default=None, ge=0, le=240)
    active: bool | None = None
    localities: list[str] | None = Field(default=None, max_length=100)
    skills: list[str] | None = Field(default=None, max_length=30)
    zones: list[str] | None = Field(default=None, min_length=1, max_length=20)
    shifts: list[ShiftIn] | None = Field(default=None, max_length=21)

    @model_validator(mode="after")
    def _no_overlapping_shifts(self):
        if self.shifts is not None:
            _check_shift_overlap(self.shifts)
        return self


def _check_shift_overlap(shifts: list[ShiftIn]) -> None:
    by_day: dict[int, list[ShiftIn]] = {}
    for s in shifts:
        by_day.setdefault(s.day_of_week, []).append(s)
    for day, items in by_day.items():
        items.sort(key=lambda s: s.start_time)
        for a, b in zip(items, items[1:]):
            if b.start_time < a.end_time:
                raise ValueError(f"overlapping shifts on day {day}")


class UnavailableIn(NaiveTimes):
    model_config = _STRICT

    start: datetime
    end: datetime
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


# ------------------------------------------------------------------- reference data
class SkillIn(BaseModel):
    model_config = _STRICT
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class ZoneIn(BaseModel):
    model_config = _STRICT
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=2, max_length=120)
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)


class CustomerAccountIn(BaseModel):
    model_config = _STRICT
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8, max_length=100)
    display_name: str = Field(min_length=2, max_length=120)


class RoleSwitchIn(BaseModel):
    model_config = _STRICT
    role: str = Field(pattern=r"^(customer|admin|electrician)$")
    username: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=1, max_length=100)


class PaymentMethodIn(BaseModel):
    model_config = _STRICT
    label: str = Field(min_length=2, max_length=80)
    brand: str = Field(min_length=2, max_length=30)
    last4: str = Field(pattern=r"^\d{4}$")
    is_default: bool = False


class BookingActionIn(BaseModel):
    model_config = _STRICT
    action: str = Field(pattern=r"^(accept|decline|start|complete|cancel|customer_unavailable|disturbed)$")
    reason: str | None = Field(default=None, max_length=250)
    electrician_id: int | None = Field(default=None, gt=0)


class ManualAssignmentIn(BaseModel):
    model_config = _STRICT
    electrician_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=250)


class DutyActionIn(BaseModel):
    model_config = _STRICT
    action: str = Field(pattern=r"^(clock_in|clock_out|available|unavailable)$")


class PaymentStatusIn(BaseModel):
    model_config = _STRICT
    status: str = Field(pattern=r"^(pending|paid|failed|refunded)$")


class CustomerFeedbackIn(BaseModel):
    model_config = _STRICT
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class CustomerComplaintIn(BaseModel):
    model_config = _STRICT
    issue_type: str = Field(pattern=r"^(service_not_done|incomplete_service|other_issue)$")
    description: str | None = Field(default=None, max_length=2000)


# ----------------------------------------------------------------------- scheduling
class RunRequest(NaiveTimes):
    model_config = _STRICT
    as_of: datetime | None = Field(default=None, description="Planning clock; defaults to the current time.")


# ---------------------------------------------------------------------- disruptions
class ElectricianUnavailableIn(NaiveTimes):
    model_config = _STRICT

    electrician_id: int
    start: datetime
    end: datetime
    reason: str | None = Field(default="Unavailable", max_length=200)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class UrgentJobIn(JobCreate):
    priority: Priority = Priority.URGENT
    as_of: datetime | None = None


class DurationChangeIn(NaiveTimes):
    model_config = _STRICT

    job_id: int
    new_duration_minutes: int = Field(gt=0, le=720)
    reason: str | None = Field(default=None, max_length=200)
    as_of: datetime | None = None


class JobCancelIn(NaiveTimes):
    model_config = _STRICT

    job_id: int
    reason: str = Field(default="Cancelled by customer", max_length=200)
    as_of: datetime | None = None


class JobCompletionIn(NaiveTimes):
    model_config = _STRICT

    job_id: int
    completed_at: datetime | None = Field(default=None, description="Defaults to as_of / now.")
    as_of: datetime | None = None
