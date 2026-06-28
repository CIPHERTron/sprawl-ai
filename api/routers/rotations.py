"""
/workspaces/{workspace_id}/rotations — rotation lifecycle + approval gates.
Full implementation in M5/M6 (engine + UI). Stub here.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth, require_role
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/rotations",
    tags=["rotations"],
)


@router.get("")
async def list_rotations(
    workspace_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"items": [], "workspace_id": workspace_id})


@router.get("/{rotation_id}")
async def get_rotation(
    workspace_id: str,
    rotation_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"id": rotation_id, "workspace_id": workspace_id})


@router.post("/{rotation_id}/approve")
async def approve_rotation(
    workspace_id: str,
    rotation_id: str,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
):
    """Approve a plan and advance to 'provisioning' (M5)."""
    return ok({"approved": True, "rotation_id": rotation_id})


@router.post("/{rotation_id}/reject")
async def reject_rotation(
    workspace_id: str,
    rotation_id: str,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
):
    return ok({"rejected": True, "rotation_id": rotation_id})


@router.post("/{rotation_id}/steps/{step_id}/confirm")
async def confirm_step(
    workspace_id: str,
    rotation_id: str,
    step_id: str,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
):
    """Confirm an individual step gate (M5)."""
    return ok({"confirmed": True, "step_id": step_id})
