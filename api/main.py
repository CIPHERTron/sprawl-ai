"""
Sprawl AI — API service entry point.

Responsibilities (§5.1):
- REST API (JWT-auth, error envelope)
- GitHub webhook receiver (M8)
- SSE fan-out (subscribes to Redis pub/sub, streams to clients)
- Triggers / enqueues agent + rotation work; never runs agents inline

Agent execution lives exclusively in `worker`.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.config import settings
from api.db.session import close_engine
from api.routers import (
    audit_router,
    connectors,
    demo,
    events,
    findings,
    graph,
    health,
    investigations,
    me,
    rotations,
    secrets,
)
from api.services.redis import close_redis, init_redis

logger = structlog.get_logger(__name__)

# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api.startup", version="0.1.0", environment=settings.environment)
    await init_redis()
    yield
    await close_redis()
    await close_engine()
    logger.info("api.shutdown")


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sprawl AI API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate-limit exceeded handler must be registered before other exception handlers
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware — order matters (innermost applied last) ────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a UUID request ID to every request + response."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Error envelope ─────────────────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": detail,
                "message": detail.replace("_", " ").capitalize(),
                "request_id": getattr(request.state, "request_id", None),
            },
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "api.unhandled_error",
        request_id=getattr(request.state, "request_id", None),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
                "request_id": getattr(request.state, "request_id", None),
            },
        },
    )


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(me.router)
app.include_router(secrets.router)
app.include_router(graph.router)
app.include_router(findings.router)
app.include_router(connectors.router)
app.include_router(investigations.router)
app.include_router(rotations.router)
app.include_router(audit_router.router)
app.include_router(demo.router)
app.include_router(events.router)
