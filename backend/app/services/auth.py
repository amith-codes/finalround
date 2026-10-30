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
from app.models import User, UserRoleGrant
from app.services.errors import ApiError

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
ROLE_ALIASES = {"dispatcher": "admin", "administrator": "admin"}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, active_role: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    claims = {"sub": username, "exp": expire}
    if active_role:
        claims["role"] = active_role
    return jwt.encode(claims, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def active_role(user: User) -> str:
    role = getattr(user, "active_role", user.role)
    return ROLE_ALIASES.get(role, role)


def authorized_roles(db: Session, user: User) -> list[str]:
    roles = [ROLE_ALIASES.get(role, role) for role in db.scalars(
        select(UserRoleGrant.role).where(UserRoleGrant.user_id == user.id))]
    base_role = ROLE_ALIASES.get(user.role, user.role)
    if base_role not in roles:
        roles.append(base_role)
    return sorted(set(roles), key=("admin", "customer", "electrician").index)


def grant_role(db: Session, user: User, role: str) -> None:
    if db.get(UserRoleGrant, (user.id, role)) is None:
        db.add(UserRoleGrant(user_id=user.id, role=role))


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
        user = db.scalar(select(User).where(User.username == config.DEFAULT_ADMIN_USERNAME))
    elif user.role != "admin":
        # The configured bootstrap account is the sole trusted exception; the role is never
        # selected by a sign-in request or ordinary account creation form.
        user.role = "admin"
        db.commit()
    if user is not None:
        grant_role(db, user, "admin")
        # Admin accounts may switch to a self-scoped customer workspace; this never changes
        # the account's administrator permissions or the data owned by other customers.
        grant_role(db, user, "customer")
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
    requested_role = payload.get("role")
    if requested_role:
        requested_role = ROLE_ALIASES.get(requested_role, requested_role)
        allowed = set(authorized_roles(db, user))
        if requested_role not in allowed:
            raise unauthorized
        user.active_role = requested_role
    return user


def require_role(*roles: str):
    """Server-side role gate. The role is always read from the user row, never a request field."""
    def dependency(user: User | None = Depends(require_user)) -> User | None:
        if user is None and config.AUTH_DISABLED and "admin" in roles:
            return None
        if user is None or active_role(user) not in roles:
            raise ApiError(403, "FORBIDDEN", "Your account does not have access to this action.")
        return user
    return dependency
