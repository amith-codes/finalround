"""Idempotency-Key support for POST endpoints.

A client sends `Idempotency-Key: <uuid>`. The first request with a key is executed and its
response stored; repeats with the same key and the same body replay the stored response
(header `Idempotent-Replayed: true`) without executing again. Reusing a key with a different
body is rejected. A request still executing under the same key gets 409.
"""
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.models import IdempotencyRecord
from app.services.errors import ApiError

IN_PROGRESS_STALE_MINUTES = 5


def _hash(payload) -> str:
    raw = json.dumps(jsonable_encoder(payload), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _replay(rec: IdempotencyRecord, request_hash: str) -> JSONResponse:
    if rec.request_hash != request_hash:
        raise ApiError(
            422, "IDEMPOTENCY_KEY_REUSED",
            "This Idempotency-Key was already used with a different request body.",
        )
    if rec.status_code is None:
        raise ApiError(409, "REQUEST_IN_PROGRESS", "A request with this Idempotency-Key is still being processed.")
    return JSONResponse(rec.response_body, status_code=rec.status_code, headers={"Idempotent-Replayed": "true"})


def idempotent(
    db: Session,
    key: str | None,
    endpoint: str,
    payload,
    handler: Callable[[], object],
    status_code: int = 200,
) -> JSONResponse:
    """Run `handler` at most once per (key, endpoint). The handler must commit its own work."""
    if not key:
        return JSONResponse(jsonable_encoder(handler()), status_code=status_code)

    request_hash = _hash(payload)
    now = datetime.now()
    rec = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == key, IdempotencyRecord.endpoint == endpoint))
    if rec is not None:
        expired = rec.created_at < now - timedelta(hours=config.IDEMPOTENCY_TTL_HOURS)
        abandoned = rec.status_code is None and rec.created_at < now - timedelta(minutes=IN_PROGRESS_STALE_MINUTES)
        if expired or abandoned:
            db.delete(rec)
            db.commit()
        else:
            return _replay(rec, request_hash)

    rec = IdempotencyRecord(key=key, endpoint=endpoint, request_hash=request_hash)
    db.add(rec)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request with the same key won the race.
        db.rollback()
        existing = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key, IdempotencyRecord.endpoint == endpoint)
        )
        return _replay(existing, request_hash)

    try:
        body = jsonable_encoder(handler())
    except Exception:
        db.rollback()
        db.delete(db.merge(rec))
        db.commit()
        raise
    rec = db.merge(rec)
    rec.status_code = status_code
    rec.response_body = body
    db.commit()
    return JSONResponse(body, status_code=status_code)
