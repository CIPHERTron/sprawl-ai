"""
/workspaces/{workspace_id}/connectors — connector CRUD + probe.
Full implementation in M9 (Vault/SSM connectors). Stub here.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth, require_role
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/connectors",
    tags=["connectors"],
)


@router.get("")
async def list_connectors(
    workspace_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"items": [], "workspace_id": workspace_id})


@router.post("")
async def create_connector(
    workspace_id: str,
    claims: TokenClaims = Depends(require_role("owner")),
):
    """Register a new connector (M9)."""
    return ok({"created": True})


@router.post("/{connector_id}/probe")
async def probe_connector(
    workspace_id: str,
    connector_id: str,
    claims: TokenClaims = Depends(require_role("owner")),
):
    """Test connectivity and update capability flags (M9)."""
    return ok({"connector_id": connector_id, "status": "untested"})


@router.delete("/{connector_id}")
async def delete_connector(
    workspace_id: str,
    connector_id: str,
    claims: TokenClaims = Depends(require_role("owner")),
):
    return ok({"deleted": True})
