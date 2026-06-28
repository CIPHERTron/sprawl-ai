"""
/workspaces/{workspace_id}/rotations — rotation lifecycle + approval gates.

Implements:
  GET  /                       List rotations (newest first)
  GET  /{rotation_id}          Get rotation with steps
  POST /{rotation_id}/approve  Approve plan → enqueue run_rotation_step
  POST /{rotation_id}/reject   Reject plan → terminal 'rejected' state
  POST /{rotation_id}/steps/{step_id}/confirm
                               Confirm a step gate → re-enqueue engine
"""
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit.log import audit
from api.auth.deps import require_auth, require_role
from api.auth.jwt import TokenClaims
from api.db.session import get_db
from api.schemas.common import ok, page
from api.services.arq_pool import enqueue_job

router = APIRouter(
    prefix="/workspaces/{workspace_id}/rotations",
    tags=["rotations"],
)


@router.get("")
async def list_rotations(
    workspace_id: UUID,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List rotations for a workspace, newest first."""
    result = await db.execute(
        text("""
            SELECT
                r.id, r.secret_id, r.status, r.plan, r.coverage,
                r.plan_expires_at, r.created_at, r.updated_at,
                s.type AS secret_type
            FROM rotations r
            JOIN secrets s ON s.id = r.secret_id
            WHERE r.workspace_id = :wid
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"wid": str(workspace_id), "limit": limit, "offset": offset},
    )
    rows = result.mappings().all()

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM rotations WHERE workspace_id = :wid"),
        {"wid": str(workspace_id)},
    )
    total = count_result.scalar_one()

    return page(
        data=[_rotation_row_to_dict(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{rotation_id}")
async def get_rotation(
    workspace_id: UUID,
    rotation_id: UUID,
    claims: TokenClaims = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a single rotation with its steps."""
    result = await db.execute(
        text("""
            SELECT
                r.id, r.secret_id, r.status, r.plan, r.coverage,
                r.plan_error, r.new_secret_ref,
                r.plan_expires_at, r.created_at, r.updated_at,
                s.type AS secret_type, s.environment
            FROM rotations r
            JOIN secrets s ON s.id = r.secret_id
            WHERE r.id = :rid AND r.workspace_id = :wid
        """),
        {"rid": str(rotation_id), "wid": str(workspace_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rotation_not_found")

    data = _rotation_row_to_dict(row)
    data["plan_error"] = row["plan_error"]
    data["new_secret_ref"] = row["new_secret_ref"]

    # Attach steps
    steps_result = await db.execute(
        text("""
            SELECT id, idx, kind, target, compensation,
                   requires_confirmation, status, error,
                   confirmed_at, executed_at
            FROM rotation_steps
            WHERE rotation_id = :rid
            ORDER BY idx ASC
        """),
        {"rid": str(rotation_id)},
    )
    data["steps"] = [_step_row_to_dict(s) for s in steps_result.mappings().all()]

    return ok(data)


@router.post("/{rotation_id}/approve", status_code=status.HTTP_202_ACCEPTED)
async def approve_rotation(
    workspace_id: UUID,
    rotation_id: UUID,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve the rotation plan and kick off execution.

    Validates the rotation is in 'pending_approval' and the secret belongs to
    this workspace, then enqueues `run_rotation_step` to drive the engine.
    """
    row = await _require_rotation(rotation_id, workspace_id, db)
    if row["status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot approve rotation in status '{row['status']}'",
        )

    actor = claims.sub
    await audit(
        db, str(workspace_id), actor,
        "rotation.approved",
        target_type="rotation", target_id=str(rotation_id),
        before={"status": "pending_approval"}, after={"status": "provisioning"},
    )
    await db.commit()

    await enqueue_job(
        "run_rotation_step",
        rotation_id=str(rotation_id),
        workspace_id=str(workspace_id),
        secret_id=str(row["secret_id"]),
        use_sandbox=True,
        actor=actor,
    )

    return ok({
        "rotation_id": str(rotation_id),
        "status": "pending_approval",
        "message": "Rotation approved — engine enqueued, status will advance once the worker picks up the job",
    })


@router.post("/{rotation_id}/reject")
async def reject_rotation(
    workspace_id: UUID,
    rotation_id: UUID,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject the rotation plan — moves to terminal 'rejected' state.
    """
    row = await _require_rotation(rotation_id, workspace_id, db)
    if row["status"] not in ("pending_approval", "awaiting_confirmation"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reject rotation in status '{row['status']}'",
        )

    actor = claims.sub
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE rotations
            SET status = 'rejected', updated_at = :now
            WHERE id = :rid AND workspace_id = :wid
        """),
        {"now": now, "rid": str(rotation_id), "wid": str(workspace_id)},
    )
    await audit(
        db, str(workspace_id), actor,
        "rotation.rejected",
        target_type="rotation", target_id=str(rotation_id),
        before={"status": row["status"]}, after={"status": "rejected"},
    )
    await db.commit()

    return ok({"rotation_id": str(rotation_id), "status": "rejected"})


@router.post("/{rotation_id}/steps/{step_id}/confirm")
async def confirm_step(
    workspace_id: UUID,
    rotation_id: UUID,
    step_id: UUID,
    claims: TokenClaims = Depends(require_role("owner", "approver")),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm a step gate — marks the step confirmed and re-enqueues the engine.

    The rotation must be in 'awaiting_confirmation' state. The engine will then
    proceed past the confirmed step on its next run.
    """
    row = await _require_rotation(rotation_id, workspace_id, db)
    if row["status"] != "awaiting_confirmation":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rotation is not awaiting confirmation (status: '{row['status']}')",
        )

    # Verify step belongs to this rotation
    step_result = await db.execute(
        text("""
            SELECT id, idx, kind, status, requires_confirmation
            FROM rotation_steps
            WHERE id = :step_id AND rotation_id = :rid
        """),
        {"step_id": str(step_id), "rid": str(rotation_id)},
    )
    step = step_result.mappings().one_or_none()
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="step_not_found"
        )
    if step["status"] not in ("pending",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Step is not pending (status: '{step['status']}')",
        )

    actor = claims.sub
    now = datetime.now(timezone.utc)

    # Record confirmation on the step.
    # confirmed_by is a FK to users.id — leave NULL since the JWT sub is not
    # guaranteed to be in the users table (demo mode). The actor is captured
    # in the audit log instead.
    await db.execute(
        text("""
            UPDATE rotation_steps
            SET confirmed_at = :now,
                requires_confirmation = false
            WHERE id = :step_id
        """),
        {
            "now": now,
            "step_id": str(step_id),
        },
    )
    await audit(
        db, str(workspace_id), actor,
        "rotation.step.confirmed",
        target_type="rotation", target_id=str(rotation_id),
        after={"step_id": str(step_id), "step_idx": step["idx"], "kind": step["kind"]},
    )
    await db.commit()

    # Re-enqueue engine to continue from this step
    await enqueue_job(
        "run_rotation_step",
        rotation_id=str(rotation_id),
        workspace_id=str(workspace_id),
        secret_id=str(row["secret_id"]),
        use_sandbox=True,
        actor=actor,
    )

    return ok({
        "rotation_id": str(rotation_id),
        "step_id": str(step_id),
        "status": "confirmed",
        "message": "Step confirmed — engine re-enqueued",
    })


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _require_rotation(
    rotation_id: UUID,
    workspace_id: UUID,
    db: AsyncSession,
) -> dict:
    """Load and return a rotation row, raising 404 if not found."""
    result = await db.execute(
        text("""
            SELECT id, secret_id, status, plan, coverage, plan_expires_at, created_at, updated_at
            FROM rotations
            WHERE id = :rid AND workspace_id = :wid
        """),
        {"rid": str(rotation_id), "wid": str(workspace_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rotation_not_found")
    return dict(row)


def _rotation_row_to_dict(row) -> dict:
    return {
        "id": str(row["id"]),
        "secret_id": str(row["secret_id"]),
        "status": str(row["status"]),
        "plan": row["plan"],
        "coverage": row["coverage"],
        "plan_expires_at": (
            row["plan_expires_at"].isoformat() if row.get("plan_expires_at") else None
        ),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "secret_type": row.get("secret_type"),
    }


def _step_row_to_dict(step) -> dict:
    return {
        "id": str(step["id"]),
        "idx": step["idx"],
        "kind": str(step["kind"]),
        "target": step["target"],
        "compensation": step["compensation"],
        "requires_confirmation": step["requires_confirmation"],
        "status": str(step["status"]),
        "error": step.get("error"),
        "confirmed_at": (
            step["confirmed_at"].isoformat() if step.get("confirmed_at") else None
        ),
        "executed_at": (
            step["executed_at"].isoformat() if step.get("executed_at") else None
        ),
    }


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False
