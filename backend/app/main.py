import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.database import SessionLocal, init_db
from app.routers import auth, dashboard, disruptions, electricians, jobs, portal, reference, scheduling
from app.services.auth import ensure_default_user, require_role, require_user
from app.services.errors import ApiError
from app.services.scheduling_service import mark_interrupted_runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dispatchgrid")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        ensure_default_user(db)
        n = mark_interrupted_runs(db)
        if n:
            log.warning("Marked %d scheduling run(s) left 'running' by a previous process as interrupted", n)
    yield


app = FastAPI(
    title="DispatchGrid API",
    description="Electrician workforce scheduling & recovery engine. "
                "Authorize with the default dispatcher account (see README) to try endpoints.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Idempotent-Replayed"],
)


@app.exception_handler(ApiError)
async def api_error_handler(_req: Request, exc: ApiError):
    return JSONResponse(exc.body(), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_handler(_req: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(
        {"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed", "details": jsonable_encoder(errors)}},
        status_code=422,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_req: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse({"error": {"code": code, "message": str(exc.detail), "details": None}},
                        status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_handler(_req: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "Unexpected server error", "details": None}},
                        status_code=500)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


protected = [Depends(require_user)]
app.include_router(auth.router)
app.include_router(reference.router, dependencies=protected)
app.include_router(jobs.router, dependencies=protected)
app.include_router(portal.router, dependencies=protected)
for r in (electricians.router, scheduling.router, disruptions.router, dashboard.router):
    app.include_router(r, dependencies=[Depends(require_role("admin"))])
