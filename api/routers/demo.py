"""
/demo — demo session management (no sign-in required).

Endpoints:
  POST   /demo/session                        → create workspace + seed + JWT
  GET    /demo/session/{session_id}           → session liveness check
  POST   /demo/session/{session_id}/simulate-failure → trigger demo rollback

Rate-limited: 10 sessions per IP per hour (configurable via demo_rate_limit_per_ip).
Auth: not required to create/read a session; simulate-failure requires the demo JWT.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import optional_auth, require_auth
from api.auth.jwt import TokenClaims
from api.db.session import get_db
from api.schemas.common import ok
from api.services.demo import (
    create_demo_session,
    get_demo_session,
    simulate_failure,
)

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/session", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _claims: TokenClaims | None = Depends(optional_auth),
):
    """
    Create a sandboxed demo workspace pre-seeded with an AWS IAM leak scenario.
    Returns a short-lived JWT scoped to the demo workspace.
    No sign-in required.
    """
    result = await create_demo_session(db)
    return ok({
        "session_id": result.session_id,
        "workspace_id": result.workspace_id,
        "token": result.token,
        "expires_at": result.expires_at.isoformat(),
        "is_demo": True,
    })


@router.get("/session/{session_id}")
async def check_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return session liveness. alive=false when expired or swept."""
    info = await get_demo_session(db, session_id)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    return ok(info)


@router.post("/session/{session_id}/simulate-failure")
async def trigger_simulate_failure(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    claims: TokenClaims = Depends(require_auth),
):
    """
    Simulate a rotation failure + automatic rollback on the demo workspace.
    Transitions the rotation through provisioning → revoking (fail) → rolled_back
    so the UI can demonstrate the full safety flow.

    Requires the demo JWT returned by POST /demo/session.
    """
    result = await simulate_failure(db, session_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result["error"],
        )
    return ok(result)
