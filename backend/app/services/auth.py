"""JWT authentication for the dispatcher console."""
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.models import User
from app.services.errors import ApiError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": username, "exp": expire}, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def ensure_default_user(db: Session) -> None:
    user = db.scalar(select(User).where(User.username == config.DEFAULT_ADMIN_USERNAME))
    if user is None:
        db.add(User(
            username=config.DEFAULT_ADMIN_USERNAME,
            password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD),
            role="admin",
        ))
        db.commit()
    elif user.role != "admin":
        # The configured bootstrap account is the sole trusted exception; the role is never
        # selected by a sign-in request or ordinary account creation form.
        user.role = "admin"
        db.commit()


def require_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User | None:
    if config.AUTH_DISABLED:
        return None
    unauthorized = ApiError(401, "UNAUTHORIZED", "Missing or invalid bearer token")
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        raise unauthorized
    user = db.scalar(select(User).where(User.username == payload.get("sub")))
    if user is None:
        raise unauthorized
    return user


def require_role(*roles: str):
    """Server-side role gate. The role is always read from the user row, never a request field."""
    def dependency(user: User | None = Depends(require_user)) -> User | None:
        if user is None and config.AUTH_DISABLED and "admin" in roles:
            return None
        if user is None or user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "Your account does not have access to this action.")
        return user
    return dependency
