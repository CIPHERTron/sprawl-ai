"""
/workspaces/{workspace_id}/secrets — secret identity CRUD + triage actions.
Full implementation in M5+. Stubs here establish the URL contract.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/secrets",
    tags=["secrets"],
)


@router.get("")
async def list_secrets(
    workspace_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"items": [], "workspace_id": workspace_id})


@router.get("/{secret_id}")
async def get_secret(
    workspace_id: str,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"id": secret_id, "workspace_id": workspace_id})


@router.post("/{secret_id}/investigate")
async def trigger_investigation(
    workspace_id: str,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Enqueue an investigation agent run (M7)."""
    return ok({"queued": True, "secret_id": secret_id})


@router.post("/{secret_id}/rotate")
async def trigger_rotation(
    workspace_id: str,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Create a rotation row in 'proposed' status and enqueue plan_rotation (M5)."""
    return ok({"queued": True, "secret_id": secret_id})
