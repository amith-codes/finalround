"""Electrician CRUD, shifts and unavailability."""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Assignment, Electrician, ElectricianLocality, Job, ServiceZone, Shift, Skill, UnavailablePeriod
from app.models.enums import JobStatus
from app.schemas import ElectricianCreate, ElectricianUpdate, ShiftIn, UnavailableIn
from app.services.errors import ApiError, not_found


def get_electrician(db: Session, eid: int) -> Electrician:
    e = db.scalar(select(Electrician).where(Electrician.id == eid).options(
        selectinload(Electrician.skills), selectinload(Electrician.zones),
        selectinload(Electrician.shifts), selectinload(Electrician.unavailable_periods),
        selectinload(Electrician.service_localities),
    ))
    if e is None:
        raise not_found("Electrician", eid)
    return e


def in_progress_by_electrician(db: Session) -> dict[int, set[int]]:
    rows = db.execute(
        select(Assignment.electrician_id, Job.id).join(Job).where(
            Assignment.is_active.is_(True), Job.status == JobStatus.IN_PROGRESS.value)
    )
    out: dict[int, set[int]] = {}
    for eid, jid in rows:
        out.setdefault(eid, set()).add(jid)
    return out


def _skills(db: Session, codes: list[str]) -> list[Skill]:
    skills = list(db.scalars(select(Skill).where(Skill.code.in_(codes))))
    missing = sorted(set(codes) - {s.code for s in skills})
    if missing:
        raise ApiError(422, "UNKNOWN_SKILL", f"Unknown skill code(s): {', '.join(missing)}", {"unknown": missing})
    return skills


def _zones(db: Session, codes: list[str]) -> list[ServiceZone]:
    zones = list(db.scalars(select(ServiceZone).where(ServiceZone.code.in_(codes))))
    missing = sorted(set(codes) - {z.code for z in zones})
    if missing:
        raise ApiError(422, "UNKNOWN_ZONE", f"Unknown zone code(s): {', '.join(missing)}", {"unknown": missing})
    return zones


def _shifts(items: list[ShiftIn]) -> list[Shift]:
    return [Shift(day_of_week=s.day_of_week, start_time=s.start_time, end_time=s.end_time) for s in items]


def create_electrician(db: Session, data: ElectricianCreate) -> Electrician:
    if data.employee_code and db.scalar(select(Electrician).where(Electrician.employee_code == data.employee_code)):
        raise ApiError(409, "DUPLICATE_EMPLOYEE_CODE", f"Employee code {data.employee_code} already exists")
    e = Electrician(
        employee_code=data.employee_code or "PENDING", name=data.name, phone=data.phone, email=data.email,
        home_lat=data.home_lat, home_lon=data.home_lon, max_overtime_minutes=data.max_overtime_minutes,
        active=data.active,
    )
    e.skills = _skills(db, data.skills)
    e.zones = _zones(db, data.zones)
    e.shifts = _shifts(data.shifts)
    e.service_localities = [ElectricianLocality(locality=x) for x in sorted(
        {v.strip() for v in data.localities if v.strip()}, key=str.casefold)]
    if not data.employee_code:
        e.employee_code = f"TMP-{id(e)}"
    db.add(e)
    db.flush()
    if not data.employee_code:
        e.employee_code = f"EL-{e.id:03d}"
    return e


def planned_job_ids(db: Session, e: Electrician) -> list[int]:
    """Jobs planned (not started) for this electrician. They are kept as the prior assignment so
    the next scheduling run reports them as reassigned rather than silently dropping them."""
    return list(db.scalars(select(Job.id).join(Assignment).where(
        Assignment.is_active.is_(True), Assignment.electrician_id == e.id,
        Job.status == JobStatus.ASSIGNED.value)))


def update_electrician(db: Session, e: Electrician, data: ElectricianUpdate) -> Electrician:
    fields = data.model_dump(exclude_unset=True)
    if "skills" in fields:
        e.skills = _skills(db, fields.pop("skills"))
    if "zones" in fields:
        e.zones = _zones(db, fields.pop("zones"))
    if "shifts" in fields:
        fields.pop("shifts")
        e.shifts = _shifts(data.shifts)
    if "localities" in fields:
        values = fields.pop("localities")
        e.service_localities = [
            ElectricianLocality(locality=x.strip())
            for x in sorted({v.strip() for v in values if v.strip()}, key=str.casefold)
        ]
    if fields.get("active") is False and e.active:
        if in_progress_by_electrician(db).get(e.id):
            raise ApiError(409, "ELECTRICIAN_ON_JOB", "Cannot deactivate an electrician with a job in progress.")
    for k, v in fields.items():
        setattr(e, k, v)
    return e


def deactivate_electrician(db: Session, e: Electrician) -> list[int]:
    if in_progress_by_electrician(db).get(e.id):
        raise ApiError(409, "ELECTRICIAN_ON_JOB", "Cannot remove an electrician with a job in progress.")
    e.active = False
    return planned_job_ids(db, e)


def add_unavailability(db: Session, e: Electrician, data: UnavailableIn) -> UnavailablePeriod:
    p = UnavailablePeriod(electrician_id=e.id, start=data.start, end=data.end, reason=data.reason)
    db.add(p)
    db.flush()
    return p
