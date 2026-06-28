"""
GET /events — SSE fan-out endpoint.

Clients connect once (workspace-scoped) and receive all real-time events:
  - scan.progress / scan.complete
  - investigation.update / investigation.complete
  - rotation.step / rotation.complete / rotation.failed
  - audit.entry (for the live audit view in M10)

Authentication: Bearer JWT required (workspace_id extracted from claims).
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.services.redis import get_redis
from api.streaming.sse import workspace_event_stream
from redis.asyncio import Redis

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def stream_events(
    request: Request,
    claims: TokenClaims = Depends(require_auth),
    redis: Redis = Depends(get_redis),
):
    """
    Server-Sent Events stream for the authenticated workspace.
    Keepalive comments are sent every 15 s. Connection is closed after 1 h.
    """
    workspace_id = claims.workspace_id

    async def generate():
        async for chunk in workspace_event_stream(workspace_id, redis):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering
        },
    )
