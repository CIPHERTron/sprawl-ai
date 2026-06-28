"""
arq job: run_rotation_step

Drives the rotation state machine forward by one step (or to its next
pause point). After each successful non-terminal step, re-enqueues itself
so the engine continues without external polling.

Idempotency:
  - The distributed Redis lock (RotationLock) prevents concurrent runs for
    the same secret.
  - The engine itself skips steps already in a terminal state.
  - Multiple enqueues for the same rotation_id are therefore safe.

Connector selection:
  - If `use_sandbox=True` (default for demo workspaces), sandbox connectors
    are injected with an optional `fail_at` step kind for the simulate-failure
    endpoint.
  - Otherwise real connectors are loaded (M9 — not yet wired).
"""
from __future__ import annotations

import structlog
from arq import ArqRedis

from worker.db import async_session_maker
from worker.rotation.engine import EngineResult, advance_rotation
from worker.rotation.lock import LockNotAcquiredError, RotationLock
from worker.rotation.sandbox import build_sandbox_connectors

logger = structlog.get_logger(__name__)

# arq job parameters (picked up by arq worker)
JOB_TIMEOUT = 300       # 5 minutes — matches LOCK_TTL_MS
MAX_TRIES   = 1         # don't auto-retry on failure (engine handles its own rollback)


async def run_rotation_step(
    ctx: dict,
    *,
    rotation_id: str,
    workspace_id: str,
    secret_id: str,
    use_sandbox: bool = True,
    fail_at: str | None = None,
    actor: str = "system",
) -> dict:
    """
    Execute the next eligible rotation step and persist the result.

    Args:
        rotation_id:  UUID of the rotation row.
        workspace_id: UUID of the owning workspace.
        secret_id:    UUID of the secret being rotated (used for the lock key).
        use_sandbox:  If True, use in-memory sandbox connectors (demo mode).
        fail_at:      Step kind to inject a failure on (only used with sandbox).
        actor:        Audit actor label.

    Returns:
        dict with rotation_status, should_continue, and optional error.
    """
    log = logger.bind(rotation_id=rotation_id, workspace_id=workspace_id)

    # ── Build connectors ───────────────────────────────────────────────────────
    if use_sandbox:
        connectors = build_sandbox_connectors(fail_at=fail_at)
    else:
        # TODO(M9): load real connectors from registry based on rotation.plan
        connectors = build_sandbox_connectors()
        log.warning("run_rotation_step.real_connectors_not_yet_wired_using_sandbox")

    # ── Acquire distributed lock ───────────────────────────────────────────────
    lock = RotationLock(secret_id=secret_id, rotation_id=rotation_id)
    try:
        async with lock:
            async with async_session_maker() as db:
                result: EngineResult = await advance_rotation(
                    rotation_id=rotation_id,
                    workspace_id=workspace_id,
                    db=db,
                    connectors=connectors,
                    actor=actor,
                )

    except LockNotAcquiredError as exc:
        log.warning("run_rotation_step.lock_not_acquired", error=str(exc))
        return {
            "rotation_status": "lock_not_acquired",
            "should_continue": False,
            "error": str(exc),
        }

    # ── Re-enqueue if the engine wants to continue ────────────────────────────
    if result.should_continue:
        redis: ArqRedis = ctx.get("redis")
        if redis:
            await redis.enqueue_job(
                "run_rotation_step",
                rotation_id=rotation_id,
                workspace_id=workspace_id,
                secret_id=secret_id,
                use_sandbox=use_sandbox,
                fail_at=fail_at,
                actor=actor,
            )
            log.debug("run_rotation_step.re_enqueued", next_step=result.next_step_idx)
        else:
            log.error("run_rotation_step.no_redis_in_ctx_cannot_reenqueue")

    log.info(
        "run_rotation_step.done",
        rotation_status=result.rotation_status,
        message=result.message,
    )
    return {
        "rotation_status": result.rotation_status,
        "next_step_idx":   result.next_step_idx,
        "should_continue": result.should_continue,
        "message":         result.message,
        "error":           result.error,
    }
