"""Runtime configuration, read from environment variables with development defaults."""
import os


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DATABASE_URL = os.getenv("DISPATCHGRID_DB_URL", "sqlite:///./dispatchgrid.db")

JWT_SECRET = os.getenv("DISPATCHGRID_JWT_SECRET", "dev-only-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("DISPATCHGRID_JWT_EXPIRE_MINUTES", "720"))

# When true every endpoint is reachable without a token (handy for quick Swagger exploration).
AUTH_DISABLED = _bool("DISPATCHGRID_AUTH_DISABLED", False)

DEFAULT_ADMIN_USERNAME = os.getenv("DISPATCHGRID_ADMIN_USER", "dispatcher")
DEFAULT_ADMIN_PASSWORD = os.getenv("DISPATCHGRID_ADMIN_PASSWORD", "dispatch123")

# How long a scheduling request waits for another in-flight run before giving up with 409.
SCHEDULER_LOCK_TIMEOUT_SECONDS = float(os.getenv("DISPATCHGRID_SCHEDULER_LOCK_TIMEOUT", "30"))
# A run row left in "running" longer than this is considered stale (crashed worker).
STALE_RUN_MINUTES = int(os.getenv("DISPATCHGRID_STALE_RUN_MINUTES", "10"))

# Idempotency records older than this are ignored and replaced.
IDEMPOTENCY_TTL_HOURS = int(os.getenv("DISPATCHGRID_IDEMPOTENCY_TTL_HOURS", "24"))

CORS_ORIGINS = os.getenv(
    "DISPATCHGRID_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
3