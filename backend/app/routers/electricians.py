from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AvailabilityOverride, ManualDispatchOverride, UnavailablePeriod, User, UserProfile
from app.schemas import ElectricianCreate, ElectricianUpdate, UnavailableIn
from app.services import electrician_service as svc
from app.services.errors import ApiError, not_found
from app.services.auth import hash_password
from app.services.problem_builder import load_electricians
from app.services.serializers import electrician_dict

router = APIRouter(prefix="/api/electricians", tags=["electricians"])


def _out(db: Session, eid: int) -> dict:
    e = svc.get_electrician(db, eid)
    result = electrician_dict(e, datetime.now(), svc.in_progress_by_electrician(db).get(e.id))
    override = db.get(AvailabilityOverride, e.id)
    if override and not override.is_available:
        result["current_status"] = "unavailable"
    return result


@router.post("", status_code=201)
def create_electrician(data: ElectricianCreate, db: Session = Depends(get_db)):
    if bool(data.username) != bool(data.initial_password):
        raise ApiError(422, "ACCOUNT_FIELDS_REQUIRED", "Provide both a sign-in name and initial password, or leave both blank.")
    if data.username and db.scalar(select(User.id).where(User.username == data.username)):
        raise ApiError(409, "USERNAME_EXISTS", "That sign-in name is already in use.")
    e = svc.create_electrician(db, data)
    if data.username and data.initial_password:
        account = User(username=data.username, password_hash=hash_password(data.initial_password), role="electrician")
        db.add(account)
        db.flush()
        db.add(UserProfile(user_id=account.id, electrician_id=e.id, display_name=e.name))
    db.commit()
    return _out(db, e.id)


@router.get("")
def list_electricians(include_inactive: bool = False, db: Session = Depends(get_db)):
    busy = svc.in_progress_by_electrician(db)
    now = datetime.now()
    results = []
    for e in load_electricians(db, active_only=not include_inactive):
        item = electrician_dict(e, now, busy.get(e.id))
        override = db.get(AvailabilityOverride, e.id)
        if override and not override.is_available:
            item["current_status"] = "unavailable"
        results.append(item)
    return results


@router.get("/{electrician_id}")
def get_electrician(electrician_id: int, db: Session = Depends(get_db)):
    return _out(db, electrician_id)


@router.put("/{electrician_id}")
def update_electrician(electrician_id: int, data: ElectricianUpdate, db: Session = Depends(get_db)):
    e = svc.get_electrician(db, electrician_id)
    svc.update_electrician(db, e, data)
    for override in db.scalars(select(ManualDispatchOverride).where(
            ManualDispatchOverride.electrician_id == electrician_id, ManualDispatchOverride.active.is_(True))):
        override.active = False
    db.commit()
    return _out(db, electrician_id)


@router.delete("/{electrician_id}", summary="Deactivate an electrician (history is preserved)")
def delete_electrician(electrician_id: int, db: Session = Depends(get_db)):
    e = svc.get_electrician(db, electrician_id)
    affected = svc.deactivate_electrician(db, e)
    for override in db.scalars(select(ManualDispatchOverride).where(
            ManualDispatchOverride.electrician_id == electrician_id, ManualDispatchOverride.active.is_(True))):
        override.active = False
    db.commit()
    return {
        "electrician": _out(db, electrician_id),
        "affected_job_ids": affected,
        "message": "Electrician deactivated. Run scheduling (or re-optimise) to reassign the affected jobs.",
    }


@router.post("/{electrician_id}/unavailability", status_code=201,
             summary="Record planned unavailability (does not trigger rescheduling; use the disruption endpoint for that)")
def add_unavailability(electrician_id: int, data: UnavailableIn, db: Session = Depends(get_db)):
    e = svc.get_electrician(db, electrician_id)
    p = svc.add_unavailability(db, e, data)
    db.commit()
    return {"id": p.id, "electrician_id": e.id, "start": p.start, "end": p.end, "reason": p.reason}


@router.delete("/{electrician_id}/unavailability/{period_id}")
def delete_unavailability(electrician_id: int, period_id: int, db: Session = Depends(get_db)):
    p = db.scalar(select(UnavailablePeriod).where(
        UnavailablePeriod.id == period_id, UnavailablePeriod.electrician_id == electrician_id))
    if p is None:
        raise not_found("Unavailable period", period_id)
    db.delete(p)
    db.commit()
    return {"deleted": period_id}
