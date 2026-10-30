"""Skills and service zones (reference data used by jobs and electricians)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ServiceZone, Skill
from app.schemas import SkillIn, ZoneIn
from app.services.auth import require_role
from app.services.errors import ApiError

router = APIRouter(prefix="/api", tags=["reference data"])


@router.get("/skills")
def list_skills(db: Session = Depends(get_db)):
    return [{"id": s.id, "code": s.code, "name": s.name, "description": s.description}
            for s in db.scalars(select(Skill).order_by(Skill.code))]


@router.post("/skills", status_code=201)
def create_skill(data: SkillIn, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    if db.scalar(select(Skill).where(Skill.code == data.code)):
        raise ApiError(409, "DUPLICATE_SKILL", f"Skill {data.code} already exists")
    s = Skill(**data.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id, "code": s.code, "name": s.name, "description": s.description}


@router.get("/zones")
def list_zones(db: Session = Depends(get_db)):
    return [{"id": z.id, "code": z.code, "name": z.name, "center_lat": z.center_lat, "center_lon": z.center_lon}
            for z in db.scalars(select(ServiceZone).order_by(ServiceZone.code))]


@router.post("/zones", status_code=201)
def create_zone(data: ZoneIn, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    if db.scalar(select(ServiceZone).where(ServiceZone.code == data.code)):
        raise ApiError(409, "DUPLICATE_ZONE", f"Zone {data.code} already exists")
    z = ServiceZone(**data.model_dump())
    db.add(z)
    db.commit()
    return {"id": z.id, "code": z.code, "name": z.name, "center_lat": z.center_lat, "center_lon": z.center_lon}
