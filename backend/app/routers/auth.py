from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserProfile
from app.services.auth import authenticate, create_token, require_user
from app.services.errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", summary="Exchange username/password for a JWT bearer token")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate(db, form.username, form.password)
    if user is None:
        raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect username or password")
    return {"access_token": create_token(user.username), "token_type": "bearer", "username": user.username}


@router.get("/me")
def me(user=Depends(require_user), db: Session = Depends(get_db)):
    if user is None:
        return {"username": "anonymous", "role": "admin", "display_name": "Dispatcher", "electrician_id": None}
    from sqlalchemy import select
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    return {"username": user.username, "role": user.role, "display_name": profile.display_name,
            "electrician_id": profile.electrician_id} if profile else {
                "username": user.username, "role": user.role, "display_name": user.username, "electrician_id": None
            }
