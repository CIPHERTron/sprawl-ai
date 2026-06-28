"""
/workspaces/{workspace_id}/secrets/{secret_id}/graph — blast-radius graph.
Full implementation in M5 (agent builds nodes/edges). Stub here.
"""
from fastapi import APIRouter, Depends

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.schemas.common import ok

router = APIRouter(
    prefix="/workspaces/{workspace_id}/secrets",
    tags=["graph"],
)


@router.get("/{secret_id}/graph")
async def get_blast_radius(
    workspace_id: str,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Return nodes + edges for the blast-radius graph (M5)."""
    return ok({"nodes": [], "edges": [], "secret_id": secret_id})
