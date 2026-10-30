from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserProfile
from app.services.auth import active_role, authenticate, authorized_roles, create_token, require_user
from app.schemas import RoleSwitchIn
from app.services.errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", summary="Exchange username/password for a JWT bearer token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate(db, form.username, form.password)
    if user is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect username or password")
    role = active_role(user)
    return {"access_token": create_token(user.username, role), "token_type": "bearer", "username": user.username}


@router.get("/me")
def me(user=Depends(require_user), db: Session = Depends(get_db)):
    if user is None:
        return {"username": "anonymous", "role": "admin", "display_name": "Dispatcher", "electrician_id": None}
    from sqlalchemy import select
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    return {"username": user.username, "role": active_role(user), "roles": authorized_roles(db, user),
            "display_name": profile.display_name if profile else user.username,
            "electrician_id": profile.electrician_id if profile else None}


@router.post("/switch-role")
def switch_role(data: RoleSwitchIn, user=Depends(require_user), db: Session = Depends(get_db)):
    if user is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "Sign in with your login ID and password to switch workspaces.")
    verified_user = authenticate(db, data.username, data.password)
    if verified_user is None or verified_user.id != user.id:
        raise ApiError(401, "INVALID_CREDENTIALS", "Enter the login ID and password for your current account.")
    roles = authorized_roles(db, user)
    if data.role not in roles:
        raise ApiError(403, "ROLE_NOT_GRANTED", "Your account is not authorized for that workspace.")
    return {"access_token": create_token(user.username, data.role), "token_type": "bearer", "role": data.role}
