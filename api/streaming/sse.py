"""
SSE fan-out — subscribe to a workspace's Redis pub/sub channel and stream
events to the client as Server-Sent Events.

Wire-format (one SSE frame per Redis message):
    id: <monotonic counter>
    event: <event_type>
    data: <json payload>
    \\n\\n

The caller owns reconnect logic; we close the stream on client disconnect
or after MAX_STREAM_SECONDS to prevent zombie connections.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from redis.asyncio import Redis

from api.services.redis import workspace_channel

logger = structlog.get_logger(__name__)

MAX_STREAM_SECONDS = 3600  # 1 hour hard cap per SSE connection
KEEPALIVE_INTERVAL = 15    # seconds between heartbeat comments


async def workspace_event_stream(
    workspace_id: str,
    redis: Redis,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings for all events published
    to `workspace:{workspace_id}:events`.

    Yields a keepalive comment every KEEPALIVE_INTERVAL seconds so proxies
    and clients don't treat idle connections as dead.
    """
    channel = workspace_channel(workspace_id)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    logger.info("sse.subscribed", workspace_id=workspace_id, channel=channel)

    counter = 0
    deadline = asyncio.get_event_loop().time() + MAX_STREAM_SECONDS

    try:
        while asyncio.get_event_loop().time() < deadline:
            # Non-blocking get_message with a short timeout
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=KEEPALIVE_INTERVAL
            )

            if message is None:
                # No event within the window — send a keepalive comment
                yield ": keepalive\n\n"
                continue

            if message["type"] != "message":
                continue

            raw = message["data"]
            try:
                payload = json.loads(raw)
                event_type = payload.pop("type", "event")
                data = json.dumps(payload)
            except (json.JSONDecodeError, AttributeError):
                event_type = "event"
                data = str(raw)

            counter += 1
            yield f"id: {counter}\nevent: {event_type}\ndata: {data}\n\n"

    finally:
        await pubsub.unsubscribe(channel)
        logger.info("sse.unsubscribed", workspace_id=workspace_id)
