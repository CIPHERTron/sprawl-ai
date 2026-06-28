"""
Async Redis publish helper for the worker process.

The worker does not keep a persistent connection pool (unlike the API which
subscribes to channels for SSE fan-out).  Instead, each job creates a
short-lived connection and publishes events as needed.

Public API:
    from worker.redis import publish_event

    await publish_event(workspace_id, "investigation.update", {"node": "ingest"})
"""
from __future__ import annotations

import json

import structlog
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from worker.config import worker_settings

logger = structlog.get_logger(__name__)


def workspace_channel(workspace_id: str) -> str:
    """Canonical Redis pub/sub channel name (mirrors api/services/redis.py)."""
    return f"workspace:{workspace_id}:events"


async def publish_event(workspace_id: str, event_type: str, payload: dict) -> None:
    """
    Open a transient Redis connection, publish one event, and close.
    Fire-and-forget — failures are logged but never propagated to the caller.
    """
    try:
        client: Redis = redis_from_url(worker_settings.redis_url, decode_responses=True)
        message = json.dumps({"type": event_type, **payload})
        await client.publish(workspace_channel(workspace_id), message)
        await client.aclose()
    except Exception as exc:
        logger.warning(
            "worker.redis.publish_failed",
            workspace_id=workspace_id,
            event_type=event_type,
            error=str(exc),
        )
