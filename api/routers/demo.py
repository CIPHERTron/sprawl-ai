"""
/demo — demo session management (no sign-in required).
Full implementation (seed data, simulate-failure) in M3. Stub here.

Rate-limited per IP (demo_rate_limit_per_ip from config, default 10/hour).
"""
from fastapi import APIRouter, Depends, Request

from api.auth.deps import optional_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/session")
async def create_demo_session(
    request: Request,
    claims: TokenClaims | None = Depends(optional_auth),
):
    """
    Create a demo workspace with TTL. Returns a short-lived session token.
    Full implementation (seeded data, sandbox connectors) in M3.
    """
    return ok({"session_id": "stub", "expires_in": 3600})


@router.get("/session/{session_id}")
async def get_demo_session(session_id: str):
    """Check whether a demo session is still alive."""
    return ok({"session_id": session_id, "alive": False})
