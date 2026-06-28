"""
/workspaces/{workspace_id}/findings — detection findings list + triage.
Full implementation in M8 (gitleaks ingest). Stub here.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/findings",
    tags=["findings"],
)


@router.get("")
async def list_findings(
    workspace_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    return ok({"items": [], "workspace_id": workspace_id})


@router.patch("/{finding_id}")
async def triage_finding(
    workspace_id: str,
    finding_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Update finding state (confirmed / false_positive / ignored)."""
    return ok({"id": finding_id, "workspace_id": workspace_id})
