"""
/workspaces/{workspace_id}/audit — audit log read view.
Full implementation in M10. Stub here.
"""
from fastapi import APIRouter, Depends, Query

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/audit",
    tags=["audit"],
)


@router.get("")
async def list_audit_events(
    workspace_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    claims: TokenClaims = Depends(require_auth),
):
    """Paginated audit log. Chain verification endpoint added in M10."""
    return ok({"items": [], "workspace_id": workspace_id, "limit": limit, "offset": offset})
