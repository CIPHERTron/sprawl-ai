"""
/workspaces/{workspace_id}/investigations — investigation list + status.
Full implementation in M7 (LangGraph agent). Stub here.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/investigations",
    tags=["investigations"],
)


@router.get("")
async def list_investigations(
    workspace_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"items": [], "workspace_id": workspace_id})


@router.get("/{investigation_id}")
async def get_investigation(
    workspace_id: str,
    investigation_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"id": investigation_id, "workspace_id": workspace_id})
