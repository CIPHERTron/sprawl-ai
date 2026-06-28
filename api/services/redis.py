"""
Async Redis client — single shared connection pool for the API process.

Provides:
  - get_redis()  → FastAPI dependency (AsyncGenerator)
  - publish()    → fire-and-forget pub/sub publish helper
  - workspace_channel(workspace_id) → canonical channel name for SSE fan-out
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import structlog
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from api.config import settings

logger = structlog.get_logger(__name__)

_client: Redis | None = None


async def init_redis() -> None:
    global _client
    _client = redis_from_url(settings.redis_url, decode_responses=True)
    await _client.ping()
    logger.info("redis.connected", url=settings.redis_url)


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("redis.disconnected")


def get_redis_client() -> Redis:
    """Return the shared client (must be initialized via init_redis first)."""
    if _client is None:
        raise RuntimeError("Redis not initialised — call init_redis() at startup")
    return _client


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency that yields the shared Redis client."""
    yield get_redis_client()


def workspace_channel(workspace_id: str) -> str:
    """Canonical Redis pub/sub channel name for a workspace's SSE stream."""
    return f"workspace:{workspace_id}:events"


async def publish(workspace_id: str, event_type: str, payload: dict) -> None:
    """
    Publish a JSON event to a workspace's SSE channel.
    Fire-and-forget — callers should not await error handling here.
    """
    import json

    client = get_redis_client()
    message = json.dumps({"type": event_type, **payload})
    await client.publish(workspace_channel(workspace_id), message)
