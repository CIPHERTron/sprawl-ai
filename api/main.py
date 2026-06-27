"""
Sprawl AI — API service entry point.

Responsibilities (§5.1):
- REST API (JWT-auth, error envelope)
- GitHub webhook receiver
- SSE fan-out (subscribes to Redis pub/sub, streams to clients)
- Triggers / enqueues agent + rotation work; never runs agents inline

Agent execution lives exclusively in `worker`. This service only triggers and streams.
"""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Sprawl AI API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers (stubs — fleshed out in M2 onward) ────────────────────────────────
app.include_router(health.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("api.startup", version="0.1.0")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("api.shutdown")
