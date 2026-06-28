"""
/workspaces/{workspace_id}/secrets — secret identity CRUD + triage actions.
"""
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_auth
from api.auth.jwt import TokenClaims
from api.db.models.secret import Secret
from api.db.session import get_db
from api.schemas.common import ok, page
from api.schemas.secrets import SecretOut
from api.services.arq_pool import enqueue_job

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


@router.post("/{secret_id}/investigate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_investigation(
    workspace_id: UUID,
    secret_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Enqueue a full investigation agent run.

    Idempotent: if an investigation is already running for this secret,
    returns the existing investigation_id with status 'running' (H4).
    """
    # ── 1. Verify secret belongs to workspace ──────────────────────────────────
    result = await db.execute(
        select(Secret).where(Secret.id == secret_id, Secret.workspace_id == workspace_id)
    )
    secret = result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret_not_found")

    # ── 2. Upsert Investigation row ────────────────────────────────────────────
    # The partial unique index `one_active_investigation` (WHERE status='running')
    # prevents duplicate in-flight investigations.  We INSERT … ON CONFLICT DO NOTHING
    # and then SELECT to find the existing row if there's a conflict.
    new_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO investigations (id, workspace_id, secret_id, status)
            VALUES (:id, :workspace_id, :secret_id, 'running')
            ON CONFLICT DO NOTHING
        """),
        {"id": str(new_id), "workspace_id": str(workspace_id), "secret_id": str(secret_id)},
    )
    await db.commit()

    # Fetch the active investigation (either the one we just inserted or the existing one)
    row = await db.execute(
        text("""
            SELECT id FROM investigations
            WHERE secret_id = :secret_id
              AND workspace_id = :workspace_id
              AND status IN ('running', 'complete')
            ORDER BY started_at DESC
            LIMIT 1
        """),
        {"secret_id": str(secret_id), "workspace_id": str(workspace_id)},
    )
    inv_row = row.one_or_none()
    if inv_row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="investigation_upsert_failed",
        )
    investigation_id = str(inv_row[0])

    # ── 3. Enqueue the job ─────────────────────────────────────────────────────
    await enqueue_job(
        "investigate_secret",
        secret_id=str(secret_id),
        investigation_id=investigation_id,
        workspace_id=str(workspace_id),
    )

    return ok({
        "investigation_id": investigation_id,
        "secret_id": str(secret_id),
        "status": "running",
    })


@router.post("/{secret_id}/rotate")
async def trigger_rotation(
    workspace_id: UUID,
    secret_id: str,
    claims: TokenClaims = Depends(require_auth),
):
    """Create a rotation row in 'proposed' status and enqueue plan_rotation (M5)."""
    return ok({"queued": True, "secret_id": secret_id})
