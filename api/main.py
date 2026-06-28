"""
Sprawl AI — API service entry point.

Responsibilities (§5.1):
- REST API (JWT-auth, error envelope)
- GitHub webhook receiver
- SSE fan-out (subscribes to Redis pub/sub, streams to clients)
- Triggers / enqueues agent + rotation work; never runs agents inline

Agent execution lives exclusively in `worker`. This service only triggers and streams.
"""
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.db.session import close_engine
from api.routers import health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api.startup", version="0.1.0", environment=settings.environment)
    yield
    await close_engine()
    logger.info("api.shutdown")


app = FastAPI(
    title="Sprawl AI API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers (stubs — fleshed out in M2 onward) ────────────────────────────────
app.include_router(health.router)
