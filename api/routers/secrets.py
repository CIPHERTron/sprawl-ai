"""
/workspaces/{workspace_id}/secrets — secret identity CRUD + triage actions.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit.log import audit
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


@router.post("/{secret_id}/rotate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_rotation(
    workspace_id: UUID,
    secret_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a rotation plan and transition to pending_approval.

    Idempotent: if an active (non-terminal) rotation already exists for this
    secret, returns the existing rotation_id rather than creating a duplicate
    (enforced by the one_active_rotation partial unique index).

    For demo workspaces the plan is generated inline (sandbox connectors, no
    LLM call). For real workspaces the same inline plan is used until the
    plan_rotation job is wired in M6.
    """
    # ── 1. Verify secret belongs to workspace ──────────────────────────────────
    result = await db.execute(
        select(Secret).where(Secret.id == secret_id, Secret.workspace_id == workspace_id)
    )
    secret = result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="secret_not_found")

    # ── 2. Return existing active rotation if present ──────────────────────────
    existing = await db.execute(
        text("""
            SELECT id, status::text FROM rotations
            WHERE secret_id = :sid AND workspace_id = :wid
              AND status::text NOT IN (
                'completed','rolled_back','rejected',
                'rollback_failed','abandoned','plan_failed'
              )
            LIMIT 1
        """),
        {"sid": str(secret_id), "wid": str(workspace_id)},
    )
    ex_row = existing.one_or_none()
    if ex_row is not None:
        return ok({
            "rotation_id": str(ex_row[0]),
            "secret_id": str(secret_id),
            "status": str(ex_row[1]),
        })

    # ── 3. Build a sandbox rotation plan ──────────────────────────────────────
    now = datetime.now(timezone.utc)
    plan_expires = now + timedelta(hours=24)
    actor = claims.sub

    plan = {
        "summary": (
            f"Rotate secret '{secret.type}' — "
            "provision new credential, distribute to known consumers, verify, then revoke old."
        ),
        "steps": [
            {
                "idx": 0,
                "kind": "provision",
                "description": "Generate new credential via cloud connector",
                "requires_confirmation": False,
            },
            {
                "idx": 1,
                "kind": "distribute",
                "description": "Write new credential to all known consumers",
                "requires_confirmation": True,
            },
            {
                "idx": 2,
                "kind": "verify",
                "description": "Verify new credential is readable by all consumers",
                "requires_confirmation": False,
            },
            {
                "idx": 3,
                "kind": "revoke",
                "description": "Revoke old credential",
                "requires_confirmation": True,
            },
        ],
        "coverage": {"known_consumers": 1, "unknown_consumers": 0},
        "created_by": actor,
        "model": "sandbox-plan-v1",
    }
    coverage = {"known_consumers": 1, "unknown_consumers": 0}

    # ── 4. Insert rotation row ─────────────────────────────────────────────────
    rotation_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO rotations
              (id, workspace_id, secret_id, status, plan, coverage, plan_expires_at, created_by)
            VALUES
              (:id, :wid, :sid, 'pending_approval',
               CAST(:plan AS jsonb), CAST(:coverage AS jsonb),
               :expires_at, :created_by)
            ON CONFLICT DO NOTHING
        """),
        {
            "id": rotation_id,
            "wid": str(workspace_id),
            "sid": str(secret_id),
            "plan": json.dumps(plan),
            "coverage": json.dumps(coverage),
            "expires_at": plan_expires,
            "created_by": actor if _is_valid_uuid(actor) else None,
        },
    )

    # ── 5. Insert rotation steps ───────────────────────────────────────────────
    steps_data = [
        {
            "id": str(uuid.uuid4()),
            "kind": "provision",
            "target": json.dumps({"type": "sandbox", "credential_type": secret.type}),
            "compensation": json.dumps({"action": "delete_new_key"}),
            "requires_confirmation": False,
        },
        {
            "id": str(uuid.uuid4()),
            "kind": "distribute",
            "target": json.dumps({"type": "sandbox", "consumer": "all_known"}),
            "compensation": json.dumps({"action": "restore_old_secret_value"}),
            "requires_confirmation": True,
        },
        {
            "id": str(uuid.uuid4()),
            "kind": "verify",
            "target": json.dumps({"type": "sandbox", "check": "readability"}),
            "compensation": None,
            "requires_confirmation": False,
        },
        {
            "id": str(uuid.uuid4()),
            "kind": "revoke",
            "target": json.dumps({"type": "sandbox", "credential": "old"}),
            "compensation": json.dumps({"action": "reactivate_old_key"}),
            "requires_confirmation": True,
        },
    ]
    for idx, s in enumerate(steps_data):
        await db.execute(
            text("""
                INSERT INTO rotation_steps
                  (id, workspace_id, rotation_id, idx, kind, target,
                   compensation, requires_confirmation, status)
                VALUES
                  (:id, :wid, :rid, :idx, :kind,
                   CAST(:target AS jsonb),
                   CAST(:compensation AS jsonb),
                   :req_confirm, 'pending')
            """),
            {
                "id": s["id"],
                "wid": str(workspace_id),
                "rid": rotation_id,
                "idx": idx,
                "kind": s["kind"],
                "target": s["target"],
                "compensation": s["compensation"],
                "req_confirm": s["requires_confirmation"],
            },
        )

    # ── 6. Audit + commit ──────────────────────────────────────────────────────
    await audit(
        db, str(workspace_id), actor,
        "rotation.proposed",
        target_type="rotation", target_id=rotation_id,
        after={"status": "pending_approval", "secret_id": str(secret_id)},
    )
    await db.commit()

    return ok({
        "rotation_id": rotation_id,
        "secret_id": str(secret_id),
        "status": "pending_approval",
    })


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
