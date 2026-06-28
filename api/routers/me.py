"""
/me — current user profile (M8 will populate from DB once GitHub sign-in is live).
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
async def get_me(claims: TokenClaims = Depends(require_auth)):
    """Return the authenticated user's profile from JWT claims."""
    return ok({
        "sub": claims.sub,
        "workspace_id": claims.workspace_id,
        "role": claims.role,
        "name": claims.name,
        "github_id": claims.github_id,
    })
