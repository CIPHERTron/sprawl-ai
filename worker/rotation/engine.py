"""
Deterministic rotation state machine (§5 — M5).

`advance_rotation()` is the single entry point called by the arq job.
It reads the current rotation state from PostgreSQL (raw SQL), executes
the next eligible step, persists the result, and publishes SSE events.

Safety invariants enforced here:
  I1  verify-before-revoke    — verify_gate blocks revoke until all verifies pass
  I2  coverage gate           — coverage_gate blocks revoke if unknown_consumers > 0
  I3  plan TTL                — rotation is expired if plan_expires_at has passed
  I4  auto-rollback on fail   — failed step triggers reverse compensation loop
  I5  idempotency             — step already in terminal state is skipped
  I6  confirmation gate       — step with requires_confirmation waits for API confirm

All DB writes use raw SQL (no ORM imports from the api package).
All connector calls are synchronous and wrapped in run_in_executor to keep
the event loop non-blocking.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker.audit import audit
from worker.redis import publish_event as publish
from worker.rotation.gate import GateBlockedError, coverage_gate, verify_gate
from worker.rotation.steps import StepResult, compensate_step, execute_step

logger = structlog.get_logger(__name__)

# Map step kind → the rotation status to set while that step is running
_KIND_TO_STATUS: dict[str, str] = {
    "provision":  "provisioning",
    "distribute": "distributing",
    "verify":     "verifying",
    "revoke":     "revoking",
}

# Rotation statuses considered terminal (no further advance possible)
_TERMINAL_STATUSES = {
    "completed", "rolled_back", "rollback_failed",
    "rejected", "abandoned", "plan_failed",
}


@dataclass
class EngineResult:
    """Return value of advance_rotation()."""
    rotation_status: str
    # Next step idx that needs to run (None = done or paused)
    next_step_idx: int | None = None
    # True if the engine should be re-enqueued immediately
    should_continue: bool = False
    # Human-readable summary
    message: str = ""
    error: str | None = None


async def advance_rotation(
    rotation_id: str,
    workspace_id: str,
    db: AsyncSession,
    connectors: dict[str, Any],
    actor: str = "system",
) -> EngineResult:
    """
    Execute the next eligible rotation step and persist the result.

    Caller (arq job) is responsible for:
      - Holding the distributed lock before calling this
      - Re-enqueuing if result.should_continue is True

    Args:
        rotation_id:  UUID string of the rotation row.
        workspace_id: UUID string of the owning workspace.
        db:           Active SQLAlchemy async session (worker/db.py engine).
        connectors:   {'store': StoreConnector, 'cloud': CloudConnector}
        actor:        Audit actor label (job name or user email).

    Returns:
        EngineResult describing what happened.
    """
    log = logger.bind(rotation_id=rotation_id, workspace_id=workspace_id)

    # ── 1. Load rotation ──────────────────────────────────────────────────────
    rotation = await _load_rotation(rotation_id, workspace_id, db)
    if rotation is None:
        return EngineResult(rotation_status="not_found", message="Rotation not found")

    current_status = rotation["status"]

    # ── 2. Guard: already terminal ────────────────────────────────────────────
    if current_status in _TERMINAL_STATUSES:
        log.info("engine.already_terminal", status=current_status)
        return EngineResult(rotation_status=current_status, message="Already in terminal state")

    # ── 3. Guard: plan TTL ────────────────────────────────────────────────────
    plan_expires_at = rotation.get("plan_expires_at")
    if plan_expires_at and current_status == "pending_approval":
        expires = (
            plan_expires_at
            if isinstance(plan_expires_at, datetime)
            else datetime.fromisoformat(str(plan_expires_at))
        )
        if expires < datetime.now(timezone.utc):
            await _set_rotation_status(rotation_id, workspace_id, "needs_replan", db)
            await audit(
                db, workspace_id, actor, "rotation.plan_expired",
                target_type="rotation", target_id=rotation_id,
                before={"status": current_status}, after={"status": "needs_replan"},
            )
            await db.commit()
            await publish(workspace_id, "rotation.plan_expired", {"rotation_id": rotation_id})
            log.info("engine.plan_expired")
            return EngineResult(rotation_status="needs_replan", message="Plan TTL exceeded")

    # ── 4. Load steps ─────────────────────────────────────────────────────────
    steps = await _load_steps(rotation_id, db)
    if not steps:
        return EngineResult(
            rotation_status=current_status,
            message="No steps found; rotation may be malformed",
        )

    # ── 5. Find next pending step ─────────────────────────────────────────────
    next_step = _find_next_step(steps)
    if next_step is None:
        # All steps done → mark rotation complete
        all_done = all(s["status"] == "done" for s in steps)
        if all_done:
            await _set_rotation_status(rotation_id, workspace_id, "completed", db)
            await audit(
                db, workspace_id, actor, "rotation.completed",
                target_type="rotation", target_id=rotation_id,
                before={"status": current_status}, after={"status": "completed"},
            )
            await db.commit()
            await publish(workspace_id, "rotation.completed", {"rotation_id": rotation_id})
            log.info("engine.completed")
            return EngineResult(rotation_status="completed", message="All steps completed")
        # Steps exist but none are pending — already paused or compensated
        return EngineResult(rotation_status=current_status, message="No pending steps")

    step_idx = next_step["idx"]
    step_kind = next_step["kind"]

    # ── 6. Check requires_confirmation ───────────────────────────────────────
    if next_step.get("requires_confirmation") and current_status != "awaiting_confirmation":
        await _set_rotation_status(rotation_id, workspace_id, "awaiting_confirmation", db)
        await audit(
            db, workspace_id, actor, "rotation.awaiting_confirmation",
            target_type="rotation", target_id=rotation_id,
            before={"status": current_status},
            after={"status": "awaiting_confirmation", "waiting_on_step": step_idx},
        )
        await db.commit()
        await publish(
            workspace_id, "rotation.awaiting_confirmation",
            {"rotation_id": rotation_id, "step_idx": step_idx, "step_kind": step_kind},
        )
        log.info("engine.awaiting_confirmation", step_idx=step_idx)
        return EngineResult(
            rotation_status="awaiting_confirmation",
            next_step_idx=step_idx,
            message=f"Step {step_idx} ({step_kind}) requires explicit confirmation",
        )

    # ── 7. Pre-revoke safety gates ────────────────────────────────────────────
    if step_kind == "revoke":
        try:
            await verify_gate(rotation_id, db)
            coverage_gate(rotation.get("coverage") or {}, revoke_confirmed=True)
        except GateBlockedError as gate_err:
            await _set_rotation_status(rotation_id, workspace_id, gate_err.rotation_status, db)
            await db.commit()
            await publish(
                workspace_id, "rotation.gate_blocked",
                {"rotation_id": rotation_id, "reason": gate_err.reason},
            )
            log.warning("engine.gate_blocked", reason=gate_err.reason)
            return EngineResult(
                rotation_status=gate_err.rotation_status,
                next_step_idx=step_idx,
                message=gate_err.message,
            )

    # ── 8. Transition rotation status ─────────────────────────────────────────
    running_status = _KIND_TO_STATUS.get(step_kind, current_status)
    if current_status != running_status:
        await _set_rotation_status(rotation_id, workspace_id, running_status, db)
        await audit(
            db, workspace_id, actor, f"rotation.step.{step_kind}.started",
            target_type="rotation", target_id=rotation_id,
            before={"status": current_status},
            after={"status": running_status, "step_idx": step_idx},
        )
        await db.commit()
        await publish(
            workspace_id, f"rotation.step.{step_kind}.started",
            {"rotation_id": rotation_id, "step_idx": step_idx},
        )

    # ── 9. Execute step (run sync connector in thread) ────────────────────────
    log.info("engine.executing_step", step_idx=step_idx, kind=step_kind)
    result: StepResult = await asyncio.get_event_loop().run_in_executor(
        None,
        execute_step,
        next_step,
        rotation,
        connectors,
    )

    # ── 10. Persist step result ───────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc)

    if result.status == "done":
        await db.execute(
            text("""
                UPDATE rotation_steps
                SET status = 'done',
                    executed_at = :now
                WHERE id = :step_id
            """),
            {"now": now_iso, "step_id": next_step["id"]},
        )

        # If provision returned a new_secret_ref, persist it to the rotation row
        if result.new_secret_ref:
            await db.execute(
                text("""
                    UPDATE rotations
                    SET new_secret_ref = CAST(:ref AS jsonb),
                        updated_at = :now
                    WHERE id = :rid
                """),
                {
                    "ref": json.dumps(result.new_secret_ref),
                    "now": now_iso,
                    "rid": rotation_id,
                },
            )
            rotation["new_secret_ref"] = result.new_secret_ref

        await audit(
            db, workspace_id, actor, f"rotation.step.{step_kind}.done",
            target_type="rotation", target_id=rotation_id,
            after={"step_idx": step_idx, "kind": step_kind},
        )
        await db.commit()
        await publish(
            workspace_id, f"rotation.step.{step_kind}.done",
            {"rotation_id": rotation_id, "step_idx": step_idx},
        )

        # Check if this was the last step
        remaining = [s for s in steps if s["idx"] > step_idx and s["status"] == "pending"]
        if not remaining:
            await _set_rotation_status(rotation_id, workspace_id, "completed", db)
            await audit(
                db, workspace_id, actor, "rotation.completed",
                target_type="rotation", target_id=rotation_id,
                before={"status": running_status}, after={"status": "completed"},
            )
            await db.commit()
            await publish(workspace_id, "rotation.completed", {"rotation_id": rotation_id})
            log.info("engine.completed", step_idx=step_idx)
            return EngineResult(
                rotation_status="completed",
                message="Last step done — rotation complete",
            )

        log.info("engine.step_done_continuing", step_idx=step_idx)
        return EngineResult(
            rotation_status=running_status,
            next_step_idx=step_idx + 1,
            should_continue=True,
            message=f"Step {step_idx} done — continuing",
        )

    else:
        # Step failed → rollback
        await db.execute(
            text("""
                UPDATE rotation_steps
                SET status = 'failed',
                    executed_at = :now,
                    error = :error
                WHERE id = :step_id
            """),
            {"now": now_iso, "error": result.error, "step_id": next_step["id"]},
        )
        await audit(
            db, workspace_id, actor, f"rotation.step.{step_kind}.failed",
            target_type="rotation", target_id=rotation_id,
            after={"step_idx": step_idx, "error": result.error},
        )
        await db.commit()
        await publish(
            workspace_id, f"rotation.step.{step_kind}.failed",
            {"rotation_id": rotation_id, "step_idx": step_idx, "error": result.error},
        )

        log.warning("engine.step_failed_rolling_back", step_idx=step_idx, error=result.error)
        return await _rollback(
            rotation_id, workspace_id, step_idx, steps, rotation, connectors, db, actor
        )


async def _rollback(
    rotation_id: str,
    workspace_id: str,
    failed_idx: int,
    steps: list[dict],
    rotation: dict,
    connectors: dict,
    db: AsyncSession,
    actor: str,
) -> EngineResult:
    """
    Run compensation on all completed steps in reverse order (§5.3.5).
    """
    await _set_rotation_status(rotation_id, workspace_id, "rolling_back", db)
    await audit(
        db, workspace_id, actor, "rotation.rolling_back",
        target_type="rotation", target_id=rotation_id,
        after={"status": "rolling_back", "failed_at_step": failed_idx},
    )
    await db.commit()
    await publish(workspace_id, "rotation.rolling_back", {"rotation_id": rotation_id})

    # Compensate completed steps in reverse order (excluding the failed one)
    done_steps = sorted(
        [s for s in steps if s["status"] == "done"],
        key=lambda s: s["idx"],
        reverse=True,
    )

    compensation_failures: list[str] = []
    now_iso = datetime.now(timezone.utc)

    for step in done_steps:
        comp_result: StepResult = await asyncio.get_event_loop().run_in_executor(
            None,
            compensate_step,
            step,
            rotation,
            connectors,
        )
        new_status = "compensated" if comp_result.status == "compensated" else "failed"
        await db.execute(
            text("""
                UPDATE rotation_steps
                SET status = :status,
                    executed_at = :now,
                    error = :error
                WHERE id = :step_id
            """),
            {
                "status": new_status,
                "now": now_iso,
                "error": comp_result.error,
                "step_id": step["id"],
            },
        )
        await db.commit()
        if new_status == "failed":
            compensation_failures.append(f"step {step['idx']}: {comp_result.error}")

    final_status = "rollback_failed" if compensation_failures else "rolled_back"
    await _set_rotation_status(rotation_id, workspace_id, final_status, db)
    await audit(
        db, workspace_id, actor, f"rotation.{final_status}",
        target_type="rotation", target_id=rotation_id,
        after={"status": final_status, "compensation_failures": compensation_failures},
    )
    await db.commit()
    await publish(workspace_id, f"rotation.{final_status}", {"rotation_id": rotation_id})

    logger.info("engine.rollback_complete", final_status=final_status)
    return EngineResult(
        rotation_status=final_status,
        error="; ".join(compensation_failures) or None,
        message=f"Rollback {'succeeded' if final_status == 'rolled_back' else 'partially failed'}",
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _load_rotation(rotation_id: str, workspace_id: str, db: AsyncSession) -> dict | None:
    result = await db.execute(
        text("""
            SELECT
                id, workspace_id, secret_id, status,
                plan, coverage, new_secret_ref,
                plan_expires_at, created_at, updated_at
            FROM rotations
            WHERE id = :rid AND workspace_id = :wid
        """),
        {"rid": rotation_id, "wid": workspace_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    return dict(row)


async def _load_steps(rotation_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT
                id, rotation_id, idx, kind, target, compensation,
                requires_confirmation, status, executed_at, error
            FROM rotation_steps
            WHERE rotation_id = :rid
            ORDER BY idx ASC
        """),
        {"rid": rotation_id},
    )
    return [dict(r) for r in result.mappings().all()]


def _find_next_step(steps: list[dict]) -> dict | None:
    """Return the lowest-idx step that is still 'pending'."""
    for step in sorted(steps, key=lambda s: s["idx"]):
        if step["status"] == "pending":
            return step
    return None


async def _set_rotation_status(
    rotation_id: str,
    workspace_id: str,
    new_status: str,
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            UPDATE rotations
            SET status = :status, updated_at = :now
            WHERE id = :rid AND workspace_id = :wid
        """),
        {
            "status": new_status,
            "now": datetime.now(timezone.utc),
            "rid": rotation_id,
            "wid": workspace_id,
        },
    )
