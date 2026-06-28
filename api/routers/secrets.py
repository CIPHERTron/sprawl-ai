"""
/workspaces/{workspace_id}/secrets — secret identity CRUD + triage actions.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.db.models.secret import Secret
from api.db.session import get_db
from api.schemas.common import ok, page
from api.schemas.secrets import SecretOut

router = APIRouter(
    prefix="/workspaces/{workspace_id}/secrets",
    tags=["secrets"],
)


@router.get("")
async def list_secrets(
    workspace_id: UUID,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Secret)
        .where(Secret.workspace_id == workspace_id)
        .order_by(Secret.severity_score.desc().nullslast(), Secret.last_seen.desc())
        .limit(limit)
        .offset(offset)
    )
    secrets = result.scalars().all()
    return page(
        data=[SecretOut.model_validate(s).model_dump() for s in secrets],
        total=len(secrets),
        limit=limit,
        offset=offset,
    )


@router.get("/{secret_id}")
async def get_secret(
    workspace_id: UUID,
    secret_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Secret)
        .where(Secret.workspace_id == workspace_id, Secret.id == secret_id)
    )
    secret = result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret_not_found")
    return ok(SecretOut.model_validate(secret).model_dump())


@router.post("/{secret_id}/investigate")
async def trigger_investigation(
    workspace_id: UUID,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Enqueue an investigation agent run (M7)."""
    return ok({"queued": True, "secret_id": secret_id})


@router.post("/{secret_id}/rotate")
async def trigger_rotation(
    workspace_id: UUID,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Create a rotation row in 'proposed' status and enqueue plan_rotation (M5)."""
    return ok({"queued": True, "secret_id": secret_id})
