import os
import tempfile
from pathlib import Path

# Point the app at a throwaway database before anything imports app.database.
_TMP = Path(tempfile.mkdtemp(prefix="dispatchgrid-tests-"))
os.environ["DISPATCHGRID_DB_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ.setdefault("DISPATCHGRID_SCHEDULER_LOCK_TIMEOUT", "30")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, reset_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.auth import ensure_default_user  # noqa: E402

# Fixed planning clock: Friday 30 Oct 2026 07:00. Seed data lands on Sat..Mon.
NOW = datetime(2026, 10, 30, 7, 0)


@pytest.fixture()
def db():
    reset_db()
    with SessionLocal() as session:
        ensure_default_user(session)
        yield session


@pytest.fixture()
def seeded(db):
    from app.seed import build

    build(db, now=NOW)
    return db


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        token = c.post("/api/auth/login", data={"username": "dispatcher", "password": "dispatch123"}).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
