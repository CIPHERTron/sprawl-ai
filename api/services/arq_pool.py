"""
arq Redis pool — used by the API to enqueue background jobs.

Provides `enqueue_job()` for fire-and-forget job dispatch from API handlers.
The pool is initialised once at lifespan startup (via init_arq_pool) and
closed at shutdown (via close_arq_pool).

Usage in routers:
    from api.services.arq_pool import enqueue_job

    await enqueue_job("investigate_secret",
                      secret_id=str(secret.id),
                      investigation_id=str(inv.id),
                      workspace_id=str(workspace_id))
"""
from __future__ import annotations

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from api.config import settings

logger = structlog.get_logger(__name__)

_pool: ArqRedis | None = None


async def init_arq_pool() -> None:
    global _pool
    _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("arq_pool.connected", redis_url=settings.redis_url)


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("arq_pool.closed")


def get_arq_pool() -> ArqRedis:
    """Return the shared arq pool (must be initialised first)."""
    if _pool is None:
        raise RuntimeError("arq pool not initialised — call init_arq_pool() at startup")
    return _pool


async def enqueue_job(function_name: str, **kwargs) -> str | None:
    """
    Enqueue a background job.

    Returns the job ID string, or None if the pool is unavailable.
    Logs but never propagates enqueue errors — the caller should handle None.
    """
    try:
        pool = get_arq_pool()
        job = await pool.enqueue_job(function_name, **kwargs)
        job_id = job.job_id if job else None
        logger.info("arq_pool.enqueued", function=function_name, job_id=job_id)
        return job_id
    except Exception as exc:
        logger.error("arq_pool.enqueue_failed", function=function_name, error=str(exc))
        return None
