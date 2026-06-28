"""
Hash-chained audit log append (§8.3).

Safety properties maintained here:
  - Per-workspace advisory lock (`pg_advisory_xact_lock`) serialises appends so
    the chain never forks under concurrent api + worker writers.
  - `prev_hash` is always the latest row's hash, ordered by `id` (bigserial).
  - `hash = sha256(prev_hash || canonical_json(entry_without_hash))`.
  - Canonical JSON = compact, keys sorted — deterministic across Python versions.
  - No secret values ever enter `before`/`after`; callers are responsible.

Public API:
    from api.audit.log import audit

    await audit(
        db=session,
        workspace_id=workspace_id,
        actor="user-uuid",           # or "system"
        action="rotation.approved",
        target_type="rotation",
        target_id=str(rotation.id),
        after={"status": "pending_approval"},
        correlation_id=request.state.request_id,
    )
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.audit import AuditLog

logger = structlog.get_logger(__name__)


def _canonical_json(obj: dict) -> str:
    """Compact, sorted-key JSON — deterministic across calls."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, payload: dict) -> str:
    """sha256(prev_hash || canonical_json(payload))"""
    raw = (prev_hash + _canonical_json(payload)).encode()
    return hashlib.sha256(raw).hexdigest()


async def audit(
    db: AsyncSession,
    workspace_id: str,
    actor: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> AuditLog:
    """
    Append a tamper-evident audit entry within the caller's transaction.

    Must be called inside an active transaction (i.e. inside `async with db.begin()`
    or after `await db.begin()`). The advisory lock is transaction-scoped so it
    releases automatically on commit or rollback.
    """
    # ── 1. Serialise chain writes per workspace ───────────────────────────────
    # hashtext() is Postgres's int4 hash — guaranteed to fit in pg_advisory_xact_lock
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"audit:{workspace_id}"},
    )

    # ── 2. Fetch previous hash (ordered by id — bigserial canonical order) ────
    result = await db.execute(
        select(AuditLog.hash)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    prev_hash: str = result.scalar_one_or_none() or ("0" * 64)

    # ── 3. Build canonical payload (no hash field yet) ────────────────────────
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "actor": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "before": before,
        "after": after,
        "correlation_id": correlation_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── 4. Compute hash and insert ────────────────────────────────────────────
    new_hash = _compute_hash(prev_hash, payload)

    entry = AuditLog(
        workspace_id=workspace_id,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        correlation_id=correlation_id,
        prev_hash=prev_hash,
        hash=new_hash,
    )
    db.add(entry)
    await db.flush()  # assign id (bigserial) without committing

    logger.info(
        "audit.appended",
        workspace_id=workspace_id,
        action=action,
        actor=actor,
        entry_id=entry.id,
    )
    return entry
